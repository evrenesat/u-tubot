"""A diagnostic score for a stored caption track (`utubot captions-score`).

The stored VTT is compared with a reference: evenly spaced windows of the archived audio are
transcribed with one named engine, and the onsets of its phrases are matched with the track's cue
starts (`syncscore`). It reads the archive and a speech engine; it never touches YouTube.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import statistics
import subprocess
import tempfile
import unicodedata
from pathlib import Path
from typing import Any

import httpx

from ..config import AsrEngineConfig, Config
from ..db import Database
from ..media_archive import KIND_AUDIO, MediaArchive
from ..transcripts import parse_vtt
from .align import detect_silences
from .asr import audio_start_offset, normalize_language, run_ffmpeg
from .chunking import bare
from .engines import AsrRouter, EngineFactory
from .meaning import meaning_block
from .pipeline import ASR_CACHE_STAGE, ASR_CACHE_VERSION, asr_from_cache
from .syncscore import (
    PERCENTILE_HIGH,
    PERCENTILE_LOW,
    PERCENTILE_TAIL,
    SECONDS_DIGITS,
    SHARE_DIGITS,
    percentile,
    phrase_onsets,
    score_starts,
)
from .types import Word
from .wordtimes import repair_words


class ScoreError(RuntimeError):
    pass


def _is_latin(ch: str) -> bool:
    return ch.isascii() or "LATIN" in unicodedata.name(ch, "")


def latin_share(words: list[Word]) -> float:
    """Share of words whose letters are all Latin (0 for no words)."""
    letters = [[ch for ch in w.text if ch.isalpha()] for w in words]
    letters = [chars for chars in letters if chars]
    if not letters:
        return 0.0
    return sum(1 for chars in letters if all(_is_latin(ch) for ch in chars)) / len(letters)


def cached_engine_words(db: Database, video_id: str) -> list[Word] | None:
    """The newest cached raw engine words of the video (current cache layout, word-time answer).

    The one cache holds the strongest answer per (audio, audio variant, language); the newest one
    that actually carries words is the one a scored track was aligned from."""
    for row in db.all(
        "SELECT json FROM stage_cache WHERE video_id=? AND stage=? AND cache_key LIKE ?"
        " ORDER BY created_at DESC",
        [video_id, ASR_CACHE_STAGE, f"v{ASR_CACHE_VERSION}:%"],
    ):
        try:
            words = asr_from_cache(json.loads(row["json"])).words
        except (ValueError, TypeError, IndexError):
            continue
        if words:
            return sorted(words, key=lambda w: w.start) or None
    return None


def match_errors(reference: list[Word], cached: list[Word], offset: float) -> list[float]:
    """`cached.start - reference.start - offset` for every token the two lists share, in order."""
    ref_tokens = [bare(w.text) for w in reference]
    own_tokens = [bare(w.text) for w in cached]
    matcher = difflib.SequenceMatcher(None, ref_tokens, own_tokens, autojunk=False)
    errors: list[float] = []
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            if ref_tokens[block.a + k]:
                errors.append(cached[block.b + k].start - reference[block.a + k].start - offset)
    return errors


def words_block(
    windows: list[tuple[float, float, list[Word]]], cached: list[Word], cfg: Config
) -> dict[str, Any]:
    """The engine's cached words checked against the same audio transcribed in windows."""
    errors: list[float] = []
    total = 0
    for begin, end, ref_words in windows:
        inside = [w for w in cached if begin <= w.start < end]
        total += len(ref_words)
        errors += match_errors(ref_words, inside, begin)
    if not errors:
        return {
            "matched": 0,
            "matched_share": 0.0,
            "median_s": None,
            "p10_s": None,
            "p90_s": None,
            "p95_s": None,
            "within_s": 0.0,
        }
    ordered = sorted(errors)
    within = sum(1 for e in ordered if abs(e) <= cfg.captions.sync_late_s)
    return {
        "matched": len(ordered),
        "matched_share": round(len(ordered) / total, SHARE_DIGITS) if total else 0.0,
        "median_s": round(statistics.median(ordered), SECONDS_DIGITS),
        "p10_s": round(percentile(ordered, PERCENTILE_LOW), SECONDS_DIGITS),
        "p90_s": round(percentile(ordered, PERCENTILE_HIGH), SECONDS_DIGITS),
        "p95_s": round(percentile(ordered, PERCENTILE_TAIL), SECONDS_DIGITS),
        "within_s": round(within / len(ordered), SHARE_DIGITS),
    }


def _automated() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("CI"))


def window_starts(total_s: float, windows: int, window_s: float) -> list[float]:
    """Starts of `windows` evenly spaced windows of `window_s` inside `total_s` (one window if short)."""
    if total_s <= window_s:
        return [0.0]
    room = total_s - window_s
    return [round(room * (i + 0.5) / windows, 3) for i in range(windows)]


