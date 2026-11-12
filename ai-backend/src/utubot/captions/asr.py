from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from ..config import CaptionsConfig
from .types import Word

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


class ASRBackend(Protocol):
    async def transcribe(
        self, wav: Path, language: str | None, progress: ProgressFn
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


def wav_duration(path: Path, sample_rate: int) -> float:
    bytes_per_sample = 2
    return max(path.stat().st_size - 44, 0) / (sample_rate * bytes_per_sample)


class OpenAIASR:
    def __init__(self, cfg: CaptionsConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.cfg = cfg
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        key = os.environ.get(self.cfg.asr_api_key_env)
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def _post(self, http: httpx.AsyncClient, path: Path, language: str | None) -> dict:
        data = {
            "model": self.cfg.asr_model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["word", "segment"],
        }
        if language:
            data["language"] = language
        with path.open("rb") as fh:
            resp = await http.post(
                self.cfg.asr_url,
                data=data,
                files={"file": (path.name, fh, "audio/wav")},
                headers=self._headers(),
            )
        if resp.status_code >= 400:
            raise ASRError(f"asr http {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    async def transcribe(self, wav: Path, language: str | None, progress: ProgressFn) -> ASRResult:
        total = wav_duration(wav, self.cfg.sample_rate)
        chunk_s = self.cfg.asr_chunk_s
        spans = (
            [(0.0, total)]
            if total <= chunk_s
            else [
                (float(s), min(float(s + chunk_s), total))
                for s in range(0, int(total) + 1, chunk_s)
                if s < total
            ]
        )
        words: list[Word] = []
        detected: str | None = None
        async with httpx.AsyncClient(
            timeout=self.cfg.asr_timeout_s, transport=self._transport
        ) as http:
            for idx, (start, end) in enumerate(spans):
                part = wav
                if len(spans) > 1:
                    part = wav.with_name(f"{wav.stem}.part{idx}.wav")
                    await run_ffmpeg(
                        "-ss",
                        str(start),
                        "-t",
                        str(end - start),
                        "-i",
                        str(wav),
                        "-c",
                        "copy",
                        str(part),
                    )
                try:
                    data = await self._post(http, part, language or detected)
                finally:
                    if part != wav:
                        part.unlink(missing_ok=True)
                detected = detected or normalize_language(data.get("language"))
                words.extend(self._parse(data, start))
                progress((idx + 1) / len(spans))
        return ASRResult(words, detected)

    @staticmethod
    def _parse(data: dict, offset: float) -> list[Word]:
        raw_words = data.get("words") or []
        if raw_words:
            return [
                Word(offset + w["start"], offset + w["end"], str(w.get("word", w.get("text", ""))))
                for w in raw_words
            ]
        out: list[Word] = []
        for seg in data.get("segments") or []:
            out.extend(
                words_from_segment(offset + seg["start"], offset + seg["end"], seg.get("text", ""))
            )
        return out


class FasterWhisperASR:
    def __init__(self, cfg: CaptionsConfig):
        self.cfg = cfg
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise ASRError("faster-whisper is not installed (uv sync --extra asr)") from exc
            self._model = WhisperModel(
                self.cfg.whisper_model,
                device="cpu",
                compute_type=self.cfg.whisper_compute_type,
                cpu_threads=self.cfg.whisper_threads,
            )
        return self._model

    def _run(self, wav: Path, language: str | None, progress: ProgressFn) -> ASRResult:
        model = self._load()
        segments, info = model.transcribe(
            str(wav), language=language, word_timestamps=True, vad_filter=True
        )
        total = max(info.duration, 1e-6)
        words: list[Word] = []
        for seg in segments:
            if seg.words:
                words.extend(Word(w.start, w.end, w.word.strip()) for w in seg.words)
            else:
                words.extend(words_from_segment(seg.start, seg.end, seg.text))
            progress(min(seg.end / total, 1.0))
        return ASRResult(words, normalize_language(info.language))

    async def transcribe(self, wav: Path, language: str | None, progress: ProgressFn) -> ASRResult:
        return await asyncio.to_thread(self._run, wav, language, progress)


def make_asr(cfg: CaptionsConfig) -> ASRBackend:
    if cfg.asr_backend == "openai":
        return OpenAIASR(cfg)
    if cfg.asr_backend == "faster_whisper":
        return FasterWhisperASR(cfg)
    raise ASRError(f"unknown asr_backend {cfg.asr_backend}")


def ffmpeg_available() -> bool:
    try:
        return subprocess.run(["ffmpeg", "-version"], capture_output=True).returncode == 0
    except FileNotFoundError:
        return False
