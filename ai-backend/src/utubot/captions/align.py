"""Alignment: YouTube caption timing, ASR words and silence, combined into good cues.

Two jobs:
- `merge_words_into_cues`: the video had captions, so their timing is kept and each cue's text is
  replaced by the ASR words that fall inside its window (better transcription); a cue the ASR heard
  nothing in keeps the caption text. Cue boundaries move to the words they now hold.
- `snap_cues`: cue boundaries are nudged to the middle of a nearby silence (ffmpeg silencedetect),
  so a cue does not cut into a word; a light stand-in for a full forced alignment.

`caption_cues` turns the timed segments of a fetched caption track into cues: it drops the repeats
of rolling windows and re-breaks text that is too long for one cue (`segment.retime_split`).
"""

from __future__ import annotations

import re
import subprocess

from ..config import CaptionsConfig
from .segment import enforce_timing, retime_split, wrap_lines
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


def merge_words_into_cues(
    cues: list[Cue], words: list[Word], cfg: CaptionsConfig
) -> tuple[list[Cue], int]:
    """Replace cue text with the ASR words inside each cue window (plus `align_window_s` margin).

    Every word goes to at most one cue: the one whose window its midpoint is closest to, and only
    when that distance is within the margin. Words outside every window are dropped. Returns the
    new cues (timing re-enforced) and how many cues took their text from the ASR.
    """
    margin = max(cfg.align_window_s, 0.0)
    buckets: list[list[Word]] = [[] for _ in cues]
    for word in words:
        if not word.text.strip():
            continue
        mid = _midpoint(word)
        best, best_dist = None, margin + MIDPOINT_EPS
        for i, cue in enumerate(cues):
            dist = _window_distance(mid, cue.start, cue.end)
            if dist < best_dist:
                best, best_dist = i, dist
        if best is not None:
            buckets[best].append(word)
    out: list[Cue] = []
    from_asr = 0
    for cue, bucket in zip(cues, buckets, strict=True):
        if bucket:
            from_asr += 1
            out.append(
                Cue(
                    bucket[0].start,
                    max(bucket[-1].end, bucket[0].start),
                    [" ".join(w.text.strip() for w in bucket)],
                    cue.speaker,
                )
            )
        else:
            out.append(Cue(cue.start, cue.end, list(cue.lines), cue.speaker))
    return enforce_timing(out, cfg), from_asr


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
    """Nudge each cue boundary to a silence midpoint within `align_window_s`; never cross a neighbour.

    A boundary only moves when the cue keeps at least `min_cue_s` afterwards. Cues that touch their
    neighbour (back-to-back speech) stay put; there is no silence between them to snap to anyway.
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
    hi = next_start if next_start is not None else cue.end
    for point in midpoints:
        if abs(point - cue.start) <= window and cue.end - point >= cfg.min_cue_s and point >= lo:
            cue.start = point
            break
    for point in midpoints:
        if abs(point - cue.end) <= window and point - cue.start >= cfg.min_cue_s and point <= hi:
            cue.end = point
            break
