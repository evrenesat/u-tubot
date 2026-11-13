"""Recorded YouTube fixtures: the record/replay layer that keeps tests and dev servers off YouTube.

A cassette is one video's recorded YouTube answers: the yt-dlp info dict (metadata, the player
response essence and the caption track tables) and the text of the caption track the server would
deliver, with every URL removed (they carry signed tokens; they expire and never belong in git).
Cassettes are small JSON files, kept in-repo under `fixtures/youtube/` (`[youtube] fixtures_dir`
moves them); recorded media (audio, video) is large and belongs in the media archive, never in
the repository.

Recording (`record_cassette`, the `utubot youtube-record` command) is the only path here that
touches YouTube, and it is an owner action, run by hand: never from tests, CI or an agent's
verification runs — the real-network path refuses to run inside an automated test run. Everyone
else replays: tests wire cassettes into `YoutubeFetcher`'s seams, and the offline dev-proxy mode
(`[youtube] offline`) serves them through `OfflineYoutubeFetcher` — unknown videos then answer
"offline" instead of leaving the machine.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yt_dlp

from .config import Config
from .transcripts import (
    ANSWERED_NO_CAPTIONS,
    FetchResult,
    extract_meta,
    info_complete,
    parse_json3,
    parse_vtt,
    pick_format,
    pick_track,
    segments_to_text,
)
from .youtube import (
    CLASS_CAPTIONS,
    CLASS_METADATA,
    YoutubeOffline,
    redact_urls,
    ytdlp_runtime_options,
)

# Where the cassettes live when `[youtube] fixtures_dir` is empty: the repository checkout.
FIXTURE_SUBDIR = Path("fixtures/youtube")
# Keys dropped everywhere (URLs carry signed tokens; headers are noise the replayers rebuild).
DROPPED_KEYS = frozenset({"url", "fragment_base_url", "http_headers"})
VALUE_MAX_CHARS = 4000
DESCRIPTION_MAX_CHARS = 2000
VERSION_MAX_CHARS = 40


def default_fixture_dir() -> Path:
    """The repository's cassette directory (`ai-backend/fixtures/youtube`)."""
    return Path(__file__).resolve().parents[2] / FIXTURE_SUBDIR


def fixture_dir(cfg: Config) -> Path:
    """The cassette directory this config serves: `[youtube] fixtures_dir` or the repository's."""
    return Path(cfg.youtube.fixtures_dir) if cfg.youtube.fixtures_dir else default_fixture_dir()


def _sanitize(value: Any) -> Any:
    """A git-safe copy of a yt-dlp answer: no URLs, no headers, capped strings."""
    if isinstance(value, dict):
        return {
            key: _sanitize(item)
            for key, item in value.items()
            if key not in DROPPED_KEYS and item is not None
        }
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        text = redact_urls(value)
        if len(text) > VALUE_MAX_CHARS:
            text = text[:VALUE_MAX_CHARS] + "…"
        return text
    return value


def sanitize_info(info: dict[str, Any]) -> dict[str, Any]:
    """The yt-dlp info dict a cassette keeps: structure and metadata, nothing signed."""
    clean = _sanitize(info)
    description = clean.get("description")
    if isinstance(description, str) and len(description) > DESCRIPTION_MAX_CHARS:
        clean["description"] = description[:DESCRIPTION_MAX_CHARS]
    return clean


