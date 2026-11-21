from __future__ import annotations

from dataclasses import dataclass, field

TIMING_REAL = "real"  # from the engine's word timestamps
TIMING_INTERPOLATED = "interpolated"  # spread over a segment by character count
TIMING_REPAIRED = "repaired"  # real, then corrected by wordtimes.repair_words
TIMING_SUSPECT = "suspect"  # real but implausible (squeezed run), re-spread
TIMING_REFERENCE = "reference"  # moved onto the YouTube reference (later checkpoint)
REAL_ORIGIN = frozenset({TIMING_REAL, TIMING_REPAIRED, TIMING_SUSPECT, TIMING_REFERENCE})


@dataclass
class Word:
    start: float
    end: float
    text: str
    speaker: str | None = None
    prob: float | None = None
    timing: str = TIMING_REAL


@dataclass
class Cue:
    start: float
    end: float
    lines: list[str]
    speaker: str | None = None
    words: list[Word] | None = field(default=None, repr=False, compare=False)
    # False once the text is a translation: its tokens no longer map one to one onto `words`
    words_match_text: bool = field(default=True, repr=False, compare=False)
    # the times were shared over the text by character count (no word times behind them)
    char_timed: bool = field(default=False, repr=False, compare=False)


@dataclass
class Segment:
    start: float
    end: float
    text: str
    no_speech_prob: float | None = None
    avg_logprob: float | None = None
    compression_ratio: float | None = None
