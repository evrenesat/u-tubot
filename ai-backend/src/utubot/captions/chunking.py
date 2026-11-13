"""Cut long audio into overlapping chunks and stitch the transcripts back together.

Chunks overlap by `overlap_s` so a word cut by one chunk edge is whole in the neighbour. Stitching
keeps, from each chunk, only what lies on its side of the midpoint of every overlap, then removes
words that the two sides still say twice (an engine's segment can straddle the cut).
"""

from __future__ import annotations

import re
import wave
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from .types import Segment, Word

MIN_TAIL_S = 3.0
DEDUPE_MAX_WORDS = 12
DEDUPE_MIN_WORDS = 2
NON_WORD_RE = re.compile(r"[^\w]+", re.UNICODE)


@dataclass
class StitchStats:
    """What stitching did, for the job's event log: items cut at the overlaps, words dropped as repeats."""

    cut: int = 0
    repeated_words: int = 0


@dataclass(frozen=True)
class Span:
    index: int
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def plan_chunks(total_s: float, chunk_s: float, overlap_s: float) -> list[Span]:
    """Spans of at most `chunk_s` (0 or less: one span) covering `total_s`, each overlapping the last.

    A tail shorter than `MIN_TAIL_S` is folded into the previous chunk instead of becoming a clip
    too short to transcribe reliably, so the last chunk may exceed `chunk_s` by that much.
    """
    if total_s <= 0:
        return []
    if chunk_s <= 0 or total_s <= chunk_s:
        return [Span(0, 0.0, total_s)]
    overlap = min(max(overlap_s, 0.0), chunk_s / 2)
    spans: list[Span] = []
    start = 0.0
    while True:
        end = min(start + chunk_s, total_s)
        if total_s - end < MIN_TAIL_S:
            end = total_s
        spans.append(Span(len(spans), start, end))
        if end >= total_s:
            return spans
        start = end - overlap


def write_chunk(source: Path, span: Span, target: Path) -> Path:
    """Copy `span` of a PCM WAV file into `target` (blocking: run it in a thread)."""
    with wave.open(str(source), "rb") as src:
        rate = src.getframerate()
        first = min(int(span.start * rate), src.getnframes())
        count = max(int(span.duration * rate), 0)
        src.setpos(first)
        frames = src.readframes(count)
        with wave.open(str(target), "wb") as out:
            out.setnchannels(src.getnchannels())
            out.setsampwidth(src.getsampwidth())
            out.setframerate(rate)
            out.writeframes(frames)
    return target


class Timed(Protocol):
    start: float
    end: float
    text: str


def shift[T: (Segment, Word)](items: list[T], offset: float) -> list[T]:
    return [replace(item, start=item.start + offset, end=item.end + offset) for item in items]


def words_of(text: str) -> list[str]:
    return [w for w in NON_WORD_RE.split(text.lower()) if w]


def _keep_range(index: int, spans: list[Span]) -> tuple[float, float]:
    """The stretch of the timeline chunk `index` is trusted for: cut at the middle of each overlap."""
    low = -float("inf") if index == 0 else (spans[index].start + spans[index - 1].end) / 2
    last = index == len(spans) - 1
    high = float("inf") if last else (spans[index + 1].start + spans[index].end) / 2
    return low, high


def _mid(item: Timed) -> float:
    return (item.start + item.end) / 2


def cut_overlaps[T: (Segment, Word)](
    parts: list[list[T]], spans: list[Span], stats: StitchStats | None = None
) -> list[list[T]]:
    """Per chunk, the items (times already absolute) that fall in the stretch it owns."""
    kept: list[list[T]] = []
    for index, items in enumerate(parts):
        low, high = _keep_range(index, spans)
        kept.append([item for item in items if low <= _mid(item) < high])
        if stats is not None:
            stats.cut += len(items) - len(kept[-1])
    return kept


def _repeat_length(previous: list[str], following: list[str]) -> int:
    for size in range(
        min(DEDUPE_MAX_WORDS, len(previous), len(following)), DEDUPE_MIN_WORDS - 1, -1
    ):
        if previous[-size:] == following[:size]:
            return size
    return 0


def _drop_leading_words(text: str, count: int) -> str:
    parts = text.split()
    taken = 0
    for position, part in enumerate(parts):
        if words_of(part):
            taken += len(words_of(part))
        if taken >= count:
            return " ".join(parts[position + 1 :])
    return ""


def dedupe_segments(
    parts: list[list[Segment]], spans: list[Span], stats: StitchStats | None = None
) -> list[Segment]:
    """Join chunk segments; text a chunk repeats from its predecessor's end is cut from its start.

    Only a chunk whose first segment starts inside the overlap with the previous chunk can repeat it.
    """
    out: list[Segment] = []
    for index, items in enumerate(parts):
        if not items:
            continue
        if out and index > 0 and items[0].start < spans[index - 1].end:
            tail = [w for seg in out[-3:] for w in words_of(seg.text)]
            repeat = _repeat_length(tail, words_of(items[0].text))
            if repeat:
                if stats is not None:
                    stats.repeated_words += repeat
                head = replace(items[0], text=_drop_leading_words(items[0].text, repeat))
                items = [head, *items[1:]] if head.text else items[1:]
        out.extend(items)
    return out


def dedupe_words(
    parts: list[list[Word]], spans: list[Span], stats: StitchStats | None = None
) -> list[Word]:
    out: list[Word] = []
    for index, items in enumerate(parts):
        if not items:
            continue
        if out and index > 0 and items[0].start < spans[index - 1].end:
            tail = [_bare(w.text) for w in out[-DEDUPE_MAX_WORDS:]]
            head = [_bare(w.text) for w in items[:DEDUPE_MAX_WORDS]]
            repeat = _repeat_length(tail, head)
            if stats is not None:
                stats.repeated_words += repeat
            items = items[repeat:]
        out.extend(items)
    return out


def _bare(word: str) -> str:
    return "".join(words_of(word))


def stitch_segments(
    parts: list[list[Segment]], spans: list[Span], stats: StitchStats | None = None
) -> list[Segment]:
    return dedupe_segments(cut_overlaps(parts, spans, stats), spans, stats)


def stitch_words(
    parts: list[list[Word]], spans: list[Span], stats: StitchStats | None = None
) -> list[Word]:
    return dedupe_words(cut_overlaps(parts, spans, stats), spans, stats)
