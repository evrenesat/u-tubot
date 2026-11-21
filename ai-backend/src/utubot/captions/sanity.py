"""Chunk review: is a chunk's transcript in the right language, and is it speech at all?

Whisper-style engines sometimes label a chunk with the wrong language and then make text up ("Thank
you" every 30 s over continuous speech). Pure functions: `flag_segments` marks segments that are not
speech, `chunk_health` summarises one chunk, `review` says which chunks deserve a second listen and
`drop_flagged` removes what a final answer still holds of the made-up text. The router
(`engines.AsrRouter`) runs the re-listening.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from ..config import CaptionsConfig
from .chunking import bare
from .types import Segment, Word

FLAG_NO_SPEECH = "no_speech"
FLAG_REPEAT = "repeat_loop"
FLAG_PHANTOM = "phantom"
FLAG_COMPRESSED = "compressed"
FLAG_LOW_CONF = "low_confidence"
DROP_FLAGS = frozenset({FLAG_NO_SPEECH, FLAG_REPEAT, FLAG_PHANTOM})
SHARE_FLAGS = DROP_FLAGS | {FLAG_COMPRESSED}  # what counts toward a chunk's flagged seconds

REASON_LANGUAGE = "language_mismatch"
REASON_HALLUCINATION = "hallucination"
REASON_SPARSE = "sparse"

SHARE_DIGITS = 2
MIN_DURATION_S = 0.01  # a segment shorter than this is rated as if it lasted this long


def base_code(code: str | None) -> str | None:
    return code.split("-")[0].lower() if code else None


def flag_segments(segments: list[Segment], cfg: CaptionsConfig) -> list[set[str]]:
    """Per segment, why it is probably not speech (see the `FLAG_*` names); empty set: no doubt."""
    phrases = {bare(p) for p in cfg.halluc_phrases}
    flags: list[set[str]] = [set() for _ in segments]
    for index, seg in enumerate(segments):
        if (
            seg.no_speech_prob is not None
            and seg.avg_logprob is not None
            and seg.no_speech_prob > cfg.halluc_no_speech_prob
            and seg.avg_logprob < cfg.halluc_avg_logprob
        ):
            flags[index].add(FLAG_NO_SPEECH)
        words = len(seg.text.split())
        rate = words / max(seg.end - seg.start, MIN_DURATION_S)
        if bare(seg.text) in phrases and rate < cfg.halluc_min_rate:
            flags[index].add(FLAG_PHANTOM)
        if (
            seg.compression_ratio is not None
            and seg.compression_ratio > cfg.halluc_compression_ratio
        ):
            flags[index].add(FLAG_COMPRESSED)
        if seg.avg_logprob is not None and seg.avg_logprob < cfg.halluc_avg_logprob:
            flags[index].add(FLAG_LOW_CONF)
    start = 0
    while start < len(segments):
        end = start
        key = bare(segments[start].text)
        while end + 1 < len(segments) and bare(segments[end + 1].text) == key:
            end += 1
        if key and end - start + 1 >= cfg.halluc_repeat_min:
            for index in range(start, end + 1):
                flags[index].add(FLAG_REPEAT)
        start = end + 1
    return flags


@dataclass
class ChunkHealth:
    language_ok: bool
    flagged_s: float
    flagged_share: float
    chars: int
    chars_per_s: float
    language: str | None = None
    reasons: list[str] = field(default_factory=list)

    def rank(self) -> tuple[bool, float, int]:
        """Higher is better: right language, then less made-up text, then more text."""
        return (self.language_ok, -round(self.flagged_share, SHARE_DIGITS), self.chars)


def chunk_health(
    segments: list[Segment],
    duration_s: float,
    language: str | None,
    expected: str | None,
    cfg: CaptionsConfig,
) -> ChunkHealth:
    """One chunk's health. `reasons` holds the ones a chunk shows alone (language, hallucination);
    `review` adds the one that needs its neighbours (sparse)."""
    flags = flag_segments(segments, cfg)
    flagged = sum(
        max(seg.end - seg.start, 0.0)
        for seg, found in zip(segments, flags, strict=True)
        if found & SHARE_FLAGS
    )
    span = max(duration_s, MIN_DURATION_S)
    flagged = min(flagged, span)
    chars = sum(len(seg.text) for seg in segments)
    language_ok = not (expected and language and base_code(language) != base_code(expected))
    health = ChunkHealth(
        language_ok, flagged, flagged / span, chars, chars / span, language=language
    )
    if not language_ok:
        health.reasons.append(REASON_LANGUAGE)
    if health.flagged_share >= cfg.halluc_chunk_share:
        health.reasons.append(REASON_HALLUCINATION)
    return health


def median_rate(healths: list[ChunkHealth]) -> float:
    return statistics.median(h.chars_per_s for h in healths) if healths else 0.0


def recheck_reasons(
    health: ChunkHealth, median_cps: float, chunks: int, cfg: CaptionsConfig
) -> list[str]:
    """The reasons a chunk asks for a second listen, given how its neighbours did."""
    reasons = list(health.reasons)
    if (
        chunks >= cfg.sparse_min_chunks
        and median_cps > 0
        and health.chars_per_s < cfg.sparse_chunk_ratio * median_cps
    ):
        reasons.append(REASON_SPARSE)
    return reasons


def review(healths: list[ChunkHealth], cfg: CaptionsConfig) -> list[list[str]]:
    """Per chunk, the reasons that ask for a recheck (empty: the chunk is fine)."""
    median = median_rate(healths)
    return [recheck_reasons(h, median, len(healths), cfg) for h in healths]


def drop_flagged(
    segments: list[Segment], words: list[Word], flags: list[set[str]]
) -> tuple[list[Segment], list[Word], list[Segment]]:
    """The segments and words left once the segments flagged as not speech are removed.

    Words go with the segment their midpoint lies in. The third item lists the dropped segments.
    """
    dropped = [seg for seg, found in zip(segments, flags, strict=True) if found & DROP_FLAGS]
    if not dropped:
        return segments, words, []
    kept = [seg for seg, found in zip(segments, flags, strict=True) if not found & DROP_FLAGS]
    kept_words = [
        w for w in words if not any(seg.start <= (w.start + w.end) / 2 < seg.end for seg in dropped)
    ]
    return kept, kept_words, dropped
