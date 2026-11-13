from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import yt_dlp

from .config import Config
from .db import METADATA_ONLY, Database
from .llm import BACKGROUND, INTERACTIVE, parse_retry_after
from .youtube import (
    CLASS_CAPTIONS,
    CLASS_METADATA,
    FETCH_CLASSES,
    REASON_EMPTY,
    REASON_EMPTY_TRACK,
    REASON_INCOMPLETE,
    REASON_NETWORK,
    REASON_OFFLINE,
    YoutubeCooldown,
    YoutubeDelayed,
    YoutubeError,
    YoutubeGate,
    YoutubeOffline,
    YoutubeVideoError,
    classify_failure,
    classify_status,
    ytdlp_runtime_options,
)

log = logging.getLogger("utubot.transcripts")

TIMESTAMP_BLOCK_S = 20
SOURCE_CAPTIONS = "youtube_captions"
SOURCE_ASR = "asr"
VIDEO_URL = "https://www.youtube.com/watch?v={}"
HTTP_ERROR_FLOOR = 400
HOLD_FAILED = "failed"
HOLD_DELAYED = "delayed"
TAG_RE = re.compile(r"<[^>]+>")
VTT_TIME_RE = re.compile(
    r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})\s+-->\s+(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})"
)


@dataclass
class Transcript:
    video_id: str
    text: str
    lang: str | None
    source: str
    meta: dict[str, Any] = field(default_factory=dict)
    engine: str | None = None
    model: str | None = None


@dataclass
class FetchResult:
    meta: dict[str, Any]
    text: str | None
    lang: str | None
    answered: tuple[str, ...] | None = None


# A complete yt-dlp answer that lists no caption track says the video has none: the caption class
# has nothing left to refuse, so it counts as answered too (else a probe on such a video would leave
# the class half-open and the next probe would follow at once).
ANSWERED_NO_CAPTIONS = (CLASS_METADATA, CLASS_CAPTIONS)

Fetcher = Callable[[str], Awaitable[FetchResult]]
Extractor = Callable[[str], dict[str, Any]]


class NoCaptions(RuntimeError):
    """YouTube lists no usable captions for this video. An expected outcome, not a failure."""

    expected = True

    def __init__(self, video_id: str):
        super().__init__("no captions")
        self.video_id = video_id


