from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import yt_dlp

from .config import Config
from .db import METADATA_ONLY, Database
from .llm import INTERACTIVE, parse_retry_after
from .youtube import (
    REASON_EMPTY,
    REASON_NETWORK,
    YoutubeCooldown,
    YoutubeDelayed,
    YoutubeError,
    YoutubeGate,
    classify_failure,
    classify_status,
)

TIMESTAMP_BLOCK_S = 20
SOURCE_CAPTIONS = "youtube_captions"
SOURCE_ASR = "asr"
VIDEO_URL = "https://www.youtube.com/watch?v={}"
HTTP_ERROR_FLOOR = 400
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


@dataclass
class FetchResult:
    meta: dict[str, Any]
    text: str | None
    lang: str | None


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
        }
        if self.cfg.transcripts.cookies_file:
            opts["cookiefile"] = self.cfg.transcripts.cookies_file
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(VIDEO_URL.format(video_id), download=False)

    def _extract_classified(self, video_id: str) -> dict[str, Any]:
        try:
            return self._extract_fn(video_id)
        except yt_dlp.utils.YoutubeDLError as exc:
            raise classify_failure(exc, self.cfg.youtube.network_retry_s) from None

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
            resp.status_code, retry_s, parse_retry_after(resp.headers.get("retry-after"))
        )
        if problem is not None:
            raise problem
        if resp.status_code >= HTTP_ERROR_FLOOR:
            raise YoutubeError(f"caption download http {resp.status_code}")
        if not resp.text.strip():
            raise YoutubeDelayed(REASON_EMPTY, retry_s)
        return resp.text

    async def __call__(self, video_id: str) -> FetchResult:
        info = await asyncio.to_thread(self._extract_classified, video_id)
        meta = extract_meta(info)
        track = pick_track(info, self.cfg.transcripts.default_language)
        if not track:
            return FetchResult(meta, None, None)
        formats, lang = track
        fmt = pick_format(formats)
        if not fmt:
            return FetchResult(meta, None, lang)
        raw = await self._download_track(fmt["url"])
        segments = parse_json3(raw) if fmt["ext"] == "json3" else parse_vtt(raw)
        return FetchResult(meta, segments_to_text(segments) or None, lang)


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
            video_id, row["text"], row["lang"], row["source"], self.cached_meta(video_id) or {}
        )

    def no_captions(self, video_id: str) -> bool:
        """True while a recent check found no captions. Expires; never permanent."""
        row = self.db.one("SELECT checked_at FROM no_captions WHERE video_id=?", [video_id])
        return (
            bool(row) and time.time() - row["checked_at"] <= self.cfg.transcripts.no_captions_ttl_s
        )

    def store_asr(self, video_id: str, text: str, lang: str | None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO transcripts(video_id,lang,source,text,fetched_at)"
            " VALUES(?,?,?,?,?)",
            [video_id, lang, SOURCE_ASR, text, time.time()],
        )
        self.db.execute("DELETE FROM no_captions WHERE video_id=?", [video_id])

    async def get(self, video_id: str, priority: int = INTERACTIVE) -> Transcript:
        """The transcript, fetched at most once per TTL.

        Raises `NoCaptions` (cached for `no_captions_ttl_s`) or `YoutubeDelayed` (transient).
        Background callers wait while the breaker is open; interactive ones get `YoutubeCooldown`.
        """
        hit = self.cached(video_id)
        if hit:
            return hit
        if self.no_captions(video_id):
            raise NoCaptions(video_id)
        task = self._inflight.get(video_id)
        if task is None:
            task = asyncio.create_task(self._fetch(video_id, priority))
            self._inflight[video_id] = task
            task.add_done_callback(lambda _t: self._inflight.pop(video_id, None))
            task.add_done_callback(lambda t: t.cancelled() or t.exception())
        elif priority == INTERACTIVE:
            if not self.gate.healthy():
                raise YoutubeCooldown(self.gate.cooldown_remaining())
            self.gate.promote(video_id)
        return await asyncio.shield(task)

    async def _fetch(self, video_id: str, priority: int) -> Transcript:
        result = await self.gate.run(lambda: self.fetcher(video_id), priority, key=video_id)
        self.store_meta(video_id, result.meta)
        if not result.text:
            self.db.execute(
                "INSERT OR REPLACE INTO no_captions(video_id,checked_at) VALUES(?,?)",
                [video_id, time.time()],
            )
            raise NoCaptions(video_id)
        self.db.execute(
            "INSERT OR REPLACE INTO transcripts(video_id,lang,source,text,fetched_at)"
            " VALUES(?,?,?,?,?)",
            [video_id, result.lang, SOURCE_CAPTIONS, result.text, time.time()],
        )
        self.db.execute("DELETE FROM no_captions WHERE video_id=?", [video_id])
        return Transcript(
            video_id, result.text, result.lang, SOURCE_CAPTIONS, self.cached_meta(video_id) or {}
        )
