"""One sequential vision request per 2x2 grid with bounded running context.

Adapted from `evrenesat/r2t4` (`scene-analyser/context_strategies.py` bounded-memory strategy and
`inference_runner.py`'s sequential loop at commit 29075554; by the repository owner, contributed
under MIT). The prompt is fed from u·tubot's transcript, never grows with the video, and an HTTP
400 is retried once with half the context. Finished segments are written to the cache row as they
come in, so a restart continues at the next grid.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..config import Config
from ..llm import INTERACTIVE, LLMClient, LLMError
from ..transcripts import Transcript, fmt_ts
from .grids import GRIDS_DIRNAME, GridPlan, ManifestRow, settings_key
from .memory import BoundedSceneMemory, format_carry, format_recent
from .tdt import (
    DescribeFormatError,
    SceneAnalysis,
    assemble,
    parse_description,
    prompt_hash,
    validate_tdt,
)

log = logging.getLogger("utubot.watch")

SYSTEM_PROMPT = (
    "You describe one moment of a video for a TV editor. The picture is one grid of four frames "
    "from a short, continuous moment, in time order. Treat the grid as one scene; never mention "
    "the grid or count the frames, never reveal or guess the source, and keep it brief, objective "
    "and factual. The picture is the primary evidence; the transcript is supporting context only. "
    "Say 'unknown' when the picture does not show something. "
    "Reply ONLY with JSON: "
    '{"visual_summary":"<at most 240 characters, what happens on screen>",'
    '"kind":"talking_head|screen|slide|demo|broll|title_card|sponsor_card|other",'
    '"on_screen_text":"<readable text on screen, at most 160 characters, or \\"\\">",'
    '"same_as_previous":<true|false>}'
)

USER_TEMPLATE = (
    "Describe this scene grid as one chronological moment.\n"
    "Scene timing: {start} to {end}.\n"
    "Transcript spoken inside this scene:\n{inside}\n\n"
    "Recent exact transcript lines from the last few scenes:\n{recent}\n\n"
    "Carry-forward state from earlier successful scene descriptions:\n{carry}"
)

CONTEXT_HALF = 0.5
DESCRIBE_SYSTEM_MARK = "You describe one moment of a video"
MAX_UNSEEN_MARGIN = 1e-9
GRID_JPEG = "image/jpeg"


@dataclass
class DescribingResult:
    tdt: dict[str, Any]
    partial: bool
    unseen: int
    seen: int
    seconds: list[float] = field(default_factory=list)
    raw_records: list[dict[str, Any]] = field(default_factory=list)


def is_watched_installed() -> bool:
    try:
        import PIL  # noqa: F401
    except ImportError:
        return False
    try:
        import subprocess

        return subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False


def describe_message(
    row: ManifestRow,
    plan: GridPlan,
    memory: BoundedSceneMemory,
    context_chars: int,
    image_bytes: bytes,
) -> list[dict[str, Any]]:
    snapshot = memory.build_snapshot(row.chunk_start, row.chunk_end)
    inside = "\n".join(memory.inside_lines(row.chunk_start, row.chunk_end)) or "(No speech.)"
    recent = format_recent(snapshot.recent_lines, context_chars)
    carry = format_carry(snapshot.carry_summaries)
    text = USER_TEMPLATE.format(
        start=fmt_ts(row.chunk_start),
        end=fmt_ts(row.chunk_end),
        inside=inside,
        recent=recent,
        carry=carry,
    )
    image = "data:" + GRID_JPEG + ";base64," + base64.b64encode(image_bytes).decode("ascii")
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": image}},
            ],
        },
    ]


async def _ask(
    llm: LLMClient,
    cfg: Config,
    messages: list[dict[str, Any]],
    *,
    timeout_s: float,
) -> tuple[Any, str]:
    task = cfg.llm.cuts_vision
    if task is None:
        raise LLMError("watched cuts have no vision model")
    result = await asyncio.wait_for(
        llm.chat_result(task, messages, priority=INTERACTIVE, deadline_s=timeout_s),
        timeout_s,
    )
    return _json_or_error(result.text), result.text


def _json_or_error(text: str) -> Any:
    from ..llm import extract_json

    try:
        return extract_json(text)
    except ValueError:
        raise DescribeFormatError("the answer was not a JSON object") from None


async def describe_scenes(
    cfg: Config,
    llm: LLMClient,
    plan: GridPlan,
    transcript: Transcript,
    video_sha256: str,
    *,
    existing_tdt: dict[str, Any] | None = None,
    progress: Callable[[float], None] | None = None,
    on_segment: Callable[[dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    yield_check: Callable[[], Awaitable[None]] | None = None,
) -> DescribingResult:
    """Describe every grid in order, resuming the seen segments of `existing_tdt`."""
    task = cfg.llm.cuts_vision
    if task is None:
        raise LLMError("watched cuts have no vision model")
    watched = cfg.cuts.watched
    p_hash = prompt_hash(watched)
    memory = BoundedSceneMemory(
        transcript.segments or [],
        recent_window_count=watched.recent_window_count,
        carry_forward_scenes=watched.carry_forward_scenes,
    )
    analyses: dict[str, SceneAnalysis] = {}
    records: list[dict[str, Any]] = []
    seconds: list[float] = []
    if existing_tdt:
        for segment in existing_tdt.get("segments") or []:
            provenance = segment.get("analysis_provenance") or {}
            if not provenance.get("seen"):
                continue
            labels = segment.get("labels") or {}
            analyses[str(segment["grid_filename"])] = SceneAnalysis(
                visual_summary=str(segment.get("visual_summary") or ""),
                kind=str(labels.get("kind") or "other"),
                on_screen_text=str(labels.get("on_screen_text") or ""),
                same_as_previous=bool(labels.get("same_as_previous")),
            )
            memory.record(
                float(segment["start"]),
                float(segment["end"]),
                visual_summary=analyses[str(segment["grid_filename"])].visual_summary,
                kind=analyses[str(segment["grid_filename"])].kind,
                seen=True,
            )
    for row in plan.manifest:
        if row.grid_filename in analyses:
            continue
        if should_stop is not None and should_stop():
            raise LLMError("the watched build was dismissed")
        path = plan.grid_dir / GRIDS_DIRNAME / row.grid_filename
        if not path.is_file():
            raise LLMError("the grid file is gone before describing")
        started = time.monotonic()
        retry = 0
        error: str | None = None
        raw = ""
        context = watched.describe_context_chars
        seen = False
        try:
            messages = describe_message(row, plan, memory, context, path.read_bytes())
            data, raw = await _ask(llm, cfg, messages, timeout_s=watched.describe_timeout_s)
            try:
                scene = parse_description(data)
            except DescribeFormatError as exc:
                retry = 1
                messages.append({"role": "assistant", "content": raw[:2000]})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Your previous answer was rejected: {exc.problem}. "
                            "Reply with the JSON object only."
                        ),
                    }
                )
                data, raw = await _ask(llm, cfg, messages, timeout_s=watched.describe_timeout_s)
                scene = parse_description(data)
            seen = True
        except LLMError as exc:
            error = str(exc)
            if "http 400" in error:
                try:
                    retry = 2
                    messages = describe_message(
                        row,
                        plan,
                        memory,
                        max(1, int(context * CONTEXT_HALF)),
                        path.read_bytes(),
                    )
                    data, raw = await _ask(llm, cfg, messages, timeout_s=watched.describe_timeout_s)
                    scene = parse_description(data)
                    seen = True
                except (LLMError, DescribeFormatError) as exc2:
                    error = str(exc2)
        except DescribeFormatError as exc:
            error = f"invalid answer after one retry: {exc.problem}"
        except TimeoutError:
            error = "the vision request took too long"
        elapsed = round(time.monotonic() - started, 3)
        seconds.append(elapsed)
        records.append(
            {
                "grid_filename": row.grid_filename,
                "seconds": elapsed,
                "retry_count": retry,
                "raw_char_count": len(raw),
                "error": error,
            }
        )
        if seen:
            analyses[row.grid_filename] = scene
            memory.record(
                row.chunk_start,
                row.chunk_end,
                visual_summary=scene.visual_summary,
                kind=scene.kind,
                seen=True,
            )
        if on_segment is not None:
            on_segment(
                assemble(
                    video_sha256=video_sha256,
                    settings_key=settings_key(watched),
                    model=task.model,
                    prompt_hash=p_hash,
                    scene_cuts=plan.scene_cuts,
                    rows=plan.manifest,
                    analyses=analyses,
                )
            )
        if progress is not None:
            progress(len(records) / max(1, len(plan.manifest)))
        # A prime demanding job that arrived while this grid was described takes the slot next;
        # stop after the grid, resume later. Describing is resumable per grid, so the paused
        # build continues at the next one with the same stored TDT.
        if yield_check is not None:
            await yield_check()
    seen_count = len(analyses)
    unseen = len(plan.manifest) - seen_count
    partial = unseen > 0
    tdt = assemble(
        video_sha256=video_sha256,
        settings_key=settings_key(watched),
        model=task.model,
        prompt_hash=p_hash,
        scene_cuts=plan.scene_cuts,
        rows=plan.manifest,
        analyses=analyses,
    )
    tdt["records"] = records
    errors = validate_tdt(tdt, plan.manifest)
    if errors:
        raise DescribeFormatError("; ".join(errors[:3]))
    if plan.manifest and unseen / len(plan.manifest) > watched.max_unseen_frac + MAX_UNSEEN_MARGIN:
        raise LLMError(
            f"{unseen} of {len(plan.manifest)} scenes could not be seen; "
            "a watched cut needs at least most of the video described"
        )
    return DescribingResult(
        tdt=tdt,
        partial=partial,
        unseen=unseen,
        seen=seen_count,
        seconds=seconds,
        raw_records=records,
    )


def tdt_cache_key(cfg: Config, video_sha256: str, model: str, thash: str) -> str:
    watched = cfg.cuts.watched
    blob = f"{video_sha256}|{settings_key(watched)}|{model}|{prompt_hash(watched)}|{thash}"
    return hashlib.sha256(blob.encode()).hexdigest()


def tdt_from_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
