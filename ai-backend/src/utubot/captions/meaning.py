"""Deterministic meaning check for `utubot captions-score` (pure functions).

A track and a reference translation are reduced to their words and compared as token bags: the F1
of precision (track words that the reference has) and recall (reference words the track has). It is
offline and repeatable, the same report on the same files, and it needs no model. A cue that drops
or invents words moves the score; a rephrasing does not.

The reference is a translation of the video, not another copy of the track: VTT/SRT (any timed
subtitle file `parse_vtt` reads) or plain text. Both sides are normalised the same way, so script
and punctuation do not decide the result.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from ..transcripts import parse_vtt
from .chunking import bare


def reference_text(raw: str) -> str:
    """The text of a reference file: subtitle cues when it is timed, else the whole file."""
    cues = parse_vtt(raw)
    if cues:
        return " ".join(text for _start, _end, text in cues)
    return raw


def tokens(text: str) -> list[str]:
    return [word for word in (bare(part) for part in text.split()) if word]


def token_f1(candidate: str, reference: str) -> float:
    """The bag-of-words F1 of two texts (0 when either side has no words)."""
    cand = Counter(tokens(candidate))
    ref = Counter(tokens(reference))
    if not cand or not ref:
        return 0.0
    overlap = sum((cand & ref).values())
    if not overlap:
        return 0.0
    precision = overlap / sum(cand.values())
    recall = overlap / sum(ref.values())
    return 2 * precision * recall / (precision + recall)


def meaning_block(track_text: str, path: str | Path, minimum: float) -> dict[str, object]:
    """The report's `meaning` block for a reference translation file."""
    reference = reference_text(Path(path).read_text(encoding="utf-8"))
    score = token_f1(track_text, reference)
    return {
        "score": round(score, 3),
        "passed": score >= minimum,
        "reference": str(path),
    }
