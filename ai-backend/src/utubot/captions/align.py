"""Alignment: YouTube caption timing, ASR words and silence, combined into good cues.

Three jobs:
- `cues_from_words`: the video had captions and the engine gave real word times. The cues are built
  from the words' own times (no word is dropped for lying outside a caption window); caption cues
  no word touches (`[Music]`, speech the engine missed) fill the wordless gaps.
- `merge_words_into_cues`: the older caption-window merge. Each cue's text is replaced by the ASR
  words that fall inside its window; a cue the ASR heard nothing in keeps the caption text. With
  `retime=True` cue boundaries move to the words they hold (legacy mode); with `retime=False` the
  caption timing is kept (the words' times are only estimates).
- `snap_cues`: cue boundaries are nudged outward to the middle of a nearby silence (ffmpeg
  silencedetect), so a cue does not cut into a word; a light stand-in for a full forced alignment.

`caption_cues` turns the timed segments of a fetched caption track into cues: it drops the repeats
of rolling windows and re-breaks text that is too long for one cue (`segment.retime_split`).
"""

from __future__ import annotations

import bisect
import re
import subprocess

from ..config import CaptionsConfig
from .segment import build_cues, enforce_timing, pad_cues, retime_split, wrap_lines
from .types import Cue, Word

MIDPOINT_EPS = 1e-9


def _midpoint(word: Word) -> float:
    return (word.start + word.end) / 2


def _window_distance(point: float, start: float, end: float) -> float:
    if start - MIDPOINT_EPS <= point <= end + MIDPOINT_EPS:
        return 0.0
    return min(abs(point - start), abs(point - end))


def _cue_text(cue: Cue) -> str:
    return " ".join(cue.lines).strip()


def _bucket_words(cues: list[Cue], words: list[Word], margin: float) -> list[list[Word]]:
    """Each word in the bucket of the one cue whose window its midpoint is closest to.

    Only a cue whose `[start-margin, end+margin]` holds the midpoint is a candidate. The cues are
    expected sorted and non-overlapping, so their ends are sorted too and the candidates form one
    contiguous run around the `bisect` position: no scan of every cue. Words outside every window
    land in no bucket.
    """
    starts = [cue.start for cue in cues]
    buckets: list[list[Word]] = [[] for _ in cues]
    for word in words:
        if not word.text.strip():
            continue
        mid = _midpoint(word)
        best, best_dist = None, margin + MIDPOINT_EPS
        j_hi = bisect.bisect_right(starts, mid)
        while j_hi < len(cues) and cues[j_hi].start - margin <= mid:
            j_hi += 1
        j_lo = j_hi
        while j_lo > 0 and cues[j_lo - 1].end + margin >= mid:
            j_lo -= 1
        for j in range(j_lo, j_hi):
            dist = _window_distance(mid, cues[j].start, cues[j].end)
            if dist < best_dist:
                best, best_dist = j, dist
        if best is not None:
            buckets[best].append(word)
    return buckets


