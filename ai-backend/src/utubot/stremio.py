"""The owner's Stremio account for the films library: log in and read the watch state.

The server logs in once with the owner's email and password (``POST {auth}/api/auth``, the Stremio
``login`` event), keeps only the returned auth key (encrypted in the secret store, see
``secretstore.py``), and never stores or logs the password. The library is read with
``datastoreGet`` on the ``libraryItem`` key (``GET {datastore}/api/datastoreGet``); each entry maps
to a u·tubot film or episode by its IMDb id, carrying the resume position (``timeOffset``) and the
watched state (the ``watched`` / ``watchedAnyway`` episode maps).

The API shape comes from recorded fixtures, with no real account in tests: the transport is injected
and the endpoints are fixed public hosts held to the address guard (``docs/development.md``, the
"no real service" rule). See the pull request for the endpoint and field references.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from .config import StremioConfig
from .urlguard import (
    RequestTooLarge,
    Resolver,
    UrlRejected,
    guarded_request,
    system_resolver,
)

# Stremio ids: a movie is the IMDb id, an episode is <imdb>:<season>:<episode>.
IMDB_ID_RE = re.compile(r"^tt\d{5,10}$")
EPISODE_ID_RE = re.compile(r"^(tt\d{5,10}):(\d{1,3}):(\d{1,4})$")
WATCHED_KEY_RE = re.compile(r"[Ss]?(\d+)[Ee](\d+)")
# A fraction at or above this counts as a fully watched episode.
WATCHED_SHARE = 0.9
LIBRARY_KEY = "libraryItem"


class StremioError(RuntimeError):
    """A Stremio API failure. The message is plain words the TV or the page shows."""

    def __init__(self, message: str, *, reason: str = "error") -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


def _b64url_encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


@dataclass
class LibraryItem:
    """One entry of the Stremio ``libraryItem`` datastore, with its watch state."""

    id: str
    type: str
    name: str
    year: str
    poster: str
    background: str
    time_offset_s: int = 0
    watched: dict[str, float] = field(default_factory=dict)
    watched_anyway: set[str] = field(default_factory=set)
    last_watched: str = ""

    @classmethod
    def parse(cls, resource_id: str, raw: Any) -> LibraryItem | None:
        if not isinstance(raw, dict):
            return None
        name = str(raw.get("name") or "").strip()
        if not name:
            return None
        imdb = raw.get("imdb")
        poster = ""
        background = ""
        if isinstance(imdb, dict):
            poster = str(imdb.get("poster") or "")
            background = str(imdb.get("background") or "")
        if not poster:
            poster = str(raw.get("poster") or "")
        if not background:
            background = str(raw.get("background") or "")
        offset = raw.get("timeOffset")
        try:
            time_offset_s = int(offset) if offset else 0
        except (TypeError, ValueError):
            time_offset_s = 0
        watched = {
            key: float(value)
            for key, value in (raw.get("watched") or {}).items()
            if isinstance(value, (int, float))
        }
        watched_anyway = {key for key, value in (raw.get("watchedAnyway") or {}).items() if value}
        return cls(
            id=resource_id,
            type=str(raw.get("type") or ""),
            name=name,
            year=str(raw.get("year") or ""),
            poster=poster,
            background=background,
            time_offset_s=time_offset_s,
            watched=watched,
            watched_anyway=watched_anyway,
            last_watched=str(raw.get("lastWatched") or ""),
        )


@dataclass
class FilmImport:
    """One library item mapped to a u·tubot film or episode, ready for the TV's store."""

    id: str
    type: str
    title_id: str
    name: str
    poster: str
    season: int
    episode: int
    position_ms: int
    watched: bool
    last_watched: str = ""

    @property
    def is_episode(self) -> bool:
        return self.season > 0 or self.episode > 0


def parse_episode_id(resource_id: str) -> tuple[str, int, int] | None:
    """`(imdb, season, episode)` of a series resource id, or None for a movie id."""
    match = EPISODE_ID_RE.match(resource_id or "")

    if match is None:
        if IMDB_ID_RE.match(resource_id or ""):
            return None
        return None

    return match.group(1), int(match.group(2)), int(match.group(3))


def parse_watched_key(key: str) -> tuple[int, int] | None:
    """The season and episode of a ``S1E2`` watch key, or None when it is not one."""
    match = WATCHED_KEY_RE.match(key or "")

    return (int(match.group(1)), int(match.group(2))) if match else None


def map_item(item: LibraryItem) -> list[FilmImport]:
    """The u·tubot entries of one Stremio library item.

    A movie is one film entry with its resume position. A series is one watched entry per episode
    in its ``watched`` / ``watchedAnyway`` maps, plus one series-level resume entry from
    ``timeOffset`` (the episode the owner is on). All entries keep the IMDb id so the TV can show
    them and look up the runtime.
    """
    out: list[FilmImport] = []

    if item.type == "series":
        # Every watched episode, from the fraction map and the "watched anyway" map.
        keys = set(item.watched) | set(item.watched_anyway)
        for key in sorted(keys):
            episode = parse_watched_key(key)

            if episode is None:
                continue

            season, number = episode
            fraction = item.watched.get(key, 0.0)
            out.append(
                FilmImport(
                    id=f"{item.id}:{season}:{number}",
                    type="series",
                    title_id=item.id,
                    name=item.name,
                    poster=item.poster,
                    season=season,
                    episode=number,
                    position_ms=0,
                    watched=fraction >= WATCHED_SHARE or key in item.watched_anyway,
                    last_watched=item.last_watched,
                )
            )

        if item.time_offset_s > 0:
            out.append(
                FilmImport(
                    id=item.id,
                    type="series",
                    title_id=item.id,
                    name=item.name,
                    poster=item.poster,
                    season=0,
                    episode=0,
                    position_ms=item.time_offset_s * 1000,
                    watched=False,
                    last_watched=item.last_watched,
                )
            )
    else:
        out.append(
            FilmImport(
                id=item.id,
                type=item.type or "movie",
                title_id=item.id,
                name=item.name,
                poster=item.poster,
                season=0,
                episode=0,
                position_ms=item.time_offset_s * 1000,
                watched=False,
                last_watched=item.last_watched,
            )
        )

    return out


