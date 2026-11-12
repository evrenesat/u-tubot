from __future__ import annotations

import asyncio
import json
import logging
import time

import httpx
import pytest
import yt_dlp

from tests.fakes import FakeClock
from utubot.config import Config
from utubot.db import Database
from utubot.llm import BACKGROUND, INTERACTIVE
from utubot.transcripts import NoCaptions, TranscriptService, YoutubeFetcher
from utubot.youtube import (
    REASON_BOT_CHECK,
    REASON_EMPTY,
    REASON_EMPTY_TRACK,
    REASON_FORBIDDEN_MEDIA,
    REASON_INCOMPLETE,
    REASON_MEMBERS_ONLY,
    REASON_NETWORK,
    REASON_PRIVATE,
    REASON_RATE_LIMITED,
    REASON_UNAVAILABLE,
    STATE_CLOSED,
    YoutubeBlocked,
    YoutubeCooldown,
    YoutubeDelayed,
    YoutubeGate,
    YoutubeVideoError,
)

VID = "abcdefghijk"
OTHER = "bcdefghijkl"
TRACK_URL = "https://www.youtube.com/api/timedtext?v=abcdefghijk&sig=SECRETSIG&lang=en&fmt=json3"
CAPTIONS = json.dumps(
    {
        "events": [
            {"tStartMs": 0, "segs": [{"utf8": "Hello world."}]},
            {"tStartMs": 21000, "segs": [{"utf8": "The answer is yes."}]},
        ]
    }
)
BOT_CHECK = "ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. Use --cookies"


def info(captions: bool = True) -> dict:
    out = {
        "id": VID,
        "title": "A title",
        "duration": 600,
        "language": "en",
        "formats": [{"format_id": "251", "ext": "webm"}],
    }
    if captions:
        out["automatic_captions"] = {"en": [{"ext": "json3", "url": TRACK_URL}]}
    return out


class Rig:
    def __init__(self, tmp_path, handler=None, extract=None):
        self.cfg = Config()
        self.cfg.youtube.min_interval_s = 0.0
        self.cfg.youtube.jitter_s = 0.0
        self.clock = FakeClock()
        self.db = Database(tmp_path / "t.sqlite")
        self.http: list[httpx.Request] = []
        self.extracts = 0
        self.handler = handler or (lambda req: httpx.Response(200, text=CAPTIONS))
        self.extract_result = extract or (lambda: info())

        def _extract(video_id: str) -> dict:
            self.extracts += 1
            result = self.extract_result()
            if isinstance(result, Exception):
                raise result
            return result

        def _handle(request: httpx.Request) -> httpx.Response:
            self.http.append(request)
            return self.handler(request)

        fetcher = YoutubeFetcher(self.cfg, _extract, httpx.MockTransport(_handle))
        self.gate = YoutubeGate(self.cfg.youtube, self.db, self.clock)
        self.svc = TranscriptService(self.cfg, self.db, fetcher, self.gate)


async def test_captions_are_fetched_once_per_ttl(tmp_path):
    rig = Rig(tmp_path)
    first = await rig.svc.get(VID)
    assert first.source == "youtube_captions" and "[00:00] Hello world." in first.text
    again = await asyncio.gather(rig.svc.get(VID), rig.svc.get(VID, BACKGROUND))
    assert all(t.text == first.text for t in again)
    assert rig.extracts == 1 and len(rig.http) == 1
    assert rig.svc.cached_meta(VID)["title"] == "A title"


async def test_concurrent_callers_share_one_fetch(tmp_path):
    rig = Rig(tmp_path)
    results = await asyncio.gather(*(rig.svc.get(VID) for _ in range(5)))
    assert len({t.text for t in results}) == 1
    assert rig.extracts == 1 and len(rig.http) == 1


