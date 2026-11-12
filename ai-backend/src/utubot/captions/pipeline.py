from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import yt_dlp

from ..config import Config
from ..db import Database
from ..llm import BACKGROUND, LLMClient
from ..transcripts import segments_to_text
from ..youtube import YoutubeGate, classify_failure
from .asr import (
    LANGUAGE_NAMES,
    ASRBackend,
    ASRError,
    ASRResult,
    normalize_language,
    run_ffmpeg,
)
from .diarize import Diarizer, assign_speakers, make_diarizer
from .segment import build_cues, count_speakers, to_vtt, wrap_lines
from .types import Cue

log = logging.getLogger("utubot.captions")
VIDEO_URL = "https://www.youtube.com/watch?v={}"
SPEAKER_PREFIX_LEN = 5
TRANSLATE_SYSTEM = (
    "Translate each subtitle line into {lang}. Return ONLY a JSON array of strings with the "
    "same length and order as the input. Keep it short enough for subtitles."
)

Downloader = Callable[[str, Path], Awaitable[Path]]
Progress = Callable[[float], None]


class PipelineError(RuntimeError):
    pass


async def download_audio(
    video_id: str, out_dir: Path, fmt: str, network_retry_s: float = 60.0
) -> Path:
    def _run() -> Path:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "format": fmt,
            "outtmpl": str(out_dir / "audio.%(ext)s"),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(VIDEO_URL.format(video_id), download=True)
                return Path(ydl.prepare_filename(info))
        except yt_dlp.utils.YoutubeDLError as exc:
            raise classify_failure(exc, network_retry_s) from None

    return await asyncio.to_thread(_run)


def track_label(lang: str, speakers: int) -> str:
    name = LANGUAGE_NAMES.get(lang, lang)
    extra = f", {speakers} speakers" if speakers > 1 else ""
    return f"{name} (u·tubot{extra})"


class CaptionPipeline:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        asr: ASRBackend,
        llm: LLMClient | None = None,
        diarizer: Diarizer | None = None,
        downloader: Downloader | None = None,
        gate: YoutubeGate | None = None,
    ):
        self.cfg, self.db, self.asr, self.llm = cfg, db, asr, llm
        self.gate = gate or YoutubeGate(cfg.youtube, db)
        self.diarizer = diarizer or make_diarizer(cfg.captions)
        self.downloader = downloader or (
            lambda vid, out: download_audio(
                vid, out, cfg.captions.audio_format, cfg.youtube.network_retry_s
            )
        )

    async def _recognise(
        self, video_id: str, requested: str | None, work: Path, progress: Progress
    ) -> tuple[ASRResult, Path]:
        """Audio download (through the YouTube gate), 16 kHz mono WAV, ASR. Shared by both jobs."""
        c = self.cfg.captions
        progress(0.02)
        src = await self.gate.run(
            lambda: self.downloader(video_id, work), BACKGROUND, key=f"audio:{video_id}"
        )
        progress(0.2)
        wav = work / "audio16k.wav"
        await run_ffmpeg(
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(c.sample_rate),
            "-c:a",
            "pcm_s16le",
            str(wav),
        )
        progress(0.25)
        result = await self.asr.transcribe(wav, requested, lambda f: progress(0.25 + 0.6 * f))
        if not result.words:
            raise PipelineError("ASR returned no words")
        return result, wav

    async def transcribe(self, video_id: str, progress: Progress) -> tuple[str, str | None]:
        """Plain-text transcript from the audio (language auto-detected): `(text, language)`."""
        work = self.cfg.media_dir / video_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            result, _wav = await self._recognise(video_id, None, work, progress)
            cues = build_cues(result.words, self.cfg.captions)
            text = segments_to_text([(cue.start, " ".join(cue.lines)) for cue in cues])
            if not text:
                raise PipelineError("ASR returned no text")
            progress(1.0)
            return text, result.language
        finally:
            if not self.cfg.captions.keep_media:
                shutil.rmtree(work, ignore_errors=True)

    async def run(
        self, video_id: str, lang: str, translate_to: str | None, progress: Progress
    ) -> str:
        c = self.cfg.captions
        work = self.cfg.media_dir / video_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            requested = None if lang == "auto" else lang
            result, wav = await self._recognise(video_id, requested, work, progress)
            turns = await self.diarizer.diarize(wav)
            progress(0.9)
            assign_speakers(result.words, turns)
            cues = build_cues(result.words, c)
            track_lang = result.language or normalize_language(requested) or "und"
            if translate_to and translate_to != track_lang:
                cues = await self.translate(cues, translate_to)
                track_lang = translate_to
            vtt = to_vtt(cues)
            speakers = count_speakers(cues)
            self.db.execute(
                "INSERT OR REPLACE INTO captions(video_id,lang,label,speakers,vtt,created_at)"
                " VALUES(?,?,?,?,?,?)",
                [
                    video_id,
                    track_lang,
                    track_label(track_lang, speakers),
                    speakers,
                    vtt,
                    time.time(),
                ],
            )
            progress(1.0)
            return track_lang
        finally:
            if not c.keep_media:
                shutil.rmtree(work, ignore_errors=True)

    async def translate(self, cues: list[Cue], target: str) -> list[Cue]:
        if self.llm is None:
            raise PipelineError("translation needs an LLM client")
        batch = self.cfg.captions.translate_batch
        c = self.cfg.captions
        out: list[Cue] = []
        for i in range(0, len(cues), batch):
            part = cues[i : i + batch]
            prefixes, texts = [], []
            for cue in part:
                joined = " ".join(cue.lines)
                has = joined.startswith("[S")
                prefixes.append(joined[:SPEAKER_PREFIX_LEN] if has else "")
                texts.append(joined[SPEAKER_PREFIX_LEN:] if has else joined)
            data = await self.llm.chat_json(
                self.cfg.llm.captions,
                [
                    {"role": "system", "content": TRANSLATE_SYSTEM.format(lang=target)},
                    {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
                ],
            )
            if not isinstance(data, list) or len(data) != len(part):
                raise PipelineError("translation length mismatch")
            for cue, prefix, text in zip(part, prefixes, data, strict=True):
                full = f"{prefix}{text}".strip()
                lines = wrap_lines(full, c.max_chars_per_line, c.max_lines) or [full]
                out.append(Cue(cue.start, cue.end, lines, cue.speaker))
        return out


__all__ = ["CaptionPipeline", "PipelineError", "ASRError"]
