"""Which YouTube audio format to download: the lowest bitrate of the original-language track.

Many videos carry several audio tracks (the original, YouTube's AI-dubbed translations, an audio
description). A plain "worst audio" pick can land on a dub, and the transcript is then in the wrong
language. `pick_audio_format` works on yt-dlp's format dicts and never picks a dubbed or described
track while an original one exists.

Fallback chain, first match wins:

1. audio-only formats whose track is marked `original` (`format_note`), lowest bitrate;
2. audio-only formats that are not dubbed or described and belong to the preferred track
   (higher `language_preference`, or the `(default)` track) when the tracks differ;
3. audio-only formats that are not dubbed or described (single-track videos);
4. audio-only formats of any track (every track is dubbed: the original is not offered);
5. the same four steps over formats that carry video too (a muxed stream; ffmpeg drops the video);
6. nothing: the caller falls back to yt-dlp's own selector (`captions.audio_format`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from typing import Any

NONE_CODEC = "none"
ORIGINAL_RE = re.compile(r"\boriginal\b", re.IGNORECASE)
DUBBED_RE = re.compile(r"\bdubbed\b", re.IGNORECASE)
DESCRIPTIVE_RE = re.compile(r"\bdescriptive\b", re.IGNORECASE)
DEFAULT_TRACK_RE = re.compile(r"\(default\)", re.IGNORECASE)
DRC_RE = re.compile(r"\bDRC\b")
BROKEN_RE = re.compile(r"\b(?:DAMAGED|BROKEN)\b")
UNSUPPORTED_PROTOCOLS = ("mhtml",)
MANIFEST_PROTOCOL_PREFIX = "m3u8"
UNKNOWN_BITRATE = float("inf")

Format = dict[str, Any]
FormatSelector = Callable[[dict[str, Any]], Iterator[Format]]


def _note(fmt: Format) -> str:
    return str(fmt.get("format_note") or "")


def has_audio(fmt: Format) -> bool:
    return (fmt.get("acodec") or NONE_CODEC) != NONE_CODEC


def has_video(fmt: Format) -> bool:
    return (fmt.get("vcodec") or NONE_CODEC) != NONE_CODEC


def usable(fmt: Format) -> bool:
    protocol = str(fmt.get("protocol") or "")
    return (
        has_audio(fmt)
        and bool(fmt.get("url") or fmt.get("fragments"))
        and not BROKEN_RE.search(_note(fmt))
        and protocol not in UNSUPPORTED_PROTOCOLS
    )


def is_dubbed(fmt: Format) -> bool:
    return bool(DUBBED_RE.search(_note(fmt)))


def is_original(fmt: Format) -> bool:
    return bool(ORIGINAL_RE.search(_note(fmt))) and not is_dubbed(fmt)


def is_plain_track(fmt: Format) -> bool:
    """Neither a dub nor an audio description."""
    return not is_dubbed(fmt) and not DESCRIPTIVE_RE.search(_note(fmt))


def _bitrate(fmt: Format) -> float:
    for key in ("abr", "tbr"):
        value = fmt.get(key)
        if isinstance(value, int | float) and value > 0:
            return float(value)
    return UNKNOWN_BITRATE


def _size(fmt: Format) -> float:
    value = fmt.get("filesize") or fmt.get("filesize_approx")
    return float(value) if isinstance(value, int | float) and value > 0 else UNKNOWN_BITRATE


def _cost(fmt: Format) -> tuple[bool, bool, float, float, str]:
    """Sort key, cheapest first: a plain HTTPS stream, no loudness compression, then the bitrate."""
    return (
        str(fmt.get("protocol") or "").startswith(MANIFEST_PROTOCOL_PREFIX),
        bool(DRC_RE.search(_note(fmt))),
        _bitrate(fmt),
        _size(fmt),
        str(fmt.get("format_id") or ""),
    )


def _preferred_track(plain: list[Format]) -> list[Format]:
    """The tracks YouTube prefers (highest `language_preference`, else marked default), if any differ."""
    prefs = {int(fmt.get("language_preference") or 0) for fmt in plain}
    if len(prefs) > 1:
        top = max(prefs)
        return [fmt for fmt in plain if int(fmt.get("language_preference") or 0) == top]
    defaults = [fmt for fmt in plain if DEFAULT_TRACK_RE.search(_note(fmt))]
    return defaults if 0 < len(defaults) < len(plain) else plain


def _original_group(pool: list[Format]) -> list[Format]:
    originals = [fmt for fmt in pool if is_original(fmt)]
    if originals:
        return originals
    plain = [fmt for fmt in pool if is_plain_track(fmt)]
    return _preferred_track(plain) if plain else pool


def track_kind(fmt: Format) -> str:
    """How the format's audio track is marked: `original`, `dubbed`, `descriptive` or `unmarked`."""
    if is_original(fmt):
        return "original"
    if is_dubbed(fmt):
        return "dubbed"
    if DESCRIPTIVE_RE.search(_note(fmt)):
        return "descriptive"
    return "unmarked"


def pick_audio_format(formats: Iterable[Format]) -> Format | None:
    """The lowest-bitrate usable format of the original-language track, or None (see module doc)."""
    candidates = [fmt for fmt in formats if usable(fmt)]
    audio_only = [fmt for fmt in candidates if not has_video(fmt)]
    pool = audio_only or candidates
    if not pool:
        return None
    return min(_original_group(pool), key=_cost)


def audio_selector(fallback: Callable[[], FormatSelector | None]) -> FormatSelector:
    """A yt-dlp `format` callable: `pick_audio_format`, else the string selector from `fallback()`."""

    def select(ctx: dict[str, Any]) -> Iterator[Format]:
        chosen = pick_audio_format(ctx.get("formats") or [])
        if chosen is not None:
            yield chosen
            return
        alternative = fallback()
        if alternative is not None:
            yield from alternative(ctx)

    return select
