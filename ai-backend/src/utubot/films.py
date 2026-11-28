"""Films as a cut source: source keys, release ids, and the subtitles that stand in for a transcript.

A film or an episode that plays on the TV has a source key (`imdb:tt0111161`, `imdb:tt0944947:S1E2`)
and a release key (the stream's file name and size). Cuts are shared per release, so the release
decides the backend id of a film (`film_video_id`): an id of the same shape as a YouTube video id,
so every route and table keyed by a video id works unchanged, without a YouTube-only assumption.

The transcript of a film is a subtitle file asked from a Stremio subtitles add-on by IMDb id. Only
the IMDb id, the season and episode and the stream's file name and size leave the server, never
anything about the user. A subtitle is used only when its timing fits the release (`check_timing`);
otherwise the cut is refused in plain words the TV shows.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .config import FilmsConfig
from .transcripts import parse_vtt
from .urlguard import Resolver, UrlRejected, guarded_get, system_resolver

SOURCE_KIND_FILM = "film"
SOURCE_KEY_RE = re.compile(r"^imdb:(tt\d{5,10})(?::S(\d{1,3})E(\d{1,4}))?$")
FILM_ID_PREFIX = "f"
FILM_ID_HEX_CHARS = 10
RELEASE_KEY_MAX_CHARS = 400
SUBTITLE_ADDON_TYPES = {"movie": "movie", "series": "series"}
SRT_TIME_RE = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)
MARKUP_RE = re.compile(r"<[^>]+>|\{\\[^}]*\}")
TOKEN_RE = re.compile(r"[a-z0-9]+")
GROUP_RE = re.compile(r"-([A-Za-z0-9]{2,12})(?:\.[A-Za-z0-9]{2,4})?$")
# Words that say nothing about which release a subtitle was made for.
NOISE_TOKENS = frozenset(
    {"srt", "sub", "subs", "mkv", "mp4", "avi", "the", "and", "eng", "en", "english", "cd1", "cd2"}
)
HASH_MATCH = "h"
HASH_BONUS = 0.15
GROUP_BONUS = 0.3
# OpenSubtitles language codes (ISO 639-2) of the TV's two-letter subtitle language setting.
LANGUAGE_CODES: dict[str, tuple[str, ...]] = {
    "en": ("eng",),
    "tr": ("tur",),
    "de": ("ger", "deu"),
    "fr": ("fre", "fra"),
    "es": ("spa",),
    "it": ("ita",),
    "pt": ("por", "pob"),
    "nl": ("dut", "nld"),
    "ru": ("rus",),
    "pl": ("pol",),
    "ar": ("ara",),
    "ja": ("jpn",),
    "ko": ("kor",),
    "zh": ("chi", "zho"),
    "sv": ("swe",),
    "da": ("dan",),
    "no": ("nor",),
    "fi": ("fin",),
    "el": ("gre", "ell"),
    "he": ("heb",),
    "hu": ("hun",),
    "cs": ("cze", "ces"),
    "ro": ("rum", "ron"),
    "uk": ("ukr",),
    "bg": ("bul",),
    "hr": ("hrv",),
    "sr": ("scc", "srp"),
    "id": ("ind",),
    "vi": ("vie",),
    "th": ("tha",),
    "hi": ("hin",),
    "fa": ("per", "fas"),
}
FALLBACK_LANGUAGE = "en"
# (stream, subtitle) frame rates whose mix-up shifts the end of a subtitle by their ratio.
FRAME_RATE_PAIRS = ((25.0, 23.976), (25.0, 24.0), (24.0, 23.976))
FRAME_RATE_RATIO_SLACK = 0.012
MAX_LISTED = 24
CACHE_ENTRIES = 64
CACHE_TTL_S = 3600.0
ID_RE = re.compile(r"[^A-Za-z0-9_.-]")
ID_MAX_CHARS = 48


class FilmRefused(RuntimeError):
    """A film cut cannot be built; the message is plain words for the TV."""

    def __init__(self, message: str, *, reason: str = "refused"):
        super().__init__(message)
        self.message = message
        self.reason = reason


@dataclass
class FilmSource:
    """The identity of one film release as the TV states it."""

    key: str
    release_key: str
    release_duration_ms: int | None = None
    imdb_id: str = ""
    season: int | None = None
    episode: int | None = None

    @property
    def video_id(self) -> str:
        return film_video_id(self.key, self.release_key)


@dataclass
class Subtitle:
    """One subtitle file chosen for a release: its cues and where it came from."""

    segments: list[tuple[float, float, str]]
    lang: str
    name: str
    score: float = 0.0
    notes: list[str] = field(default_factory=list)


def parse_source_key(key: str) -> tuple[str, int | None, int | None]:
    """`(imdb id, season, episode)` of a film source key; the season and episode are None for a film."""
    match = SOURCE_KEY_RE.match(key or "")
    if match is None:
        raise ValueError("a film source key is imdb:tt1234567 or imdb:tt1234567:S1E2")
    season = int(match.group(2)) if match.group(2) else None
    episode = int(match.group(3)) if match.group(3) else None
    return match.group(1), season, episode


def film_video_id(source_key: str, release_key: str) -> str:
    """The backend id of one release: eleven characters like a YouTube id, derived, never guessed."""
    digest = hashlib.sha256(f"{source_key}|{release_key}".encode()).hexdigest()
    return FILM_ID_PREFIX + digest[:FILM_ID_HEX_CHARS]


def film_source(key: str, release_key: str, release_duration_ms: int | None = None) -> FilmSource:
    """A checked film source; raises `ValueError` for a key or release the TV could not have sent."""
    imdb_id, season, episode = parse_source_key(key)
    release_key = (release_key or "").strip()
    if not release_key or len(release_key) > RELEASE_KEY_MAX_CHARS:
        raise ValueError("a film needs a release key (the stream's file name)")
    duration = int(release_duration_ms) if release_duration_ms else None
    return FilmSource(
        key, release_key, duration if duration and duration > 0 else None, imdb_id, season, episode
    )


def release_fits(left: dict[str, Any], right: dict[str, Any], tolerance_ms: int) -> bool:
    """Another release of the same title fits when both lengths are known and agree within the tolerance."""
    if left["key"] != right["key"]:
        return False
    a, b = left.get("release_duration_ms"), right.get("release_duration_ms")
    if not a or not b:
        return False
    return abs(a - b) <= tolerance_ms


# ---- subtitle files ------------------------------------------------------------------------------


def clean_cue(text: str) -> str:
    lines = [MARKUP_RE.sub("", line).strip() for line in text.splitlines()]
    return " ".join(line for line in lines if line)


def parse_srt(raw: str) -> list[tuple[float, float, str]]:
    """`(start, end, text)` cues of an SRT file in order; a WebVTT file is read as well."""
    raw = raw.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    if raw.lstrip().startswith("WEBVTT"):
        return sorted(parse_vtt(raw))
    cues: list[tuple[float, float, str]] = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            m = SRT_TIME_RE.search(line)
            if m is None:
                continue
            h, mi, s, ms, h2, mi2, s2, ms2 = m.groups()
            start = int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000
            end = int(h2) * 3600 + int(mi2) * 60 + int(s2) + int(ms2.ljust(3, "0")) / 1000
            text = clean_cue("\n".join(lines[i + 1 :]))
            if text:
                cues.append((start, max(end, start), text))
            break
    cues.sort(key=lambda cue: cue[0])
    return cues


def decode_subtitle(body: bytes) -> str:
    """The add-on converts to UTF-8; a file that still is not falls back to a Western encoding."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("latin-1")


