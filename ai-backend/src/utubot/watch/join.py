"""Join the TDT scenes with transcript units; snap kept boundaries to real shot cuts.

Adapted from scene-analyser's idea that a scene line is evidence and only unit ids may be kept
(`evrenesat/r2t4` at 29075554; by the repository owner, contributed under MIT). Silent stretches
become ordinary `(no speech)` units so a silent demo can be chosen by id like any other part.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import WatchedCutsConfig
from ..cuts import Part, Unit, build_units, serialize_units
from ..transcripts import fmt_ts
from .tdt import KINDS

NO_SPEECH = "(no speech)"
S_LINE = "S"
UNIT_LINE = "#"
WATCHED_SYSTEM_ADDITION = (
    " Lines starting with S describe what was on screen in that time range; they are evidence "
    "for your choice. Only # unit ids can be kept: never name an S line as a kept part."
)


@dataclass
class SceneLine:
    number: int
    start: float
    end: float
    kind: str
    visual_summary: str
    on_screen_text: str


@dataclass
class WatchedJoin:
    units: list[Unit]
    scenes: list[SceneLine]
    unit_ids: dict[int, list[int]]


def watched_units(
    segments: list[tuple[float, float, str]],
    tdt: dict[str, Any],
    cfg: WatchedCutsConfig,
    *,
    duration_s: float | None = None,
    cuts_cfg: Any,
) -> list[Unit]:
    """Speech units plus `(no speech)` units for silent gaps; ids are one sequence."""
    speech = build_units(segments, cuts_cfg)
    spans: list[tuple[float, float, str]] = [(unit.start, unit.end, unit.text) for unit in speech]
    tdt_segments = [segment for segment in tdt.get("segments") or [] if isinstance(segment, dict)]
    boundaries = sorted(float(segment["start"]) for segment in tdt_segments) + sorted(
        float(segment["end"]) for segment in tdt_segments
    )
    duration = float(duration_s or (spans[-1][1] if spans else 0.0))
    at = 0.0
    gaps: list[tuple[float, float]] = []
    for start, end, _text in spans:
        if start - at > cfg.silent_unit_min_s:
            gaps.append((at, start))
        at = max(at, end)
    if duration - at > cfg.silent_unit_min_s:
        gaps.append((at, duration))
    for gap_start, gap_end in gaps:
        points = sorted(
            {gap_start, gap_end, *[value for value in boundaries if gap_start < value < gap_end]}
        )
        for left, right in zip(points, points[1:], strict=False):
            if right - left <= 0:
                continue
            cursor = left
            while right - cursor > 1e-6:
                end = min(right, cursor + cuts_cfg.unit_max_s)
                spans.append((cursor, end, NO_SPEECH))
                cursor = end
    spans.sort(key=lambda item: (item[0], item[1]))
    units = [Unit(number, start, end, text) for number, (start, end, text) in enumerate(spans, 1)]
    return units


def scene_lines(tdt: dict[str, Any]) -> list[SceneLine]:
    """One S line per TDT segment, collapsing consecutive same-kind repeats."""
    segments = [segment for segment in tdt.get("segments") or [] if isinstance(segment, dict)]
    lines: list[SceneLine] = []
    for segment in segments:
        labels = segment.get("labels") or {}
        kind = str(labels.get("kind") or "other")
        summary = str(segment.get("visual_summary") or "").strip()
        on_screen = str(labels.get("on_screen_text") or "").strip()
        same = bool(labels.get("same_as_previous"))
        previous = lines[-1] if lines else None
        if previous is not None and same and previous.kind == kind:
            previous.end = float(segment["end"])
            previous.visual_summary = previous.visual_summary or summary
            previous.on_screen_text = previous.on_screen_text or on_screen
        else:
            lines.append(
                SceneLine(
                    number=len(lines) + 1,
                    start=float(segment["start"]),
                    end=float(segment["end"]),
                    kind=kind if kind in KINDS else "other",
                    visual_summary=summary,
                    on_screen_text=on_screen,
                )
            )
    return lines


def assign_unit_ids(units: list[Unit], tdt: dict[str, Any]) -> dict[int, list[int]]:
    """A unit belongs to the segment it overlaps most; a segment lists those unit ids."""
    segments = [segment for segment in tdt.get("segments") or [] if isinstance(segment, dict)]
    out: dict[int, list[int]] = {index + 1: [] for index in range(len(segments))}
    for unit in units:
        best = None
        best_overlap = 0.0
        for index, segment in enumerate(segments, 1):
            start, end = float(segment["start"]), float(segment["end"])
            overlap = max(0.0, min(unit.end, end) - max(unit.start, start))
            if overlap > best_overlap:
                best, best_overlap = index, overlap
        if best is not None and best_overlap > 0:
            out[best].append(unit.n)
    return out


def watched_serialize(
    units: list[Unit],
    scenes: list[SceneLine],
    chapters: list[tuple[float, str]],
    meta: dict[str, Any],
    instruction: str,
    target_s: int | None = None,
    over_ask_frac: float = 0.0,
    *,
    drop_talking_head_summaries: bool = False,
) -> str:
    """The watched editor message: video facts, task, then S evidence and # units in time order.

    `drop_talking_head_summaries` removes the visual summary of collapsed `talking_head` scene
    lines, which is the first thing dropped when a watched prompt is over its token budget."""
    header = serialize_units(units, chapters, meta, instruction, target_s, over_ask_frac)
    lines = header.splitlines()
    marker_index = lines.index("Transcript units (each line starts with its id and time range):")
    head, tail = lines[:marker_index], lines[marker_index + 1 :]
    body: list[tuple[float, str]] = []
    for scene in scenes:
        summary = scene.visual_summary
        if drop_talking_head_summaries and scene.kind == "talking_head":
            summary = ""
        text = f" {summary}" if summary else ""
        shown = f'; text: "{scene.on_screen_text}"' if scene.on_screen_text else ""
        body.append(
            (
                scene.start,
                f"S{scene.number} [{fmt_ts(scene.start)}-{fmt_ts(scene.end)}] "
                f"{scene.kind}:{text}{shown}",
            )
        )
    for unit in units:
        body.append(
            (
                unit.start,
                f"#{unit.n} [{fmt_ts(unit.start)}-{fmt_ts(unit.end)}] {unit.text}",
            )
        )
    body.sort(key=lambda item: item[0])
    legend = (
        "Scenes and transcript (lines starting with S are what is on screen, lines starting with "
        "# are units you can keep):"
    )
    return "\n".join([*head, legend, *(line for _at, line in body), *tail])


def snap_parts(
    parts: list[Part],
    scene_cuts: list[float],
    units: list[Unit],
    snap_s: float,
) -> list[Part]:
    """Move a part outward to a real shot cut within `snap_s`, never across a speech unit."""
    cuts = sorted(scene_cuts)
    speech = [unit for unit in units if unit.text != NO_SPEECH]

    def speech_between(start_ms: int, end_ms: int) -> bool:
        for unit in speech:
            a, b = int(unit.start * 1000), int(unit.end * 1000)
            if b > start_ms and a < end_ms:
                return True
        return False

    snapped: list[Part] = []
    for part in parts:
        start_ms, end_ms = part.start_ms, part.end_ms
        backwards = [cut for cut in cuts if start_ms - snap_s * 1000 <= cut * 1000 <= start_ms]
        if backwards:
            candidate = int(round(backwards[-1] * 1000))
            if not speech_between(candidate, start_ms):
                start_ms = candidate
        forwards = [cut for cut in cuts if end_ms <= cut * 1000 <= end_ms + snap_s * 1000]
        if forwards:
            candidate = int(round(forwards[0] * 1000))
            if not speech_between(end_ms, candidate):
                end_ms = candidate
        snapped.append(Part(part.label, start_ms, end_ms))
    return snapped
