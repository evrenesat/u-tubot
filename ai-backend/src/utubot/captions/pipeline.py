from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yt_dlp

from ..config import Config
from ..db import Database
from ..llm import BACKGROUND, LLMClient
from ..media_archive import KIND_AUDIO, SHA_PREFIX, MediaArchive, MediaArchiveError
from ..transcripts import segments_to_text
from ..youtube import (
    CLASS_MEDIA,
    MEDIA_CLASSES,
    REASON_LIVE,
    REASON_TOO_LONG,
    YoutubeGate,
    YoutubeVideoError,
    classify_failure,
    ytdlp_runtime_options,
)
from . import events
from .asr import (
    LANGUAGE_NAMES,
    ASRBackend,
    ASRError,
    ASRResult,
    make_asr,
    normalize_language,
    run_ffmpeg,
    wav_duration,
)
from .diarize import Diarizer, assign_speakers, make_diarizer
from .formats import audio_selector, track_kind
from .segment import build_cues, count_speakers, to_vtt, wrap_lines
from .types import Cue, Segment

log = logging.getLogger("utubot.captions")
VIDEO_URL = "https://www.youtube.com/watch?v={}"
SPEAKER_PREFIX_LEN = 5
TRANSLATE_SYSTEM = (
    "Translate each subtitle line into {lang}. Return ONLY a JSON array of strings with the "
    "same length and order as the input. Keep it short enough for subtitles."
)

Started = Callable[[], None]
Downloader = Callable[[str, Path, Started], Awaitable[Path]]
Progress = Callable[[float], None]


class PipelineError(RuntimeError):
    pass


@dataclass
class AsrTranscript:
    """A plain-text transcript from audio, with the segments and the engine that made them."""

    text: str
    language: str | None
    segments: list[Segment]
    engine: str | None
    model: str | None

    def segment_rows(self) -> list[tuple[float, float, str]]:
        return [(round(seg.start, 2), round(seg.end, 2), seg.text) for seg in self.segments]


def audio_filter(max_duration_s: int, verdict: dict[str, str]) -> Callable[..., str | None]:
    """yt-dlp `match_filter`: judge the real info before any audio is downloaded.

    A rejected video is skipped by yt-dlp; the reason lands in `verdict` for the caller.
    """

    def check(info: dict[str, Any], *, incomplete: bool = False) -> str | None:
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            verdict["reason"] = REASON_LIVE
            return "live streams cannot be transcribed"
        duration = info.get("duration")
        if duration and duration > max_duration_s:
            verdict["reason"] = REASON_TOO_LONG
            return "video is longer than the transcription limit"
        return None

    return check


async def download_audio(
    video_id: str,
    out_dir: Path,
    started: Started,
    *,
    fmt: str,
    max_duration_s: int,
    max_bytes: int,
    network_retry_s: float = 60.0,
    extra_opts: dict[str, Any] | None = None,
) -> Path:
    """The original-language audio at the lowest bitrate through yt-dlp (see `formats.py`).

    `fmt` is yt-dlp's own selector, used only when no usable format was recognised. `started` is
    called when the first bytes arrive.
    """

    def _hook(_status: dict[str, Any]) -> None:
        started()

    def _run() -> Path:
        verdict: dict[str, str] = {}
        fallback: list[Callable] = []
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "format": audio_selector(lambda: fallback[0] if fallback else None),
            "outtmpl": str(out_dir / "audio.%(ext)s"),
            "match_filter": audio_filter(max_duration_s, verdict),
            "max_filesize": max_bytes,
            "progress_hooks": [_hook],
            **(extra_opts or {}),
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                build = getattr(ydl, "build_format_selector", None)
                if build is not None:
                    fallback.append(build(fmt))
                info = ydl.extract_info(VIDEO_URL.format(video_id), download=True)
                if info is None:
                    raise YoutubeVideoError(verdict.get("reason", REASON_TOO_LONG))
                path = Path(ydl.prepare_filename(info))
                if not path.exists():
                    raise YoutubeVideoError(REASON_TOO_LONG)
                events.note(**chosen_format(info))
                return path
        except yt_dlp.utils.YoutubeDLError as exc:
            raise classify_failure(exc, network_retry_s, media=True, klass=CLASS_MEDIA) from None

    return await asyncio.to_thread(_run)