# ---- choosing --------------------------------------------------------------------------------


def release_tokens(name: str) -> set[str]:
    return {
        t for t in TOKEN_RE.findall((name or "").lower()) if len(t) > 1 and t not in NOISE_TOKENS
    }


def release_group(name: str) -> str:
    match = GROUP_RE.search((name or "").strip())
    return match.group(1).lower() if match else ""


def release_score(candidate: dict[str, Any], file_name: str) -> float:
    """How well a subtitle's release name matches the stream's file name; higher is better.

    The token overlap of the two names (resolution, source, codec, group), plus a bonus when the
    release group agrees and when the add-on matched by the file's hash.
    """
    wanted = release_tokens(file_name)
    sub_name = str(candidate.get("subtitleFileName") or candidate.get("release") or "")
    have = release_tokens(sub_name)
    score = 0.0
    if wanted and have:
        score = 2 * len(wanted & have) / (len(wanted) + len(have))
    group = release_group(file_name)
    sub_group = str(candidate.get("releaseGroup") or "").lower() or release_group(sub_name)
    if group and group == sub_group:
        score += GROUP_BONUS
    if candidate.get("m") == HASH_MATCH:
        score += HASH_BONUS
    return score


def language_rank(candidate_lang: str, wanted: list[str]) -> int | None:
    """Position of the candidate's language in the wanted list, None when it is not wanted."""
    code = (candidate_lang or "").lower()
    for rank, language in enumerate(wanted):
        if code == language or code in LANGUAGE_CODES.get(language, ()):
            return rank
    return None


