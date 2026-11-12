"""Video id from what a person pastes: an id, a watch/shorts/live/embed link or a youtu.be link."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)
SHORT_HOSTS = frozenset({"youtu.be", "www.youtu.be"})
PATH_PREFIXES = frozenset({"shorts", "embed", "live", "v"})
MAX_REF_CHARS = 500


def parse_video_ref(text: str) -> str | None:
    """The 11-character video id, or None. No network access, no redirects followed."""
    text = (text or "").strip()
    if not text or len(text) > MAX_REF_CHARS:
        return None
    if VIDEO_ID_RE.match(text):
        return text
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    segments = [s for s in parts.path.split("/") if s]
    candidate: str | None = None
    if host in SHORT_HOSTS and segments:
        candidate = segments[0]
    elif host in YOUTUBE_HOSTS:
        if segments and segments[0] == "watch":
            candidate = (parse_qs(parts.query).get("v") or [None])[0]
        elif len(segments) >= 2 and segments[0] in PATH_PREFIXES:
            candidate = segments[1]
    return candidate if candidate and VIDEO_ID_RE.match(candidate) else None
