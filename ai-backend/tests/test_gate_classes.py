"""One breaker per YouTube endpoint class: captions (timedtext), metadata (watch/player/yt-dlp), media."""

from __future__ import annotations

import asyncio

import pytest

from tests.fakes import FakeClock, settle
from utubot.config import YoutubeConfig
from utubot.db import Database
from utubot.llm import BACKGROUND, INTERACTIVE
from utubot.youtube import (
    CLASS_CAPTIONS,
    CLASS_MEDIA,
    CLASS_METADATA,
    CLASSES,
    FETCH_CLASSES,
    MEDIA_CLASSES,
    REASON_BOT_CHECK,
    REASON_RATE_LIMITED,
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    YoutubeBlocked,
    YoutubeCooldown,
    YoutubeError,
    YoutubeGate,
    YoutubeVideoError,
    classify_failure,
    classify_status,
)


def make_gate(clock: FakeClock, db: Database | None = None, **kw) -> YoutubeGate:
    cfg = YoutubeConfig(**{"min_interval_s": 0.0, "jitter_s": 0.0, **kw})
    return YoutubeGate(cfg, db, clock, lambda: 0.0)


def block(klass: str | None, retry_after: float | None = 300, reason: str = REASON_RATE_LIMITED):
    async def fn():
        raise YoutubeBlocked(reason, retry_after, klass)

    return fn


async def media_ok(started):
    started()
    return "audio"


async def fetch_ok():
    return "fetched"


async def test_a_caption_429_does_not_stop_audio_downloads():
    gate = make_gate(FakeClock())
    with pytest.raises(YoutubeBlocked):
        await gate.run(block(CLASS_CAPTIONS), classes=FETCH_CLASSES)
    assert not gate.healthy(CLASS_CAPTIONS)
    assert gate.healthy(CLASS_MEDIA) and gate.healthy(CLASS_METADATA)
    assert gate.state(CLASS_CAPTIONS) == STATE_OPEN and gate.state(CLASS_MEDIA) == STATE_CLOSED
    assert await gate.run_started(media_ok, INTERACTIVE) == "audio"
    assert gate.state(CLASS_MEDIA) == STATE_CLOSED


async def test_a_caption_fetch_is_refused_while_its_class_cools_but_metadata_alone_still_works():
    gate = make_gate(FakeClock())
    with pytest.raises(YoutubeBlocked):
        await gate.run(block(CLASS_CAPTIONS), classes=FETCH_CLASSES)
    with pytest.raises(YoutubeCooldown) as info:
        await gate.run(fetch_ok, INTERACTIVE, classes=FETCH_CLASSES)
    assert info.value.klass == CLASS_CAPTIONS and info.value.retry_after_s == pytest.approx(300)
    assert await gate.run(fetch_ok, INTERACTIVE, classes=(CLASS_METADATA,)) == "fetched"


async def test_a_media_429_leaves_captions_and_metadata_alone():
    gate = make_gate(FakeClock())

    async def refused(started):
        raise YoutubeBlocked(REASON_RATE_LIMITED, 600, CLASS_MEDIA)

    with pytest.raises(YoutubeBlocked):
        await gate.run_started(refused)
    assert not gate.healthy(CLASS_MEDIA)
    assert gate.healthy(*FETCH_CLASSES)
    assert await gate.run(fetch_ok, INTERACTIVE, classes=FETCH_CLASSES) == "fetched"
    with pytest.raises(YoutubeCooldown):
        await gate.run_started(media_ok, INTERACTIVE)


async def test_an_unattributed_block_opens_every_class_the_operation_needed_and_no_other():
    gate = make_gate(FakeClock())
    with pytest.raises(YoutubeBlocked):
        await gate.run(block(None), classes=FETCH_CLASSES)
    assert not gate.healthy(CLASS_METADATA) and not gate.healthy(CLASS_CAPTIONS)
    assert gate.healthy(CLASS_MEDIA)