def merge_words_into_cues(
    cues: list[Cue], words: list[Word], cfg: CaptionsConfig, *, retime: bool = True
) -> tuple[list[Cue], int]:
    """Replace cue text with the ASR words inside each cue window (plus `align_window_s` margin).

    Every word goes to at most one cue: the one whose window its midpoint is closest to, and only
    when that distance is within the margin. Words outside every window are dropped. A cue that took
    ASR words is re-wrapped to the line limits; text that does not fit — or runs faster than
    `max_cps` — is re-split into several cues over the words' own timings (`build_cues`). Returns the
    new cues and how many cues took their text from the ASR.

    With `retime=False` (the words' times are only estimates) a cue keeps its caption `start` and
    `end` and takes just the text; text that does not fit goes through `retime_split` over the
    caption's own span. Legacy path and estimated-times path only: real word times go through
    `cues_from_words`.
    """
    margin = max(cfg.align_window_s, 0.0)
    buckets = _bucket_words(cues, words, margin)
    out: list[Cue] = []
    from_asr = 0
    for cue, bucket in zip(cues, buckets, strict=True):
        if not bucket:
            out.append(Cue(cue.start, cue.end, list(cue.lines), cue.speaker))
            continue
        from_asr += 1
        text = " ".join(w.text.strip() for w in bucket)
        lines = wrap_lines(text, cfg.max_chars_per_line, cfg.max_lines)
        if not retime:
            if lines is not None:
                out.append(Cue(cue.start, cue.end, lines, cue.speaker))
            else:
                out.extend(retime_split(text, cue.start, cue.end, cfg))
        elif lines is not None and not _too_fast(text, bucket[0].start, bucket[-1].end, cfg):
            out.append(
                Cue(bucket[0].start, max(bucket[-1].end, bucket[0].start), lines, cue.speaker)
            )
        else:
            # does not fit one cue: let the words' own timings re-split it, so line, duration
            # and cps limits all hold
            out.extend(build_cues(bucket, cfg))
    return enforce_timing(out, cfg), from_asr


def word_cues(
    words: list[Word], captions: list[Cue], cfg: CaptionsConfig
) -> tuple[list[Cue], int, int]:
    """Speech cues from the words' own times plus fill cues from the captions: `(cues, speech, fill)`.

    A caption cue is a fill cue when no word midpoint lies within `align_window_s` of it (a `[Music]`
    row, speech the engine missed); it is clipped to the wordless gap between its neighbouring speech
    cues and dropped when under `min_cue_s` after that. The cues are neither snapped nor padded yet.
    """
    speech = build_cues(words, cfg)
    margin = max(cfg.align_window_s, 0.0)
    mids = sorted(_midpoint(w) for w in words if w.text.strip())
    starts = [cue.start for cue in speech]
    fills: list[Cue] = []
    for cue in captions:
        first = bisect.bisect_left(mids, cue.start - margin - MIDPOINT_EPS)
        if first < len(mids) and mids[first] <= cue.end + margin + MIDPOINT_EPS:
            continue
        after = bisect.bisect_right(starts, cue.start)
        low = speech[after - 1].end if after else 0.0
        high = speech[after].start if after < len(speech) else float("inf")
        start, end = max(cue.start, low), min(cue.end, high)
        if end - start >= cfg.min_cue_s:
            fills.append(Cue(start, end, list(cue.lines), cue.speaker))
    merged = sorted([*speech, *fills], key=lambda cue: cue.start)
    return merged, len(speech), len(fills)


def finish_cues(cues: list[Cue], cfg: CaptionsConfig) -> list[Cue]:
    """The last step of word-built cues: linger after the last word, then the timing limits."""
    return enforce_timing(pad_cues(cues, cfg), cfg)


def cues_from_words(
    words: list[Word],
    captions: list[Cue],
    cfg: CaptionsConfig,
    silences: list[tuple[float, float]] | None = None,
) -> tuple[list[Cue], int, int]:
    """Cues built from the words' own times; caption cues no word touches fill the gaps.

    Returns `(cues, speech_cues, fill_cues)` (see `word_cues`). With `silences` the boundaries are
    snapped to them before the linger is added, so a cue never ends far after its last word.
    """
    cues, speech, fill = word_cues(words, captions, cfg)
    if silences:
        cues = snap_cues(cues, silences, cfg)
    return finish_cues(cues, cfg), speech, fill


def _too_fast(text: str, start: float, end: float, cfg: CaptionsConfig) -> bool:
    if cfg.max_cps <= 0:
        return False
    return len(text) / max(end - start, 0.1) > cfg.max_cps


