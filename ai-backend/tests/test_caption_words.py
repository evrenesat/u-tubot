"""YouTube's own word offsets and caption kind are kept next to the transcript."""

from __future__ import annotations

import json

import httpx
import pytest
import yt_dlp

from tests.test_youtube_fetch import BOT_CHECK, VID, Rig
from utubot.db import Database
from utubot.transcripts import (
    CAPTION_AUTO,
    CAPTION_MANUAL,
    parse_json3_words,
    track_kind_of,
)
from utubot.youtube import YoutubeDelayed

WORDS_TRACK = json.dumps(
    {
        "events": [
            {
                "tStartMs": 1000,
                "segs": [
                    {"utf8": "hello"},
                    {"utf8": " big", "tOffsetMs": 400},
                    {"utf8": " world", "tOffsetMs": 900},
                ],
            },
            {"tStartMs": 3000, "segs": [{"utf8": "\n"}]},
            {"tStartMs": 4000, "segs": [{"utf8": "again", "tOffsetMs": 0}]},
        ]
    }
)
PLAIN_TRACK = json.dumps({"events": [{"tStartMs": 0, "segs": [{"utf8": "Hello world."}]}]})


def test_json3_words_use_the_segment_offsets_and_need_some():
    assert parse_json3_words(WORDS_TRACK) == [
        (1.0, "hello"),
        (1.4, "big"),
        (1.9, "world"),
        (4.0, "again"),
    ]
    assert parse_json3_words(PLAIN_TRACK) == []


def test_track_kind_follows_the_subtitles_table():
    assert track_kind_of({"subtitles": {"en": [{}]}}, "EN") == CAPTION_MANUAL
    assert track_kind_of({"automatic_captions": {"en-orig": [{}]}}, "en-orig") == CAPTION_AUTO
    assert track_kind_of({}, None) == CAPTION_AUTO


async def test_a_fetch_keeps_words_and_kind(tmp_path):
    rig = Rig(tmp_path, lambda req: httpx.Response(200, text=WORDS_TRACK))
    found = await rig.svc.get(VID)
    assert found.words[1] == (1.4, "big") and found.caption_kind == CAPTION_AUTO
    again = rig.svc.cached(VID)
    assert again.words == found.words and again.caption_kind == CAPTION_AUTO
    plain = Rig(tmp_path / "p", lambda req: httpx.Response(200, text=PLAIN_TRACK))
    got = await plain.svc.get(VID)
    assert got.words is None and got.caption_kind == CAPTION_AUTO


def _legacy_row(rig):
    rig.db.execute(
        "INSERT INTO transcripts(video_id,lang,source,text,fetched_at,segments) VALUES(?,?,?,?,?,?)",
        [VID, "en", "youtube_captions", "[00:00] old", 9e12, json.dumps([[0.0, 1.0, "old"]])],
    )


async def test_a_legacy_row_is_fetched_once_for_words(tmp_path):
    rig = Rig(tmp_path, lambda req: httpx.Response(200, text=WORDS_TRACK))
    _legacy_row(rig)
    assert (await rig.svc.get(VID)).text == "[00:00] old" and rig.extracts == 0
    fresh = await rig.svc.get(VID, want_words=True)
    assert fresh.words and fresh.caption_kind == CAPTION_AUTO and rig.extracts == 1
    await rig.svc.get(VID, want_words=True)
    assert rig.extracts == 1


async def test_a_legacy_row_is_used_while_youtube_does_not_answer(tmp_path):
    rig = Rig(tmp_path, extract=lambda: yt_dlp.utils.DownloadError(BOT_CHECK))
    _legacy_row(rig)
    found = await rig.svc.get(VID, want_words=True)
    assert found.text == "[00:00] old" and found.words is None and found.caption_kind is None
    # the breaker is open now: no further request, the legacy row still answers
    again = await rig.svc.get(VID, want_words=True)
    assert again.text == found.text and rig.extracts == 1
    assert rig.gate.cooldown_remaining() > 0
    with pytest.raises(YoutubeDelayed):
        await rig.svc.get("bcdefghijkl", want_words=True)


def test_words_and_kind_columns_are_additive():
    database = Database(":memory:")
    columns = {row["name"] for row in database.all("PRAGMA table_info(transcripts)")}
    assert {"words", "caption_kind"} <= columns
    # an older revision's insert (without the new columns) still works
    database.execute(
        "INSERT INTO transcripts(video_id,lang,source,text,fetched_at) VALUES('v','en','asr','t',0)"
    )
    assert database.one("SELECT words, caption_kind FROM transcripts")["caption_kind"] is None


@pytest.mark.parametrize(("text", "has_words"), [(WORDS_TRACK, True), (PLAIN_TRACK, False)])
async def test_cassettes_give_words_only_with_offsets(tmp_path, text, has_words):
    from utubot.config import Config
    from utubot.youtube_fixtures import OfflineYoutubeFetcher, save_cassette

    track = {"lang": "en", "ext": "json3", "text": text}
    save_cassette(tmp_path, VID, {"title": "T", "automatic_captions": {"en": []}}, track)
    result = await OfflineYoutubeFetcher(Config(), tmp_path)(VID)
    assert bool(result.words) is has_words and result.caption_kind == CAPTION_AUTO


@pytest.mark.parametrize("failure", ["video", "nocaptions", "generic"])
async def test_a_legacy_row_survives_any_failed_refetch(tmp_path, failure):
    from utubot.transcripts import NoCaptions
    from utubot.youtube import YoutubeError, YoutubeVideoError

    rig = Rig(tmp_path)
    _legacy_row(rig)
    errors = {
        "video": YoutubeVideoError("private"),
        "nocaptions": NoCaptions(VID),
        "generic": YoutubeError("boom"),
    }

    async def broken(video_id):
        raise errors[failure]

    rig.svc.fetcher = broken
    found = await rig.svc.get(VID, want_words=True)
    assert found.text == "[00:00] old" and found.caption_kind is None


async def test_a_legacy_row_is_used_at_once_while_the_gate_is_not_healthy(tmp_path):
    rig = Rig(tmp_path)
    _legacy_row(rig)
    rig.gate.healthy = lambda *classes: False
    found = await rig.svc.get(VID, want_words=True)
    assert found.text == "[00:00] old" and rig.extracts == 0 and not rig.http


def test_rolling_json3_repeats_are_dropped_beyond_adjacent_pairs():
    def seg(text, offset=None):
        return {"utf8": text, **({} if offset is None else {"tOffsetMs": offset})}

    rolling = json.dumps(
        {
            "events": [
                {"tStartMs": 0, "segs": [seg("one", 0), seg(" two", 400), seg(" three", 800)]},
                {"tStartMs": 1200, "segs": [seg("two", 0), seg(" three", 100), seg(" four", 500)]},
                {"tStartMs": 2400, "segs": [seg("three", 0), seg(" four", 0), seg(" five", 300)]},
            ]
        }
    )
    got = parse_json3_words(rolling)
    assert [t for _s, t in got] == ["one", "two", "three", "four", "five"]
    assert got[3][0] == pytest.approx(1.7)