async def test_a_bot_check_opens_both_yt_dlp_classes_but_not_the_caption_api():
    gate = make_gate(FakeClock())
    with pytest.raises(YoutubeBlocked):
        await gate.run(block(CLASS_METADATA, None, REASON_BOT_CHECK), classes=FETCH_CLASSES)
    assert not gate.healthy(CLASS_METADATA) and not gate.healthy(CLASS_MEDIA)
    assert gate.healthy(CLASS_CAPTIONS)


async def test_a_cooling_background_waiter_does_not_hold_up_another_class():
    clock = FakeClock()
    gate = make_gate(clock)
    with pytest.raises(YoutubeBlocked):
        await gate.run(block(CLASS_CAPTIONS, 300), classes=FETCH_CLASSES)
    waiting = asyncio.create_task(gate.run(fetch_ok, BACKGROUND, classes=FETCH_CLASSES))
    await settle()
    assert not waiting.done()
    assert await asyncio.wait_for(gate.run_started(media_ok, BACKGROUND), 5) == "audio"
    await clock.advance(301)
    assert await asyncio.wait_for(waiting, 5) == "fetched"
    assert gate.state(CLASS_CAPTIONS) == STATE_CLOSED


async def test_a_success_closes_only_the_classes_it_answered():
    clock = FakeClock()
    gate = make_gate(clock)
    gate.report_block(REASON_RATE_LIMITED, 60, FETCH_CLASSES)
    await clock.advance(61)
    assert gate.state(CLASS_CAPTIONS) == STATE_HALF_OPEN

    class Answer:
        answered = (CLASS_METADATA,)

    async def metadata_only():
        return Answer()

    await gate.run(metadata_only, classes=FETCH_CLASSES)
    assert gate.state(CLASS_METADATA) == STATE_CLOSED
    assert gate.state(CLASS_CAPTIONS) == STATE_HALF_OPEN
    await gate.run(fetch_ok, classes=FETCH_CLASSES)
    assert gate.state(CLASS_CAPTIONS) == STATE_CLOSED


async def test_a_per_video_error_closes_only_the_class_that_answered():
    clock = FakeClock()
    gate = make_gate(clock)
    gate.report_block(REASON_RATE_LIMITED, 60, FETCH_CLASSES)
    await clock.advance(61)

    async def private():
        raise YoutubeVideoError("private", CLASS_METADATA)

    with pytest.raises(YoutubeVideoError):
        await gate.run(private, classes=FETCH_CLASSES)
    assert gate.state(CLASS_METADATA) == STATE_CLOSED
    assert gate.state(CLASS_CAPTIONS) == STATE_HALF_OPEN


async def test_each_class_escalates_its_own_cooldown():
    clock = FakeClock()
    gate = make_gate(clock, cooldown_base_s=300.0)
    gate.report_block(REASON_RATE_LIMITED, None, CLASS_CAPTIONS)
    await clock.advance(301)
    gate.report_block(REASON_RATE_LIMITED, None, CLASS_CAPTIONS)
    assert gate.cooldown_remaining(CLASS_CAPTIONS) == pytest.approx(600)
    gate.report_block(REASON_RATE_LIMITED, None, CLASS_MEDIA)
    assert gate.cooldown_remaining(CLASS_MEDIA) == pytest.approx(300)


async def test_state_is_persisted_per_class_and_restored(tmp_path):
    clock = FakeClock()
    db = Database(tmp_path / "gate.sqlite")
    gate = make_gate(clock, db)
    gate.report_block(REASON_RATE_LIMITED, 900, CLASS_CAPTIONS)
    rows = {
        r["klass"]: (r["cooldown_until"], r["strikes"])
        for r in db.all("SELECT * FROM youtube_gate_class")
    }
    assert rows == {CLASS_CAPTIONS: (clock.now() + 900, 1)}

    again = make_gate(clock, db)
    assert again.cooldown_remaining(CLASS_CAPTIONS) == pytest.approx(900)
    assert again.healthy(CLASS_MEDIA) and again.healthy(CLASS_METADATA)
    assert again.state(CLASS_CAPTIONS) == STATE_OPEN
    await clock.advance(901)
    assert again.state(CLASS_CAPTIONS) == STATE_HALF_OPEN
    await again.run(fetch_ok, classes=(CLASS_CAPTIONS,))
    assert make_gate(clock, db).state(CLASS_CAPTIONS) == STATE_CLOSED


