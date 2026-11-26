from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yt_dlp

from ..classes import NORMAL
from ..config import CaptionsConfig, Config
from ..db import Database
from ..llm import BACKGROUND, LLMBadJSONError, LLMClient
from ..media_archive import (
    KIND_AUDIO,
    SHA_PREFIX,
    MediaArchive,
    MediaArchiveError,
    MediaArchiveFull,
)
from ..transcripts import CAPTION_MANUAL, segments_to_text
from ..youtube import (
    CLASS_MEDIA,
    MEDIA_CLASSES,
    REASON_LIVE,
    REASON_TOO_LONG,
    YoutubeGate,
    YoutubeVideoError,
    classify_failure,
    retry_forbidden,
    ytdlp_runtime_options,
)
from . import events, gate, reference
from .align import (
    AlignStats,
    caption_cues,
    detect_silences,
    finish_cues,
    merge_words_into_cues,
    snap_cues,
    word_cues,
)
from .asr import (
    LANGUAGE_NAMES,
    ASRBackend,
    ASRError,
    ASRResult,
    make_asr,
    normalize_language,
    run_ffmpeg,
    transcode_wav,
    wav_duration,
)
from .diarize import Diarizer, assign_speakers, make_diarizer
from .formats import audio_selector, track_kind
from .proofread import Proofreader
from .reference import Check
from .reference import check as check_reference
from .sanity import FLAG_CREDIT, drop_flagged, flag_segments
from .segment import (
    SplitStats,
    build_cues,
    count_speakers,
    merge_short,
    pad_cues,
    split_cue,
    to_vtt,
    wrap_lines,
)
from .separate import make_separator
from .stages import StageCache
from .syncscore import self_check
from .types import TIMING_INTERPOLATED, Cue, Segment, Word
from .wordtimes import WordStats, classify, count_kinds, repair_words

log = logging.getLogger("utubot.captions")
VIDEO_URL = "https://www.youtube.com/watch?v={}"
SPEAKER_PREFIX_LEN = 5
TRANSLATE_SYSTEM = (
    "Translate each subtitle line into {lang}. Return ONLY a JSON array of strings with the "
    "same length and order as the input. Keep it short enough for subtitles."
)

TRANSLATE_STRICT = (
    "Return exactly {n} strings: one translation per input string, same order, as a JSON array."
)

Started = Callable[[], None]
Downloader = Callable[[str, Path, Started], Awaitable[Path]]
Progress = Callable[[float], None]
ASR_CACHE_STAGE = "asr"


ASR_CACHE_VERSION = 5  # the layout and meaning of a cached ASR answer: a new value ignores older rows (3: chunk review, 4: audio start offset, 5: one cache, strongest answer serves every ask)
TIMING_VERSION = 5  # the caption timing scheme of a stored track (`captions.timing_version`)
SEGMENT_METRICS = 3  # no_speech_prob, avg_logprob, compression_ratio follow start, end, text


def asr_to_cache(result: ASRResult) -> dict[str, Any]:
    """The engine's answer as stored: its words as the engine gave them, before `repair_words`."""
    return {
        "v": ASR_CACHE_VERSION,
        "language": result.language,
        "engine": result.engine,
        "model": result.model,
        "word_timing": result.word_timing,
        "stats": result.stats,
        "dropped": result.dropped,
        "chunks": result.chunks,
        "segments": [
            [
                seg.start,
                seg.end,
                seg.text,
                seg.no_speech_prob,
                seg.avg_logprob,
                seg.compression_ratio,
            ]
            for seg in result.segments
        ],
        "words": [[w.start, w.end, w.text, w.prob, w.timing] for w in result.words],
    }


def _word_from_row(row: list[Any]) -> Word:
    prob = row[3] if len(row) > 3 else None
    timing = row[4] if len(row) > 4 else TIMING_INTERPOLATED
    return Word(row[0], row[1], row[2], prob=prob, timing=timing)


def _segment_from_row(row: list[Any]) -> Segment:
    metrics = row[3 : 3 + SEGMENT_METRICS]
    metrics += [None] * (SEGMENT_METRICS - len(metrics))
    return Segment(row[0], row[1], row[2], *metrics)


