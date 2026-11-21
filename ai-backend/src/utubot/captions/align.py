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
from dataclasses import dataclass, replace

from ..config import CaptionsConfig
from .segment import build_cues, enforce_timing, merge_short, pad_cues, retime_split, wrap_lines
from .types import TIMING_REFERENCE, Cue, Word

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
                out.extend(retime_split(text, cue.start, cue.end, cfg, char_timed=False))
        elif lines is not None and not _too_fast(text, bucket[0].start, bucket[-1].end, cfg):
            out.append(
                Cue(
                    bucket[0].start,
                    max(bucket[-1].end, bucket[0].start),
                    lines,
                    cue.speaker,
                    words=list(bucket),
                )
            )
        else:
            # does not fit one cue: let the words' own timings re-split it, so line, duration
            # and cps limits all hold
            out.extend(build_cues(bucket, cfg))
    return enforce_timing(out, cfg), from_asr


NON_SPEECH_GROUPS_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)")


def is_non_speech(cue: Cue) -> bool:
    """A caption that is only a tag (`[Music]`, `(applause)`) or music notes, no spoken text."""
    text = " ".join(cue.lines)
    rest = NON_SPEECH_GROUPS_RE.sub(" ", text)
    return bool(text.strip()) and not any(ch.isalnum() for ch in rest)


@dataclass
class AlignStats:
    """What `word_cues` made of YouTube's word times: fill cues built from them, and their words."""

    cues: int = 0
    words: int = 0
    merged_short: int = 0  # short cues joined to a neighbour (`segment.merge_short`)


def reference_words(ref: list[tuple[float, str]], lead_s: float, cfg: CaptionsConfig) -> list[Word]:
    """YouTube's `(start, text)` words as `Word`s on the engine's clock (`lead_s` added).

    A word ends where the next begins, at most `word_max_s` after its own start; the last one (and one
    before a long pause) lasts its nominal length.
    """
    ordered = sorted((start + lead_s, text) for start, text in ref if text.strip())
    out: list[Word] = []
    for i, (start, text) in enumerate(ordered):
        nominal = min(max(len(text) * cfg.word_char_s, cfg.word_nominal_min_s), cfg.word_max_s)
        cap = start + cfg.word_max_s
        end = min(ordered[i + 1][0], cap) if i + 1 < len(ordered) else start + nominal
        out.append(Word(start, max(end, start), text, timing=TIMING_REFERENCE))
    return out


