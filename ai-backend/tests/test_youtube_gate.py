from __future__ import annotations

import asyncio
import logging

import pytest

from tests.fakes import FakeClock, settle
from utubot.config import YoutubeConfig
from utubot.db import Database
from utubot.llm import BACKGROUND, INTERACTIVE
from utubot.youtube import (
    REASON_AGE_RESTRICTED,
    REASON_BOT_CHECK,
    REASON_FORBIDDEN,
    REASON_FORBIDDEN_MEDIA,
    REASON_MEMBERS_ONLY,
    REASON_NETWORK,
    REASON_PRIVATE,
    REASON_RATE_LIMITED,
    REASON_UNAVAILABLE,
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    YoutubeBlocked,
    YoutubeCooldown,
    YoutubeDelayed,
    YoutubeError,
    YoutubeGate,
    YoutubeVideoError,
    classify_failure,
    classify_status,
    redact_urls,
)

NETWORK_RETRY_S = 60.0


def make_gate(clock: FakeClock, db: Database | None = None, rand=lambda: 0.0, **kw) -> YoutubeGate:
    cfg = YoutubeConfig(**{"min_interval_s": 3.0, "jitter_s": 0.0, **kw})
    return YoutubeGate(cfg, db, clock, rand)


def blocked(retry_after: float | None = None, reason: str = REASON_RATE_LIMITED):
    async def fn():
        raise YoutubeBlocked(reason, retry_after)

    return fn


async def ok():
    return "ok"


async def test_pacer_spaces_requests_by_min_interval():
    clock = FakeClock()
    gate = make_gate(clock)
    started: list[float] = []

    async def fn():
        started.append(clock.now())

    t0 = clock.now()
    tasks = [asyncio.create_task(gate.run(fn)) for _ in range(3)]
    await settle()
    assert started == [t0]
    await clock.advance(2.9)
    assert len(started) == 1
    await clock.advance(0.2)
    assert len(started) == 2
    await clock.advance(3.0)
    await asyncio.gather(*tasks)
    assert [round(b - a, 1) for a, b in zip(started, started[1:], strict=False)] == [3.0, 3.0]


async def test_pacer_adds_jitter_to_the_gap():
    clock = FakeClock()
    gate = make_gate(clock, rand=lambda: 0.5, jitter_s=2.0)
    started: list[float] = []

    async def fn():
        started.append(clock.now())

    tasks = [asyncio.create_task(gate.run(fn)) for _ in range(2)]
    await settle()
    await clock.advance(3.9)
    assert len(started) == 1
    await clock.advance(0.2)
    await asyncio.gather(*tasks)
    assert started[1] - started[0] == pytest.approx(4.0)


@pytest.mark.parametrize(("limit", "expected"), [(1, 1), (2, 2)])
async def test_concurrency_defaults_to_one_and_is_configurable(limit, expected):
    gate = make_gate(FakeClock(), min_interval_s=0.0, max_concurrent=limit)
    release = asyncio.Event()
    running = 0
    peak = 0

    async def fn():
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await release.wait()
        running -= 1

    tasks = [asyncio.create_task(gate.run(fn)) for _ in range(4)]
    await settle()
    assert peak == expected
    release.set()
    await asyncio.gather(*tasks)
    assert YoutubeConfig().max_concurrent == 1


async def test_interactive_goes_before_background():
    clock = FakeClock()
    gate = make_gate(clock, min_interval_s=0.0)
    order: list[str] = []
    hold = asyncio.Event()

    async def holder():
        await hold.wait()

    def named(label):
        async def fn():
            order.append(label)

        return fn

    first = asyncio.create_task(gate.run(holder))
    await settle()
    bg1 = asyncio.create_task(gate.run(named("bg1"), BACKGROUND))
    bg2 = asyncio.create_task(gate.run(named("bg2"), BACKGROUND))
    await settle()
    ui = asyncio.create_task(gate.run(named("ui"), INTERACTIVE))
    await settle()
    hold.set()
    await asyncio.gather(first, bg1, bg2, ui)
    assert order == ["ui", "bg1", "bg2"]


