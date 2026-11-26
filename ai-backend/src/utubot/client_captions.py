"""Caption tracks a client already holds (the TV's player, the browser's page), stored like a fetch.

A client that plays a video has YouTube's caption tracks through its own session; uploading them lets
the server skip its rate-limited yt-dlp request. The upload is validated (counts, sizes, formats),
one track is picked the way the server's own fetch picks, and it is stored by
`TranscriptService.store_client_captions`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from .config import TranscriptConfig
from .transcripts import (
    CAPTION_AUTO,
    CAPTION_MANUAL,
    STORED,
    TranscriptService,
    parse_json3,
    parse_json3_words,
    parse_srv3,
    parse_vtt,
    segments_to_text,
)

LANG_RE = re.compile(r"^[A-Za-z]{2,3}([-_][A-Za-z0-9]{2,8}){0,3}$")
LANG_MAX_CHARS = 35
NAME_MAX_CHARS = 100
ORIGINAL_SUFFIX = "-orig"
FORMATS = ("json3", "srv3", "vtt")


class ClientTrack(BaseModel):
    lang: str = Field(max_length=LANG_MAX_CHARS)
    kind: Literal["auto", "manual"]
    name: str = Field("", max_length=NAME_MAX_CHARS)
    format: Literal["json3", "srv3", "vtt"]
    body: str
    original: bool = False  # the track is in the video's own spoken language


class ClientCaptions(BaseModel):
    tracks: list[ClientTrack]


class ClientCaptionsRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class ParsedTrack:
    track: ClientTrack
    segments: list[tuple[float, float, str]]
    words: list[tuple[float, str]]
    text: str


def check_limits(upload: ClientCaptions, cfg: TranscriptConfig) -> None:
    if not upload.tracks:
        raise ClientCaptionsRefused(400, "no caption tracks")
    if len(upload.tracks) > cfg.client_max_tracks:
        raise ClientCaptionsRefused(400, f"at most {cfg.client_max_tracks} tracks")
    for track in upload.tracks:
        if not LANG_RE.match(track.lang):
            raise ClientCaptionsRefused(400, "invalid language code")
        if len(track.body.encode("utf-8", "ignore")) > cfg.client_max_track_bytes:
            raise ClientCaptionsRefused(413, f"a track is over {cfg.client_max_track_bytes} bytes")


def parse_track(track: ClientTrack) -> ParsedTrack | None:
    """The track's rows and text, or None when its body is not valid timed text of its format."""
    try:
        if track.format == "json3":
            segments = parse_json3(track.body)
            words = parse_json3_words(track.body)
        else:
            segments = parse_srv3(track.body) if track.format == "srv3" else parse_vtt(track.body)
            words = []
    except (ValueError, AttributeError, TypeError, KeyError, SyntaxError):
        return None  # ElementTree's ParseError is a SyntaxError
    text = segments_to_text([(start, text) for start, _end, text in segments])
    if not text:
        return None
    return ParsedTrack(track, segments, words, text)


def _rank(parsed: ParsedTrack, wanted: str) -> int:
    """Lower is better; the server's own order: authored in the video's language, its automatic
    original, any authored track, any automatic track."""
    track = parsed.track
    base = track.lang.lower().replace("_", "-").split("-")[0]
    own = track.original or track.lang.lower().endswith(ORIGINAL_SUFFIX) or base == wanted
    if track.kind == CAPTION_MANUAL:
        return 0 if own else 2
    return 1 if own else 3


def pick(parsed: list[ParsedTrack], wanted_lang: str) -> ParsedTrack:
    wanted = wanted_lang.lower().split("-")[0]
    return min(parsed, key=lambda item: _rank(item, wanted))


def kind_of(track: ClientTrack) -> str:
    return CAPTION_MANUAL if track.kind == "manual" else CAPTION_AUTO


def store_upload(service: TranscriptService, video_id: str, upload: ClientCaptions) -> dict:
    """Validate an upload, pick its track and store it. Raises `ClientCaptionsRefused`."""
    cfg = service.cfg.transcripts
    check_limits(upload, cfg)
    parsed = [item for item in map(parse_track, upload.tracks) if item is not None]
    if not parsed:
        raise ClientCaptionsRefused(400, "no track holds readable timed text")
    meta_language = (service.cached_meta(video_id) or {}).get("language")
    chosen = pick(parsed, meta_language or cfg.default_language)
    kind = kind_of(chosen.track)
    result = service.store_client_captions(
        video_id,
        chosen.text,
        chosen.track.lang,
        kind,
        segments=chosen.segments or None,
        words=chosen.words or None,
    )
    return {
        "stored": result == STORED,
        "reason": result,
        "lang": chosen.track.lang,
        "kind": kind,
        "tracks": len(parsed),
    }