def parse_library(payload: Any) -> list[LibraryItem]:
    """The ``libraryItem`` entries of a decoded datastore payload, in order."""
    items = []
    library = payload.get(LIBRARY_KEY) if isinstance(payload, dict) else None

    if not isinstance(library, dict):
        return items

    for resource_id, raw in library.items():
        item = LibraryItem.parse(resource_id, raw)

        if item is not None:
            items.append(item)

    return items


def map_library(payload: Any) -> tuple[list[FilmImport], int]:
    """Every library item mapped, and the count that could not be mapped to an IMDb id."""
    mapped: list[FilmImport] = []
    unmapped = 0

    for item in parse_library(payload):
        if parse_episode_id(item.id) is None and not IMDB_ID_RE.match(item.id):
            unmapped += 1
            continue

        mapped.extend(map_item(item))

    return mapped, unmapped


class StremioClient:
    """Logs in to Stremio and reads the library. Every host is held to the address guard."""

    def __init__(
        self,
        cfg: StremioConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = system_resolver,
    ) -> None:
        self.cfg = cfg
        self._transport = transport
        self._resolver = resolver

    async def login(self, email: str, password: str) -> str:
        """The auth key for an email and password. The password is never returned or logged."""
        host = urlsplit(self.cfg.auth_url).hostname or ""
        body = {"event": "login", "payload": {"email": email, "password": password}}

        try:
            status, raw = await guarded_request(
                "POST",
                self.cfg.auth_url,
                allow_hosts=[host],
                max_redirects=3,
                timeout_s=self.cfg.timeout_s,
                limit=65_536,
                transport=self._transport,
                resolver=self._resolver,
                json_body=body,
            )
        except UrlRejected as exc:
            raise StremioError("The Stremio address was refused.", reason="service") from exc
        except RequestTooLarge:
            raise StremioError("The Stremio answer was too large.", reason="service") from None
        except httpx.HTTPError as exc:
            raise StremioError(
                "The Stremio server could not be reached.", reason="service"
            ) from exc

        if status >= 400:
            raise StremioError(f"Stremio answered HTTP {status}.", reason="service")

        try:
            data = json.loads(raw)
        except ValueError:
            raise StremioError(
                "Stremio answered in an unexpected format.", reason="format"
            ) from None
        if not isinstance(data, dict):
            raise StremioError("Stremio answered in an unexpected format.", reason="format")
        if data.get("status") != "OK":
            detail = _auth_error(data)
            raise StremioError(
                detail or "Sign in to Stremio failed. Check the email and password.",
                reason="auth",
            )
        auth = data.get("auth")

        if not isinstance(auth, str) or not auth.strip():
            raise StremioError("Stremio did not return an account key.", reason="auth")

        return auth.strip()

    async def library(self, auth_key: str) -> dict[str, Any]:
        """The decoded ``libraryItem`` payload for an auth key."""
        host = urlsplit(self.cfg.datastore_url).hostname or ""
        payload = _b64url_encode(json.dumps({"op": "read", "key": LIBRARY_KEY}))

        try:
            status, raw = await guarded_request(
                "GET",
                self.cfg.datastore_url,
                allow_hosts=[host],
                max_redirects=3,
                timeout_s=self.cfg.timeout_s,
                limit=self.cfg.max_library_bytes,
                transport=self._transport,
                resolver=self._resolver,
                query={"payload": payload, "auth": auth_key},
            )
        except UrlRejected as exc:
            raise StremioError("The Stremio address was refused.", reason="service") from exc
        except RequestTooLarge:
            raise StremioError("The Stremio library was too large.", reason="service") from None
        except httpx.HTTPError as exc:
            raise StremioError(
                "The Stremio server could not be reached.", reason="service"
            ) from exc

        if status >= 400:
            raise StremioError(f"Stremio answered HTTP {status}.", reason="service")

        try:
            data = json.loads(raw)
        except ValueError:
            raise StremioError(
                "Stremio answered in an unexpected format.", reason="format"
            ) from None
        if not isinstance(data, dict):
            raise StremioError("Stremio answered in an unexpected format.", reason="format")
        if isinstance(data.get("payload"), str):
            try:
                data = json.loads(_b64url_decode(data["payload"]))
            except (binascii.Error, ValueError) as exc:
                raise StremioError(
                    "Stremio answered in an unexpected format.", reason="format"
                ) from exc

        return data


def _auth_error(data: dict[str, Any]) -> str:
    """A short reason from a Stremio ``{"status": "Error", ...}`` answer, when it has one."""
    error = data.get("error")

    if isinstance(error, dict):
        message = error.get("message") or error.get("error")

        if isinstance(message, str) and message.strip():
            return message.strip()
    elif isinstance(error, str) and error.strip():
        return error.strip()

    return ""
