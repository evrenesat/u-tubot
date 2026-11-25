"""Bounded running context for the vision requests.

Adapted from `evrenesat/r2t4`, `scene-analyser/scene_memory.py` and the bounded strategy of
`context_strategies.py` at commit 29075554 (by the repository owner, contributed under MIT). The
memory is fed from u·tubot's transcript segments instead of subtitle files; it keeps the last
`recent_window_count` windows' exact lines and the last `carry_forward_scenes` visual summaries,
and never grows with the video (the earlier whole-episode run ended in HTTP 400).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

Segment = tuple[float, float, str]
SUMMARY_LINE_MAX_CHARS = 240
RECENT_MAX_CHARS = 0
NO_EARLIER = "(No earlier subtitle context.)"


@dataclass(frozen=True)
class SceneWindow:
    chunk_start: float
    chunk_end: float


@dataclass
class SceneRecord:
    chunk_start: float
    chunk_end: float
    visual_summary: str = ""
    kind: str = "other"
    seen: bool = False


@dataclass
class BoundedSnapshot:
    recent_lines: list[str] = field(default_factory=list)
    carry_summaries: list[dict[str, Any]] = field(default_factory=list)
    transcript_chars: int = 0
    recent_char_count: int = 0

    def metadata(self, context_end: float) -> dict[str, Any]:
        return {
            "mode": "bounded_memory",
            "context_end": context_end,
            "recent_char_count": self.recent_char_count,
            "carry_forward_scene_count": len(self.carry_summaries),
        }


class BoundedSceneMemory:
    def __init__(
        self,
        segments: list[Segment],
        recent_window_count: int = 3,
        carry_forward_scenes: int = 2,
    ) -> None:
        self._segments = sorted(segments, key=lambda event: (event[0], event[1], event[2]))
        self._recent_window_count = max(1, recent_window_count)
        self._carry_forward_scenes = max(0, carry_forward_scenes)
        self._windows: list[SceneWindow] = []
        self._records: list[SceneRecord] = []

    def build_snapshot(self, chunk_start: float, chunk_end: float) -> BoundedSnapshot:
        previous = self._windows[-(self._recent_window_count - 1) :]
        recent_start = min([chunk_start, *(window.chunk_start for window in previous)])
        recent = [
            segment
            for segment in self._segments
            if segment[0] <= chunk_end and segment[1] >= recent_start
        ]
        inside = [
            (round(start, 1), round(end, 1), text)
            for start, end, text in self._segments
            if start >= chunk_start and start <= chunk_end
        ]
        merged: dict[tuple[float, float, str], None] = {}
        for start, end, text in recent + inside:
            merged[(float(start), float(end), str(text))] = None
        lines = [
            f"{start:.1f}-{end:.1f}s: {text}"
            for start, end, text in sorted(merged, key=lambda item: (item[0], item[1], item[2]))
        ]
        summaries = [
            {
                "start": record.chunk_start,
                "end": record.chunk_end,
                "kind": record.kind,
                "summary": record.visual_summary[:SUMMARY_LINE_MAX_CHARS],
            }
            for record in self._records[-self._carry_forward_scenes :]
            if record.seen and record.visual_summary
        ]
        return BoundedSnapshot(
            recent_lines=lines,
            carry_summaries=summaries,
            transcript_chars=sum(len(line) for line in lines),
            recent_char_count=sum(len(line) for line in lines),
        )

    def inside_lines(self, chunk_start: float, chunk_end: float) -> list[str]:
        """The transcript text spoken inside one chunk, its own prompt context."""
        return [
            f"{start:.1f}-{end:.1f}s: {text}"
            for start, end, text in self._segments
            if start >= chunk_start and start <= chunk_end
        ]

    def record(
        self,
        chunk_start: float,
        chunk_end: float,
        *,
        visual_summary: str,
        kind: str,
        seen: bool,
    ) -> None:
        self._windows.append(SceneWindow(chunk_start=chunk_start, chunk_end=chunk_end))
        self._records.append(
            SceneRecord(
                chunk_start=chunk_start,
                chunk_end=chunk_end,
                visual_summary=visual_summary,
                kind=kind,
                seen=seen,
            )
        )


def format_recent(lines: list[str], limit_chars: int) -> str:
    """The recent exact lines, oldest dropped first when the prompt is over its hard limit."""
    if not lines:
        return "(No subtitles in the last scene windows.)"
    kept = list(lines)
    while kept and sum(len(line) + 1 for line in kept) > limit_chars:
        kept.pop(0)
    return "\n".join(kept)


def format_carry(summaries: list[dict[str, Any]]) -> str:
    if not summaries:
        return "Recent scene summaries:\n- None"
    lines = [
        f"- {entry['start']:.1f}-{entry['end']:.1f}s [{entry['kind']}] {entry['summary']}"
        for entry in summaries
    ]
    return "Recent scene summaries:\n" + "\n".join(lines)