def chosen_format(info: dict[str, Any]) -> dict[str, Any]:
    """What the job's log says about the downloaded audio: format id, track kind, language, duration."""
    fmt = (info.get("requested_formats") or [info])[0]
    kind = track_kind(fmt)
    return {
        "format_id": fmt.get("format_id"),
        "track": kind,
        "original": kind == "original",
        "language": fmt.get("language") or info.get("language"),
        "codec": fmt.get("acodec"),
        "ext": fmt.get("ext"),
        "bitrate_kbps": fmt.get("abr"),
        "duration_s": info.get("duration"),
    }


def file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except OSError:
        return None


def sweep_media(media_dir: Path, max_age_s: float) -> int:
    """Remove scratch directories left by a crash (older than `max_age_s`); returns the count."""
    if not media_dir.is_dir():
        return 0
    cutoff = time.time() - max_age_s
    removed = 0
    for child in media_dir.iterdir():
        if child.is_dir() and child.stat().st_mtime < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


def track_label(lang: str, speakers: int) -> str:
    name = LANGUAGE_NAMES.get(lang, lang)
    extra = f", {speakers} speakers" if speakers > 1 else ""
    return f"{name} (u·tubot{extra})"


def _keep_for_archive(work: Path) -> bool:
    """True while a failed archive store unwinds through a `finally`: the downloaded file stays.

    The archive could not keep the media, so the scratch directory that holds it must survive the
    cleanup of the job that downloaded it (the owner rule: never throw away downloaded media).
    """
    exc = sys.exc_info()[1]
    return isinstance(exc, MediaArchiveError) and exc.work == work


