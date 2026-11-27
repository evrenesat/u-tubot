#!/usr/bin/env python3
"""Paper cuts of a film from its captions (ai/FILM_CUTS_PLAN.md, checkpoint 1). No server change.

Runs the story method (read, link, select, critic; `utubot.story`) per candidate model on one
caption file and writes, per candidate, the story map, a text paper cut and a measurement row,
plus one HTML page the owner can score without watching. Captions and everything derived from
them stay in `--out` (keep it outside the repository). The model is reached directly through an
OpenAI-compatible endpoint; the key is read from the named environment variable, never logged.

    cd ai-backend
    uv run python scripts/story_cut_bench.py --vtt /tmp/film-cuts/evq.tr.vtt --video-id evqNEHYAfDE \\
        --title "..." --channel "..." --duration 4889 --out /tmp/film-cuts/run1 \\
        --base-url http://gateway:8787/v1 --api-key-env KEY_ENV \\
        --candidate utubot:low --candidate heavy:low
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utubot import story  # noqa: E402
from utubot.config import CutsConfig  # noqa: E402
from utubot.cuts import build_units  # noqa: E402
from utubot.transcripts import fmt_ts, parse_vtt  # noqa: E402

DEFAULT_PURPOSE = "A first-time viewer follows the whole story, start to end, in half the time."
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cuts" / "story"
STEP_MAX_TOKENS = {"read": 8000, "link": 8000, "select": 3000, "critic": 2500}
THINKING_HEADROOM = 16000
RETRY_STATUS = (429, 500, 502, 503, 504)
MAX_ATTEMPTS = 3
BACKOFF_S = 5.0
TIMEOUT_S = 900.0


def make_fn(client: httpx.Client, model: str, step: str, effort: str) -> story.ModelFn:
    """A model callable for one step: messages in, a `Reply` (text, tokens, seconds) out."""
    max_tokens = STEP_MAX_TOKENS[step] + (THINKING_HEADROOM if effort != "none" else 0)

    def call(messages: list[dict[str, str]]) -> story.Reply:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2,
            "reasoning_effort": effort,
            "response_format": {"type": "json_object"},
        }
        started = time.monotonic()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            resp = client.post("/chat/completions", json=body, timeout=TIMEOUT_S)
            if resp.status_code == 400 and "response_format" in body:
                body.pop("response_format")
                continue
            if resp.status_code in RETRY_STATUS and attempt < MAX_ATTEMPTS:
                time.sleep(BACKOFF_S * attempt)
                continue
            resp.raise_for_status()
            break
        data = resp.json()
        usage = data.get("usage") or {}
        if not data["choices"][0]["message"].get("content"):
            print(
                f"[{model}] empty answer, finish={data['choices'][0].get('finish_reason')} "
                f"usage={usage}",
                flush=True,
            )
        return story.Reply(
            text=data["choices"][0]["message"].get("content") or "",
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            seconds=time.monotonic() - started,
        )

    return call


def smap_to_json(smap: story.StoryMap) -> dict[str, Any]:
    return dataclasses.asdict(smap)


def smap_from_json(data: dict[str, Any]) -> story.StoryMap:
    beats = [story.Beat(**b) for b in data.pop("beats")]
    return story.StoryMap(beats=beats, **data)


def step_totals(calls: list[story.CallRecord]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for c in calls:
        row = out.setdefault(c.step, {"calls": 0, "seconds": 0.0, "in": 0, "out": 0})
        row["calls"] += 1
        row["seconds"] = round(row["seconds"] + c.seconds, 1)
        row["in"] += c.prompt_tokens
        row["out"] += c.completion_tokens
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vtt", required=True, type=Path)
    ap.add_argument("--video-id", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--channel", default="")
    ap.add_argument("--duration", type=float, required=True, help="film length in seconds")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key-env", required=True)
    ap.add_argument(
        "--candidate",
        action="append",
        required=True,
        help="alias[:effort]; effort (none|low|medium|high) applies to link, select, critic",
    )
    ap.add_argument("--target-frac", type=float, default=0.5)
    ap.add_argument("--purpose", default=DEFAULT_PURPOSE)
    ap.add_argument("--pairs", type=Path, default=None)
    args = ap.parse_args()

    key = os.environ.get(args.api_key_env, "")
    if not key:
        print(f"environment variable {args.api_key_env} is empty", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    params = story.StoryParams()
    segments = parse_vtt(args.vtt.read_text(encoding="utf-8"))
    units = build_units(segments, CutsConfig())
    meta = {"title": args.title, "channel": args.channel, "duration_s": args.duration}
    target_s = int(args.duration * args.target_frac)
    pairs_path = args.pairs or FIXTURES / f"{args.video_id}.pairs.json"
    pairs = json.loads(pairs_path.read_text())["pairs"] if pairs_path.exists() else []
    print(f"{len(segments)} segments, {len(units)} units, target {fmt_ts(target_s)}", flush=True)

    results: list[tuple[str, story.StoryResult]] = []
    table: list[dict[str, Any]] = []
    with httpx.Client(base_url=args.base_url, headers={"Authorization": f"Bearer {key}"}) as client:
        for spec in args.candidate:
            alias, _, effort = spec.partition(":")
            effort = effort or "none"
            label = f"{alias}-{effort}"
            cdir = args.out / label
            cdir.mkdir(exist_ok=True)
            rec = story.Recorder()
            sel_rec = story.Recorder()
            map_file = cdir / "story_map.json"
            started = time.monotonic()
            try:
                read_file = cdir / "read_map.json"
                if map_file.exists():
                    smap = smap_from_json(json.loads(map_file.read_text()))
                else:
                    if read_file.exists():
                        smap = smap_from_json(json.loads(read_file.read_text()))
                    else:
                        smap = story.read_film(
                            units, meta, [], make_fn(client, alias, "read", "none"), params, rec
                        )
                        read_file.write_text(
                            json.dumps(smap_to_json(smap), ensure_ascii=False, indent=1)
                        )
                        print(f"[{label}] read: {len(smap.beats)} beats", flush=True)
                    story.link_film(smap, make_fn(client, alias, "link", effort), params, rec)
                    map_file.write_text(
                        json.dumps(smap_to_json(smap), ensure_ascii=False, indent=1)
                    )
                    calls_file = cdir / "map_calls.json"
                    prior = json.loads(calls_file.read_text()) if calls_file.exists() else []
                    calls_file.write_text(
                        json.dumps([*prior, *(dataclasses.asdict(c) for c in rec.calls)])
                    )
                res = story.run_selection(
                    smap,
                    units,
                    args.purpose,
                    target_s,
                    args.duration,
                    make_fn(client, alias, "select", effort),
                    make_fn(client, alias, "critic", effort),
                    params,
                    sel_rec,
                )
            except (story.StoryFormatError, httpx.HTTPError) as exc:
                (cdir / "failed_answer.txt").write_text(
                    f"{rec.last_text}\n---\n{sel_rec.last_text}\n"
                )
                print(f"[{label}] failed: {type(exc).__name__}: {exc}", flush=True)
                table.append({"candidate": label, "error": f"{type(exc).__name__}: {exc}"[:300]})
                continue
            map_calls = [
                story.CallRecord(**c) for c in json.loads((cdir / "map_calls.json").read_text())
            ]
            res.calls = [*map_calls, *res.calls]
            results.append((label, res))
            (cdir / "paper_cut.txt").write_text(story.render_text(res, params, label))
            row = {
                "candidate": label,
                "kept_s": res.checks["kept_s"],
                "parts": len(story.parts_of(res.kept, res.smap, params)),
                "beats": len(res.smap.beats),
                "checks": res.checks,
                "review": {k: res.review[k] for k in ("consistency", "density", "goal")},
                "passed": res.passed,
                "rounds": len(res.rounds),
                "pairs": story.pair_results(pairs, res.kept, res.smap, params),
                "steps": step_totals(res.calls),
                "total_s": round(time.monotonic() - started, 1),
                "notes": res.smap.notes,
            }
            table.append(row)
            (cdir / "measure.json").write_text(json.dumps(row, ensure_ascii=False, indent=1))
            print(f"[{label}] done: {row['kept_s']} s kept, critic {row['review']}", flush=True)
    (args.out / "measurements.json").write_text(json.dumps(table, ensure_ascii=False, indent=1))
    if results:
        title = f"Paper cuts: {args.title or args.video_id}"
        (args.out / "paper_cuts.html").write_text(story.render_html(results, params, title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