def wanted_languages(preferred: str | None) -> list[str]:
    first = (preferred or "").lower().replace("_", "-").split("-")[0]
    out = [first] if first and first != FALLBACK_LANGUAGE else []
    out.append(FALLBACK_LANGUAGE)
    return out


def choose_subtitles(
    candidates: list[dict[str, Any]],
    file_name: str,
    preferred_language: str | None,
    season: int | None = None,
    episode: int | None = None,
) -> list[dict[str, Any]]:
    """The candidates to try, best first: the user's language else English, then the best release match.

    A candidate that names another episode is dropped. The result keeps only one language: the
    first wanted language that has any candidate.
    """
    usable = []
    for item in candidates:
        if not item.get("url"):
            continue
        if season is not None and (item.get("season") or season) != season:
            continue
        if episode is not None and (item.get("episode") or episode) != episode:
            continue
        usable.append(item)
    wanted = wanted_languages(preferred_language)
    for rank in range(len(wanted)):
        chosen = [c for c in usable if language_rank(str(c.get("lang", "")), wanted) == rank]
        if chosen:
            return sorted(chosen, key=lambda c: (-release_score(c, file_name), str(c.get("id"))))
    return []


# ---- timing ---------------------------------------------------------------------------------------


def covered_ms(cues: list[tuple[float, float, str]]) -> int:
    """The time the cues are on screen, overlaps counted once."""
    total = 0.0
    at = 0.0
    for start, end, _ in cues:
        start = max(start, at)
        if end > start:
            total += end - start
            at = end
    return int(total * 1000)


def check_timing(
    cues: list[tuple[float, float, str]],
    duration_ms: int | None,
    cfg: FilmsConfig,
    *,
    subtitle_fps: float | None = None,
    stream_fps: float | None = None,
) -> str | None:
    """None when the subtitle fits the release, else the plain-words reason it does not.

    The cues must be enough, the last one must lie before the end of the stream (plus a margin)
    and reach most of it, the cues together must cover a reasonable share of it, and the subtitle's
    frame rate must agree with the stream's when both are known.
    """
    if len(cues) < cfg.min_cues:
        return f"The subtitle file has only {len(cues)} lines, too few to place a cut."
    if subtitle_fps and stream_fps:
        ratio = subtitle_fps / stream_fps
        if abs(ratio - 1.0) > cfg.fps_tolerance:
            return (
                f"The subtitles are timed for {subtitle_fps:g} frames per second but this stream "
                f"runs at {stream_fps:g}, so they would drift."
            )
    if not duration_ms:
        return None
    last_end_ms = int(cues[-1][1] * 1000)
    margin_ms = int(max(cfg.end_margin_s * 1000, cfg.end_margin_frac * duration_ms))
    if last_end_ms > duration_ms + margin_ms:
        ratio = last_end_ms / duration_ms
        hint = ""
        fast, slow = min(FRAME_RATE_PAIRS, key=lambda pair: abs(ratio - pair[0] / pair[1]))
        if abs(ratio - fast / slow) < FRAME_RATE_RATIO_SLACK:
            hint = f" They look timed for {slow:g} frames per second, this stream runs at {fast:g}."
        return (
            f"The subtitles run to {last_end_ms // 60000} min but this stream is "
            f"{duration_ms // 60000} min.{hint}"
        )
    if last_end_ms < cfg.min_last_cue_frac * duration_ms:
        return (
            f"The subtitles end at {last_end_ms // 60000} min but this stream is "
            f"{duration_ms // 60000} min, so they belong to a different cut of the film."
        )
    if covered_ms(cues) < cfg.min_cover_frac * duration_ms:
        return "The subtitles cover too little of the stream to place a cut."
    return None


