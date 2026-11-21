"""A diagnostic score for a stored caption track (`utubot captions-score`).

The stored VTT is compared with a reference: evenly spaced windows of the archived audio are
transcribed with one named engine, and the onsets of its phrases are matched with the track's cue
starts (`syncscore`). It reads the archive and a speech engine; it never touches YouTube.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

from ..config import AsrEngineConfig, Config
from ..db import Database
from ..media_archive import KIND_AUDIO, MediaArchive
from ..transcripts import parse_vtt
from .align import detect_silences
from .asr import normalize_language, run_ffmpeg
from .engines import AsrRouter, EngineFactory
from .syncscore import phrase_onsets, score_starts
from .wordtimes import repair_words


class ScoreError(RuntimeError):
    pass


def _automated() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"))


def window_starts(total_s: float, windows: int, window_s: float) -> list[float]:
    """Starts of `windows` evenly spaced windows of `window_s` inside `total_s` (one window if short)."""
    if total_s <= window_s:
        return [0.0]
    room = total_s - window_s
    return [round(room * (i + 0.5) / windows, 3) for i in range(windows)]


def audio_duration(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    try:
        return float(proc.stdout.decode().strip())
    except ValueError:
        raise ScoreError("could not read the audio duration (is ffprobe installed?)") from None


def reference_engine(cfg: Config, name: str) -> AsrEngineConfig:
    for engine in cfg.captions.engines():
        if engine.name == name:
            return engine
    names = ", ".join(e.name for e in cfg.captions.engines())
    raise ScoreError(f"no engine named {name!r} in the chain (engines: {names})")


async def score_track(
    cfg: Config,
    db: Database,
    video_id: str,
    *,
    reference: str,
    lang: str | None = None,
    windows: int | None = None,
    window_s: float | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    engine_factory: EngineFactory | None = None,
) -> dict[str, Any]:
    """The sync score of the stored track of `video_id` against windows transcribed by `reference`."""
    c = cfg.captions
    if transport is None and engine_factory is None and _automated():
        raise ScoreError("captions-score reaches a speech engine; it does not run from tests or CI")
    windows = windows or c.score_windows
    window_s = window_s or c.score_window_s
    engine = reference_engine(cfg, reference)
    row = db.one(
        "SELECT lang,vtt FROM captions WHERE video_id=? ORDER BY created_at DESC LIMIT 1",
        [video_id],
    )
    if row is None:
        raise ScoreError("no stored captions for this video")
    cue_starts = [start for start, _end, _text in parse_vtt(row["vtt"])]
    archive = MediaArchive(cfg, db)
    entry = archive.lookup(video_id, KIND_AUDIO)
    if entry is None:
        raise ScoreError("the audio is not archived; nothing is downloaded by this command")
    source = archive.path_of(entry)
    if lang is None:
        transcript = db.one("SELECT lang FROM transcripts WHERE video_id=?", [video_id])
        lang = transcript["lang"] if transcript else None
    language = normalize_language(lang)
    router = AsrRouter(
        c.model_copy(update={"asr_engines": [engine]}),
        transport=transport,
        engine_factory=engine_factory,
    )
    total = await asyncio.to_thread(audio_duration, source)
    onsets_all: list[float] = []
    per_window: list[dict[str, Any]] = []
    cfg.media_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="score-", dir=cfg.media_dir) as scratch:
        for begin in window_starts(total, windows, window_s):
            length = min(window_s, total - begin)
            wav = Path(scratch) / f"w{int(begin)}.wav"
            await run_ffmpeg(
                "-ss", str(begin), "-t", str(length), "-i", str(source), "-vn", "-ac", "1",
                "-ar", str(c.sample_rate), "-c:a", "pcm_s16le", str(wav),
            )  # fmt: skip
            result = await router.transcribe(wav, language, lambda f: None, want_words=True)
            silences = await asyncio.to_thread(detect_silences, wav, c.silence_min_s)
            words, _stats = repair_words(result.words, silences, c)
            local = phrase_onsets([(w.start, w.end) for w in words], c.sentence_gap_s)
            # a window cut mid-speech makes its first "onset" a cut, not a phrase start
            onsets = [begin + t for t in (local[1:] if begin > 0 else local)]
            onsets_all += onsets
            score = score_starts(cue_starts, onsets, c)
            per_window.append(
                {
                    "start_s": begin,
                    "end_s": round(begin + length, 3),
                    "words": len(words),
                    "word_timing": result.word_timing,
                    **score.as_detail(),
                }
            )
            wav.unlink(missing_ok=True)
    return {
        "video_id": video_id,
        "lang": row["lang"],
        "reference": reference,
        "window_s": window_s,
        "windows": per_window,
        "overall": score_starts(cue_starts, onsets_all, c).as_detail(),
    }
