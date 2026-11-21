"""A measure of how well cue starts line up with speech (pure functions).

Two uses: the self-check every job logs (`self_check`: needs only the cues and the audio's silences)
and the diagnostic `utubot captions-score` / the offline sync test (`phrase_onsets` +
`score_starts`: compare cue starts to the onsets of a reference).

The direction "per reference onset, the nearest cue start" is deliberate: in dense speech every cue
start is near *some* word, so the reverse direction measures nothing.
"""

from __future__ import annotations

import bisect
import statistics
from dataclasses import dataclass
from typing import Any

from ..config import CaptionsConfig
from .types import Cue

PERCENTILE_LOW = 0.10
PERCENTILE_HIGH = 0.90
SHARE_DIGITS = 3
SECONDS_DIGITS = 3


@dataclass
class SyncScore:
    onsets: int
    hit: float  # share of onsets with a cue start in [-sync_early_s, +sync_late_s]
    loose: float  # share with a cue start within sync_loose_s
    median_s: float  # median of (nearest cue start - onset)
    p10_s: float
    p90_s: float

    def as_detail(self) -> dict[str, Any]:
        return {
            "onsets": self.onsets,
            "hit": round(self.hit, SHARE_DIGITS),
            "loose": round(self.loose, SHARE_DIGITS),
            "median_s": round(self.median_s, SECONDS_DIGITS),
            "p10_s": round(self.p10_s, SECONDS_DIGITS),
            "p90_s": round(self.p90_s, SECONDS_DIGITS),
        }


def phrase_onsets(starts_ends: list[tuple[float, float]], gap_s: float) -> list[float]:
    """Start of the first item and of every item that starts more than `gap_s` after the last end."""
    onsets: list[float] = []
    last_end: float | None = None
    for start, end in sorted(starts_ends):
        if last_end is None or start - last_end > gap_s:
            onsets.append(start)
        last_end = end if last_end is None else max(last_end, end)
    return onsets


def _percentile(sorted_values: list[float], fraction: float) -> float:
    index = round(fraction * (len(sorted_values) - 1))
    return sorted_values[index]


def score_starts(cue_starts: list[float], onsets: list[float], cfg: CaptionsConfig) -> SyncScore:
    """How close the nearest cue start is to each reference onset (negative: the cue leads)."""
    starts = sorted(cue_starts)
    if not starts or not onsets:
        return SyncScore(len(onsets), 0.0, 0.0, 0.0, 0.0, 0.0)
    errors: list[float] = []
    for onset in onsets:
        at = bisect.bisect_left(starts, onset)
        near = [starts[j] for j in (at - 1, at) if 0 <= j < len(starts)]
        errors.append(min(near, key=lambda start: abs(start - onset)) - onset)
    ordered = sorted(errors)
    hit = sum(1 for e in errors if -cfg.sync_early_s <= e <= cfg.sync_late_s)
    loose = sum(1 for e in errors if abs(e) <= cfg.sync_loose_s)
    return SyncScore(
        len(onsets),
        hit / len(errors),
        loose / len(errors),
        statistics.median(errors),
        _percentile(ordered, PERCENTILE_LOW),
        _percentile(ordered, PERCENTILE_HIGH),
    )


def _overlap_s(
    start: float, end: float, silences: list[tuple[float, float]], ends: list[float]
) -> float:
    total = 0.0
    for j in range(bisect.bisect_right(ends, start), len(silences)):
        silence_start, silence_end = silences[j]
        if silence_start >= end:
            break
        total += min(end, silence_end) - max(start, silence_start)
    return total


def self_check(
    cues: list[Cue], silences: list[tuple[float, float]], audio_s: float, cfg: CaptionsConfig
) -> dict[str, Any]:
    """What the audio alone says about a finished set of cues.

    `speech_overlap`: share of cue time outside silences. `starts_in_silence`: share of cue starts
    lying inside a silence, more than `sync_late_s` after it began (speech had ended) and more than
    `sync_early_s` before it ends (the next speech is still far off); a start at either edge of a
    silence is where a cue should start. `silence_share`: silences over the audio's length
    (it tells the reader whether the audio is informative at all). Empty when there are no silences
    to compare with.
    """
    silences = sorted(silences)
    ends = [end for _, end in silences]
    cue_time = sum(max(cue.end - cue.start, 0.0) for cue in cues)
    inside = sum(_overlap_s(cue.start, cue.end, silences, ends) for cue in cues)
    late = 0
    for cue in cues:
        at = bisect.bisect_right(ends, cue.start)
        if at < len(silences):
            silence_start, silence_end = silences[at]
            if (
                cue.start - silence_start > cfg.sync_late_s
                and silence_end - cue.start > cfg.sync_early_s
            ):
                late += 1
    return {
        "cues": len(cues),
        "speech_overlap": round(1 - inside / cue_time, SHARE_DIGITS) if cue_time > 0 else None,
        "starts_in_silence": round(late / len(cues), SHARE_DIGITS) if cues else None,
        "silence_share": round(sum(e - s for s, e in silences) / audio_s, SHARE_DIGITS)
        if audio_s > 0
        else None,
    }
