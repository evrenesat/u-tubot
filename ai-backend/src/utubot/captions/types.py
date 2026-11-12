from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Word:
    start: float
    end: float
    text: str
    speaker: str | None = None


@dataclass
class Cue:
    start: float
    end: float
    lines: list[str]
    speaker: str | None = None


@dataclass
class Segment:
    start: float
    end: float
    text: str