async def test_interactive_waiter_beats_background_during_spacing():
    clock = FakeClock()
    gate = make_gate(clock)
    order: list[str] = []

    def named(label):
        async def fn():
            order.append(label)

        return fn

    await gate.run(named("first"))
    bg = asyncio.create_task(gate.run(named("bg"), BACKGROUND))
    await settle()
    ui = asyncio.create_task(gate.run(named("ui"), INTERACTIVE))
    await settle()
    await clock.advance(10)
    await asyncio.gather(bg, ui)
    assert order == ["first", "ui", "bg"]


async def test_promote_moves_a_queued_background_fetch_to_interactive():
    clock = FakeClock()
    gate = make_gate(clock, min_interval_s=0.0)
    order: list[str] = []
    hold = asyncio.Event()

    async def holder():
        await hold.wait()

    def named(label):
        async def fn():
            order.append(label)

        return fn

    first = asyncio.create_task(gate.run(holder))
    await settle()
    a = asyncio.create_task(gate.run(named("a"), BACKGROUND, key="a"))
    b = asyncio.create_task(gate.run(named("b"), BACKGROUND, key="b"))
    await settle()
    assert gate.background_waiting() == 2
    gate.promote("b")
    await settle()
    assert gate.background_waiting() == 1
    hold.set()
    await asyncio.gather(first, a, b)
    assert order == ["b", "a"]


async def test_breaker_honours_retry_after_and_answers_interactive_at_once():
    clock = FakeClock()
    gate = make_gate(clock)
    with pytest.raises(YoutubeBlocked) as info:
        await gate.run(blocked(120))
    assert info.value.retry_after_s == pytest.approx(120)
    assert gate.state() == STATE_OPEN and not gate.healthy()
    calls = []

    async def fn():
        calls.append(1)

    with pytest.raises(YoutubeCooldown) as cool:
        await gate.run(fn, INTERACTIVE)
    assert cool.value.retry_after_s == pytest.approx(120)
    assert calls == []
    await clock.advance(60)
    with pytest.raises(YoutubeCooldown) as cool:
        await gate.run(fn, INTERACTIVE)
    assert cool.value.retry_after_s == pytest.approx(60)


async def test_breaker_exponential_cooldown_5_to_60_minutes_and_reset_on_success():
    clock = FakeClock()
    gate = make_gate(clock, min_interval_s=0.0)
    seen = []
    for _ in range(6):
        with pytest.raises(YoutubeBlocked) as info:
            await gate.run(blocked())
        seen.append(info.value.retry_after_s)
        await clock.advance(info.value.retry_after_s + 1)
        assert gate.state() == STATE_HALF_OPEN and gate.healthy()
    assert seen == pytest.approx([300, 600, 1200, 2400, 3600, 3600])
    assert await gate.run(ok) == "ok"
    assert gate.state() == STATE_CLOSED
    with pytest.raises(YoutubeBlocked) as info:
        await gate.run(blocked())
    assert info.value.retry_after_s == pytest.approx(300)


async def test_breaker_caps_a_huge_retry_after():
    gate = make_gate(FakeClock())
    with pytest.raises(YoutubeBlocked) as info:
        await gate.run(blocked(86400))
    assert info.value.retry_after_s == pytest.approx(3600)


async def test_background_is_paused_not_failed_while_open_then_resumes():
    clock = FakeClock()
    gate = make_gate(clock)
    with pytest.raises(YoutubeBlocked):
        await gate.run(blocked(300))
    calls = []

    async def fn():
        calls.append(clock.now())
        return "done"

    bg = asyncio.create_task(gate.run(fn, BACKGROUND))
    await settle()
    await clock.advance(299)
    assert not bg.done() and calls == []
    await clock.advance(2)
    assert await bg == "done"
    assert len(calls) == 1
    assert gate.state() == STATE_CLOSED