# ---- the add-on -----------------------------------------------------------------------------------


class TtlCache:
    """A small in-memory cache for the add-on's lists and the files, so the cut builder and the picker ask once."""

    def __init__(self, entries: int = CACHE_ENTRIES, ttl_s: float = CACHE_TTL_S, clock=time.time):
        self.entries, self.ttl_s, self.clock = entries, ttl_s, clock
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        if self.clock() - hit[0] > self.ttl_s:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return hit[1]

    def put(self, key: str, value: Any) -> None:
        self._data[key] = (self.clock(), value)
        self._data.move_to_end(key)
        while len(self._data) > self.entries:
            self._data.popitem(last=False)


class FilmSubtitles:
    """Asks the subtitles add-on for a title and downloads the file that fits the release."""

    def __init__(
        self,
        cfg: FilmsConfig,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = system_resolver,
    ):
        self.cfg = cfg
        self.transport = transport
        self.resolver = resolver
        self.cache = TtlCache()

    def addon_url(self, source: FilmSource, file_name: str, size_bytes: int | None) -> str:
        """The add-on request: type, IMDb id (with season and episode), the stream's file name and size."""
        kind = "series" if source.season is not None else "movie"
        video = source.imdb_id
        if source.season is not None:
            video += f":{source.season}:{source.episode}"
        extra = []
        if file_name:
            extra.append("filename=" + quote(file_name, safe=""))
        if size_bytes:
            extra.append(f"videoSize={int(size_bytes)}")
        tail = video + ("/" + "&".join(extra) if extra else "")
        return f"{self.cfg.subtitles_url.rstrip('/')}/subtitles/{kind}/{tail}.json"

    async def _get(self, url: str, *, allow_hosts: list[str], limit: int) -> bytes:
        body = bytearray()
        try:
            async with guarded_get(
                url,
                allow_hosts=allow_hosts,
                max_redirects=3,
                timeout_s=self.cfg.timeout_s,
                transport=self.transport,
                resolver=self.resolver,
            ) as resp:
                if resp.status_code >= 400:
                    raise FilmRefused(
                        f"The subtitles service answered HTTP {resp.status_code}.", reason="service"
                    )
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise FilmRefused("A subtitle file was too large.", reason="service")
        except UrlRejected as exc:
            raise FilmRefused(f"A subtitle address was refused: {exc}.", reason="service") from exc
        except httpx.HTTPError as exc:
            raise FilmRefused(
                "The subtitles service could not be reached.", reason="service"
            ) from exc
        return bytes(body)

    async def candidates(
        self, source: FilmSource, file_name: str, size_bytes: int | None
    ) -> list[dict[str, Any]]:
        url = self.addon_url(source, file_name, size_bytes)
        cached = self.cache.get("list|" + url)
        if cached is not None:
            return cached
        host = urlsplit(self.cfg.subtitles_url).hostname or ""
        raw = await self._get(url, allow_hosts=[host], limit=self.cfg.max_subtitle_bytes)
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise FilmRefused("The subtitles service answered nonsense.", reason="service") from exc
        items = data.get("subtitles") if isinstance(data, dict) else None
        found = [item for item in items or [] if isinstance(item, dict)]
        self.cache.put("list|" + url, found)
        return found

    async def download(self, item: dict[str, Any]) -> bytes:
        """The file of a candidate, from the cache when it was fetched lately."""
        address = str(item["url"])
        cached = self.cache.get("file|" + address)
        if cached is not None:
            return cached
        body = await self._get(
            address, allow_hosts=self.cfg.download_hosts, limit=self.cfg.max_subtitle_bytes
        )
        self.cache.put("file|" + address, body)
        return body

    async def listing(
        self,
        source: FilmSource,
        *,
        file_name: str,
        size_bytes: int | None = None,
        preferred_language: str | None = None,
    ) -> list[dict[str, Any]]:
        found = await self.candidates(source, file_name, size_bytes)
        return list_subtitles(found, file_name, preferred_language, source.season, source.episode)

    async def webvtt_of(
        self, source: FilmSource, *, file_name: str, size_bytes: int | None, subtitle: str
    ) -> str:
        """One listed subtitle as WebVTT; the TV names it by the id of the list, never by an address."""
        found = await self.candidates(source, file_name, size_bytes)
        item = next((c for c in found if c.get("url") and subtitle_id(c) == subtitle), None)
        if item is None:
            raise FilmRefused("That subtitle is not offered for this film.", reason="none")
        cues = parse_srt(decode_subtitle(await self.download(item)))
        if not cues:
            raise FilmRefused("That subtitle file has no readable lines.", reason="service")
        return webvtt(cues)

    async def fetch(
        self,
        source: FilmSource,
        *,
        file_name: str,
        size_bytes: int | None = None,
        preferred_language: str | None = None,
        duration_ms: int | None = None,
        stream_fps: float | None = None,
    ) -> Subtitle:
        """The best subtitle whose timing fits the release, or `FilmRefused` with the reason."""
        found = await self.candidates(source, file_name, size_bytes)
        ordered = choose_subtitles(
            found, file_name, preferred_language, source.season, source.episode
        )
        if not ordered:
            raise FilmRefused(
                "No subtitles were found for this film in your language or in English.",
                reason="none",
            )
        failure = ""  # the reason the best release match was refused: the one worth telling
        for item in ordered[: self.cfg.max_candidates_tried]:
            try:
                body = await self.download(item)
            except FilmRefused as exc:
                failure = failure or exc.message
                continue
            cues = parse_srt(decode_subtitle(body))
            fps_milli = item.get("fpsMilli")
            problem = check_timing(
                cues,
                duration_ms,
                self.cfg,
                subtitle_fps=float(fps_milli) / 1000 if fps_milli else None,
                stream_fps=stream_fps,
            )
            if problem is not None:
                failure = failure or problem
                continue
            return Subtitle(
                cues,
                str(item.get("lang") or ""),
                str(item.get("subtitleFileName") or ""),
                release_score(item, file_name),
            )
        raise FilmRefused(failure or "No subtitle file fits this stream.", reason="timing")