class CaptionPipeline:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        asr: ASRBackend | None,
        llm: LLMClient | None = None,
        diarizer: Diarizer | None = None,
        downloader: Downloader | None = None,
        gate: YoutubeGate | None = None,
        archive: MediaArchive | None = None,
    ):
        self.cfg, self.db, self.llm = cfg, db, llm
        self.asr = asr or make_asr(cfg.captions)
        self.gate = gate or YoutubeGate(cfg.youtube, db)
        self.diarizer = diarizer or make_diarizer(cfg.captions)
        self.archive = archive or MediaArchive(cfg, db)
        self.downloader = downloader or (
            lambda vid, out, started: download_audio(
                vid,
                out,
                started,
                fmt=cfg.captions.audio_format,
                max_duration_s=cfg.captions.max_duration_s,
                max_bytes=cfg.captions.max_download_bytes,
                network_retry_s=cfg.youtube.network_retry_s,
                extra_opts=ytdlp_runtime_options(cfg.youtube),
            )
        )

    async def _recognise(
        self,
        video_id: str,
        requested: str | None,
        work: Path,
        progress: Progress,
        *,
        priority: int = BACKGROUND,
        want_words: bool = True,
    ) -> tuple[ASRResult, Path]:
        """Audio (from the archive, else a download that the archive keeps), 16 kHz WAV, ASR."""
        c = self.cfg.captions
        progress(0.02)
        asked = time.monotonic()

        entry = self.archive.lookup(video_id, KIND_AUDIO)
        if entry is not None:
            with events.stage(events.AUDIO, source=events.AUDIO_FROM_ARCHIVE) as st:
                st.set(
                    bytes=entry["size"],
                    format_id=entry["format_id"],
                    track="original" if entry["original"] else None,
                    language=entry["language"],
                    codec=entry["codec"],
                    bitrate_kbps=entry["bitrate_kbps"],
                )
            src = self.archive.path_of(entry)
        else:
            self.archive.require_room()

            async def fetch(started: Started) -> tuple[Path, dict[str, Any]]:
                events.emit(
                    events.GATE_WAIT,
                    events.OK,
                    klass=CLASS_MEDIA,
                    waited_s=round(time.monotonic() - asked, 2),
                    priority=events.priority_name(priority),
                )
                with events.stage(events.AUDIO) as st:
                    path = await self.downloader(video_id, work, started)
                    notes = events.take_notes()
                    st.set(
                        source=notes.pop("source", events.AUDIO_DOWNLOADED),
                        bytes=file_size(path),
                        **notes,
                    )
                return path, notes

            src, notes = await self.gate.run_started(
                fetch, priority, key=f"audio:{video_id}", classes=MEDIA_CLASSES
            )
            with events.stage(events.ARCHIVE) as st:
                stored = await asyncio.to_thread(
                    self.archive.store,
                    video_id,
                    src,
                    kind=KIND_AUDIO,
                    format_id=notes.get("format_id"),
                    codec=notes.get("codec"),
                    bitrate_kbps=notes.get("bitrate_kbps"),
                    language=notes.get("language"),
                    original=notes.get("original", 1),
                    job_id=events.job_id(),
                    work=work,
                )
                src = self.archive.path_of(stored)
                st.set(bytes=stored["size"], sha256=stored["sha256"][:SHA_PREFIX])
        progress(0.2)
        wav = work / "audio16k.wav"
        with events.stage(events.FFMPEG) as st:
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
            audio_s = wav_duration(wav, c.sample_rate)
            st.set(audio_s=round(audio_s, 1), bytes=file_size(wav), sample_rate=c.sample_rate)
        progress(0.25)
        if audio_s > c.max_duration_s:
            raise YoutubeVideoError(REASON_TOO_LONG)
        with events.stage(events.ASR, requested_language=requested) as st:
            result = await self.asr.transcribe(
                wav,
                requested,
                lambda f: progress(0.25 + 0.6 * f),
                priority=priority,
                want_words=want_words,
            )
            st.set(
                engine=result.engine,
                model=result.model,
                language=result.language,
                segments=len(result.segments),
                words=len(result.words),
                chars=sum(len(seg.text) for seg in result.segments),
            )
            if not (result.words if want_words else result.segments):
                raise PipelineError("ASR returned no words")
        return result, wav

    async def transcribe(
        self,
        video_id: str,
        progress: Progress,
        *,
        priority: int = BACKGROUND,
        language: str | None = None,
    ) -> AsrTranscript:
        """Plain-text transcript from the audio. `language` is a hint; unset, the engine detects it."""
        work = self.cfg.media_dir / video_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            result, _wav = await self._recognise(
                video_id, language, work, progress, priority=priority, want_words=False
            )
            with events.stage(events.TEXT, announce=False) as st:
                text = segments_to_text([(seg.start, seg.text) for seg in result.segments])
                if not text:
                    raise PipelineError("ASR returned no text")
                st.set(segments=len(result.segments), chars=len(text), lines=text.count("\n") + 1)
            progress(1.0)
            return AsrTranscript(
                text, result.language, result.segments, result.engine, result.model
            )
        finally:
            if not self.cfg.captions.keep_media and not _keep_for_archive(work):
                shutil.rmtree(work, ignore_errors=True)

    async def run(
        self,
        video_id: str,
        lang: str,
        translate_to: str | None,
        progress: Progress,
        priority: int = BACKGROUND,
    ) -> str:
        c = self.cfg.captions
        work = self.cfg.media_dir / video_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            requested = None if lang == "auto" else lang
            result, wav = await self._recognise(
                video_id, requested, work, progress, priority=priority
            )
            with events.stage(events.DIARIZATION) as st:
                turns = await self.diarizer.diarize(wav)
                notes = events.take_notes()
                if notes.get("skip"):
                    st.skip(reason=notes["skip"], message=notes.get("message"))
                else:
                    st.set(turns=len(turns), speakers=len({turn[2] for turn in turns}))
            progress(0.9)
            assign_speakers(result.words, turns)
            with events.stage(events.CUES, announce=False) as st:
                cues = build_cues(result.words, c)
                st.set(
                    cues=len(cues),
                    words=len(result.words),
                    max_line_chars=max((len(ln) for cue in cues for ln in cue.lines), default=0),
                    max_lines=max((len(cue.lines) for cue in cues), default=0),
                    limit_line_chars=c.max_chars_per_line,
                )
            track_lang = result.language or normalize_language(requested) or "und"
            if translate_to and translate_to != track_lang:
                with events.stage(events.TRANSLATE, source=track_lang, to=translate_to) as st:
                    cues = await self.translate(cues, translate_to)
                    st.set(cues=len(cues))
                track_lang = translate_to
            vtt = to_vtt(cues)
            speakers = count_speakers(cues)
            label = track_label(track_lang, speakers)
            self.db.execute(
                "INSERT OR REPLACE INTO captions(video_id,lang,label,speakers,vtt,created_at,job_id)"
                " VALUES(?,?,?,?,?,?,?)",
                [video_id, track_lang, label, speakers, vtt, time.time(), events.job_id()],
            )
            events.emit(
                events.STORED,
                events.OK,
                kind="captions",
                lang=track_lang,
                label=label,
                speakers=speakers,
                cues=len(cues),
                bytes=len(vtt.encode()),
            )
            progress(1.0)
            return track_lang
        finally:
            if not c.keep_media and not _keep_for_archive(work):
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
