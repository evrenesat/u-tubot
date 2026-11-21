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
FLAG_CREDIT = "credit"
FLAG_COMPRESSED = "compressed"
FLAG_LOW_CONF = "low_confidence"
ALWAYS_DROPPED = frozenset({FLAG_NO_SPEECH, FLAG_PHANTOM, FLAG_CREDIT})
DROP_FLAGS = ALWAYS_DROPPED | {
    FLAG_REPEAT
}  # a repeat loop goes only when no re-listen reproduced it
SHARE_FLAGS = DROP_FLAGS | {FLAG_COMPRESSED}  # what counts toward a chunk's flagged seconds
TIMING_RANK = {"real": 2, "mixed": 1, "interpolated": 0}

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
    credits = {bare(p) for p in cfg.halluc_credits}
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
        if bare(seg.text) in credits:
            flags[index].add(
                FLAG_CREDIT
            )  # a credit line no speaker says: at any rate, in any chunk
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
                # a chant or a chorus is confident speech: only a loop the engine itself doubts counts
                if flags[index] & {FLAG_LOW_CONF, FLAG_COMPRESSED}:
                    flags[index].add(FLAG_REPEAT)
        start = end + 1
    return flags


def repeated_texts(segments: list[Segment], cfg: CaptionsConfig) -> set[str]:
    """The texts a re-listen says at least `halluc_repeat_min` times with confidence.

    Segments the engine doubts (low `avg_logprob`, high compression ratio) do not count: a loop the
    engine makes up again in every window is not speech heard twice.
    """
    counts: dict[str, int] = {}
    for seg in segments:
        key = bare(seg.text)
        doubted = (seg.avg_logprob is not None and seg.avg_logprob < cfg.halluc_avg_logprob) or (
            seg.compression_ratio is not None
            and seg.compression_ratio > cfg.halluc_compression_ratio
        )
        if key and not doubted:
            counts[key] = counts.get(key, 0) + 1
    return {key for key, count in counts.items() if count >= cfg.halluc_repeat_min}


@dataclass
class ChunkHealth:
    language_ok: bool
    flagged_s: float
    flagged_share: float
    chars: int
    chars_per_s: float
    language: str | None = None
    reasons: list[str] = field(default_factory=list)
    duration_s: float = 0.0
    avg_logprob: float | None = None  # mean over the segments no rule flagged
    timing: str | None = None  # "real" | "mixed" | "interpolated" (None: no words)

    def rank(self, chars_cap: float | None = None) -> tuple[bool, float, int, int]:
        """Higher is better: right language, less made-up text, better word times, then more text
        (counted only up to `chars_cap`: more characters alone do not beat music)."""
        chars = self.chars if chars_cap is None else min(self.chars, int(chars_cap))
        return (
            self.language_ok,
            -round(self.flagged_share, SHARE_DIGITS),
            TIMING_RANK.get(self.timing or "", 0),
            chars,
        )


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
    clear = [
        seg.avg_logprob
        for seg, found in zip(segments, flags, strict=True)
        if not found & SHARE_FLAGS and seg.avg_logprob is not None
    ]
    health = ChunkHealth(
        language_ok,
        flagged,
        flagged / span,
        chars,
        chars / span,
        language=language,
        duration_s=duration_s,
        avg_logprob=sum(clear) / len(clear) if clear else None,
    )
    if not language_ok:
        health.reasons.append(REASON_LANGUAGE)
    if health.flagged_share >= cfg.halluc_chunk_share:
        health.reasons.append(REASON_HALLUCINATION)
    return health


def median_rate(healths: list[ChunkHealth], cfg: CaptionsConfig) -> float:
    """Median characters per second of the chunks long enough to judge."""
    rates = [h.chars_per_s for h in healths if h.duration_s >= cfg.sparse_min_chunk_s]
    return statistics.median(rates) if rates else 0.0


def recheck_reasons(
    health: ChunkHealth, median_cps: float, chunks: int, cfg: CaptionsConfig
) -> list[str]:
    """The reasons a chunk asks for a second listen, given how its neighbours did."""
    reasons = list(health.reasons)
    if (
        chunks >= cfg.sparse_min_chunks
        and health.duration_s >= cfg.sparse_min_chunk_s
        and median_cps > 0
        and health.chars_per_s < cfg.sparse_chunk_ratio * median_cps
    ):
        reasons.append(REASON_SPARSE)
    return reasons


def review(healths: list[ChunkHealth], cfg: CaptionsConfig) -> list[list[str]]:
    """Per chunk, the reasons that ask for a recheck (empty: the chunk is fine).

    A wrong language with nothing else wrong counts only while the chunks that show it are a small
    minority of the audio (`asr_mismatch_minority_share`): when more of the video is "wrong" it is
    bilingual, not mislabelled, and forcing a language would damage the stretches that are right.
    """
    median = median_rate(healths, cfg)
    reasons = [recheck_reasons(h, median, len(healths), cfg) for h in healths]
    total = sum(h.duration_s for h in healths) or 1.0
    wrong = sum(h.duration_s for h in healths if REASON_LANGUAGE in h.reasons)
    if wrong / total > cfg.asr_mismatch_minority_share:
        reasons = [
            [r for r in why if r != REASON_LANGUAGE] if why == [REASON_LANGUAGE] else why
            for why in reasons
        ]
    return reasons


@dataclass
class DroppedSpan:
    start: float
    end: float
    reason: str


def drop_flagged(
    segments: list[Segment],
    words: list[Word],
    flags: list[set[str]],
    reproduced: set[str] | frozenset[str] = frozenset(),
) -> tuple[list[Segment], list[Word], list[DroppedSpan]]:
    """The segments and words left once the segments flagged as not speech are removed.

    `no_speech` and `phantom` segments always go. A `repeat_loop` segment goes only when a re-listen
    in other windows did not say the same thing (`reproduced`: its bare text): a text the engine
    hears twice is more likely repeated speech than a made-up loop. Words go with the segment
    their midpoint lies in. The third item lists what was dropped.
    """

    def doomed(seg: Segment, found: set[str]) -> bool:
        if found & ALWAYS_DROPPED:
            return True
        return FLAG_REPEAT in found and bare(seg.text) not in reproduced

    gone = [doomed(seg, found) for seg, found in zip(segments, flags, strict=True)]
    dropped = [
        DroppedSpan(seg.start, seg.end, ",".join(sorted(found & DROP_FLAGS)))
        for seg, found, drop in zip(segments, flags, gone, strict=True)
        if drop
    ]
    if not dropped:
        return segments, words, []
    kept = [seg for seg, drop in zip(segments, gone, strict=True) if not drop]
    spans = [(d.start, d.end) for d in dropped]
    kept_words = [w for w in words if not any(a <= (w.start + w.end) / 2 < b for a, b in spans)]
    return kept, kept_words, dropped
