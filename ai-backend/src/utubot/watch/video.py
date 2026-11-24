"""The small video copy Watched keeps: archive lookup, one gated download, no audio.

The download goes through the same YouTube gate class as audio (`media`) and is stored in the
media archive under `kind = "video"`. Its selector prefers a 360-line video-only stream; the
length limit is checked before any download. Offline mode only uses the archive.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

import yt_dlp

from ..captions import events
from ..config import Config
from ..db import Database
from ..media_archive import MediaArchive, KIND_VIDEO
from ..transcripts import TranscriptService, VIDEO_URL
from ..youtube import (
    CLASS_MEDIA,
    MEDIA_CLASSES,
    REASON_LIVE,
    REASON_TOO_LONG,
    YoutubeGate,
    YoutubeOffline,
    YoutubeVideoError,
    classify_failure,
)
from ..llm import BACKGROUND

log = logging.getLogger("utubot.watch")

MAX_SELECTOR_MINUTES_CHECK = "video is longer than the watched limit"
STORE_HOOK_EXT = ".mp4"


def _filter(max_minutes: int, verdict: dict[str, str]) -> Callable[..., str | None]:
    """yt-dlp `match_filter`: refuse a live stream or a video over the watched limit."""

    def check(info: dict[str, Any], *, incomplete: bool = False) -> str | None:
        if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
            verdict["reason"] = REASON_LIVE
            return "live streams cannot be watched"
        duration = info.get("duration")
        if duration and duration > max_minutes * 60:
            verdict["reason"] = REASON_TOO_LONG
            return MAX_SELECTOR_MINUTES_CHECK
        return None

    return check


async def download_video(
    video_id: str,
    out_dir: Path,
    started: Callable[[], None],
    *,
    cfg: Config,
    network_retry_s: float,
) -> Path:
    """One video-only download through yt-dlp, with the watched length cap."""
    watched = cfg.cuts.watched

    def hook(_status: dict[str, Any]) -> None:
        started()

    def _run() -> Path:
        verdict: dict[str, str] = {}
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "format": watched.video_format,
            "outtmpl": str(out_dir / "video.%(ext)s"),
            "match_filter": _filter(watched.max_video_minutes, verdict),
            "max_filesize": watched.video_max_bytes,
            "progress_hooks": [hook],
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ythelper:
                info = ythelper.extract_info(VIDEO_URL.format(video_id), download=True)
                path = Path(ythelper.prepare_filename(info))
                if not path.is_file():
                    raise YoutubeVideoError(verdict.get("reason", REASON_TOO_LONG))
                chosen = (info.get("requested_formats") or [info])[0]
                events.note(
                    format_id=chosen.get("format_id"),
                    codec=chosen.get("vcodec"),
                    ext=chosen.get("ext"),
                    bytes=path.stat().st_size,
                    duration_s=info.get("duration"),
                )
                return path
        except yt_dlp.utils.YoutubeDLError as exc:
            raise classify_failure(exc, network_retry_s, media=True, klass=CLASS_MEDIA) from None

    return await asyncio.to_thread(_run)


async def ensure_video(
    cfg: Config,
    db: Database,
    archive: MediaArchive,
    gate: YoutubeGate,
    transcripts: TranscriptService,
    video_id: str,
    work: Path,
    *,
    priority: int = BACKGROUND,
) -> dict[str, Any]:
    """The archive entry of this video's small copy, downloading it once when missing."""
    entry = archive.lookup(video_id, KIND_VIDEO)
    if entry is not None:
        return entry
    if cfg.youtube.offline:
        raise YoutubeOffline(CLASS_MEDIA)
    meta = transcripts.cached_meta(video_id) or {}
    duration = meta.get("duration_s")
    if duration and float(duration) > cfg.cuts.watched.max_video_minutes * 60:
        raise YoutubeVideoError(REASON_TOO_LONG, CLASS_MEDIA)
    archive.require_room()
    work.mkdir(parents=True, exist_ok=True)

    async def fetch(started: Callable[[], None]) -> tuple[Path, dict[str, Any]]:
        events.emit(
            events.GATE_WAIT,
            events.OK,
            klass=CLASS_MEDIA,
            priority=events.priority_name(priority),
        )
        with events.stage(events.AUDIO) as stage_holder:
            path = await download_video(
                video_id,
                work,
                started,
                cfg=cfg,
                network_retry_s=cfg.youtube.network_retry_s,
            )
            notes = events.take_notes()
            stage_holder.set(source=events.AUDIO_DOWNLOADED, **notes)
        return path, notes

    src, notes = await gate.run_started(
        fetch, priority, key=f"video:{video_id}", classes=MEDIA_CLASSES
    )
    with events.stage(events.ARCHIVE) as stage_holder:
        stored = await asyncio.to_thread(
            archive.store,
            video_id,
            src,
            kind=KIND_VIDEO,
            format_id=notes.get("format_id"),
            codec=notes.get("codec"),
            original=1,
            job_id=events.job_id(),
            work=work,
        )
        stage_holder.set(bytes=stored["size"], sha256=stored["sha256"][:12])
    return stored


async def video_file(archive: MediaArchive, entry: dict[str, Any], work: Path) -> Path:
    """The stored file, or a fresh `.mp4` copy the grid tools can read."""
    path = archive.path_of(entry)
    return path


async def make_readable(path: Path, work: Path) -> Path:
    """Copy the archived bytes into the scratch directory as a readable video file."""
    target = work / f"video{path.suffix or STORE_HOOK_EXT}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(path.read_bytes())
    return target