def word_cues(
    words: list[Word],
    captions: list[Cue],
    cfg: CaptionsConfig,
    ref_words: list[tuple[float, str]] | None = None,
    ref_lead_s: float = 0.0,
    manual: bool = False,
    fill_stats: AlignStats | None = None,
) -> tuple[list[Cue], int, int]:
    """Speech cues from the words' own times plus fill cues from the captions: `(cues, speech, fill)`.

    A caption cue is a fill cue when it is a non-speech tag (`[Music]`, `(applause)`, ♪, whatever the
    words around it), or when it has text and no word overlaps its span widened by `align_window_s`
    (speech the engine did not hear). Fill cues are clipped to the wordless gap between their
    neighbouring speech cues and to each other, and dropped when under `min_cue_s` after that. A
    spoken caption that words overlap is never repeated: the words are the text. The cues are
    neither snapped nor padded yet.

    With `ref_words` (YouTube's own word starts) and an automatic track, the speech YouTube heard
    and the engine did not is not shown as whole caption rows (rolling rows overlap and last several
    seconds): its text comes from the reference words inside the wordless gap, each moved by
    `ref_lead_s` onto the engine's clock and cut into cues like any words (`fill_stats` counts them).
    Tags, and every row of a `manual` track (authored, kept whole), keep the row rule.
    """
    speech = build_cues(words, cfg)
    margin = max(cfg.align_window_s, 0.0)
    timed = sorted((w for w in words if w.text.strip()), key=lambda w: w.start)
    starts = [w.start for w in timed]
    latest_end: list[float] = []
    for word in timed:
        latest_end.append(max(word.end, latest_end[-1] if latest_end else word.end))
    speech_starts = [cue.start for cue in speech]
    fills: list[Cue] = []
    last_end = 0.0
    from_words = bool(ref_words) and not manual
    ref = reference_words(ref_words or [], ref_lead_s, cfg) if from_words else []

    def heard(point: float) -> bool:
        first = bisect.bisect_right(latest_end, point - margin - MIDPOINT_EPS)
        return first < len(timed) and starts[first] <= point + margin + MIDPOINT_EPS

    ordered = sorted(captions, key=lambda c: c.start)

    def unheard(cue: Cue) -> bool:
        if is_non_speech(cue):
            return False
        first = bisect.bisect_right(latest_end, cue.start - margin - MIDPOINT_EPS)
        return not (first < len(timed) and starts[first] <= cue.end + margin + MIDPOINT_EPS)

    # unheard speech rows that overlap each other (rolling rows) are one stretch: (start, end)
    stretches: list[list[float]] = []
    stretch_of: dict[int, int] = {}
    if from_words:
        for i, cue in enumerate(ordered):
            if not unheard(cue):
                continue
            if stretches and cue.start < stretches[-1][1]:
                stretches[-1][1] = max(stretches[-1][1], cue.end)
            else:
                stretches.append([cue.start, cue.end])
            stretch_of[i] = len(stretches) - 1
    built_stretch: dict[int, bool] = {}
    for i, cue in enumerate(ordered):
        if not is_non_speech(cue):
            first = bisect.bisect_right(latest_end, cue.start - margin - MIDPOINT_EPS)
            if first < len(timed) and starts[first] <= cue.end + margin + MIDPOINT_EPS:
                continue
        if i in stretch_of:
            k = stretch_of[i]
            if k not in built_stretch:
                begin, finish = stretches[k]
                made = _reference_fill(
                    ref, begin, finish, speech, speech_starts, last_end, heard, cfg
                )
                built_stretch[k] = bool(made)
                if made:
                    fills.extend(made)
                    last_end = max(last_end, made[-1].end)
                    if fill_stats is not None:
                        fill_stats.cues += len(made)
                        fill_stats.words += sum(len(c.words or []) for c in made)
            if built_stretch[k]:
                continue
        after = bisect.bisect_right(speech_starts, cue.start)
        low = max(speech[after - 1].end if after else 0.0, last_end)
        high = speech[after].start if after < len(speech) else float("inf")
        start, end = max(cue.start, low), min(cue.end, high)
        if end - start >= cfg.min_cue_s:
            fills.append(replace(cue, start=start, end=end, lines=list(cue.lines), words=None))
            last_end = end
    merged = sorted([*speech, *fills], key=lambda cue: cue.start)
    return merged, len(speech), len(fills)


def _reference_fill(
    ref: list[Word],
    begin: float,
    end: float,
    speech: list[Cue],
    speech_starts: list[float],
    last_end: float,
    heard,
    cfg: CaptionsConfig,
) -> list[Cue]:
    """Cues from the reference words of the wordless gap around `[begin, end]` (empty: none there)."""
    after = bisect.bisect_right(speech_starts, begin)
    low = max(speech[after - 1].end if after else 0.0, last_end)
    high = speech[after].start if after < len(speech) else float("inf")
    low, high = max(begin, low), min(end, high)
    inside = [w for w in ref if low <= w.start < high and not heard(w.start)]
    if not inside:
        return []
    out = []
    for cue in build_cues(inside, cfg):
        words = cue.words or []
        cue.end = min(max(cue.end, cue.start), high)
        if words and cue.end - cue.start >= cfg.min_cue_s:
            out.append(cue)
    return out


def finish_cues(cues: list[Cue], cfg: CaptionsConfig, stats: AlignStats | None = None) -> list[Cue]:
    """The last step of word-built cues: join short cues, linger after the last word, then the timing limits."""
    cues, merged = merge_short(cues, cfg)
    if stats is not None:
        stats.merged_short += merged
    return enforce_timing(pad_cues(cues, cfg), cfg)


def cues_from_words(
    words: list[Word],
    captions: list[Cue],
    cfg: CaptionsConfig,
    silences: list[tuple[float, float]] | None = None,
    **reference: object,
) -> tuple[list[Cue], int, int]:
    """Cues built from the words' own times; caption cues no word touches fill the gaps.

    Returns `(cues, speech_cues, fill_cues)` (see `word_cues`). With `silences` the boundaries are
    snapped to them before the linger is added, so a cue never ends far after its last word.
    """
    cues, speech, fill = word_cues(words, captions, cfg, **reference)  # type: ignore[arg-type]
    if silences:
        cues = snap_cues(cues, silences, cfg)
    return finish_cues(cues, cfg, reference.get("fill_stats")), speech, fill


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
            cues.extend(retime_split(text, start, end, cfg, char_timed=False))
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