def save_cassette(
    out_dir: Path,
    video_id: str,
    info: dict[str, Any],
    track: dict[str, Any] | None,
    *,
    note: str | None = None,
    yt_dlp_version: str | None = None,
) -> Path:
    """Write one cassette (`<video_id>.json`) atomically; `track` is `{lang, ext, text}` or None."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cassette = {
        "video_id": video_id,
        "recorded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "yt_dlp_version": (yt_dlp_version or yt_dlp.version.__version__)[:VERSION_MAX_CHARS],
        **({"note": note} if note else {}),
        "info": sanitize_info(info),
        "track": track,
    }
    target = out_dir / f"{video_id}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cassette, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(target)
    return target


def load_cassette(fixture_dir_path: Path, video_id: str) -> dict[str, Any] | None:
    """The cassette of `video_id`, or None when it was never recorded."""
    path = fixture_dir_path / f"{video_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


class OfflineYoutubeFetcher:
    """The fetcher of the offline dev-proxy mode: recorded cassettes instead of YouTube.

    Wired by `build_services` when `[youtube] offline` is set and no explicit fetcher is given.
    A video with a cassette answers like `YoutubeFetcher` would have (same parsers, same result
    shape); anything else raises `YoutubeOffline` — nothing leaves the machine.
    """

    def __init__(self, cfg: Config, dir_path: Path | None = None):
        self.cfg = cfg
        self._dir = dir_path or fixture_dir(cfg)

    def cassette(self, video_id: str) -> dict[str, Any] | None:
        return load_cassette(self._dir, video_id)

    async def __call__(self, video_id: str) -> FetchResult:
        cassette = self.cassette(video_id)
        if cassette is None:
            raise YoutubeOffline(CLASS_METADATA)
        info = cassette.get("info") or {}
        meta = extract_meta({"id": video_id, **info})
        track = cassette.get("track")
        if not track or not track.get("text"):
            return FetchResult(meta, None, None, answered=ANSWERED_NO_CAPTIONS)
        segments = (
            parse_json3(track["text"]) if track.get("ext") == "json3" else parse_vtt(track["text"])
        )
        text = segments_to_text(segments)
        if not text:
            raise YoutubeOffline(CLASS_CAPTIONS)
        return FetchResult(meta, text, track.get("lang"))


async def record_cassette(
    cfg: Config,
    video_id: str,
    *,
    lang: str | None = None,
    out_dir: Path | None = None,
    note: str | None = None,
    extract: Any = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Path:
    """Record one video's answers into a cassette. Owner action only — it reaches YouTube.

    `extract` and `transport` stand in for yt-dlp and the track download in tests; without them
    this calls the real services, so it refuses to run inside an automated test run and must
    only be started by hand (never from tests, CI or an agent's verification runs).
    """
    if extract is None or transport is None:
        guard_recording()
    extract_fn = extract or (lambda vid: _default_extract(cfg, vid))
    info = await asyncio.to_thread(extract_fn, video_id)
    if not info_complete(info):
        raise RuntimeError("yt-dlp returned an incomplete answer; try again later")
    prefer = lang or cfg.transcripts.default_language
    found = pick_track(info, prefer)
    track: dict[str, Any] | None = None
    if found:
        formats, track_lang = found
        fmt = pick_format(formats)
        if fmt and fmt.get("url"):
            track = {
                "lang": track_lang,
                "ext": fmt["ext"],
                "text": await _download_track_text(cfg, fmt["url"], transport),
            }
        else:
            track = {"lang": track_lang, "ext": "vtt", "text": ""}
    return save_cassette(
        out_dir or fixture_dir(cfg),
        video_id,
        info,
        track,
        note=note,
        yt_dlp_version=yt_dlp.version.__version__,
    )


def guard_recording() -> None:
    """Refuse to record from an automated run (tests, CI); the owner starts it by hand."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError("recording a fixture reaches YouTube; never run it from tests")


async def _download_track_text(
    cfg: Config, url: str, transport: httpx.AsyncBaseTransport | None
) -> str:
    """The raw caption track of a recorded video (timedtext json3/vtt), via httpx."""
    async with httpx.AsyncClient(
        timeout=cfg.transcripts.fetch_timeout_s, transport=transport, follow_redirects=True
    ) as http:
        resp = await http.get(url)
    resp.raise_for_status()
    return resp.text


def _default_extract(cfg: Config, video_id: str) -> dict[str, Any]:
    """The owner-run yt-dlp extraction behind `record_cassette` (real YouTube)."""
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": cfg.transcripts.fetch_timeout_s,
        **ytdlp_runtime_options(cfg.youtube),
    }
    if cfg.transcripts.cookies_file:
        opts["cookiefile"] = cfg.transcripts.cookies_file
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
