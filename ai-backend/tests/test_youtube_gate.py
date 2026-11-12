from __future__ import annotations

import asyncio
import logging

import pytest

from tests.fakes import FakeClock, settle
from utubot.config import YoutubeConfig
from utubot.db import Database
from utubot.llm import BACKGROUND, INTERACTIVE
from utubot.youtube import (
    REASON_BOT_CHECK,
    REASON_FORBIDDEN,
    REASON_NETWORK,
    REASON_RATE_LIMITED,
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    YoutubeBlocked,
    YoutubeCooldown,
    YoutubeDelayed,
    YoutubeError,
    YoutubeGate,
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
    exc = classify_failure(RuntimeError(f"Video unavailable: {url}"), NETWORK_RETRY_S)
    assert type(exc) is YoutubeError
    assert "SECRET" not in str(exc) and "sig=" not in str(exc)
    assert redact_urls(f"see {url} now") == "see https://www.youtube.com/api/timedtext now"


def test_classify_status():
    assert isinstance(classify_status(429, NETWORK_RETRY_S, 30), YoutubeBlocked)
    assert classify_status(429, NETWORK_RETRY_S, 30).hint_s == 30
    assert isinstance(classify_status(403, NETWORK_RETRY_S, None), YoutubeBlocked)
    assert type(classify_status(503, NETWORK_RETRY_S, None)) is YoutubeDelayed
    assert classify_status(200, NETWORK_RETRY_S, None) is None
