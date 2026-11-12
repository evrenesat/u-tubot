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
from .db import Database

TIMESTAMP_BLOCK_S = 20
VIDEO_URL = "https://www.youtube.com/watch?v={}"
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
    def __init__(self, cfg: Config):
        self.cfg = cfg

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

    async def __call__(self, video_id: str) -> FetchResult:
        info = await asyncio.to_thread(self._extract, video_id)
        meta = extract_meta(info)
        track = pick_track(info, self.cfg.transcripts.default_language)
        if not track:
            return FetchResult(meta, None, None)
        formats, lang = track
        fmt = pick_format(formats)
        if not fmt:
            return FetchResult(meta, None, lang)
        async with httpx.AsyncClient(timeout=self.cfg.transcripts.fetch_timeout_s) as http:
            resp = await http.get(fmt["url"], follow_redirects=True)
            resp.raise_for_status()
        segments = parse_json3(resp.text) if fmt["ext"] == "json3" else parse_vtt(resp.text)
        return FetchResult(meta, segments_to_text(segments) or None, lang)


class TranscriptService:
    def __init__(self, cfg: Config, db: Database, fetcher: Fetcher | None = None):
        self.cfg = cfg
        self.db = db
        self.fetcher: Fetcher = fetcher or YoutubeFetcher(cfg)
        self._sem = asyncio.Semaphore(cfg.transcripts.max_concurrency)
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
        if not row or time.time() - row["fetched_at"] > self.cfg.transcripts.cache_ttl_s:
            return None
        return Transcript(
            video_id, row["text"], row["lang"], row["source"], self.cached_meta(video_id) or {}
        )

    async def get(self, video_id: str) -> Transcript:
        hit = self.cached(video_id)
        if hit:
            return hit
        task = self._inflight.get(video_id)
        if task is None:
            task = asyncio.create_task(self._fetch(video_id))
            self._inflight[video_id] = task
            task.add_done_callback(lambda _t: self._inflight.pop(video_id, None))
        return await asyncio.shield(task)

    async def _fetch(self, video_id: str) -> Transcript:
        async with self._sem:
            result = await self.fetcher(video_id)
        self.store_meta(video_id, result.meta)
        meta = self.cached_meta(video_id) or {}
        source = "youtube_captions" if result.text else "metadata_only"
        text = result.text or ""
        self.db.execute(
            "INSERT OR REPLACE INTO transcripts(video_id,lang,source,text,fetched_at)"
            " VALUES(?,?,?,?,?)",
            [video_id, result.lang, source, text, time.time()],
        )
        return Transcript(video_id, text, result.lang, source, meta)
