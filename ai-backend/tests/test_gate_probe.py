"""The caption class after a cooldown: one background probe, no interactive requests, capped escalation."""

from __future__ import annotations

import asyncio

import pytest

from tests.fakes import FakeClock, settle
from utubot.config import YoutubeConfig
from utubot.llm import BACKGROUND, INTERACTIVE
from utubot.youtube import (
    CLASS_CAPTIONS,
    CLASS_MEDIA,
    CLASS_METADATA,
    FETCH_CLASSES,
    REASON_RATE_LIMITED,
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    YoutubeBlocked,
    YoutubeCooldown,
    YoutubeGate,
)

COOLDOWN_S = 300
PROBE_RETRY_S = 10.0
CAPTIONS_CAP_S = 1800.0
GENERAL_CAP_S = 3600.0


def make_gate(clock: FakeClock, **kw) -> YoutubeGate:
    cfg = YoutubeConfig(
        **{
            "min_interval_s": 0.0,
            "jitter_s": 0.0,
            "captions_probe_retry_s": PROBE_RETRY_S,
            **kw,
        }
    )
    return YoutubeGate(cfg, None, clock, lambda: 0.0)


async def half_open(clock: FakeClock, **kw) -> YoutubeGate:
    gate = make_gate(clock, **kw)
    gate.report_block(REASON_RATE_LIMITED, COOLDOWN_S, FETCH_CLASSES)
    await clock.advance(COOLDOWN_S + 1)
    assert gate.state(CLASS_CAPTIONS) == STATE_HALF_OPEN
    return gate


async def ok():
    return "ok"


def blocked(klass: str | None = CLASS_CAPTIONS, hint: float | None = COOLDOWN_S):
    async def fn():
        raise YoutubeBlocked(REASON_RATE_LIMITED, hint, klass)

    return fn


async def test_an_interactive_request_never_probes_a_half_open_caption_class():
    clock = FakeClock()
    gate = await half_open(clock)
    assert gate.healthy(CLASS_CAPTIONS) and not gate.interactive_ok(CLASS_CAPTIONS)
    assert gate.interactive_ok(CLASS_METADATA) and gate.interactive_ok(CLASS_MEDIA)
    calls: list[int] = []

    async def fn():
        calls.append(1)
        return "sent"

    with pytest.raises(YoutubeCooldown) as info:
        await gate.run(fn, INTERACTIVE, classes=FETCH_CLASSES)
    assert info.value.klass == CLASS_CAPTIONS and info.value.retry_after_s == PROBE_RETRY_S
    assert calls == []
    assert await gate.run(fn, INTERACTIVE, classes=(CLASS_METADATA,)) == "sent"
    assert calls == [1]


async def test_an_interactive_request_is_refused_while_the_class_cools_too():
    clock = FakeClock()
    gate = make_gate(clock)
    gate.report_block(REASON_RATE_LIMITED, COOLDOWN_S, CLASS_CAPTIONS)
    assert not gate.interactive_ok(CLASS_CAPTIONS) and not gate.interactive_ok()
    with pytest.raises(YoutubeCooldown) as info:
        await gate.run(ok, INTERACTIVE, classes=FETCH_CLASSES)
    assert info.value.retry_after_s == pytest.approx(COOLDOWN_S)
    assert gate.interactive_ok(CLASS_METADATA)


async def test_exactly_one_background_request_probes_and_the_others_wait_for_it():
    clock = FakeClock()
    gate = await half_open(clock)
    release = asyncio.Event()
    started: list[str] = []

    async def slow(name: str):
        started.append(name)
        await release.wait()
        return name

    first = asyncio.create_task(gate.run(lambda: slow("a"), BACKGROUND, classes=FETCH_CLASSES))
    second = asyncio.create_task(gate.run(lambda: slow("b"), BACKGROUND, classes=FETCH_CLASSES))
    third = asyncio.create_task(gate.run(lambda: slow("c"), BACKGROUND, classes=FETCH_CLASSES))
    await settle()
    assert started == ["a"] and not second.done() and not third.done()
    release.set()
    assert await first == "a"
    assert await asyncio.wait_for(second, 5) == "b" and await asyncio.wait_for(third, 5) == "c"
    assert started == ["a", "b", "c"]
    assert gate.state(CLASS_CAPTIONS) == STATE_CLOSED and gate.interactive_ok(CLASS_CAPTIONS)


async def test_a_failed_probe_cools_the_class_again_and_the_waiting_ones_stay_paused():
    clock = FakeClock()
    gate = await half_open(clock)
    release = asyncio.Event()
    sent: list[str] = []

    async def probe():
        await release.wait()
        raise YoutubeBlocked(REASON_RATE_LIMITED, None, CLASS_CAPTIONS)

    async def other():
        sent.append("other")
        return "other"

    first = asyncio.create_task(gate.run(probe, BACKGROUND, classes=FETCH_CLASSES))
    waiting = asyncio.create_task(gate.run(other, BACKGROUND, classes=FETCH_CLASSES))
    await settle()
    release.set()
    with pytest.raises(YoutubeBlocked):
        await first
    await settle()
    assert not waiting.done() and sent == []
    assert gate.state(CLASS_CAPTIONS) == STATE_OPEN
    assert gate.cooldown_remaining(CLASS_CAPTIONS) == pytest.approx(2 * COOLDOWN_S)
    await clock.advance(2 * COOLDOWN_S + 1)
    assert await asyncio.wait_for(waiting, 5) == "other"
    assert sent == ["other"] and gate.state(CLASS_CAPTIONS) == STATE_CLOSED