async def test_a_background_waiter_does_not_block_interactive_during_cooldown():
    clock = FakeClock()
    gate = make_gate(clock)
    with pytest.raises(YoutubeBlocked):
        await gate.run(blocked(300))
    bg = asyncio.create_task(gate.run(ok, BACKGROUND))
    await settle()
    with pytest.raises(YoutubeCooldown):
        await gate.run(ok, INTERACTIVE)
    assert not bg.done()
    await clock.advance(301)
    assert await bg == "ok"


async def test_queued_interactive_gets_cooldown_when_the_running_request_is_blocked():
    clock = FakeClock()
    gate = make_gate(clock, min_interval_s=0.0)
    release = asyncio.Event()

    async def first():
        await release.wait()
        raise YoutubeBlocked(REASON_BOT_CHECK, None)

    t1 = asyncio.create_task(gate.run(first))
    await settle()
    t2 = asyncio.create_task(gate.run(ok, INTERACTIVE))
    await settle()
    release.set()
    with pytest.raises(YoutubeBlocked):
        await t1
    with pytest.raises(YoutubeCooldown):
        await t2


async def test_network_errors_do_not_open_the_breaker():
    gate = make_gate(FakeClock())

    async def fn():
        raise YoutubeDelayed(REASON_NETWORK, NETWORK_RETRY_S)

    with pytest.raises(YoutubeDelayed):
        await gate.run(fn)
    assert gate.state() == STATE_CLOSED and gate.healthy()


async def test_breaker_state_survives_a_restart(tmp_path):
    clock = FakeClock()
    db = Database(tmp_path / "gate.sqlite")
    with pytest.raises(YoutubeBlocked):
        await make_gate(clock, db).run(blocked(600))
    again = make_gate(clock, db)
    assert again.state() == STATE_OPEN
    assert again.cooldown_remaining() == pytest.approx(600)
    await clock.advance(601)
    assert again.state() == STATE_HALF_OPEN
    await again.run(ok)
    assert make_gate(clock, db).state() == STATE_CLOSED


async def test_state_transitions_are_logged_without_urls(caplog):
    caplog.set_level(logging.INFO, logger="utubot.youtube")
    clock = FakeClock()
    gate = make_gate(clock)
    with pytest.raises(YoutubeBlocked):
        await gate.run(blocked(300))
    await clock.advance(301)
    await gate.run(ok)
    text = caplog.text
    assert "youtube gate open" in text and "reason=rate_limited" in text
    assert "half-open" in text and "gate closed" in text
    assert "http" not in text and "sig=" not in text


def test_classify_bot_check_rate_limit_forbidden_and_network():
    bot = classify_failure(
        RuntimeError("ERROR: [youtube] abc: Sign in to confirm you’re not a bot"), NETWORK_RETRY_S
    )
    assert isinstance(bot, YoutubeBlocked) and bot.reason == REASON_BOT_CHECK
    ascii_bot = classify_failure(
        RuntimeError("Sign in to confirm you're not a bot. Use --cookies"), NETWORK_RETRY_S
    )
    assert isinstance(ascii_bot, YoutubeBlocked)
    limited = classify_failure(RuntimeError("HTTP Error 429: Too Many Requests"), NETWORK_RETRY_S)
    assert isinstance(limited, YoutubeBlocked) and limited.reason == REASON_RATE_LIMITED
    forbidden = classify_failure(RuntimeError("HTTP Error 403: Forbidden"), NETWORK_RETRY_S)
    assert isinstance(forbidden, YoutubeBlocked) and forbidden.reason == REASON_FORBIDDEN
    net = classify_failure(TimeoutError("read timed out"), NETWORK_RETRY_S)
    assert isinstance(net, YoutubeDelayed) and not isinstance(net, YoutubeBlocked)
    assert net.retry_after_s == NETWORK_RETRY_S