def begins(total_s: float, at: list[float] | None, windows: int, window_s: float) -> list[float]:
    """Window starts: the requested ones (kept inside the audio), else evenly spaced."""
    if not at:
        return window_starts(total_s, windows, window_s)
    room = max(total_s - window_s, 0.0)
    return [round(min(max(start, 0.0), room), 3) for start in at]


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
    spoken: str | None = None,
    at: list[float] | None = None,
    windows: int | None = None,
    window_s: float | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    engine_factory: EngineFactory | None = None,
    review: bool = False,
    reference_translation: str | None = None,
) -> dict[str, Any]:
    """The sync score of a stored track of `video_id` against windows transcribed by `reference`.

    `lang` picks the track; by default the newest one that has a `timing_version`, else the newest.
    `spoken` is the audio's language (default: the transcript's). `at` lists window starts in
    seconds instead of evenly spaced windows. `reference_translation` is a VTT/SRT/text file
    translated from the video's speech; its token F1 against this track becomes the report's
    `meaning` block, the input the release gate compares.
    """
    c = cfg.captions
    if transport is None and engine_factory is None and _automated():
        raise ScoreError("captions-score reaches a speech engine; it does not run from tests or CI")
    windows = windows or c.score_windows
    window_s = window_s or c.score_window_s
    engine = reference_engine(cfg, reference)
    columns = "SELECT lang,vtt,timing_version,created_at FROM captions WHERE video_id=?"
    if lang:
        row = db.one(columns + " AND lang=? ORDER BY created_at DESC LIMIT 1", [video_id, lang])
    else:
        row = db.one(
            columns + " ORDER BY (timing_version IS NOT NULL) DESC, created_at DESC LIMIT 1",
            [video_id],
        )
    if row is None:
        raise ScoreError("no stored captions for this video")
    cues = parse_vtt(row["vtt"])
    cue_starts = [start for start, _end, _text in cues]
    track = {
        "lang": row["lang"],
        "timing_version": row["timing_version"],
        "created_at": row["created_at"],
        "cues": len(cues),
        "first_cue_start_s": round(min(cue_starts), 3) if cue_starts else None,
        "max_cue_s": round(max((end - start for start, end, _t in cues), default=0.0), 3),
        "short_cues": sum(1 for start, end, _t in cues if end - start < c.gate_short_cue_s),
    }
    archive = MediaArchive(cfg, db)
    entry = archive.lookup(video_id, KIND_AUDIO)
    if entry is None:
        raise ScoreError("the audio is not archived; nothing is downloaded by this command")
    source = archive.path_of(entry)
    if spoken is None:
        transcript = db.one("SELECT lang FROM transcripts WHERE video_id=?", [video_id])
        spoken = transcript["lang"] if transcript else None
    language = normalize_language(spoken)
    router = AsrRouter(
        c.model_copy(update={"asr_engines": [engine]}),
        transport=transport,
        engine_factory=engine_factory,
    )
    total = await asyncio.to_thread(audio_duration, source)
    audio_offset = await audio_start_offset(source)
    onsets_all: list[float] = []
    per_window: list[dict[str, Any]] = []
    ref_windows: list[tuple[float, float, list[Word]]] = []
    cfg.media_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="score-", dir=cfg.media_dir) as scratch:
        for begin in begins(total, at, windows, window_s):
            length = min(window_s, total - begin)
            origin = max(begin, audio_offset)
            wav = Path(scratch) / f"w{int(begin)}.wav"
            await run_ffmpeg(
                "-ss", str(begin), "-t", str(length), "-i", str(source), "-vn", "-ac", "1",
                "-ar", str(c.sample_rate), "-c:a", "pcm_s16le", str(wav),
            )  # fmt: skip
            result = await router.transcribe(
                wav, language, lambda f: None, want_words=True, review=review
            )
            silences = await asyncio.to_thread(detect_silences, wav, c.silence_min_s)
            words, _stats = repair_words(result.words, silences, c)
            local = phrase_onsets([(w.start, w.end) for w in words], c.sentence_gap_s)
            # a window cut mid-speech makes its first "onset" a cut, not a phrase start; the
            # first window can start before a late first sample, where nothing was cut
            onsets = [origin + t for t in (local[1:] if begin > 0 and origin == begin else local)]
            onsets_all += onsets
            ref_windows.append((origin, origin + length, words))
            score = score_starts(cue_starts, onsets, c)
            per_window.append(
                {
                    "start_s": begin,
                    "end_s": round(begin + length, 3),
                    "words": len(words),
                    "language": result.language,
                    "latin_share": round(latin_share(words), SHARE_DIGITS),
                    "word_timing": result.word_timing,
                    **score.as_detail(),
                }
            )
            wav.unlink(missing_ok=True)
    cached = cached_engine_words(db, video_id)
    meaning = (
        meaning_block(
            " ".join(text for _start, _end, text in cues),
            reference_translation,
            c.gate_meaning_min,
        )
        if reference_translation
        else None
    )
    return {
        "video_id": video_id,
        "track": track,
        "reference": reference,
        "window_s": window_s,
        "spoken_language": language,
        "reference_language_ok": language is None
        or all(win["language"] == language for win in per_window),
        "windows": per_window,
        "words": words_block(ref_windows, cached, cfg) if cached else None,
        "meaning": meaning,
        "overall": score_starts(cue_starts, onsets_all, c).as_detail(),
    }