def fmt_ts(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def segments_to_text(segments: list[tuple[float, str]]) -> str:
    lines: list[str] = []
    block_start = -TIMESTAMP_BLOCK_S
    current: list[str] = []
    for start, text in segments:
        text = " ".join(text.split())
        if not text:
            continue
        if start - block_start >= TIMESTAMP_BLOCK_S:
            if current:
                lines.append(" ".join(current))
            block_start = start
            current = [f"[{fmt_ts(start)}]"]
        current.append(text)
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def parse_json3(raw: str) -> list[tuple[float, str]]:
    data = json.loads(raw)
    out: list[tuple[float, str]] = []
    for event in data.get("events", []):
        segs = event.get("segs")
        if not segs:
            continue
        text = "".join(seg.get("utf8", "") for seg in segs).replace("\n", " ").strip()
        if text:
            out.append((event.get("tStartMs", 0) / 1000.0, text))
    return out


def parse_vtt(raw: str) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    last = ""
    for block in re.split(r"\n\s*\n", raw.replace("\r", "")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = VTT_TIME_RE.search(line)
            if not m:
                continue
            h, mi, s, ms = (int(m.group(1) or 0), int(m.group(2)), int(m.group(3)), int(m.group(4)))
            start = h * 3600 + mi * 60 + s + ms / 1000
            text = " ".join(TAG_RE.sub("", ln).strip() for ln in lines[i + 1 :]).strip()
            if text and text != last:
                out.append((start, text))
                last = text
            break
    return out


def pick_track(info: dict[str, Any], prefer: str) -> tuple[list[dict], str] | None:
    manual = info.get("subtitles") or {}
    auto = info.get("automatic_captions") or {}
    lang = (info.get("language") or prefer or "en").lower()
    base = lang.split("-")[0]

    def lookup(table: dict, keys: list[str]) -> tuple[list[dict], str] | None:
        for key in keys:
            for name, formats in table.items():
                if name.lower() == key and formats:
                    return formats, name
        return None

    hit = lookup(manual, [lang, base])
    if hit:
        return hit
    hit = lookup(auto, [f"{lang}-orig", f"{base}-orig", lang, base])
    if hit:
        return hit
    for name, formats in manual.items():
        if formats and name != "live_chat":
            return formats, name
    for name, formats in auto.items():
        if formats and name.endswith("-orig"):
            return formats, name
    return None


def pick_format(formats: list[dict]) -> dict | None:
    for ext in ("json3", "vtt", "srv3"):
        for fmt in formats:
            if fmt.get("ext") == ext and fmt.get("url"):
                return fmt
    return None


def info_complete(info: dict[str, Any]) -> bool:
    """A full yt-dlp answer: a throttled or partial one lacks the formats list."""
    return bool(info.get("id")) and bool(info.get("title")) and bool(info.get("formats"))


def degraded_tracks(info: dict[str, Any]) -> bool:
    """Caption languages listed without any format: YouTube answered, but only in part."""
    for table in (info.get("subtitles") or {}, info.get("automatic_captions") or {}):
        for name, formats in table.items():
            if name != "live_chat" and not formats:
                return True
    return False


def extract_meta(info: dict[str, Any]) -> dict[str, Any]:
    return {
        "video_id": info.get("id"),
        "title": info.get("title"),
        "channel": info.get("channel") or info.get("uploader"),
        "channel_id": info.get("channel_id"),
        "duration_s": info.get("duration"),
        "description": (info.get("description") or "")[:2000],
        "language": info.get("language"),
        "is_live": bool(info.get("is_live")),
    }


class YoutubeFetcher:
    """Metadata and caption text through yt-dlp and httpx. Failures are classified, never raw.

    Pacing and the circuit breaker live in `YoutubeGate`, which `TranscriptService` wraps around
    every call.
    """

    def __init__(
        self,
        cfg: Config,
        extract: Extractor | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.cfg = cfg
        self._extract_fn: Extractor = extract or self._extract
        self._transport = transport

    def _extract(self, video_id: str) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "socket_timeout": self.cfg.transcripts.fetch_timeout_s,
            **ytdlp_runtime_options(self.cfg.youtube),
        }
        if self.cfg.transcripts.cookies_file:
            opts["cookiefile"] = self.cfg.transcripts.cookies_file
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(VIDEO_URL.format(video_id), download=False)

    def _extract_classified(self, video_id: str) -> dict[str, Any]:
        try:
            return self._extract_fn(video_id)
        except yt_dlp.utils.YoutubeDLError as exc:
            raise classify_failure(
                exc, self.cfg.youtube.network_retry_s, klass=CLASS_METADATA
            ) from None

    async def _download_track(self, url: str) -> str:
        retry_s = self.cfg.youtube.network_retry_s
        try:
            async with httpx.AsyncClient(
                timeout=self.cfg.transcripts.fetch_timeout_s, transport=self._transport
            ) as http:
                resp = await http.get(url, follow_redirects=True)
        except httpx.HTTPError:
            raise YoutubeDelayed(REASON_NETWORK, retry_s) from None
        problem = classify_status(
            resp.status_code,
            retry_s,
            parse_retry_after(resp.headers.get("retry-after")),
            media=True,
            klass=CLASS_CAPTIONS,
        )
        if problem is not None:
            raise problem
        if resp.status_code >= HTTP_ERROR_FLOOR:
            raise YoutubeError(f"caption download http {resp.status_code}")
        if not resp.text.strip():
            raise YoutubeDelayed(REASON_EMPTY, retry_s)
        return resp.text

    async def __call__(self, video_id: str) -> FetchResult:
        retry_s = self.cfg.youtube.network_retry_s
        if self.cfg.youtube.offline:
            # The offline dev-proxy mode: never reach YouTube; the fixture fetcher answers instead.
            raise YoutubeOffline(CLASS_METADATA)
        info = await asyncio.to_thread(self._extract_classified, video_id)
        if not info_complete(info):
            raise YoutubeDelayed(REASON_INCOMPLETE, retry_s)
        meta = extract_meta(info)
        track = pick_track(info, self.cfg.transcripts.default_language)
        if not track:
            if degraded_tracks(info):
                raise YoutubeDelayed(REASON_INCOMPLETE, retry_s)
            return FetchResult(meta, None, None, answered=ANSWERED_NO_CAPTIONS)
        formats, lang = track
        fmt = pick_format(formats)
        if not fmt:
            return FetchResult(meta, None, lang, answered=ANSWERED_NO_CAPTIONS)
        raw = await self._download_track(fmt["url"])
        segments = parse_json3(raw) if fmt["ext"] == "json3" else parse_vtt(raw)
        text = segments_to_text(segments)
        if not text:
            raise YoutubeDelayed(REASON_EMPTY_TRACK, self.cfg.transcripts.empty_track_retry_s)
        return FetchResult(meta, text, lang)


class TranscriptService:
    """Transcript cache in front of YouTube: one fetch per video per TTL, always through the gate."""

    def __init__(
        self,
        cfg: Config,
        db: Database,
        fetcher: Fetcher | None = None,
        gate: YoutubeGate | None = None,
    ):
        self.cfg = cfg
        self.db = db
        self.gate = gate or YoutubeGate(cfg.youtube, db)
        self.fetcher: Fetcher = fetcher or YoutubeFetcher(cfg)
        self._inflight: dict[str, asyncio.Task[Transcript]] = {}
        self._probe: asyncio.Task[None] | None = None

    def cached_meta(self, video_id: str) -> dict[str, Any] | None:
        return self.db.get_json("video_meta", "video_id=?", [video_id])

    def store_meta(self, video_id: str, meta: dict[str, Any]) -> None:
        clean = {k: v for k, v in meta.items() if v is not None}
        existing = self.cached_meta(video_id) or {}
        self.db.execute(
            "INSERT OR REPLACE INTO video_meta(video_id,json,fetched_at) VALUES(?,?,?)",
            [video_id, json.dumps({**existing, **clean}), time.time()],
        )

    def cached(self, video_id: str) -> Transcript | None:
        row = self.db.one("SELECT * FROM transcripts WHERE video_id=?", [video_id])
        if not row or not row["text"] or row["source"] == METADATA_ONLY:
            return None
        expired = time.time() - row["fetched_at"] > self.cfg.transcripts.cache_ttl_s
        if expired and row["source"] != SOURCE_ASR:
            return None
        return Transcript(
            video_id,
            row["text"],
            row["lang"],
            row["source"],
            self.cached_meta(video_id) or {},
            row["engine"],
            row["model"],
        )

    def no_captions(self, video_id: str) -> bool:
        """True while a recent check found no captions. Expires; never permanent."""
        row = self.db.one("SELECT checked_at FROM no_captions WHERE video_id=?", [video_id])
        return (
            bool(row) and time.time() - row["checked_at"] <= self.cfg.transcripts.no_captions_ttl_s
        )

    def hold(self, video_id: str) -> dict[str, Any] | None:
        """A remembered per-video outcome that must not be re-fetched yet, else None."""
        row = self.db.one(
            "SELECT kind, reason, until FROM video_holds WHERE video_id=?", [video_id]
        )
        if row is None or row["until"] <= time.time():
            return None
        return dict(row)

    def _record_hold(self, video_id: str, kind: str, reason: str, seconds: float) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO video_holds(video_id,kind,reason,until) VALUES(?,?,?,?)",
            [video_id, kind, reason, time.time() + seconds],
        )

    def record_failure(self, video_id: str, reason: str) -> None:
        """Remember that this video cannot be read (private, members-only, too long, ...).

        An offline miss is not remembered: a missing fixture cassette says nothing about the
        video, so the next attempt — with a cassette recorded, or offline mode off — starts clean.
        """
        if reason == REASON_OFFLINE:
            return
        self._record_hold(video_id, HOLD_FAILED, reason, self.cfg.transcripts.video_failure_ttl_s)

    @staticmethod
    def _audio_can_help(held: dict[str, Any]) -> bool:
        return held["kind"] == HOLD_FAILED and YoutubeVideoError(held["reason"]).can_transcribe

    @staticmethod
    def _hold_error(held: dict[str, Any]) -> YoutubeError:
        if held["kind"] == HOLD_FAILED:
            return YoutubeVideoError(held["reason"])
        return YoutubeDelayed(held["reason"], max(0.0, held["until"] - time.time()))

    def store_asr(
        self,
        video_id: str,
        text: str,
        lang: str | None,
        *,
        engine: str | None = None,
        model: str | None = None,
        segments: list[tuple[float, float, str]] | None = None,
        job_id: str | None = None,
    ) -> bool:
        """Keep an ASR transcript unless the video has fresh stored YouTube captions.

        A transcript stored first stays: ASR does not replace usable captions, and captions fetched
        later do not replace ASR (`_fetch`). Captions older than `cache_ttl_s` are no longer used
        (`cached`), so the ASR transcript replaces them. Returns False when nothing was stored.
        `segments` are `(start_s, end_s, text)` rows kept next to the text with the engine and
        model that produced them; `job_id` is the job that made it (for its delivery log).
        """
        now = time.time()
        stored = self.db.execute_rc(
            "INSERT INTO transcripts(video_id,lang,source,text,fetched_at,engine,model,segments,job_id)"
            " VALUES(?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(video_id) DO UPDATE SET lang=excluded.lang, source=excluded.source,"
            " text=excluded.text, fetched_at=excluded.fetched_at, engine=excluded.engine,"
            " model=excluded.model, segments=excluded.segments, job_id=excluded.job_id"
            " WHERE transcripts.source != ? OR transcripts.fetched_at < ?",
            [
                video_id,
                lang,
                SOURCE_ASR,
                text,
                now,
                engine,
                model,
                json.dumps(segments) if segments else None,
                job_id,
                SOURCE_CAPTIONS,
                now - self.cfg.transcripts.cache_ttl_s,
            ],
        )
        if stored:
            self.db.execute("DELETE FROM no_captions WHERE video_id=?", [video_id])
            self.db.execute("DELETE FROM video_holds WHERE video_id=?", [video_id])
        return bool(stored)

    async def get(
        self, video_id: str, priority: int = INTERACTIVE, recheck: bool = False
    ) -> Transcript:
        """The transcript, fetched at most once per TTL.

        Raises `NoCaptions` (cached for `no_captions_ttl_s`), `YoutubeVideoError` (this video cannot
        be read) or `YoutubeDelayed` (transient). Background callers wait while the breaker is open;
        interactive ones get `YoutubeCooldown`. `recheck` ignores the "no captions" memory, for a
        caller about to spend real effort on a video it believes has none.
        """
        hit = self.cached(video_id)
        if hit:
            return hit
        held = self.hold(video_id)
        if held and not (recheck and self._audio_can_help(held)):
            raise self._hold_error(held)
        if not recheck and self.no_captions(video_id):
            raise NoCaptions(video_id)
        task = self._inflight.get(video_id)
        if task is None:
            task = asyncio.create_task(self._fetch(video_id, priority))
            self._inflight[video_id] = task
            task.add_done_callback(lambda _t: self._inflight.pop(video_id, None))
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
        elif priority == INTERACTIVE:
            if not self.gate.interactive_ok(*FETCH_CLASSES):
                raise YoutubeCooldown(
                    self.gate.cooldown_remaining(*FETCH_CLASSES)
                    or self.cfg.youtube.captions_probe_retry_s,
                    CLASS_CAPTIONS,
                )
            self.gate.promote(video_id)
        return await asyncio.shield(task)

    def probe_captions(self, video_id: str) -> bool:
        """After a caption cooldown, send the one background request that decides the next step.

        Interactive requests never probe a class that just came out of a cooldown (the gate refuses
        them), so the first caller that finds it half-open asks for this video's captions in the
        background. The answer closes the class or opens it again; either way the caller carries on
        with the audio. Returns True when a probe was started.
        """
        if not self.gate.probe_pending() or (self._probe is not None and not self._probe.done()):
            return False
        if self.cached(video_id) or self.hold(video_id) or self.no_captions(video_id):
            return False
        try:
            self._probe = asyncio.get_running_loop().create_task(self._probe_run(video_id))
        except RuntimeError:
            return False
        return True

    async def _probe_run(self, video_id: str) -> None:
        try:
            await self.get(video_id, BACKGROUND)
        except Exception as exc:
            log.info("caption probe ended: %s", type(exc).__name__)

    async def _fetch(self, video_id: str, priority: int) -> Transcript:
        try:
            result = await self.gate.run(
                lambda: self.fetcher(video_id), priority, key=video_id, classes=FETCH_CLASSES
            )
        except YoutubeVideoError as exc:
            self.record_failure(video_id, exc.reason)
            raise
        except YoutubeDelayed as exc:
            if exc.reason == REASON_EMPTY_TRACK:
                self._record_hold(video_id, HOLD_DELAYED, exc.reason, exc.retry_after_s)
            raise
        self.store_meta(video_id, result.meta)
        if not result.text:
            self.db.execute(
                "INSERT OR REPLACE INTO no_captions(video_id,checked_at) VALUES(?,?)",
                [video_id, time.time()],
            )
            self.db.execute(
                "DELETE FROM transcripts WHERE video_id=? AND source=?", [video_id, SOURCE_CAPTIONS]
            )
            raise NoCaptions(video_id)
        stored = self.db.execute_rc(
            "INSERT INTO transcripts(video_id,lang,source,text,fetched_at) VALUES(?,?,?,?,?)"
            " ON CONFLICT(video_id) DO UPDATE SET lang=excluded.lang, source=excluded.source,"
            " text=excluded.text, fetched_at=excluded.fetched_at, engine=NULL, model=NULL,"
            " segments=NULL, job_id=NULL WHERE transcripts.source != ?",
            [video_id, result.lang, SOURCE_CAPTIONS, result.text, time.time(), SOURCE_ASR],
        )
        self.db.execute("DELETE FROM no_captions WHERE video_id=?", [video_id])
        if not stored:
            kept = self.cached(video_id)
            if kept is not None:
                return kept
        return Transcript(
            video_id, result.text, result.lang, SOURCE_CAPTIONS, self.cached_meta(video_id) or {}
        )