def drop_cached_credits(result: ASRResult, cfg: CaptionsConfig) -> ASRResult:
    """A cached answer without the credit lines Whisper makes up (answers cached before the rule)."""
    if not cfg.asr_recheck or not result.segments:
        return result
    flags = [found & {FLAG_CREDIT} for found in flag_segments(result.segments, cfg)]
    segments, words, dropped = drop_flagged(result.segments, result.words, flags)
    if not dropped:
        return result
    result.segments, result.words = segments, words
    result.stats["hallucination_drops"] = result.stats.get("hallucination_drops", 0) + len(dropped)
    result.dropped = [*result.dropped, *([d.start, d.end, d.reason] for d in dropped)]
    return result


def asr_from_cache(payload: dict[str, Any]) -> ASRResult:
    """An `asr_to_cache` payload back; rows of the older three-item layout load as well."""
    return ASRResult(
        words=[_word_from_row(row) for row in payload.get("words") or []],
        language=payload.get("language"),
        segments=[_segment_from_row(row) for row in payload.get("segments") or []],
        engine=payload.get("engine"),
        model=payload.get("model"),
        word_timing=payload.get("word_timing"),
        stats=dict(payload.get("stats") or {}),
        dropped=list(payload.get("dropped") or []),
        chunks=list(payload.get("chunks") or []),
    )


def _set_asr(st, result: ASRResult, cached: bool = False) -> None:
    real, interpolated = count_kinds(result.words)
    st.set(
        cached=cached or None,
        engine=result.engine,
        model=result.model,
        language=result.language,
        segments=len(result.segments),
        words=len(result.words),
        chars=sum(len(seg.text) for seg in result.segments),
        word_timing=result.word_timing,
        words_real=real,
        words_interpolated=interpolated,
        rechecked_chunks=result.stats.get("rechecked_chunks"),
        hallucination_drops=result.stats.get("hallucination_drops"),
        dropped_s=result.stats.get("dropped_s"),
        recheck_requests=result.stats.get("recheck_requests"),
        skipped_chunks=result.stats.get("skipped_chunks"),
    )


def asr_cache_key(audio_sha: str, requested: str | None, separation: str) -> str:
    """The ASR stage-cache key: the cache layout version, the audio bytes, the audio variant and the
    language the answer is for (`auto` when the ask did not name one).

    Word times are not part of the key. The strongest answer (with real or mixed word times) is
    stored once and answers a segments-only ask too, so a transcript and the HQ captions it feeds
    share one speech-recognition run instead of each computing its own. A result is stored under the
    language it was made for, so one language-detected run answers a later ask with that language."""
    return f"v{ASR_CACHE_VERSION}:{audio_sha}:{separation}:{requested or 'auto'}"


def _asr_base_code(code: str | None) -> str:
    return (code or "").split("-")[0].lower()


def asr_answer_gives_words(asr: Any, requested: str | None) -> bool:
    """Whether the current engine chain is known to return word times for this ask."""
    gives_words = getattr(asr, "chain_gives_words", None)
    return bool(gives_words and gives_words(requested))


def asr_answer_usable(
    payload: dict[str, Any], asr: Any, want_words: bool, requested: str | None
) -> bool:
    """A cached ASR answer serves this ask: its language matches and it is strong enough.

    `want_words` needs words (real or mixed times). A wordless (interpolated) answer is reusable
    only while no engine of the chain gives words: once one does, the ask recomputes for real times
    instead of reusing an estimate. A named language matches that language; an unset one takes any
    result, so a language-detected run answers a later ask with that language."""
    if requested:
        lang = normalize_language(payload.get("language"))
        if not lang or _asr_base_code(lang) != _asr_base_code(normalize_language(requested)):
            return False
    if not want_words:
        return True
    if not payload.get("words"):
        return False
    if payload.get("word_timing") == "interpolated" and asr_answer_gives_words(asr, requested):
        return False
    return True


def ref_check_summary(verdict: Check) -> dict[str, Any]:
    """The `ref_check` entry of the stored `timing`: small, no word lists."""
    if verdict.status == reference.STATUS_SKIPPED or verdict.agreement is None:
        return {"skipped": verdict.reason}
    agreement = verdict.agreement
    return {
        "anchors": agreement.anchors,
        "median_s": round(agreement.median_s, 3),
        "within_s": round(agreement.within_s, 3),
        "regions": len(agreement.regions),
    }