async def test_a_probe_that_only_met_the_metadata_class_leaves_the_caption_class_half_open():
    clock = FakeClock()
    gate = await half_open(clock)

    class MetadataOnly:
        answered = (CLASS_METADATA,)

    async def no_captions():
        return MetadataOnly()

    await gate.run(no_captions, BACKGROUND, classes=FETCH_CLASSES)
    assert gate.state(CLASS_METADATA) == STATE_CLOSED
    assert gate.state(CLASS_CAPTIONS) == STATE_HALF_OPEN
    assert not gate.interactive_ok(CLASS_CAPTIONS) and gate.probe_pending()
    assert await gate.run(ok, BACKGROUND, classes=FETCH_CLASSES) == "ok"
    assert not gate.probe_pending() and gate.interactive_ok(CLASS_CAPTIONS)


async def test_a_probe_that_ends_in_a_network_error_frees_the_slot_for_the_next_one():
    clock = FakeClock()
    gate = await half_open(clock)

    async def broken():
        raise RuntimeError("connection reset")

    with pytest.raises(RuntimeError):
        await gate.run(broken, BACKGROUND, classes=FETCH_CLASSES)
    assert gate.state(CLASS_CAPTIONS) == STATE_HALF_OPEN
    assert await asyncio.wait_for(gate.run(ok, BACKGROUND, classes=FETCH_CLASSES), 5) == "ok"
    assert gate.state(CLASS_CAPTIONS) == STATE_CLOSED


async def test_a_cancelled_probe_frees_the_slot():
    clock = FakeClock()
    gate = await half_open(clock)
    hold = asyncio.Event()

    async def stuck():
        await hold.wait()

    probe = asyncio.create_task(gate.run(stuck, BACKGROUND, classes=FETCH_CLASSES))
    await settle()
    probe.cancel()
    with pytest.raises(asyncio.CancelledError):
        await probe
    assert await asyncio.wait_for(gate.run(ok, BACKGROUND, classes=FETCH_CLASSES), 5) == "ok"


async def test_promoting_a_probe_does_not_make_it_interactive():
    clock = FakeClock()
    gate = await half_open(clock)
    release = asyncio.Event()

    async def slow():
        await release.wait()
        return "done"

    probe = asyncio.create_task(gate.run(slow, BACKGROUND, key="v", classes=FETCH_CLASSES))
    await settle()
    waiting = asyncio.create_task(gate.run(slow, BACKGROUND, key="w", classes=FETCH_CLASSES))
    await settle()
    gate.promote("w")
    await settle()
    assert gate.background_waiting() == 1 and not waiting.done()
    release.set()
    assert await probe == "done" and await asyncio.wait_for(waiting, 5) == "done"


async def test_the_caption_cooldown_escalates_to_the_configured_cap_and_no_further():
    clock = FakeClock()
    gate = make_gate(clock)
    seen = []
    for _ in range(6):
        with pytest.raises(YoutubeBlocked) as info:
            await gate.run(blocked(CLASS_CAPTIONS, None), BACKGROUND, classes=(CLASS_CAPTIONS,))
        seen.append(info.value.retry_after_s)
        await clock.advance(info.value.retry_after_s + 1)
    assert seen == pytest.approx([300, 600, 1200, CAPTIONS_CAP_S, CAPTIONS_CAP_S, CAPTIONS_CAP_S])


async def test_a_long_retry_after_is_capped_for_captions_but_not_for_the_other_classes():
    gate = make_gate(FakeClock())
    gate.report_block(REASON_RATE_LIMITED, 7200, CLASS_CAPTIONS)
    gate.report_block(REASON_RATE_LIMITED, 7200, CLASS_METADATA)
    assert gate.cooldown_remaining(CLASS_CAPTIONS) == pytest.approx(CAPTIONS_CAP_S)
    assert gate.cooldown_remaining(CLASS_METADATA) == pytest.approx(GENERAL_CAP_S)


async def test_the_caption_cap_is_a_config_value():
    gate = make_gate(FakeClock(), captions_cooldown_max_s=900.0)
    gate.report_block(REASON_RATE_LIMITED, 7200, CLASS_CAPTIONS)
    assert gate.cooldown_remaining(CLASS_CAPTIONS) == pytest.approx(900)
    assert YoutubeConfig().captions_cooldown_max_s == CAPTIONS_CAP_S
    assert (
        make_gate(FakeClock(), cooldown_max_s=600.0).cfg.captions_cooldown_max_s == CAPTIONS_CAP_S
    )


async def test_the_general_ceiling_still_wins_over_a_higher_caption_cap():
    gate = make_gate(FakeClock(), cooldown_max_s=600.0, captions_cooldown_max_s=5000.0)
    gate.report_block(REASON_RATE_LIMITED, 7200, CLASS_CAPTIONS)
    assert gate.cooldown_remaining(CLASS_CAPTIONS) == pytest.approx(600)


async def test_the_probe_state_is_not_a_cooldown_for_the_other_classes():
    clock = FakeClock()
    gate = await half_open(clock)
    assert gate.healthy() and gate.state() == STATE_HALF_OPEN
    assert gate.interactive_ok(CLASS_MEDIA) and gate.interactive_ok(CLASS_METADATA)
    assert gate.probe_pending()
    await gate.run(ok, BACKGROUND, classes=FETCH_CLASSES)
    assert not gate.probe_pending()
