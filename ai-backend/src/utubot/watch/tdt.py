"""The slim Timed Descriptive Transcript of the watched cut and its validator.

Adapted from `evrenesat/r2t4`, `scene-analyser/tdt_format.py` at commit 29075554 (by the
repository owner, contributed under MIT). The film fields (mood, tension, discomfort) are not
part of this plan; a u·tubot segment carries what the cut needs: the chunk window, the four
frame times, a short visual summary and the kind of picture. Segments are assembled by code,
never authored by a model, and a validator keeps their shape before the row is stored.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .grids import ManifestRow

TDT_FORMAT_ID = "tdt"
TDT_FORMAT_VERSION = "1.0-utubot"
KINDS = (
    "talking_head",
    "screen",
    "slide",
    "demo",
    "broll",
    "title_card",
    "sponsor_card",
    "other",
)
LABEL_VOCAB_VERSION = 1
CATEGORIES = (
    "violence",
    "gore",
    "sex",
    "nudity",
    "language",
    "drugs",
    "frightening",
    "flashing",
)
SUMMARY_MAX_CHARS = 240
ON_SCREEN_MAX_CHARS = 160
UNKNOWN = "unknown"


class DescribeFormatError(ValueError):
    """A vision answer that breaks the describe format; one retry may repair it."""

    def __init__(self, problem: str):
        super().__init__(problem)
        self.problem = problem


@dataclass
class SceneAnalysis:
    visual_summary: str
    kind: str
    on_screen_text: str
    same_as_previous: bool
    seen: bool = True


def parse_description(data: Any) -> SceneAnalysis:
    """The vision model's JSON answer as one scene, or `DescribeFormatError` naming the problem."""
    if not isinstance(data, dict):
        raise DescribeFormatError("the answer is not a JSON object")
    summary = data.get("visual_summary")
    if not isinstance(summary, str) or not summary.strip():
        raise DescribeFormatError("'visual_summary' is missing or empty")
    summary = " ".join(summary.split())
    if len(summary) > SUMMARY_MAX_CHARS:
        raise DescribeFormatError(f"'visual_summary' is longer than {SUMMARY_MAX_CHARS} characters")
    kind = str(data.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise DescribeFormatError(f"'kind' must be one of {', '.join(KINDS)}")
    on_screen = data.get("on_screen_text")
    if on_screen is None:
        on_screen = ""
    if not isinstance(on_screen, str):
        raise DescribeFormatError("'on_screen_text' must be a string")
    on_screen = " ".join(on_screen.split())
    if len(on_screen) > ON_SCREEN_MAX_CHARS:
        raise DescribeFormatError(
            f"'on_screen_text' is longer than {ON_SCREEN_MAX_CHARS} characters"
        )
    same = data.get("same_as_previous")
    if not isinstance(same, bool):
        raise DescribeFormatError("'same_as_previous' must be true or false")
    return SceneAnalysis(
        visual_summary=summary, kind=kind, on_screen_text=on_screen, same_as_previous=same
    )


def prompt_hash(cfg: Any) -> str:
    blob = (
        f"{TDT_FORMAT_VERSION}|{cfg.describe_context_chars}|{cfg.recent_window_count}|"
        f"{cfg.carry_forward_scenes}|{','.join(KINDS)}"
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def assemble(
    *,
    video_sha256: str,
    settings_key: str,
    model: str,
    prompt_hash: str,
    scene_cuts: list[float],
    rows: list[ManifestRow],
    analyses: dict[str, SceneAnalysis],
    unit_ids: list[list[int]] | None = None,
) -> dict[str, Any]:
    """The TDT payload: every manifest row becomes one segment, aligned to its chunk window."""
    segments: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        analysis = analyses.get(row.grid_filename)
        seen = analysis is not None
        scene = analysis or SceneAnalysis("", "other", "", False, seen=False)
        segments.append(
            {
                "segment_id": f"S{index + 1}",
                "grid_filename": row.grid_filename,
                "start": row.chunk_start,
                "end": row.chunk_end,
                "timestamps": row.selected_timestamps,
                "visual_summary": scene.visual_summary,
                "labels": {
                    "kind": scene.kind,
                    "on_screen_text": scene.on_screen_text,
                    "same_as_previous": scene.same_as_previous,
                },
                "unit_ids": unit_ids[index] if unit_ids and index < len(unit_ids) else [],
                "analysis_provenance": {
                    "model": model,
                    "prompt_version": prompt_hash,
                    "retry_count": 0,
                    "seen": seen,
                },
            }
        )
    return {
        "format": TDT_FORMAT_ID,
        "format_version": TDT_FORMAT_VERSION,
        "video_sha256": video_sha256,
        "settings_key": settings_key,
        "model": model,
        "prompt_hash": prompt_hash,
        "scene_cuts": list(scene_cuts),
        "segments": segments,
    }


def validate_tdt(
    payload: dict[str, Any], expected_rows: list[ManifestRow] | None = None
) -> list[str]:
    """Errors of a TDT payload; empty means it may be stored."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["the TDT is not a JSON object"]
    for field in (
        "format",
        "format_version",
        "video_sha256",
        "settings_key",
        "model",
        "prompt_hash",
        "scene_cuts",
        "segments",
    ):
        if field not in payload:
            errors.append(f"missing top-level field: {field}")
    if payload.get("format") != TDT_FORMAT_ID:
        errors.append(f"format must be {TDT_FORMAT_ID!r}")
    if payload.get("format_version") != TDT_FORMAT_VERSION:
        errors.append(f"format_version must be {TDT_FORMAT_VERSION!r}")
    segments = payload.get("segments")
    if not isinstance(segments, list):
        errors.append("segments must be a list")
        return errors
    if expected_rows is not None and len(segments) != len(expected_rows):
        errors.append("segments length does not match the manifest")
    previous_end = -1.0
    seen_ids: set[str] = set()
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            errors.append(f"segments[{index}] must be an object")
            continue
        for field in ("segment_id", "grid_filename", "start", "end", "visual_summary", "labels"):
            if field not in segment:
                errors.append(f"segments[{index}] missing field: {field}")
        segment_id = segment.get("segment_id")
        if not isinstance(segment_id, str) or not segment_id:
            errors.append(f"segments[{index}] segment_id must be a string")
        elif segment_id in seen_ids:
            errors.append(f"segments[{index}] duplicate segment_id")
        else:
            seen_ids.add(segment_id)
        start, end = segment.get("start"), segment.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            errors.append(f"segments[{index}] start/end must be numbers")
        else:
            if end < start:
                errors.append(f"segments[{index}] end must be >= start")
            if start < previous_end:
                errors.append("segments must be sorted by time")
            previous_end = max(previous_end, float(end))
        labels = segment.get("labels")
        if not isinstance(labels, dict):
            errors.append(f"segments[{index}] labels must be an object")
        else:
            if labels.get("kind") not in KINDS:
                errors.append(f"segments[{index}] labels.kind is invalid")
            on_screen = labels.get("on_screen_text")
            if on_screen is not None and not isinstance(on_screen, str):
                errors.append(f"segments[{index}] labels.on_screen_text must be a string")
            if not isinstance(labels.get("same_as_previous"), bool):
                errors.append(f"segments[{index}] labels.same_as_previous must be a bool")
            errors.extend(validate_content(labels.get("content"), index))
        provenance = segment.get("analysis_provenance")
        if not isinstance(provenance, dict):
            errors.append(f"segments[{index}] analysis_provenance must be an object")
        if expected_rows is not None and index < len(expected_rows):
            row = expected_rows[index]
            if segment.get("grid_filename") != row.grid_filename:
                errors.append(f"segments[{index}] grid_filename does not match the manifest")
            if abs(float(segment.get("start") or 0) - row.chunk_start) > 1e-6:
                errors.append(f"segments[{index}] start does not match the chunk window")
            if abs(float(segment.get("end") or 0) - row.chunk_end) > 1e-6:
                errors.append(f"segments[{index}] end does not match the chunk window")
    return errors


def validate_content(content: Any, index: int) -> list[str]:
    """The optional future filter list (#88); absent here, validated when present."""
    if content is None:
        return []
    if not isinstance(content, list):
        return [f"segments[{index}] labels.content must be a list"]
    errors: list[str] = []
    for entry in content:
        if not isinstance(entry, dict):
            errors.append(f"segments[{index}] labels.content entry must be an object")
            continue
        if entry.get("category") not in CATEGORIES:
            errors.append(f"segments[{index}] labels.content category is invalid")
        intensity = entry.get("intensity")
        if not isinstance(intensity, int) or not 0 <= intensity <= 3:
            errors.append(f"segments[{index}] labels.content intensity must be 0 to 3")
        confidence = entry.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            errors.append(f"segments[{index}] labels.content confidence must be 0 to 1")
    return errors