def test_classify_other_failures_are_sanitised():
    url = "https://www.youtube.com/api/timedtext?v=abcdefghijk&sig=SECRET&expire=1"
    exc = classify_failure(RuntimeError(f"Something odd happened: {url}"), NETWORK_RETRY_S)
    assert type(exc) is YoutubeError
    assert "SECRET" not in str(exc) and "sig=" not in str(exc)
    assert redact_urls(f"see {url} now") == "see https://www.youtube.com/api/timedtext now"


def test_classify_status():
    assert isinstance(classify_status(429, NETWORK_RETRY_S, 30), YoutubeBlocked)
    assert classify_status(429, NETWORK_RETRY_S, 30).hint_s == 30
    assert isinstance(classify_status(403, NETWORK_RETRY_S, None), YoutubeBlocked)
    assert type(classify_status(503, NETWORK_RETRY_S, None)) is YoutubeDelayed
    assert classify_status(200, NETWORK_RETRY_S, None) is None


# ---- review fixes: scoped breaker, media start gating -------------------------------------------


def test_only_gate_level_signals_open_the_breaker():
    bot = classify_failure(RuntimeError("Sign in to confirm you're not a bot"), NETWORK_RETRY_S)
    assert isinstance(bot, YoutubeBlocked)
    for media in (False, True):
        assert isinstance(
            classify_failure(RuntimeError("HTTP Error 429: Too Many Requests"), 60, media=media),
            YoutubeBlocked,
        )
    watch = "ERROR: [youtube] abc: Unable to download webpage: HTTP Error 403: Forbidden"
    assert isinstance(classify_failure(RuntimeError(watch), 60), YoutubeBlocked)
    assert isinstance(classify_failure(RuntimeError(watch), 60, media=True), YoutubeBlocked)
    api = "ERROR: [youtube] abc: Unable to download API page: HTTP Error 403: Forbidden"
    assert isinstance(classify_failure(RuntimeError(api), 60, media=True), YoutubeBlocked)


def test_403_and_410_on_media_or_caption_urls_belong_to_the_video():
    media = "ERROR: unable to download video data: HTTP Error 403: Forbidden"
    err = classify_failure(RuntimeError(media), 60, media=True)
    assert isinstance(err, YoutubeVideoError) and err.reason == REASON_FORBIDDEN_MEDIA
    assert err.can_transcribe is True
    gone = classify_failure(RuntimeError("HTTP Error 410: Gone"), 60)
    assert isinstance(gone, YoutubeVideoError) and gone.reason == REASON_UNAVAILABLE
    forbidden = classify_status(403, 60, None, media=True)
    assert isinstance(forbidden, YoutubeVideoError) and forbidden.reason == REASON_FORBIDDEN_MEDIA
    assert isinstance(classify_status(403, 60, None), YoutubeBlocked)
    assert isinstance(classify_status(410, 60, None, media=True), YoutubeVideoError)
    assert isinstance(classify_status(429, 60, 5, media=True), YoutubeBlocked)


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("Join this channel to get access to members-only content", REASON_MEMBERS_ONLY),
        ("Sign in to confirm your age. This video may be inappropriate", REASON_AGE_RESTRICTED),
        (
            "ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
            REASON_PRIVATE,
        ),
        ("ERROR: [youtube] abc: Video unavailable", REASON_UNAVAILABLE),
        ("This video has been removed by the uploader", REASON_UNAVAILABLE),
    ],
)
def test_private_members_only_age_gated_and_unavailable_are_per_video(text, reason):
    err = classify_failure(RuntimeError(text), NETWORK_RETRY_S)
    assert isinstance(err, YoutubeVideoError) and err.reason == reason
    assert err.can_transcribe is False and err.message


