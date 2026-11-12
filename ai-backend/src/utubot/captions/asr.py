from __future__ import annotations

import asyncio
import subprocess
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ..config import CaptionsConfig
from .types import Segment, Word

if TYPE_CHECKING:
    import httpx

    from .engines import AsrRouter

ProgressFn = Callable[[float], None]
LANGUAGE_CODES = {
    "english": "en",
    "turkish": "tr",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "japanese": "ja",
    "korean": "ko",
    "chinese": "zh",
    "arabic": "ar",
    "dutch": "nl",
    "polish": "pl",
    "ukrainian": "uk",
    "hindi": "hi",
    "swedish": "sv",
    "greek": "el",
    "czech": "cs",
    "romanian": "ro",
    "hungarian": "hu",
    "finnish": "fi",
    "danish": "da",
    "norwegian": "no",
    "hebrew": "he",
    "indonesian": "id",
    "vietnamese": "vi",
    "thai": "th",
    "persian": "fa",
}
LANGUAGE_NAMES = {code: name.capitalize() for name, code in LANGUAGE_CODES.items()}


class ASRError(RuntimeError):
    pass


@dataclass
class ASRResult:
    words: list[Word]
    language: str | None
    segments: list[Segment] = field(default_factory=list)
    engine: str | None = None
    model: str | None = None


class ASRBackend(Protocol):
    """Speech to text for one 16 kHz mono WAV file.

    `priority` is `llm.INTERACTIVE` or `BACKGROUND`; `want_words` asks for word timestamps (captions)
    instead of segments only (transcripts).
    """

    async def transcribe(
        self,
        wav: Path,
        language: str | None,
        progress: ProgressFn,
        *,
        priority: int = ...,
        want_words: bool = ...,
    ) -> ASRResult: ...


def normalize_language(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    return LANGUAGE_CODES.get(value, value.split("-")[0] if len(value) <= 5 else value)


def words_from_segment(start: float, end: float, text: str) -> list[Word]:
    tokens = text.split()
    if not tokens:
        return []
    total = sum(len(t) for t in tokens) or 1
    span = max(end - start, 0.0)
    out: list[Word] = []
    cursor = start
    for tok in tokens:
        dur = span * len(tok) / total
        out.append(Word(cursor, cursor + dur, tok))
        cursor += dur
    return out


async def run_ffmpeg(*args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await proc.communicate()
    if proc.returncode != 0:
        raise ASRError(f"ffmpeg failed: {err.decode(errors='replace')[:300]}")


def wav_duration(path: Path, sample_rate: int = 16000) -> float:
    """Seconds of audio in a PCM WAV file (from its header; by file size if the header is unreadable)."""
    try:
        with wave.open(str(path), "rb") as fh:
            return fh.getnframes() / fh.getframerate()
    except (wave.Error, EOFError):
        bytes_per_sample = 2
        return max(path.stat().st_size - 44, 0) / (sample_rate * bytes_per_sample)


def make_asr(cfg: CaptionsConfig, transport: httpx.AsyncBaseTransport | None = None) -> AsrRouter:
    """The engine chain configured in `[captions]` (`asr_engines`, or the legacy single backend)."""
    from .engines import AsrRouter

    return AsrRouter(cfg, transport=transport)


def ffmpeg_available() -> bool:
    try:
        return subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False