async def test_timedtext_429_with_retry_after_opens_the_breaker_and_is_not_cached(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    rig = Rig(tmp_path, lambda req: httpx.Response(429, headers={"Retry-After": "120"}))
    with pytest.raises(YoutubeBlocked) as info_:
        await rig.svc.get(VID)
    assert info_.value.reason == REASON_RATE_LIMITED
    assert info_.value.retry_after_s == pytest.approx(120)
    assert rig.svc.cached(VID) is None and not rig.svc.no_captions(VID)
    assert rig.db.one("SELECT 1 FROM transcripts") is None
    with pytest.raises(YoutubeCooldown) as cool:
        await rig.svc.get(VID)
    assert cool.value.retry_after_s == pytest.approx(120)
    assert rig.extracts == 1 and len(rig.http) == 1
    assert "SECRETSIG" not in caplog.text and "sig=" not in caplog.text
    rig.handler = lambda req: httpx.Response(200, text=CAPTIONS)
    await rig.clock.advance(121)
    transcript = await rig.svc.get(VID)
    assert transcript.source == "youtube_captions"
    assert rig.gate.healthy() and rig.extracts == 2


async def test_429_without_retry_after_uses_exponential_cooldown(tmp_path):
    rig = Rig(tmp_path, lambda req: httpx.Response(429))
    with pytest.raises(YoutubeBlocked) as info_:
        await rig.svc.get(VID)
    assert info_.value.retry_after_s == pytest.approx(rig.cfg.youtube.cooldown_base_s)


async def test_bot_check_from_ytdlp_blocks(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    rig = Rig(tmp_path, extract=lambda: yt_dlp.utils.DownloadError(BOT_CHECK))
    with pytest.raises(YoutubeBlocked) as info_:
        await rig.svc.get(VID)
    assert info_.value.reason == REASON_BOT_CHECK
    assert not rig.gate.healthy()
    assert rig.http == []
    with pytest.raises(YoutubeCooldown):
        await rig.svc.get(VID)
    assert rig.extracts == 1
    assert rig.db.one("SELECT 1 FROM transcripts") is None
    assert rig.db.one("SELECT 1 FROM no_captions") is None


async def test_ytdlp_429_blocks(tmp_path):
    rig = Rig(
        tmp_path,
        extract=lambda: yt_dlp.utils.DownloadError(
            "ERROR: Unable to download webpage: HTTP Error 429: Too Many Requests"
        ),
    )
    with pytest.raises(YoutubeBlocked) as info_:
        await rig.svc.get(VID)
    assert info_.value.reason == REASON_RATE_LIMITED


async def test_no_captions_is_cached_for_a_while_then_checked_again(tmp_path):
    rig = Rig(tmp_path, extract=lambda: info(captions=False))
    with pytest.raises(NoCaptions):
        await rig.svc.get(VID)
    assert rig.svc.no_captions(VID) and rig.http == []
    with pytest.raises(NoCaptions):
        await rig.svc.get(VID)
    assert rig.extracts == 1
    assert rig.gate.healthy()
    assert rig.svc.cached_meta(VID)["duration_s"] == 600
    old = time.time() - rig.cfg.transcripts.no_captions_ttl_s - 1
    rig.db.execute("UPDATE no_captions SET checked_at=?", [old])
    assert not rig.svc.no_captions(VID)
    rig.extract_result = lambda: info()
    assert (await rig.svc.get(VID)).source == "youtube_captions"
    assert rig.extracts == 2
    assert rig.db.one("SELECT 1 FROM no_captions") is None


async def test_no_captions_default_ttl_is_three_days():
    assert Config().transcripts.no_captions_ttl_s == 3 * 86400


async def test_empty_caption_body_is_transient_and_not_cached(tmp_path):
    rig = Rig(tmp_path, lambda req: httpx.Response(200, text=""))
    with pytest.raises(YoutubeDelayed) as info_:
        await rig.svc.get(VID)
    assert info_.value.reason == REASON_EMPTY and not isinstance(info_.value, YoutubeBlocked)
    assert rig.gate.healthy()
    assert rig.db.one("SELECT 1 FROM transcripts") is None
    assert rig.db.one("SELECT 1 FROM no_captions") is None


async def test_server_error_and_network_error_are_transient(tmp_path):
    rig = Rig(tmp_path, lambda req: httpx.Response(503))
    with pytest.raises(YoutubeDelayed) as info_:
        await rig.svc.get(VID)
    assert info_.value.reason == REASON_NETWORK
    assert info_.value.retry_after_s == rig.cfg.youtube.network_retry_s

    def boom(request):
        raise httpx.ConnectTimeout("slow", request=request)

    rig.handler = boom
    with pytest.raises(YoutubeDelayed) as net:
        await rig.svc.get(VID)
    assert net.value.reason == REASON_NETWORK and rig.gate.healthy()


async def test_background_get_waits_out_the_cooldown_instead_of_failing(tmp_path):
    rig = Rig(tmp_path)
    rig.gate.report_block(REASON_RATE_LIMITED, 300)
    task = asyncio.create_task(rig.svc.get(VID, BACKGROUND))
    await asyncio.sleep(0.05)
    assert not task.done() and rig.extracts == 0
    with pytest.raises(YoutubeCooldown):
        await rig.svc.get("zzzzzzzzzzz", INTERACTIVE)
    await rig.clock.advance(301)
    transcript = await asyncio.wait_for(task, 5)
    assert transcript.source == "youtube_captions" and rig.extracts == 1


async def test_interactive_caller_joining_a_paused_background_fetch_is_told_to_wait(tmp_path):
    rig = Rig(tmp_path)
    rig.gate.report_block(REASON_RATE_LIMITED, 300)
    bg = asyncio.create_task(rig.svc.get(VID, BACKGROUND))
    await asyncio.sleep(0.05)
    with pytest.raises(YoutubeCooldown):
        await rig.svc.get(VID, INTERACTIVE)
    assert not bg.done() and rig.extracts == 0
    await rig.clock.advance(301)
    assert (await asyncio.wait_for(bg, 5)).source == "youtube_captions"


async def test_interactive_caller_promotes_a_queued_background_fetch(tmp_path):
    rig = Rig(tmp_path)
    order: list[str] = []
    release = asyncio.Event()
    real = rig.svc.fetcher

    async def slow(video_id: str):
        order.append(video_id)
        if video_id == "holdholdhol":
            await release.wait()
        return await real(video_id)

    rig.svc.fetcher = slow
    hold = asyncio.create_task(rig.svc.get("holdholdhol", INTERACTIVE))
    await asyncio.sleep(0.05)
    other = asyncio.create_task(rig.svc.get("otherotherot", BACKGROUND))
    wanted = asyncio.create_task(rig.svc.get(VID, BACKGROUND))
    await asyncio.sleep(0.05)
    joined = asyncio.create_task(rig.svc.get(VID, INTERACTIVE))
    await asyncio.sleep(0.05)
    release.set()
    await asyncio.gather(hold, other, wanted, joined)
    assert order == ["holdholdhol", VID, "otherotherot"]


async def test_ttl_expires_youtube_captions_but_not_an_asr_transcript(tmp_path):
    rig = Rig(tmp_path)
    await rig.svc.get(VID)
    rig.svc.store_asr(OTHER, "[00:00] spoken words", "en")
    old = time.time() - rig.cfg.transcripts.cache_ttl_s - 1
    rig.db.execute("UPDATE transcripts SET fetched_at=?", [old])
    assert rig.svc.cached(VID) is None
    assert rig.svc.cached(OTHER).source == "asr"
    await rig.svc.get(VID)
    assert rig.extracts == 2


# ---- review fixes: per-video failures, soft-degraded answers, holds ----------------------------


async def test_403_on_the_caption_url_is_a_per_video_failure_not_a_breaker_trip(tmp_path):
    rig = Rig(tmp_path, lambda req: httpx.Response(403))
    with pytest.raises(YoutubeVideoError) as first:
        await rig.svc.get(VID)
    assert first.value.reason == REASON_FORBIDDEN_MEDIA
    assert rig.gate.healthy() and rig.gate.state() == STATE_CLOSED
    assert rig.svc.hold(VID)["kind"] == "failed"
    with pytest.raises(YoutubeVideoError):
        await rig.svc.get(VID)
    assert rig.extracts == 1 and len(rig.http) == 1
    rig.handler = lambda req: httpx.Response(200, text=CAPTIONS)
    assert (await rig.svc.get("zzzzzzzzzzz")).source == "youtube_captions"


async def test_410_and_members_only_are_per_video_failures(tmp_path):
    rig = Rig(tmp_path, lambda req: httpx.Response(410))
    with pytest.raises(YoutubeVideoError) as gone:
        await rig.svc.get(VID)
    assert gone.value.reason == REASON_UNAVAILABLE and rig.gate.healthy()
    members = Rig(
        tmp_path / "m",
        extract=lambda: yt_dlp.utils.DownloadError(
            "ERROR: [youtube] abc: Join this channel to get access to members-only content"
        ),
    )
    with pytest.raises(YoutubeVideoError) as info_:
        await members.svc.get(VID)
    assert info_.value.reason == REASON_MEMBERS_ONLY and members.gate.healthy()


async def test_403_on_the_watch_request_still_opens_the_breaker(tmp_path):
    rig = Rig(
        tmp_path,
        extract=lambda: yt_dlp.utils.DownloadError(
            "ERROR: [youtube] abc: Unable to download webpage: HTTP Error 403: Forbidden"
        ),
    )
    with pytest.raises(YoutubeBlocked):
        await rig.svc.get(VID)
    assert not rig.gate.healthy()


async def test_a_video_failure_expires_and_is_fetched_again(tmp_path):
    rig = Rig(tmp_path, lambda req: httpx.Response(403))
    with pytest.raises(YoutubeVideoError):
        await rig.svc.get(VID)
    rig.db.execute("UPDATE video_holds SET until=?", [time.time() - 1])
    rig.handler = lambda req: httpx.Response(200, text=CAPTIONS)
    assert (await rig.svc.get(VID)).source == "youtube_captions"
    assert rig.extracts == 2


async def test_an_incomplete_ytdlp_answer_is_delayed_and_never_cached_as_no_captions(tmp_path):
    partial = {"id": VID, "title": "A title", "duration": 600}
    rig = Rig(tmp_path, extract=lambda: partial)
    with pytest.raises(YoutubeDelayed) as info_:
        await rig.svc.get(VID)
    assert info_.value.reason == REASON_INCOMPLETE and not isinstance(info_.value, YoutubeBlocked)
    assert not rig.svc.no_captions(VID) and rig.db.one("SELECT 1 FROM no_captions") is None
    assert rig.gate.healthy()
    rig.extract_result = lambda: info(captions=False)
    with pytest.raises(NoCaptions):
        await rig.svc.get(VID)
    assert rig.svc.no_captions(VID)


async def test_caption_languages_listed_without_formats_are_a_degraded_answer(tmp_path):
    degraded = {**info(captions=False), "automatic_captions": {"en": []}}
    rig = Rig(tmp_path, extract=lambda: degraded)
    with pytest.raises(YoutubeDelayed) as info_:
        await rig.svc.get(VID)
    assert info_.value.reason == REASON_INCOMPLETE
    assert not rig.svc.no_captions(VID)


async def test_an_empty_parsed_track_is_delayed_with_a_short_hold_not_no_captions(tmp_path):
    rig = Rig(tmp_path, lambda req: httpx.Response(200, text='{"events": []}'))
    with pytest.raises(YoutubeDelayed) as info_:
        await rig.svc.get(VID)
    assert info_.value.reason == REASON_EMPTY_TRACK
    assert info_.value.retry_after_s == rig.cfg.transcripts.empty_track_retry_s == 3600
    assert not rig.svc.no_captions(VID) and rig.db.one("SELECT 1 FROM no_captions") is None
    assert rig.db.one("SELECT 1 FROM transcripts") is None
    assert rig.gate.healthy()
    with pytest.raises(YoutubeDelayed) as held:
        await rig.svc.get(VID)
    assert held.value.reason == REASON_EMPTY_TRACK and 3500 < held.value.retry_after_s <= 3600
    assert rig.extracts == 1
    rig.db.execute("UPDATE video_holds SET until=?", [time.time() - 1])
    rig.handler = lambda req: httpx.Response(200, text=CAPTIONS)
    assert (await rig.svc.get(VID)).source == "youtube_captions"
    assert rig.svc.hold(VID) is None


async def test_asr_never_replaces_youtube_captions(tmp_path):
    rig = Rig(tmp_path)
    await rig.svc.get(VID)
    assert rig.svc.store_asr(VID, "[00:00] spoken words", "en") is False
    assert rig.svc.cached(VID).source == "youtube_captions"
    assert "Hello world." in rig.svc.cached(VID).text
    assert rig.svc.store_asr(OTHER, "[00:00] spoken words", "en") is True
    assert rig.svc.store_asr(OTHER, "[00:00] newer words", "en") is True
    assert rig.svc.cached(OTHER).text == "[00:00] newer words"


async def test_recheck_ignores_the_no_captions_memory_but_not_other_holds(tmp_path):
    rig = Rig(tmp_path, extract=lambda: info(captions=False))
    with pytest.raises(NoCaptions):
        await rig.svc.get(VID)
    rig.extract_result = lambda: info()
    with pytest.raises(NoCaptions):
        await rig.svc.get(VID)
    assert rig.extracts == 1
    assert (await rig.svc.get(VID, recheck=True)).source == "youtube_captions"
    assert rig.extracts == 2
    rig.svc.record_failure(OTHER, REASON_PRIVATE)
    with pytest.raises(YoutubeVideoError):
        await rig.svc.get(OTHER, recheck=True)
    rig.svc.record_failure(OTHER, REASON_FORBIDDEN_MEDIA)
    assert (await rig.svc.get(OTHER, recheck=True)).source == "youtube_captions"