def caption_cues(segments: list[tuple[float, float, str]], cfg: CaptionsConfig) -> list[Cue]:
    """Timed `(start, end, text)` rows of a fetched caption track as cues, rolling repeats dropped."""
    rows = sorted(
        (float(start), float(end), " ".join(str(text).split()))
        for start, end, text in segments
        if str(text).strip()
    )
    spans: list[tuple[float, float, str]] = []
    for start, end, text in rows:
        if spans and start <= spans[-1][1] + MIDPOINT_EPS and text == spans[-1][2]:
            continue
        spans.append((start, max(end, start), text))
    cues: list[Cue] = []
    for i, (start, end, text) in enumerate(spans):
        if end <= start:
            end = spans[i + 1][0] if i + 1 < len(spans) else start + 2.0
        lines = wrap_lines(text, cfg.max_chars_per_line, cfg.max_lines)
        if lines is not None:
            cues.append(Cue(start, end, lines))
        else:
            cues.extend(retime_split(text, start, end, cfg))
    return enforce_timing(cues, cfg)


SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")


def parse_silencedetect(output: str) -> list[tuple[float, float]]:
    """The `(start, end)` pairs ffmpeg's silencedetect printed, in order, ends before starts."""
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in output.splitlines():
        found = SILENCE_START_RE.search(line)
        if found:
            start = max(float(found.group(1)), 0.0)
            continue
        found = SILENCE_END_RE.search(line)
        if found and start is not None:
            end = float(found.group(1))
            if end > start:
                silences.append((start, end))
            start = None
    return silences


def detect_silences(wav, min_silence_s: float, noise: str = "-30dB") -> list[tuple[float, float]]:
    """Silence spans of a WAV file via ffmpeg's silencedetect filter (a few seconds for hours of audio)."""
    proc = subprocess.run(
        [
            "ffmpeg",
            "-nostats",
            "-loglevel",
            "info",
            "-i",
            str(wav),
            "-af",
            f"silencedetect=noise={noise}:d={max(min_silence_s, 0.05)}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        check=False,
    )
    return parse_silencedetect(proc.stderr.decode(errors="replace"))


def _silence_midpoints(silences: list[tuple[float, float]]) -> list[float]:
    return [(start + end) / 2 for start, end in silences]


def snap_cues(
    cues: list[Cue], silences: list[tuple[float, float]], cfg: CaptionsConfig
) -> list[Cue]:
    """Nudge each cue boundary outward to the nearest silence midpoint within `align_window_s`.

    A start may only move earlier and an end only later — onto a silence *outside* the cue.
    Snapping inward would park the boundary on a pause inside the cue and cut its first or last
    word. A boundary never crosses a neighbour, and the cue keeps at least `min_cue_s`.
    """
    if not cues or not silences:
        return cues
    midpoints = _silence_midpoints(silences)
    window = max(cfg.align_window_s, 0.0)
    for i, cue in enumerate(cues):
        prev_end = cues[i - 1].end if i else None
        next_start = cues[i + 1].start if i + 1 < len(cues) else None
        _snap_one(cue, midpoints, window, prev_end, next_start, cfg)
    return cues


def _snap_one(
    cue: Cue,
    midpoints: list[float],
    window: float,
    prev_end: float | None,
    next_start: float | None,
    cfg: CaptionsConfig,
) -> None:
    lo = prev_end if prev_end is not None else 0.0
    # the last cue has no neighbour: its end may still move outward, within the window
    hi = next_start if next_start is not None else cue.end + window
    best, best_dist = None, window + MIDPOINT_EPS
    for point in midpoints:
        if point > cue.start + MIDPOINT_EPS or point < lo or cue.end - point < cfg.min_cue_s:
            continue
        dist = cue.start - point
        if dist < best_dist:
            best, best_dist = point, dist
    if best is not None:
        cue.start = best
    best, best_dist = None, window + MIDPOINT_EPS
    for point in midpoints:
        if point < cue.end - MIDPOINT_EPS or point > hi or point - cue.start < cfg.min_cue_s:
            continue
        dist = point - cue.end
        if dist < best_dist:
            best, best_dist = point, dist
    if best is not None:
        cue.end = best