async def test_the_old_single_breaker_row_is_adopted_by_every_class_once(tmp_path):
    clock = FakeClock()
    db = Database(tmp_path / "gate.sqlite")
    db.execute(
        "INSERT INTO youtube_gate(id,cooldown_until,strikes) VALUES(1,?,2)", [clock.now() + 500]
    )
    gate = make_gate(clock, db)
    for name in CLASSES:
        assert gate.cooldown_remaining(name) == pytest.approx(500)
    assert db.one("SELECT COUNT(*) AS n FROM youtube_gate")["n"] == 0
    await clock.advance(501)
    await gate.run(fetch_ok, classes=CLASSES)
    assert make_gate(clock, db).healthy()
    assert make_gate(clock, db).state() == STATE_CLOSED


async def test_snapshot_reports_every_class_for_the_status_endpoint():
    gate = make_gate(FakeClock())
    gate.report_block(REASON_RATE_LIMITED, 120, CLASS_CAPTIONS)
    snap = gate.snapshot()
    assert set(snap) == set(CLASSES)
    assert snap[CLASS_CAPTIONS] == {"state": STATE_OPEN, "cooldown_remaining_s": 120, "strikes": 1}
    assert snap[CLASS_MEDIA] == {"state": STATE_CLOSED, "cooldown_remaining_s": 0, "strikes": 0}


def test_classifiers_tag_the_class_of_the_request_that_failed():
    blocked = classify_failure(Exception("HTTP Error 429: Too Many Requests"), 60.0)
    assert isinstance(blocked, YoutubeBlocked) and blocked.klass == CLASS_METADATA
    media = classify_failure(Exception("HTTP Error 429"), 60.0, media=True, klass=CLASS_MEDIA)
    assert isinstance(media, YoutubeBlocked) and media.klass == CLASS_MEDIA
    status = classify_status(429, 60.0, 30.0, media=True)
    assert isinstance(status, YoutubeBlocked) and status.klass == CLASS_CAPTIONS
    gone = classify_status(410, 60.0, None, media=True)
    assert isinstance(gone, YoutubeVideoError) and gone.klass == CLASS_CAPTIONS
    plain = classify_failure(Exception("boom"), 60.0)
    assert isinstance(plain, YoutubeError) and plain.klass is None


def test_class_groups_are_disjoint_where_it_matters():
    assert set(FETCH_CLASSES) == {CLASS_METADATA, CLASS_CAPTIONS}
    assert MEDIA_CLASSES == (CLASS_MEDIA,)


async def test_the_status_endpoint_reports_each_class_and_the_engine_chain(env):
    env.svc.gate.report_block(REASON_RATE_LIMITED, 120, CLASS_CAPTIONS)
    body = (await env.client.get("/v1/status")).json()
    classes = body["youtube"]["classes"]
    assert set(classes) == set(CLASSES)
    assert classes[CLASS_CAPTIONS]["state"] == STATE_OPEN
    assert classes[CLASS_CAPTIONS]["cooldown_remaining_s"] == 120
    assert classes[CLASS_MEDIA] == {"state": STATE_CLOSED, "cooldown_remaining_s": 0, "strikes": 0}
    assert body["youtube"]["state"] == STATE_OPEN and body["youtube"]["healthy"] is False
    (engine,) = body["asr"]["engines"]
    assert engine["name"] == "default" and engine["enabled"] and engine["healthy"]
    assert "url" not in engine and "api_key_env" not in engine