def word_mode_suffix(asr: Any, language: str | None) -> str:
    """The key part of an answer without word times: the engines and how each is asked for words.

    A server that never gives words keeps answering the same way, so its answer is reusable only
    while the engine configuration (and its resolved word mode) is the same one.
    """
    signature = getattr(asr, "word_signature", None)
    return f":wm-{signature(language)}" if signature else ":wm-unknown"


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
    player_clients: list[str] | None = None,
    forbidden_backoff_s: float = 1.0,
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

        def run(player: str) -> Path:
            player_opts = {**opts, "extractor_args": {"youtube": {"player_client": [player]}}}
            with yt_dlp.YoutubeDL(player_opts) as ydl:
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

        # A 403 on the media download is retried with the next player client before the failure is
        # classified once (a download refused for this video).
        try:
            return retry_forbidden(
                run,
                player_clients or ["web", "android"],
                forbidden_backoff_s,
            )
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


@dataclass
class TranslateStats:
    """How the translation batches went: asked, retried once, split in halves, left as spoken."""

    batches: int = 0
    retried: int = 0
    split: int = 0
    untranslated: int = 0

    def as_detail(self) -> dict[str, int]:
        return {
            "batches": self.batches,
            "retried": self.retried,
            "split": self.split,
            "untranslated": self.untranslated,
        }


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
                player_clients=cfg.youtube.player_clients,
                forbidden_backoff_s=cfg.youtube.forbidden_backoff_s,
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
        klass: str = NORMAL,
        yield_check: Callable[[], Awaitable[None]] | None = None,
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
            offset = await transcode_wav(src, wav, c.sample_rate)
            audio_s = wav_duration(wav, c.sample_rate)
            detail = {
                "audio_s": round(audio_s, 1),
                "bytes": file_size(wav),
                "sample_rate": c.sample_rate,
            }
            if offset:
                detail["start_offset_s"] = round(offset, 3)
            st.set(**detail)
        if audio_s > c.max_duration_s:
            raise YoutubeVideoError(REASON_TOO_LONG)
        # the ASR cache is keyed by the separation mode too: the answer depends on the audio that
        # went in, and a hit must skip the separation (demucs can take tens of minutes on CPU). The
        # strongest cached answer (with words) answers a segments-only ask too, so a transcript and
        # the HQ captions it feeds share one speech-recognition run.
        cached = self._cached_asr(video_id, audio_sha, c.separation, want_words, requested)
        if cached is not None:
            result = drop_cached_credits(asr_from_cache(cached), self.cfg.captions)
            saved_s = self._asr_saved_s(audio_s, requested, priority)
            with events.stage(events.ASR, requested_language=requested) as st:
                _set_asr(st, result, cached=True)
                st.set(
                    reused_from_job=cached.get("job"),
                    saved_s=round(saved_s, 1) if saved_s else None,
                )
            self._require_speech(result, want_words, optional_asr)
            progress(0.85)
            return result, wav
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
        result = await self._asr_stage(
            video_id,
            wav,
            requested,
            progress,
            priority=priority,
            want_words=want_words,
            optional_asr=optional_asr,
            audio_sha=audio_sha,
            separation=c.separation,
            klass=klass,
            yield_check=yield_check,
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
        optional_asr: bool,
        audio_sha: str,
        separation: str,
        klass: str = NORMAL,
        yield_check: Callable[[], Awaitable[None]] | None = None,
    ) -> ASRResult:
        """One ASR step of `_recognise`, with its per-video cache. See `_recognise`."""
        cached = self._cached_asr(video_id, audio_sha, separation, want_words, requested)
        if cached is not None:
            result = drop_cached_credits(asr_from_cache(cached), self.cfg.captions)
            saved_s = self._asr_saved_s(
                wav_duration(wav, self.cfg.captions.sample_rate), requested, priority
            )
            with events.stage(events.ASR, requested_language=requested) as st:
                _set_asr(st, result, cached=True)
                st.set(
                    reused_from_job=cached.get("job"),
                    saved_s=round(saved_s, 1) if saved_s else None,
                )
            self._require_speech(result, want_words, optional_asr)
            return result
        try:
            with events.stage(events.ASR, requested_language=requested) as st:
                result = await self.asr.transcribe(
                    wav,
                    requested,
                    lambda f: progress(0.25 + 0.6 * f),
                    priority=priority,
                    want_words=want_words,
                    expected_language=self._expected_language(video_id, requested),
                    klass=klass,
                    yield_check=yield_check,
                )
                if want_words and result.word_timing is None:
                    result.word_timing = classify(
                        result.words, self.cfg.captions.words_real_min_share
                    )
                _set_asr(st, result)
                if result.stats.get("unresolved_chunks"):
                    st.set(cache="not_stored_unresolved")
                elif not self._asr_empty(result, want_words):
                    self._store_asr(video_id, audio_sha, separation, result, requested)
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
        self._require_speech(result, want_words, optional_asr)
        return result

    def _expected_language(self, video_id: str, requested: str | None) -> str | None:
        """The language the audio should be in: the requested one, else the video metadata's."""
        if requested:
            return requested
        meta = self.db.get_json("video_meta", "video_id=?", [video_id]) or {}
        return normalize_language(str(meta.get("language") or "")) or None

    def _cached_asr(
        self,
        video_id: str,
        audio_sha: str,
        separation: str,
        want_words: bool,
        requested: str | None,
    ) -> dict[str, Any] | None:
        """The strongest cached ASR answer for this audio, or None.

        The answer is stored once per (audio, audio variant, language); the strongest one (with
        words) answers a segments-only ask too. The exact-language key is tried first, then any other
        cached answer for the same audio and variant is scanned for: a language-detected run answers
        a later ask with that language, and an auto ask (no language) takes any cached result."""
        base = asr_cache_key(audio_sha, requested, separation)
        cached = self.cache.get(video_id, ASR_CACHE_STAGE, base)
        if cached is not None and asr_answer_usable(cached, self.asr, want_words, requested):
            return cached
        prefix = f"v{ASR_CACHE_VERSION}:{audio_sha}:{separation}:"
        best: dict[str, Any] | None = None
        best_score = (-1, -1)
        for row in self.db.all(
            "SELECT json FROM stage_cache WHERE video_id=? AND stage=? AND cache_key LIKE ?",
            [video_id, ASR_CACHE_STAGE, prefix + "%"],
        ):
            try:
                payload = json.loads(row["json"])
            except (ValueError, TypeError):
                continue
            if not asr_answer_usable(payload, self.asr, want_words, requested):
                continue
            score = (
                bool(payload.get("words")),
                1
                if payload.get("word_timing")
                in (
                    "real",
                    "mixed",
                )
                else 0,
            )
            if score > best_score:
                best_score, best = score, payload
        return best

    def _store_asr(
        self,
        video_id: str,
        audio_sha: str,
        separation: str,
        result: ASRResult,
        requested: str | None,
    ) -> str:
        """Store one ASR answer, once, under the language it was made for (its detected language, so
        a later ask with that language finds it; `auto` when none was detected). Returns the key."""
        langclass = normalize_language(result.language) or requested
        key = asr_cache_key(audio_sha, langclass, separation)
        store = asr_to_cache(result)
        store["job"] = events.job_id()  # provenance: the job this answer was made for
        self.cache.put(video_id, ASR_CACHE_STAGE, key, store)
        return key

    def _asr_saved_s(self, audio_s: float, requested: str | None, priority: int) -> float | None:
        """How long the ASR step this job skipped would have taken: the engine chain's estimate for
        the audio, so the job report can say how much a cache hit saved."""
        estimate = getattr(self.asr, "estimate_s", None)
        if not estimate:
            return None
        return estimate(audio_s, requested, priority)

    def _require_speech(self, result: ASRResult, want_words: bool, optional_asr: bool) -> None:
        """The audio path needs recognised speech; the captions-improvement path does not.

        A video whose audio carries no recognisable speech (music) still has usable captions to
        improve, so with `optional_asr` the empty answer only warns.
        """
        if not self._asr_empty(result, want_words):
            return
        if not optional_asr:
            raise PipelineError("ASR returned no words")
        events.emit(
            events.ASR,
            events.WARN,
            reason="no_speech",
            message="No speech was recognised in the audio; the caption text is kept as it is.",
        )

    @staticmethod
    def _asr_empty(result: ASRResult, want_words: bool) -> bool:
        return not (result.words if want_words else result.segments)

    async def _verify_words(
        self, result: ASRResult, wav: Path | None
    ) -> tuple[list[Word], list[tuple[float, float]], WordStats]:
        """Silences of the audio (once), the engine's words repaired against them, and a log event.

        The silences are `[]` when there is no audio or `align_silence` is off; callers that need to
        tell "unknown" from "none" use `self._silences_known`.
        """
        c = self.cfg.captions
        silences: list[tuple[float, float]] = []
        if self._silences_known(wav):
            silences = await asyncio.to_thread(detect_silences, wav, c.silence_min_s)
        words, stats = repair_words(result.words, silences, c)
        if result.word_timing is None:
            result.word_timing = classify(result.words, c.words_real_min_share)
        if not words:
            events.emit(events.WORD_TIMING, events.SKIPPED, reason="no_words")
        elif result.word_timing == "real":
            events.emit(
                events.WORD_TIMING,
                events.OK,
                word_timing=result.word_timing,
                **stats.as_detail(),
                silences=len(silences),
            )
        else:
            events.emit(
                events.WORD_TIMING,
                events.WARN,
                word_timing=result.word_timing,
                **stats.as_detail(),
                silences=len(silences),
                message="This engine returned no word times; cue times are estimates."
                if result.word_timing == "interpolated"
                else "Some words have no engine times; their cue times are estimates.",
            )
        return words, silences, stats

    def _silences_known(self, wav: Path | None) -> bool:
        return wav is not None and self.cfg.captions.align_silence

    def _emit_sync_score(
        self,
        cues: list[Cue],
        silences: list[tuple[float, float]],
        wav: Path | None,
    ) -> dict[str, Any]:
        """The audio's verdict on the finished cues, logged as `sync_score` and returned."""
        c = self.cfg.captions
        if not cues or not self._silences_known(wav) or not silences:
            reason = (
                "no_cues"
                if not cues
                else "no_audio_check"
                if not self._silences_known(wav)
                else "no_silences"
            )
            events.emit(events.SYNC_SCORE, events.SKIPPED, reason=reason)
            return {}
        check = self_check(cues, silences, wav_duration(wav, c.sample_rate), c)
        events.emit(events.SYNC_SCORE, events.OK, **check)
        return check

    async def _polish(
        self, video_id: str, cues: list[Cue], lang: str, *, skip_reason: str | None = None
    ) -> list[Cue]:
        """The proofreading pass, with the video's title and description as context."""
        meta = self.db.get_json("video_meta", "video_id=?", [video_id]) or {}
        context = {
            "title": str(meta.get("title") or "")[: self.cfg.captions.proofread_context_chars],
            "description": str(meta.get("description") or "")[
                : self.cfg.captions.proofread_context_chars
            ],
        }
        return await self.proofreader.polish(video_id, cues, lang, context, skip_reason=skip_reason)

    async def transcribe(
        self,
        video_id: str,
        progress: Progress,
        *,
        priority: int = BACKGROUND,
        language: str | None = None,
        klass: str = NORMAL,
        yield_check: Callable[[], Awaitable[None]] | None = None,
    ) -> AsrTranscript:
        """Plain-text transcript from the audio. `language` is a hint; unset, the engine detects it.

        Words are requested too: the transcript is a weaker ask than the HQ captions that reuse it,
        so computing the strongest answer once (with word times) lets captions reuse the same
        speech-recognition run instead of running speech recognition a second time."""
        work = self.cfg.media_dir / video_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            result, _wav = await self._recognise(
                video_id,
                language,
                work,
                progress,
                priority=priority,
                want_words=True,
                klass=klass,
                yield_check=yield_check,
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
        klass: str = NORMAL,
        yield_check: Callable[[], Awaitable[None]] | None = None,
    ) -> str:
        """HQ captions from the audio (no usable captions on YouTube, or fetching is limited)."""
        c = self.cfg.captions
        legacy = c.timing_mode == "legacy"
        work = self.cfg.media_dir / video_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            requested = None if lang == "auto" else lang
            result, wav = await self._recognise(
                video_id,
                requested,
                work,
                progress,
                priority=priority,
                klass=klass,
                yield_check=yield_check,
            )
            silences: list[tuple[float, float]] | None = None
            words, stats = result.words, WordStats()
            if not legacy:
                words, silences, stats = await self._verify_words(result, wav)
            if c.diarization != "none":
                with events.stage(events.DIARIZATION) as st:
                    turns = await self.diarizer.diarize(wav)
                    notes = events.take_notes()
                    if notes.get("skip"):
                        st.skip(reason=notes["skip"], message=notes.get("message"))
                    else:
                        st.set(turns=len(turns), speakers=len({turn[2] for turn in turns}))
                assign_speakers(words, turns)
            progress(0.9)
            with events.stage(events.CUES, announce=False) as st:
                cues = build_cues(words, c)
                st.set(
                    cues=len(cues),
                    words=len(words),
                    max_line_chars=max((len(ln) for cue in cues for ln in cue.lines), default=0),
                    max_lines=max((len(cue.lines) for cue in cues), default=0),
                    limit_line_chars=c.max_chars_per_line,
                )
            with events.stage(events.ALIGN, mode="silence") as st:
                if not c.align_silence:
                    st.skip(reason="off")
                else:
                    before = [(cue.start, cue.end) for cue in cues]
                    if silences is None:
                        silences = await asyncio.to_thread(detect_silences, wav, c.silence_min_s)
                    cues = snap_cues(cues, silences, c)
                    st.set(
                        silences=len(silences),
                        moved=sum(
                            1
                            for a, cue in zip(before, cues, strict=True)
                            if a != (cue.start, cue.end)
                        ),
                    )
            timing = {}
            if not legacy:
                align_stats = AlignStats()
                cues, align_stats.merged_short = merge_short(cues, c)
                cues = pad_cues(cues, c)
                timing = self._timing_summary(
                    result,
                    stats,
                    "words",
                    self._emit_sync_score(cues, silences or [], wav),
                    fill_stats=align_stats,
                )
            track_lang = result.language or normalize_language(requested) or "und"
            track_lang = await self._finish(
                video_id, cues, track_lang, translate_to, progress, timing
            )
            return track_lang
        finally:
            if not c.keep_media and not _keep_for_archive(work):
                shutil.rmtree(work, ignore_errors=True)

    @staticmethod
    def _timing_summary(
        result: ASRResult,
        stats: WordStats,
        mode: str,
        check: dict[str, Any],
        fill_cues: int = 0,
        ref_check: Check | None = None,
        fill_stats: AlignStats | None = None,
    ) -> dict[str, Any]:
        """What a stored track's `timing` column says about how its times were made."""
        detail = stats.as_detail()
        summary = {
            "word_timing": result.word_timing,
            "real_share": detail["real_share"],
            "repaired": stats.stretched + stats.zero_length + stats.squeezed,
            "fill_cues": fill_cues,
            "mode": mode,
            "self_check": check,
        }
        if fill_stats is not None:
            # YouTube's words that fill what the engine did not hear: never counted as engine words
            summary["reference"] = fill_stats.words
            summary["fill_from_words"] = fill_stats.cues
            summary["merged_short"] = fill_stats.merged_short
        if ref_check is not None:
            summary["ref_check"] = ref_check_summary(ref_check)
        return summary

    async def _ref_check(
        self,
        ref_words: list[tuple[float, str]] | None,
        rows: list[tuple[float, float, str]],
        words: list[Word],
    ) -> Check:
        """Compare the engine's word starts with YouTube's: log `ref_check`, change no times."""
        c = self.cfg.captions
        verdict = await asyncio.to_thread(check_reference, ref_words, rows, words, c)
        detail: dict[str, Any] = {"reference_words": verdict.reference_words}
        if verdict.agreement is not None:
            detail.update(verdict.agreement.as_detail())
        if verdict.status == reference.STATUS_SKIPPED:
            events.emit(events.REF_CHECK, events.SKIPPED, reason=verdict.reason, **detail)
        elif verdict.status == reference.STATUS_WARN:
            events.emit(
                events.REF_CHECK,
                events.WARN,
                message="The engine's word times differ from YouTube's in some stretches.",
                **detail,
            )
        else:
            events.emit(events.REF_CHECK, events.OK, **detail)
        return verdict

    async def improve(
        self,
        video_id: str,
        segments: list[tuple[float, float, str]],
        lang_hint: str | None,
        translate_to: str | None,
        progress: Progress,
        priority: int = BACKGROUND,
        ref_words: list[tuple[float, str]] | None = None,
        caption_kind: str | None = None,
        klass: str = NORMAL,
        yield_check: Callable[[], Awaitable[None]] | None = None,
    ) -> str:
        """HQ captions built on the video's own captions: better text, times from the audio.

        With real word times from the engine the cues are built from the words themselves
        (`word_cues`; caption cues no word touches fill the wordless gaps) and snapped to the
        audio's silences. When the engine only estimated its word times, the caption cues are kept as
        they are, text and timing (no ASR text is merged in). Without words the
        captions are proofread and stored as they are. `captions.timing_mode = "legacy"` restores
        the older caption-window merge. The proofreading pass fixes punctuation, names and terms.
        """
        c = self.cfg.captions
        legacy = c.timing_mode == "legacy"
        work = self.cfg.media_dir / video_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            base_hint = (lang_hint or "").split("-")[0] or None
            requested = normalize_language(base_hint)
            wav: Path | None = None
            try:
                result, wav = await self._recognise(
                    video_id,
                    requested,
                    work,
                    progress,
                    priority=priority,
                    want_words=True,
                    optional_asr=True,
                    klass=klass,
                    yield_check=yield_check,
                )
            except (YoutubeVideoError, MediaArchiveFull) as exc:
                # the captions are already in hand: audio trouble (unavailable video, a limited
                # media class, a full archive) only means no better words - proofread them as they are
                events.emit(
                    events.ASR,
                    events.WARN,
                    reason="audio_unavailable",
                    error_class=events.error_class(exc),
                    technical=events.technical(exc),
                    message="The audio could not be fetched; the caption text is kept as it is.",
                )
                result = ASRResult(words=[], language=None, segments=[], engine=None, model=None)
            silences: list[tuple[float, float]] = []
            words, stats = result.words, WordStats()
            if not legacy:
                words, silences, stats = await self._verify_words(result, wav)
            with events.stage(events.CUES, announce=False, source="captions") as st:
                cues = caption_cues(segments, c)
                if not cues:
                    raise PipelineError("the caption track had no usable cues")
                st.set(cues=len(cues))
            progress(0.9)
            mode, fill_cues = "legacy", 0
            ref_check: Check | None = None
            fill_stats = AlignStats()
            if legacy:
                with events.stage(events.ALIGN, mode="merge", margin_s=c.align_window_s) as st:
                    # linear in cues and words, but hours of captions still take a moment: keep the
                    # API responsive the way `detect_silences` already does
                    cues, from_asr = await asyncio.to_thread(merge_words_into_cues, cues, words, c)
                    st.set(cues=len(cues), from_asr=from_asr)
            elif not words:
                mode = "captions_only"
                with events.stage(events.ALIGN, mode="captions_timing") as st:
                    st.skip(reason="no_words", cues=len(cues))
            elif result.word_timing == "interpolated":
                # estimated word times cannot place ASR text: the captions stay as they are
                mode = "captions_timing"
                with events.stage(events.ALIGN, mode="captions_timing") as st:
                    st.skip(reason="word_times_estimated", cues=len(cues))
            else:
                mode = "words"
                ref_check = await self._ref_check(ref_words, segments, words)
                with events.stage(events.ALIGN, mode="words", words=len(words)) as st:
                    before = len(cues)
                    fill_stats = AlignStats()
                    cues, speech, fill_cues = await asyncio.to_thread(
                        word_cues,
                        words,
                        cues,
                        c,
                        ref_words,
                        ref_check.lead_s if ref_check else 0.0,
                        caption_kind == CAPTION_MANUAL,
                        fill_stats,
                    )
                    moved = 0
                    if c.align_silence and silences:
                        edges = [(cue.start, cue.end) for cue in cues]
                        cues = snap_cues(cues, silences, c)
                        moved = sum(
                            1
                            for a, cue in zip(edges, cues, strict=True)
                            if a != (cue.start, cue.end)
                        )
                    cues = finish_cues(cues, c, fill_stats)
                    st.set(
                        cues=len(cues),
                        speech_cues=speech,
                        fill_cues=fill_cues,
                        fill_from_words=fill_stats.cues,
                        merged_short=fill_stats.merged_short,
                        caption_cues=before,
                        moved=moved,
                    )
            timing = {}
            if not legacy:
                timing = self._timing_summary(
                    result,
                    stats,
                    mode,
                    self._emit_sync_score(cues, silences, wav),
                    fill_cues,
                    ref_check,
                    fill_stats,
                )
            track_lang = result.language or requested or base_hint or "und"
            track_lang = await self._finish(
                video_id, cues, track_lang, translate_to, progress, timing
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
        timing: dict[str, Any] | None = None,
    ) -> str:
        """Proofread, optionally translate, then store the track.

        `timing` says how the cue times were made (stored in the `timing` column with
        `TIMING_VERSION`); a track made in legacy mode passes none and stays `timing_version` NULL.
        """
        if self.cfg.captions.gate_required:
            reason = gate.check_attestation(self.cfg.captions.gate_attestation)
            if reason:
                raise PipelineError(f"the caption release gate has not passed: {reason}")
        translating = bool(translate_to and translate_to != track_lang)
        cues = await self._polish(
            video_id,
            cues,
            track_lang,
            skip_reason="translated" if translating and self.proofreader.enabled else None,
        )
        if translating:
            with events.stage(events.TRANSLATE, source=track_lang, to=translate_to) as st:
                split, tstats = SplitStats(), TranslateStats()
                try:
                    cues = await self.translate(cues, translate_to, split, tstats)
                finally:
                    st.set(**tstats.as_detail())
                if tstats.untranslated:
                    st.status = events.WARN
                st.set(cues=len(cues), **split.as_detail())
            track_lang = translate_to
            # the English output carries the quality bar: translated text is proofread too,
            # so names and punctuation are fixed against the title and description as well
            if self.proofreader.enabled:
                cues = await self._polish(video_id, cues, track_lang)
        if timing:
            timing["char_timed_cues"] = sum(1 for cue in cues if cue.char_timed)
        vtt = to_vtt(cues)
        speakers = count_speakers(cues)
        label = track_label(track_lang, speakers)
        self.db.execute(
            "INSERT OR REPLACE INTO captions"
            "(video_id,lang,label,speakers,vtt,created_at,job_id,timing_version,timing)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            [
                video_id,
                track_lang,
                label,
                speakers,
                vtt,
                time.time(),
                events.job_id(),
                TIMING_VERSION if timing else None,
                json.dumps(timing) if timing else None,
            ],
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

    async def _ask_translation(
        self, texts: list[str], target: str, strict: bool
    ) -> list[str] | None:
        """One LLM call; None when the answer is not a list of `len(texts)` strings."""
        assert self.llm is not None
        system = TRANSLATE_SYSTEM.format(lang=target)
        if strict:
            system += " " + TRANSLATE_STRICT.format(n=len(texts))
        user = json.dumps(texts, ensure_ascii=False)
        if strict:
            user = TRANSLATE_STRICT.format(n=len(texts)) + "\n" + user
        try:
            data = await self.llm.chat_json(
                self.cfg.llm.captions,
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                feature=self.cfg.llm.captions.feature,
            )
        except LLMBadJSONError:
            return None
        if not isinstance(data, list) or len(data) != len(texts):
            return None
        if not all(
            isinstance(item, str) and (item.strip() or not src.strip())
            for item, src in zip(data, texts, strict=True)
        ):
            return None
        return data

    async def _translate_texts(
        self, texts: list[str], target: str, stats: TranslateStats, limit: float
    ) -> list[str | None]:
        """Translate a batch; a bad answer is retried once, then the batch is split in halves.

        A single cue that still fails comes back as None (the caller keeps its source text).
        """
        for attempt in range(2):
            got = await self._ask_translation(texts, target, strict=attempt > 0)
            if got is not None:
                return list(got)
            if attempt == 0:
                stats.retried += 1
        if len(texts) == 1:
            stats.untranslated += 1
            if stats.untranslated > limit:
                raise PipelineError("translation length mismatch")
            return [None]
        stats.split += 1
        mid = len(texts) // 2
        left = await self._translate_texts(texts[:mid], target, stats, limit)
        right = await self._translate_texts(texts[mid:], target, stats, limit)
        return left + right

    async def translate(
        self,
        cues: list[Cue],
        target: str,
        stats: SplitStats | None = None,
        tstats: TranslateStats | None = None,
    ) -> list[Cue]:
        if self.llm is None:
            raise PipelineError("translation needs an LLM client")
        batch = self.cfg.captions.translate_batch
        c = self.cfg.captions
        stats = stats if stats is not None else SplitStats()
        tstats = tstats if tstats is not None else TranslateStats()
        limit = c.translate_max_untranslated_share * len(cues)
        out: list[Cue] = []
        for i in range(0, len(cues), batch):
            part = cues[i : i + batch]
            prefixes, texts = [], []
            for cue in part:
                joined = " ".join(cue.lines)
                has = joined.startswith("[S")
                prefixes.append(joined[:SPEAKER_PREFIX_LEN] if has else "")
                texts.append(joined[SPEAKER_PREFIX_LEN:] if has else joined)
            tstats.batches += 1
            data = await self._translate_texts(texts, target, tstats, limit)
            for offset, (cue, prefix, text) in enumerate(zip(part, prefixes, data, strict=True)):
                if text is None:
                    out.append(cue)
                    continue
                full = f"{prefix}{text}".strip()
                # the translation no longer maps onto the source words one to one, but its cue keeps
                # the source cue's times and words so an overflow splits on a real pause
                lines = wrap_lines(full, c.max_chars_per_line, c.max_lines)
                if c.timing_mode == "legacy":
                    # rollback switch: the old output, one cue per source cue, words dropped
                    out.append(Cue(cue.start, cue.end, lines or [full], cue.speaker))
                    continue
                source = replace(cue, words_match_text=False)
                if lines is not None:
                    out.append(replace(source, lines=lines))
                else:
                    at = i + offset + 1
                    room = cues[at].start if at < len(cues) else None
                    out.extend(split_cue(source, full, c, stats, room))
        return out


__all__ = ["CaptionPipeline", "PipelineError", "ASRError"]
