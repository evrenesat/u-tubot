"""Word times from a speech engine, checked and repaired (pure functions).

Whisper's DTW word times have known flaws: a word at a segment edge with no length, the last word
before a pause stretched over it, a run of words squeezed into a fraction of a second. `repair_words`
corrects them against the audio's silences and ordinary speaking rates and says what it did
(`WordStats`), so the job log can show it. Words whose times were only spread over a segment
(`TIMING_INTERPOLATED`) are counted and passed through untouched.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..config import CaptionsConfig
from .chunking import bare
from .types import (
    TIMING_INTERPOLATED,
    TIMING_REPAIRED,
    TIMING_SUSPECT,
    Word,
)

SHARE_DIGITS = 3
RATE_DIGITS = 2
SECONDS_DIGITS = 1
SHORT_EPS = 1e-9


@dataclass
class WordStats:
    words: int = 0
    real: int = 0
    interpolated: int = 0
    zero_length: int = 0
    stretched: int = 0
    squeezed: int = 0
    nonmonotonic: int = 0
    unfixed: int = 0  # words still shorter than `word_min_s` after every repair (marked suspect)
    words_per_s: float = 0.0  # words per second of speech (gaps over `sentence_gap_s` excluded)
    speech_s: float = 0.0

    def as_detail(self) -> dict[str, Any]:
        share = self.real / self.words if self.words else 0.0
        return {
            "words": self.words,
            "real": self.real,
            "interpolated": self.interpolated,
            "real_share": round(share, SHARE_DIGITS),
            "zero_length": self.zero_length,
            "stretched": self.stretched,
            "squeezed": self.squeezed,
            "nonmonotonic": self.nonmonotonic,
            "unfixed": self.unfixed,
            "words_per_s": round(self.words_per_s, RATE_DIGITS),
            "speech_s": round(self.speech_s, SECONDS_DIGITS),
        }


def classify(words: list[Word], real_min_share: float) -> str | None:
    """ "real" when at least `real_min_share` of the words carry engine times, "interpolated" when
    none does, else "mixed"; None for no words."""
    if not words:
        return None
    real = sum(1 for w in words if w.timing != TIMING_INTERPOLATED)
    if real == 0:
        return "interpolated"
    return "real" if real / len(words) >= real_min_share else "mixed"


def count_kinds(words: list[Word]) -> tuple[int, int]:
    """(real-origin words, interpolated words)."""
    interpolated = sum(1 for w in words if w.timing == TIMING_INTERPOLATED)
    return len(words) - interpolated, interpolated


def _nominal(word: Word, cfg: CaptionsConfig) -> float:
    length = len(bare(word.text)) * cfg.word_char_s
    return min(max(length, cfg.word_nominal_min_s), cfg.word_max_s)


def _longest_silence(
    word: Word, silences: list[tuple[float, float]], min_overlap_s: float
) -> tuple[float, float] | None:
    best, best_overlap = None, min_overlap_s
    for start, end in silences:
        overlap = min(word.end, end) - max(word.start, start)
        if overlap >= best_overlap:
            best, best_overlap = (start, end), overlap
    return best


def _fix_stretched(
    out: list[Word],
    i: int,
    silences: list[tuple[float, float]],
    cfg: CaptionsConfig,
) -> None:
    word = out[i]
    silence = _longest_silence(word, silences, cfg.silence_min_s)
    if silence is not None:
        silence_start, silence_end = silence
        if silence_start > word.start + cfg.word_min_s:
            word.end = max(silence_start, word.start + cfg.word_min_s)
        else:
            word.start = min(silence_end, word.end - cfg.word_min_s)
        return
    nominal = _nominal(word, cfg)
    nxt = out[i + 1] if i + 1 < len(out) else None
    prev = out[i - 1] if i else None
    next_close = nxt is not None and nxt.start - word.end <= cfg.word_min_s
    prev_far = prev is None or word.start - prev.end > cfg.word_min_s
    if next_close and prev_far:
        word.start = word.end - nominal
    else:
        word.end = word.start + nominal


def _fix_zero_length(out: list[Word], i: int, cfg: CaptionsConfig) -> bool:
    """Give a zero-length word room from a neighbouring gap; False when there is none."""
    word = out[i]
    nominal = _nominal(word, cfg)
    nxt = out[i + 1] if i + 1 < len(out) else None
    prev = out[i - 1] if i else None
    limit = nxt.start if nxt is not None else word.start + nominal
    grown = min(word.start + nominal, limit)
    if grown - word.start >= cfg.word_min_s:
        word.end = grown
        return True
    floor = prev.end if prev is not None else 0.0
    pulled = max(word.end - nominal, floor)
    if word.end - pulled >= cfg.word_min_s:
        word.start = pulled
        return True
    return False


def _squeezed_runs(out: list[Word], skip: list[bool], cfg: CaptionsConfig) -> list[tuple[int, int]]:
    """Index ranges `[lo, hi)` of consecutive words whose speaking rate is implausibly high."""
    size = cfg.word_squeeze_min_words
    flagged = [False] * len(out)
    for lo in range(len(out) - size + 1):
        window = out[lo : lo + size]
        if any(skip[lo : lo + size]):
            continue
        span = window[-1].end - window[0].start
        if span <= 0 or size / span > cfg.word_rate_max:
            for k in range(lo, lo + size):
                flagged[k] = True
    runs: list[tuple[int, int]] = []
    k = 0
    while k < len(out):
        if flagged[k]:
            lo = k
            while k < len(out) and flagged[k]:
                k += 1
            runs.append((lo, k))
        else:
            k += 1
    return runs


def _respread(out: list[Word], lo: int, hi: int, cfg: CaptionsConfig) -> None:
    run = out[lo:hi]
    begin = run[0].start
    nominal_total = sum(_nominal(w, cfg) for w in run)
    limit = begin + nominal_total
    if hi < len(out):
        limit = min(limit, max(out[hi].start, begin))
    weights = [max(len(bare(w.text)), 1) for w in run]
    total = sum(weights)
    cursor = begin
    for word, weight in zip(run, weights, strict=True):
        step = (limit - begin) * weight / total
        word.start, word.end = cursor, cursor + step
        word.timing = TIMING_SUSPECT
        cursor += step


def _speech_stats(words: list[Word], cfg: CaptionsConfig) -> tuple[float, float]:
    """(seconds of speech, words per second of speech); a gap over `sentence_gap_s` ends a stretch."""
    if not words:
        return 0.0, 0.0
    speech = 0.0
    begin, last_end = words[0].start, words[0].end
    for word in words[1:]:
        if word.start - last_end > cfg.sentence_gap_s:
            speech += last_end - begin
            begin = word.start
        last_end = max(last_end, word.end)
    speech += last_end - begin
    return speech, (len(words) / speech if speech > 0 else 0.0)


def repair_words(
    words: list[Word], silences: list[tuple[float, float]], cfg: CaptionsConfig
) -> tuple[list[Word], WordStats]:
    """New `Word`s with the usual DTW flaws corrected, and what was found. Input is never mutated."""
    out = [replace(w, text=w.text.strip()) for w in words if w.text.strip()]
    skip = [w.timing == TIMING_INTERPOLATED for w in out]
    stats = WordStats(words=len(out), interpolated=sum(skip), real=len(out) - sum(skip))

    for i, word in enumerate(out):
        if skip[i]:
            continue
        word.start = max(word.start, 0.0)
        word.end = max(word.end, word.start)
        prev_start = next((out[j].start for j in range(i - 1, -1, -1) if not skip[j]), None)
        if prev_start is not None and word.start < prev_start:
            word.start = prev_start
            word.end = max(word.end, word.start)
            stats.nonmonotonic += 1

    for i, word in enumerate(out):
        if not skip[i] and word.end - word.start > cfg.word_max_s:
            stats.stretched += 1
            _fix_stretched(out, i, silences, cfg)
            word.timing = TIMING_REPAIRED

    for i, word in enumerate(out):
        if not skip[i] and word.end - word.start < cfg.word_min_s:
            if _fix_zero_length(out, i, cfg):
                stats.zero_length += 1
                word.timing = TIMING_REPAIRED

    for lo, hi in _squeezed_runs(out, skip, cfg):
        _respread(out, lo, hi, cfg)
        stats.squeezed += hi - lo

    for i, word in enumerate(out[:-1]):
        if not skip[i] and word.end > out[i + 1].start:
            word.end = max(out[i + 1].start, word.start)

    for i, word in enumerate(out):
        if not skip[i] and word.end - word.start < cfg.word_min_s - SHORT_EPS:
            word.timing = TIMING_SUSPECT
            stats.unfixed += 1

    stats.speech_s, stats.words_per_s = _speech_stats(out, cfg)
    return out, stats