# ---- the TV's own subtitle picker ---------------------------------------------------------------------


def subtitle_id(item: dict[str, Any]) -> str:
    """A safe id for a path segment: the add-on's own id, else a hash of its address."""
    raw = ID_RE.sub("", str(item.get("id") or ""))[:ID_MAX_CHARS]
    return raw or hashlib.sha1(str(item.get("url") or "").encode()).hexdigest()[:16]


def vtt_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}.{ms % 1000:03d}"


def webvtt(cues: list[tuple[float, float, str]]) -> str:
    """The cues as a WebVTT file, the format the TV's player reads as a side-loaded text track."""
    out = ["WEBVTT", ""]
    for start, end, text in cues:
        out.append(f"{vtt_time(start)} --> {vtt_time(max(end, start))}")
        out.append(text.replace("-->", "->"))
        out.append("")
    return "\n".join(out)


def list_subtitles(
    candidates: list[dict[str, Any]],
    file_name: str,
    preferred_language: str | None,
    season: int | None = None,
    episode: int | None = None,
) -> list[dict[str, Any]]:
    """What the picker offers: the viewer's language, then English, each best release match first.

    The same filters as `choose_subtitles` (an address, the right episode) but every wanted
    language is kept, not only the first with a candidate.
    """
    wanted = wanted_languages(preferred_language)
    usable = []
    for item in candidates:
        if not item.get("url"):
            continue
        if season is not None and (item.get("season") or season) != season:
            continue
        if episode is not None and (item.get("episode") or episode) != episode:
            continue
        rank = language_rank(str(item.get("lang", "")), wanted)
        if rank is not None:
            usable.append((rank, item))
    usable.sort(
        key=lambda pair: (pair[0], -release_score(pair[1], file_name), subtitle_id(pair[1]))
    )
    seen: set[str] = set()
    listed = []
    for _, item in usable:
        sid = subtitle_id(item)
        if sid in seen:
            continue
        seen.add(sid)
        listed.append(
            {
                "id": sid,
                "lang": str(item.get("lang") or ""),
                "name": str(item.get("subtitleFileName") or item.get("release") or "")[:200],
                "score": round(release_score(item, file_name), 3),
                "hash_match": item.get("m") == HASH_MATCH,
            }
        )
        if len(listed) >= MAX_LISTED:
            break
    if listed:
        listed[0]["best"] = True
    return listed