def test_a_bare_try_again_later_is_not_a_rate_limit():
    err = classify_failure(RuntimeError("Something failed, please try again later"), 60)
    assert type(err) is YoutubeError
    limited = classify_failure(
        RuntimeError(
            "This content isn't available, try again later. The current session has been "
            "rate-limited by YouTube for up to an hour"
        ),
        60,
    )
    assert isinstance(limited, YoutubeBlocked)


async def test_a_per_video_error_never_opens_the_breaker_and_counts_as_a_live_answer():
    clock = FakeClock()
    gate = make_gate(clock, min_interval_s=0.0)

    async def private():
        raise YoutubeVideoError(REASON_PRIVATE)

    for _ in range(5):
        with pytest.raises(YoutubeVideoError):
            await gate.run(private)
    assert gate.state() == STATE_CLOSED and gate.healthy()
    with pytest.raises(YoutubeBlocked):
        await gate.run(blocked())
    await clock.advance(301)
    with pytest.raises(YoutubeVideoError):
        await gate.run(private)
    assert gate.state() == STATE_CLOSED
    with pytest.raises(YoutubeBlocked) as again:
        await gate.run(blocked())
    assert again.value.retry_after_s == pytest.approx(300)


async def test_media_download_holds_the_slot_only_until_it_starts():
    clock = FakeClock()
    gate = make_gate(clock)
    release = asyncio.Event()
    events: list[str] = []

    async def download(started):
        events.append("start")
        started()
        await release.wait()
        events.append("done")
        return "audio"

    media = asyncio.create_task(gate.run_started(download, BACKGROUND))
    await settle()
    assert events == ["start"] and not media.done()
    ui = asyncio.create_task(gate.run(ok, INTERACTIVE))
    await settle()
    assert not ui.done()
    await clock.advance(2.9)
    assert not ui.done()
    await clock.advance(0.2)
    assert await ui == "ok"
    assert not media.done()
    release.set()
    assert await media == "audio" and events == ["start", "done"]


async def test_media_start_is_still_paced_and_prioritised():
    clock = FakeClock()
    gate = make_gate(clock)
    order: list[str] = []

    async def meta():
        order.append("meta")

    async def download(started):
        order.append("media")
        started()
        return "audio"

    await gate.run(meta)
    bg = asyncio.create_task(gate.run_started(download, BACKGROUND))
    await settle()
    assert order == ["meta"]
    await clock.advance(3.1)
    await bg
    assert order == ["meta", "media"]


async def test_media_download_without_a_start_signal_releases_when_it_finishes():
    gate = make_gate(FakeClock(), min_interval_s=0.0)

    async def download(started):
        return "audio"

    assert await gate.run_started(download) == "audio"
    assert await gate.run(ok) == "ok"


async def test_media_download_blocked_before_or_after_start_opens_the_breaker():
    for after_start in (False, True):
        gate = make_gate(FakeClock(), min_interval_s=0.0)

        async def download(started, after_start=after_start):
            if after_start:
                started()
                await asyncio.sleep(0)
            raise YoutubeBlocked(REASON_RATE_LIMITED, 120)

        with pytest.raises(YoutubeBlocked) as info:
            await gate.run_started(download)
        assert info.value.retry_after_s == pytest.approx(120)
        assert gate.state() == STATE_OPEN


async def test_media_download_is_refused_by_an_open_breaker_before_it_starts():
    clock = FakeClock()
    gate = make_gate(clock)
    with pytest.raises(YoutubeBlocked):
        await gate.run(blocked(300))
    ran: list[int] = []

    async def download(started):
        ran.append(1)
        return "audio"

    with pytest.raises(YoutubeCooldown):
        await gate.run_started(download, INTERACTIVE)
    assert ran == []


async def test_cancelling_a_media_download_cancels_the_transfer():
    gate = make_gate(FakeClock(), min_interval_s=0.0)
    cancelled = asyncio.Event()

    async def download(started):
        started()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = asyncio.create_task(gate.run_started(download))
    await settle()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await settle()
    assert cancelled.is_set()
