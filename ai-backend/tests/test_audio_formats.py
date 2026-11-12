from __future__ import annotations

from utubot.captions.formats import audio_selector, pick_audio_format


def audio(
    format_id: str,
    abr: float,
    note: str = "",
    *,
    language: str | None = None,
    pref: int | None = None,
    ext: str = "webm",
    protocol: str = "https",
) -> dict:
    return {
        "format_id": format_id,
        "format_note": note,
        "ext": ext,
        "acodec": "opus" if ext == "webm" else "mp4a.40.2",
        "vcodec": "none",
        "abr": abr,
        "tbr": abr,
        "language": language,
        "language_preference": pref,
        "protocol": protocol,
        "url": f"https://media.invalid/{format_id}",
    }


def video(format_id: str, tbr: float, *, with_audio: bool = False) -> dict:
    return {
        "format_id": format_id,
        "format_note": "360p",
        "ext": "mp4",
        "acodec": "mp4a.40.2" if with_audio else "none",
        "vcodec": "avc1.4d401e",
        "tbr": tbr,
        "protocol": "https",
        "url": f"https://media.invalid/{format_id}",
    }


STORYBOARD = {
    "format_id": "sb0",
    "ext": "mhtml",
    "acodec": "none",
    "vcodec": "none",
    "protocol": "mhtml",
    "url": "https://media.invalid/sb0",
}

ORIGINAL = "English (United States) original (default), low"
DUB_ES = "Spanish (United States) dubbed-auto, low"
DUB_DE = "German (Germany) dubbed-auto, low"


def ids(fmt: dict | None) -> str | None:
    return fmt["format_id"] if fmt else None


def test_single_track_video_gets_the_lowest_bitrate_audio():
    formats = [
        STORYBOARD,
        audio("251", 130),
        audio("249", 50),
        audio("250", 70),
        audio("140", 128, ext="m4a"),
        video("18", 500, with_audio=True),
        video("134", 300),
    ]
    assert ids(pick_audio_format(formats)) == "249"


def test_a_dubbed_track_with_a_lower_bitrate_never_beats_the_original():
    formats = [
        audio("249-0", 50, ORIGINAL, language="en-US", pref=10),
        audio("250-0", 70, ORIGINAL, language="en-US", pref=10),
        audio("249-1", 40, DUB_ES, language="es-US", pref=-1),
        audio("249-2", 38, DUB_DE, language="de-DE", pref=-1),
        audio("251-1", 120, DUB_ES, language="es-US", pref=-1),
    ]
    assert ids(pick_audio_format(formats)) == "249-0"


def test_the_original_marker_wins_even_when_language_preference_is_missing():
    formats = [
        audio("249-1", 40, DUB_ES, language="es-US"),
        audio("251-0", 130, ORIGINAL, language="en-US"),
    ]
    assert ids(pick_audio_format(formats)) == "251-0"


def test_without_original_markers_the_preferred_track_is_chosen_over_dubs():
    formats = [
        audio("249-0", 50, "English (United States), low", language="en-US", pref=10),
        audio("249-1", 40, "Turkish (Turkey), low", language="tr-TR", pref=-1),
    ]
    assert ids(pick_audio_format(formats)) == "249-0"


def test_without_any_preference_the_default_track_is_chosen():
    formats = [
        audio("249-0", 50, "Turkish (Turkey) (default), low", language="tr-TR"),
        audio("249-1", 40, "English (United States), low", language="en-US"),
    ]
    assert ids(pick_audio_format(formats)) == "249-0"


def test_dubbed_note_excludes_a_track_even_without_an_original_marker():
    formats = [
        audio("249-1", 40, DUB_ES, language="es-US"),
        audio("251-0", 130, "English (United States), medium", language="en-US"),
    ]
    assert ids(pick_audio_format(formats)) == "251-0"


def test_other_language_tracks_named_only_by_language_lose_to_the_marked_original():
    """Shape of a real multi-track video: only the original says so, the others are just a language."""
    formats = [
        audio("249-15", 48.3, "English (US) original (default), low", language="en", pref=10),
        audio("250-9", 70.1, "English (US) original (default), low", language="en", pref=10),
        audio("249-4", 45.1, "Korean, low", language="ko", pref=-1),
        audio("249-6", 45.8, "Italian, low", language="it", pref=-1),
        audio("249-3", 45.0, "Dutch (NL), low", language="nl-NL", pref=-1),
        audio("139-7", 48.8, "Italian, low", language="it", pref=-1, ext="m4a"),
    ]
    assert ids(pick_audio_format(formats)) == "249-15"
    assert ids(pick_audio_format([f for f in formats if f["language_preference"] != 10])) == "249-3"


def test_audio_description_tracks_are_avoided():
    formats = [
        audio("249-0", 60, ORIGINAL, language="en-US", pref=10),
        audio("249-1", 30, "English (United States) descriptive, low", language="en-US", pref=-10),
    ]
    assert ids(pick_audio_format(formats)) == "249-0"
    only_plain_vs_described = [
        audio("a", 30, "English descriptive, low", pref=-10),
        audio("b", 90, "English, medium"),
    ]
    assert ids(pick_audio_format(only_plain_vs_described)) == "b"


def test_when_only_dubs_are_offered_the_cheapest_dub_is_used_rather_than_failing():
    formats = [
        audio("a", 90, DUB_ES, language="es-US"),
        audio("b", 40, DUB_DE, language="de-DE"),
    ]
    assert ids(pick_audio_format(formats)) == "b"


def test_dynamic_range_compressed_copies_are_only_a_tiebreak_loser():
    formats = [
        audio("249-drc", 50, "medium, DRC"),
        audio("249", 50, "medium"),
    ]
    assert ids(pick_audio_format(formats)) == "249"


def test_manifest_streams_lose_to_plain_https_at_a_higher_bitrate():
    formats = [
        audio("hls-48", 48, protocol="m3u8_native", ext="m4a"),
        audio("249", 52),
    ]
    assert ids(pick_audio_format(formats)) == "249"


def test_damaged_and_urlless_formats_are_skipped():
    broken = audio("low", 20, "low, DAMAGED")
    nourl = {**audio("nourl", 25), "url": None}
    assert ids(pick_audio_format([broken, nourl, audio("249", 50)])) == "249"


def test_without_audio_only_formats_the_smallest_muxed_stream_is_used():
    formats = [
        video("133", 200),
        video("18", 500, with_audio=True),
        video("22", 1500, with_audio=True),
    ]
    assert ids(pick_audio_format(formats)) == "18"


def test_nothing_usable_returns_none():
    assert pick_audio_format([]) is None
    assert pick_audio_format([STORYBOARD, video("134", 300)]) is None


def test_selector_yields_the_pick_and_otherwise_defers_to_the_fallback_selector():
    formats = [audio("249", 50), audio("251", 130)]
    asked: list[int] = []

    def fallback_selector(ctx):
        asked.append(1)
        yield {"format_id": "fallback"}

    select = audio_selector(lambda: fallback_selector)
    assert [f["format_id"] for f in select({"formats": formats})] == ["249"]
    assert asked == []
    assert [f["format_id"] for f in select({"formats": [STORYBOARD]})] == ["fallback"]
    assert asked == [1]
    assert list(audio_selector(lambda: None)({"formats": []})) == []
