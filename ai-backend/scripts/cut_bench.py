#!/usr/bin/env python3
"""Score director's-cut models offline against the hand-marked test set.

The set lives in `utubot.cutbench`: six hand-written transcripts and 19 requests, with
must-keep and must-skip spans marked by hand. Each request runs the real engine pieces
(units -> the model -> parse -> validate -> finalize) and is marked on how much of the
must-keep time survived and how much must-skip time leaked into the cut.

No YouTube, no app database: the model is reached directly, one OpenAI-compatible
chat-completions call per request (the same shape the backend sends):

    cd ai-backend
    uv run python scripts/cut_bench.py --list --base-url http://gateway:8787/v1 --api-key-env KEY_ENV
    uv run python scripts/cut_bench.py --model light --model heavy --base-url ... --api-key-env ...
    uv run python scripts/cut_bench.py --model light --json temp/cuts-scores.json

The key is read from the named environment variable and never logged. Results print per
request; pass --json to also write the full result document.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from utubot.cutbench import LONG_TRANSCRIPT, TRANSCRIPTS, RequestResult, summarize  # noqa: E402


def _client_model_fn(client: httpx.Client, model: str, timeout_s: float):
    """The model call the scorer uses: messages in, `(text, usage)` out."""

    def call(messages: list[dict[str, str]]) -> tuple[str, dict]:
        response = client.post(
            "/chat/completions",
            json={"model": model, "messages": messages},
            timeout=timeout_s,
        )
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        return text, usage

    return call


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--base-url", default="http://127.0.0.1:8787/v1", help="OpenAI-compatible base URL"
    )
    parser.add_argument(
        "--api-key-env", default=None, help="env var holding the bearer token (never logged)"
    )
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help="model/alias to score (repeatable; default: every alias of /models)",
    )
    parser.add_argument(
        "--list", action="store_true", help="list the models the endpoint serves and exit"
    )
    parser.add_argument(
        "--long",
        action="store_true",
        help="also score the three-hour case, which runs by map/reduce (many model calls)",
    )
    parser.add_argument("--timeout-s", type=float, default=900.0, help="per-request timeout")
    parser.add_argument(
        "--json", dest="json_path", default=None, help="write the full results document here"
    )
    args = parser.parse_args()

    key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=args.timeout_s) as client:
        if args.list:
            response = client.get("/models")
            response.raise_for_status()
            for model in response.json().get("data", []):
                print(model.get("id"))
            return 0
        models = args.model
        if not models:
            response = client.get("/models")
            response.raise_for_status()
            models = [m.get("id") for m in response.json().get("data", []) if m.get("id")]
            print(f"no --model given; scoring every alias the endpoint serves: {', '.join(models)}")

        started = time.monotonic()
        documents: list[dict] = []
        summaries: list[dict] = []
        for model in models:
            print(f"\n=== {model} ===")
            results: list[RequestResult] = []
            for transcript in [*TRANSCRIPTS, *([LONG_TRANSCRIPT] if args.long else [])]:
                t0 = time.monotonic()
                got = score_all_for_model(client, model, args.timeout_s, [transcript])
                results.extend(got)
                for row in got:
                    print("  " + row.row())
                print(f"  ({transcript.id} scored in {time.monotonic() - t0:.0f}s)")
            summary = summarize(results)
            summaries.append(summary)
            documents.append(
                {"model": model, "summary": summary, "results": [vars(r) for r in results]}
            )
            print(
                f"--- {model}: keep {summary['mean_keep']:.2f} skip {summary['mean_skip']:.2f}"
                f" excess {summary['mean_excess']:.2f} score {summary['mean_score']:+.2f}"
                f" refused {summary['refused']}"
                f" format {summary['format_errors']} wall {summary['mean_wall_s']}s/req"
            )

    print(f"\n{time.monotonic() - started:.0f}s total")
    for summary in sorted(summaries, key=lambda s: s["mean_score"], reverse=True):
        print(
            f"{summary['model']:<24} score {summary['mean_score']:+.3f}"
            f" (keep {summary['mean_keep']:.3f} skip {summary['mean_skip']:.3f}"
            f" excess {summary['mean_excess']:.3f})"
            f" refused {summary['refused']} format {summary['format_errors']}"
            f" repairs {summary['repairs']} {summary['mean_wall_s']}s/req"
        )
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"set": "cutbench v1", "runs": documents}, indent=2) + "\n")
        print(f"results written to {path}")
    return 0


def score_all_for_model(
    client: httpx.Client, model: str, timeout_s: float, transcripts
) -> list[RequestResult]:
    from utubot.cutbench import score_transcript

    model_fn = _client_model_fn(client, model, timeout_s)
    results: list[RequestResult] = []
    for transcript in transcripts:
        results.extend(score_transcript(transcript, model_fn, model))
    return results


if __name__ == "__main__":
    raise SystemExit(main())
