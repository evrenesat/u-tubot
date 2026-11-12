from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Protocol

from ..config import CaptionsConfig
from .types import Word

log = logging.getLogger("utubot.diarize")
Turn = tuple[float, float, str]
PYANNOTE_PIPELINE = "pyannote/speaker-diarization-community-1"


class Diarizer(Protocol):
    async def diarize(self, wav: Path) -> list[Turn]: ...


class NoDiarizer:
    async def diarize(self, wav: Path) -> list[Turn]:
        return []


class PyannoteDiarizer:
    def __init__(self, cfg: CaptionsConfig):
        self.cfg = cfg

    def _run(self, wav: Path) -> list[Turn]:
        token = os.environ.get(self.cfg.hf_token_env)
        if not token:
            log.warning("diarization skipped: %s is not set", self.cfg.hf_token_env)
            return []
        try:
            from pyannote.audio import Pipeline
        except ImportError:
            log.warning("diarization skipped: pyannote.audio is not installed")
            return []
        pipeline = Pipeline.from_pretrained(PYANNOTE_PIPELINE, token=token)
        result = pipeline(str(wav))
        annotation = getattr(result, "speaker_diarization", result)
        return [(t.start, t.end, spk) for t, _, spk in annotation.itertracks(yield_label=True)]

    async def diarize(self, wav: Path) -> list[Turn]:
        return await asyncio.to_thread(self._run, wav)


def make_diarizer(cfg: CaptionsConfig) -> Diarizer:
    if cfg.diarization == "pyannote":
        return PyannoteDiarizer(cfg)
    return NoDiarizer()


def assign_speakers(words: list[Word], turns: list[Turn]) -> None:
    if not turns:
        return
    for word in words:
        mid = (word.start + word.end) / 2
        best = min(
            turns,
            key=lambda t: 0.0 if t[0] <= mid <= t[1] else min(abs(mid - t[0]), abs(mid - t[1])),
        )
        word.speaker = best[2]
