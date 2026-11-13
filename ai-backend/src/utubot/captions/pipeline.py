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
from .align import caption_cues, detect_silences, merge_words_into_cues, snap_cues
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
from .proofread import Proofreader
from .segment import build_cues, count_speakers, to_vtt, wrap_lines
from .separate import make_separator
from .stages import StageCache
from .types import Cue, Segment, Word

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
ASR_CACHE_STAGE = "asr"


def asr_to_cache(result: ASRResult) -> dict[str, Any]:
    return {
        "language": result.language,
        "engine": result.engine,
        "model": result.model,
        "segments": [[seg.start, seg.end, seg.text] for seg in result.segments],
        "words": [[w.start, w.end, w.text] for w in result.words],
    }


def asr_from_cache(payload: dict[str, Any]) -> ASRResult:
    return ASRResult(
        words=[Word(*word) for word in payload.get("words") or []],
        language=payload.get("language"),
        segments=[Segment(seg[0], seg[1], seg[2]) for seg in payload.get("segments") or []],
        engine=payload.get("engine"),
        model=payload.get("model"),
    )


def _set_asr(st, result: ASRResult, cached: bool = False) -> None:
    st.set(
        cached=cached or None,
        engine=result.engine,
        model=result.model,
        language=result.language,
        segments=len(result.segments),
        words=len(result.words),
        chars=sum(len(seg.text) for seg in result.segments),
    )


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
        self.cache = StageCache(db)
        self.separator = make_separator(cfg.captions)
        self.proofreader = Proofreader(llm, cfg.captions, cfg.llm.captions, self.cache)
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
        optional_asr: bool = False,
    ) -> tuple[ASRResult, Path]:
        """Audio (from the archive, else a download that the archive keeps), 16 kHz WAV, ASR.

        The WAV passes the optional vocal separation first. The ASR answer is cached per video and
        audio hash (`StageCache`), so a retried job or a second job for the same video does not
        transcribe the same audio twice. With `optional_asr` (the captions-improvement path) a
        failing engine chain leaves the words empty instead of failing the job.
        """
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
            audio_sha = entry["sha256"]
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
                audio_sha = stored["sha256"]
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
        if self.cfg.captions.separation != "off":
            with events.stage(events.SEPARATION, tool="demucs") as st:
                if self.separator is None:
                    st.skip(
                        reason="not_installed",
                        message="The separation tool is not on the PATH; using the original audio.",
                    )
                else:
                    vocals = await self.separator.separate(wav, work)
                    if vocals is None:
                        st.skip(
                            reason="unavailable",
                            message="Vocal separation produced no vocals stem; using the original audio.",
                        )
                    else:
                        await run_ffmpeg(
                            "-i",
                            str(vocals),
                            "-vn",
                            "-ac",
                            "1",
                            "-ar",
                            str(c.sample_rate),
                            "-c:a",
                            "pcm_s16le",
                            str(wav),
                        )
                        st.set(
                            bytes=file_size(vocals),
                            audio_s=round(wav_duration(wav, c.sample_rate), 1),
                        )
        progress(0.25)
        if audio_s > c.max_duration_s:
            raise YoutubeVideoError(REASON_TOO_LONG)
        result = await self._asr_stage(
            video_id,
            wav,
            requested,
            progress,
            priority=priority,
            want_words=want_words,
            audio_sha=audio_sha,
            optional_asr=optional_asr,
        )
        return result, wav

    async def _asr_stage(
        self,
        video_id: str,
        wav: Path,
        requested: str | None,
        progress: Progress,
        *,
        priority: int,
        want_words: bool,
        audio_sha: str,
        optional_asr: bool,
    ) -> ASRResult:
        """One ASR step of `_recognise`, with its per-video cache. See `_recognise`."""
        key = f"{audio_sha}:{int(want_words)}:{requested or 'auto'}"
        cached = self.cache.get(video_id, ASR_CACHE_STAGE, key)
        if cached is not None:
            result = asr_from_cache(cached)
            with events.stage(events.ASR, requested_language=requested) as st:
                _set_asr(st, result, cached=True)
            if self._asr_empty(result, want_words):
                raise PipelineError("ASR returned no words")
            return result
        try:
            with events.stage(events.ASR, requested_language=requested) as st:
                result = await self.asr.transcribe(
                    wav,
                    requested,
                    lambda f: progress(0.25 + 0.6 * f),
                    priority=priority,
                    want_words=want_words,
                )
                _set_asr(st, result)
                if not self._asr_empty(result, want_words):
                    self.cache.put(video_id, ASR_CACHE_STAGE, key, asr_to_cache(result))
        except ASRError as exc:
            if not optional_asr:
                raise
            events.emit(
                events.ASR,
                events.WARN,
                reason="engines_unavailable",
                requested_language=requested,
                error_class=events.error_class(exc),
                message="No speech engine could transcribe the audio; the caption text is kept as it is.",
            )
            return ASRResult(words=[], language=None, segments=[], engine=None, model=None)
        if self._asr_empty(result, want_words):
            raise PipelineError("ASR returned no words")
        return result

    @staticmethod
    def _asr_empty(result: ASRResult, want_words: bool) -> bool:
        return not (result.words if want_words else result.segments)

    async def _polish(self, video_id: str, cues: list[Cue], lang: str) -> list[Cue]:
        """The proofreading pass, with the video's title and description as context."""
        meta = self.db.get_json("video_meta", "video_id=?", [video_id]) or {}
        context = {
            "title": str(meta.get("title") or "")[: self.cfg.captions.proofread_context_chars],
            "description": str(meta.get("description") or "")[
                : self.cfg.captions.proofread_context_chars
            ],
        }
        return await self.proofreader.polish(video_id, cues, lang, context)

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
        """HQ captions from the audio (no usable captions on YouTube, or fetching is limited)."""
        c = self.cfg.captions
        work = self.cfg.media_dir / video_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            requested = None if lang == "auto" else lang
            result, wav = await self._recognise(
                video_id, requested, work, progress, priority=priority
            )
            if c.diarization != "none":
                with events.stage(events.DIARIZATION) as st:
                    turns = await self.diarizer.diarize(wav)
                    notes = events.take_notes()
                    if notes.get("skip"):
                        st.skip(reason=notes["skip"], message=notes.get("message"))
                    else:
                        st.set(turns=len(turns), speakers=len({turn[2] for turn in turns}))
                assign_speakers(result.words, turns)
            progress(0.9)
            with events.stage(events.CUES, announce=False) as st:
                cues = build_cues(result.words, c)
                st.set(
                    cues=len(cues),
                    words=len(result.words),
                    max_line_chars=max((len(ln) for cue in cues for ln in cue.lines), default=0),
                    max_lines=max((len(cue.lines) for cue in cues), default=0),
                    limit_line_chars=c.max_chars_per_line,
                )
            with events.stage(events.ALIGN, mode="silence") as st:
                if not c.align_silence:
                    st.skip(reason="off")
                else:
                    silences = await asyncio.to_thread(detect_silences, wav, c.silence_min_s)
                    snapped = snap_cues(cues, silences, c)
                    st.set(
                        silences=len(silences),
                        moved=sum(
                            1
                            for a, b in zip(cues, snapped, strict=True)
                            if a.start != b.start or a.end != b.end
                        ),
                    )
                    cues = snapped
            track_lang = result.language or normalize_language(requested) or "und"
            cues = await self._polish(video_id, cues, track_lang)
            track_lang = await self._finish(video_id, cues, track_lang, translate_to, progress)
            return track_lang
        finally:
            if not c.keep_media and not _keep_for_archive(work):
                shutil.rmtree(work, ignore_errors=True)

    async def improve(
        self,
        video_id: str,
        segments: list[tuple[float, float, str]],
        lang_hint: str | None,
        translate_to: str | None,
        progress: Progress,
        priority: int = BACKGROUND,
    ) -> str:
        """HQ captions built on the video's own captions: their timing, better text.

        The caption track provides the cue timing; the ASR words that fall inside each cue window
        (alignment) replace its text, and the proofreading pass fixes punctuation, names and terms.
        Cues the ASR heard nothing in keep the caption text. When no engine can transcribe, the
        captions are proofread and stored as they are.
        """
        c = self.cfg.captions
        work = self.cfg.media_dir / video_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            requested = normalize_language(lang_hint)
            result, _wav = await self._recognise(
                video_id,
                requested,
                work,
                progress,
                priority=priority,
                want_words=True,
                optional_asr=True,
            )
            with events.stage(events.CUES, announce=False, source="captions") as st:
                cues = caption_cues(segments, c)
                if not cues:
                    raise PipelineError("the caption track had no usable cues")
                st.set(cues=len(cues))
            progress(0.9)
            with events.stage(events.ALIGN, mode="merge", margin_s=c.align_window_s) as st:
                cues, from_asr = merge_words_into_cues(cues, result.words, c)
                st.set(cues=len(cues), from_asr=from_asr)
            track_lang = result.language or normalize_language(requested) or lang_hint or "und"
            track_lang = await self._finish(
                video_id,
                await self._polish(video_id, cues, track_lang),
                track_lang,
                translate_to,
                progress,
            )
            return track_lang
        finally:
            if not c.keep_media and not _keep_for_archive(work):
                shutil.rmtree(work, ignore_errors=True)

    async def _finish(
        self,
        video_id: str,
        cues: list[Cue],
        track_lang: str,
        translate_to: str | None,
        progress: Progress,
    ) -> str:
        """Proofread (done by the caller), optionally translate, then store the track."""
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
