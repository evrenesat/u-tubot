from __future__ import annotations

import asyncio

import httpx
import pytest

from tests.mock_openai import MockOpenAI
from tests.test_prompts_summary import VID
from utubot.config import Config, LLMTask, ProviderConfig
from utubot.errors import MSG_BUSY
from utubot.llm import BACKGROUND, INTERACTIVE, LLMBusyError, LLMClient, LLMError, PriorityLimiter


def vid(i, title):
    return {"video_id": f"vid{i:08d}", "title": title}


@pytest.fixture
def client(cfg: Config, mock_llm: MockOpenAI):
    cfg.llm.retry_base_s = 0.01
    cfg.llm.retry_max_s = 0.05
    llm = LLMClient(cfg, transport=httpx.ASGITransport(app=mock_llm.app))
    yield llm


MSGS = [{"role": "user", "content": "hello"}]
TASK = LLMTask(model="worker")


async def test_limiter_interactive_goes_first():
    lim = PriorityLimiter(1)
    await lim.acquire(BACKGROUND)
    order: list[str] = []

    async def take(name: str, prio: int) -> None:
        await lim.acquire(prio)
        order.append(name)
        lim.release()

    bg = [asyncio.create_task(take(f"bg{i}", BACKGROUND)) for i in range(3)]
    await asyncio.sleep(0)
    fg = asyncio.create_task(take("fg", INTERACTIVE))
    await asyncio.sleep(0)
    lim.release()
    await asyncio.gather(*bg, fg)
    assert order[0] == "fg"


async def test_limiter_reserves_slot_for_interactive():
    lim = PriorityLimiter(2, reserve=1)
    await lim.acquire(BACKGROUND)
    blocked = asyncio.create_task(lim.acquire(BACKGROUND))
    await asyncio.sleep(0.01)
    assert not blocked.done()
    await asyncio.wait_for(lim.acquire(INTERACTIVE), 0.1)
    blocked.cancel()


async def test_limiter_cancel_does_not_leak_slot():
    lim = PriorityLimiter(1)
    await lim.acquire(BACKGROUND)
    waiter = asyncio.create_task(lim.acquire(BACKGROUND))
    await asyncio.sleep(0)
    waiter.cancel()
    lim.release()
    await asyncio.wait_for(lim.acquire(BACKGROUND), 0.1)


async def test_background_saturation_does_not_block_interactive(client, mock_llm, cfg):
    cfg.llm.providers["default"].max_concurrent = 2
    mock_llm.delay_s = 0.3
    loop = asyncio.get_running_loop()
    bg = [asyncio.create_task(client.chat(TASK, MSGS, priority=BACKGROUND)) for _ in range(6)]
    await asyncio.sleep(0.05)
    started = loop.time()
    await client.chat(TASK, MSGS, priority=INTERACTIVE)
    assert loop.time() - started < 0.5
    await asyncio.gather(*bg)
    assert mock_llm.max_active <= 2


async def test_retry_after_503_then_success(client, mock_llm):
    mock_llm.busy_first = 2
    mock_llm.retry_after = "0"
    text = await client.chat(TASK, MSGS, priority=INTERACTIVE)
    assert text.startswith("SUMMARY")
    assert len(mock_llm.calls) == 3


async def test_retry_after_http_date_and_429(client, mock_llm):
    mock_llm.busy_first = 1
    mock_llm.busy_status = 429
    mock_llm.retry_after = "Wed, 21 Oct 2015 07:28:00 GMT"
    await client.chat(TASK, MSGS)
    assert len(mock_llm.calls) == 2


async def test_busy_exhausts_attempts(client, mock_llm, cfg):
    mock_llm.busy_first = 99
    cfg.llm.retry_max_attempts = 3
    with pytest.raises(LLMBusyError):
        await client.chat(TASK, MSGS)
    assert len(mock_llm.calls) == 3


async def test_deadline_bounds_retries(client, mock_llm, cfg):
    mock_llm.busy_first = 99
    cfg.llm.retry_max_attempts = 50
    mock_llm.retry_after = "30"
    with pytest.raises(LLMBusyError):
        await client.chat(TASK, MSGS, priority=INTERACTIVE, deadline_s=0.2)
    assert len(mock_llm.calls) == 1


async def test_no_retry_on_400(client, mock_llm):
    mock_llm.fail_status = 400
    with pytest.raises(LLMError) as exc:
        await client.chat(TASK, MSGS)
    assert not isinstance(exc.value, LLMBusyError) and not exc.value.failover
    assert len(mock_llm.calls) == 1


async def test_no_fallback_on_400(client, mock_llm):
    mock_llm.fail_status = 400
    task = LLMTask(model="worker", fallback=["other"])
    with pytest.raises(LLMError):
        await client.chat(task, MSGS)
    assert len(mock_llm.calls) == 1


async def test_fallback_after_busy(client, mock_llm, cfg):
    cfg.llm.retry_max_attempts = 2
    mock_llm.busy_models = {"worker"}
    task = LLMTask(model="worker", fallback=["default:backup"])
    text = await client.chat(task, MSGS, priority=INTERACTIVE)
    assert "SUMMARY[backup]" in text
    assert [c["model"] for c in mock_llm.calls] == ["worker", "worker", "backup"]


async def test_fallback_after_prompt_override(client, mock_llm, cfg):
    cfg.llm.retry_max_attempts = 1
    mock_llm.busy_models = {"custom"}
    task = LLMTask(model="worker", fallback=["backup"])
    text = await client.chat(task, MSGS, model="custom")
    assert "SUMMARY[backup]" in text


async def test_fallback_other_provider(client, mock_llm, cfg):
    cfg.llm.providers["cloud"] = ProviderConfig(base_url="http://mock/v1")
    cfg.llm.retry_max_attempts = 1
    mock_llm.busy_models = {"worker"}
    task = LLMTask(model="worker", fallback=["cloud:big"])
    text = await client.chat(task, MSGS)
    assert "SUMMARY[big]" in text


async def test_all_models_busy_raises_busy(client, mock_llm, cfg):
    cfg.llm.retry_max_attempts = 1
    mock_llm.busy_models = {"worker", "backup"}
    task = LLMTask(model="worker", fallback=["backup"])
    with pytest.raises(LLMBusyError):
        await client.chat(task, MSGS)


async def test_json_mode_flag(client, mock_llm, cfg):
    cfg.llm.providers["default"].json_mode = True
    mock_llm.bad_json_first = 0
    await client.chat_json(
        TASK,
        [
            {"role": "system", "content": "analyse a YouTube video from its transcript"},
            {"role": "user", "content": "t"},
        ],
    )
    assert mock_llm.calls[-1]["response_format"] == {"type": "json_object"}
    await client.chat(TASK, MSGS)
    assert "response_format" not in mock_llm.calls[-1]
    cfg.llm.providers["default"].json_mode = False
    await client.chat_json(
        TASK,
        [
            {"role": "system", "content": "analyse a YouTube video from its transcript"},
            {"role": "user", "content": "t"},
        ],
    )
    assert "response_format" not in mock_llm.calls[-1]


async def test_json_empty_content_retries_with_more_tokens(client, mock_llm, cfg):
    mock_llm.empty_first = 1
    cfg.llm.json_retry_max_tokens = 4321
    data = await client.chat_json(
        TASK,
        [
            {"role": "system", "content": "analyse a YouTube video from its transcript"},
            {"role": "user", "content": "t"},
        ],
    )
    assert data["answer_short"]
    first, second = mock_llm.calls
    assert (
        second["max_tokens"] == 4321 + cfg.llm.reasoning_headroom_tokens
        and second["max_tokens"] > first["max_tokens"]
    )
    assert "JSON only" in second["messages"][-1]["content"]


async def test_json_empty_twice_fails_and_is_not_parsed_from_reasoning(client, mock_llm):
    mock_llm.empty_first = 5
    with pytest.raises(LLMError, match="empty"):
        await client.chat_json(TASK, MSGS)
    assert len(mock_llm.calls) == 2


async def test_truncated_kind_reported(client, mock_llm):
    mock_llm.empty_first = 5
    mock_llm.finish_reason = "length"
    with pytest.raises(LLMError, match="truncated"):
        await client.chat_json(TASK, MSGS)


async def test_busy_surfaces_distinct_user_error(env):
    env.cfg.llm.retry_max_attempts = 1
    env.llm.busy_first = 99
    r = await env.client.post(
        "/v1/videos/abcdefghijk/ask", json={"question": "why?", "wait_ms": 3000}
    )
    body = r.json()
    assert body["status"] == "failed" and body["error"] == MSG_BUSY
    assert "engine" not in body["error"]


async def test_assess_coalesces_across_requests(env):
    env.cfg.assess.coalesce_ms = 200
    reqs = [
        env.client.post(
            "/v1/assess",
            json={"videos": [vid(i, f"Title {i}"), vid(i + 100, "x")], "wait_ms": 2500},
        )
        for i in range(10)
    ]
    results = await asyncio.gather(*reqs)
    assert all(r.json()["results"][0]["status"] == "ready" for r in results)
    triage = [c for c in env.llm.calls if "triage YouTube" in c["messages"][0]["content"]]
    assert len(triage) == 1


async def test_assess_coalesce_flushes_full_batch_immediately(env):
    env.cfg.assess.coalesce_ms = 2000
    videos = [vid(i, f"Title {i}") for i in range(25)]
    r = await env.client.post("/v1/assess", json={"videos": videos, "wait_ms": 1000})
    assert all(v["status"] == "ready" for v in r.json()["results"])


async def test_headroom_added_to_max_tokens(client, mock_llm, cfg):
    await client.chat(LLMTask(model="worker", max_tokens=500), MSGS)
    assert mock_llm.calls[0]["max_tokens"] == 500 + cfg.llm.reasoning_headroom_tokens
    await client.chat(LLMTask(model="worker", max_tokens=500), MSGS, max_tokens=700)
    assert mock_llm.calls[1]["max_tokens"] == 700 + cfg.llm.reasoning_headroom_tokens


async def test_task_headroom_override_zero(client, mock_llm):
    task = LLMTask(model="worker", max_tokens=500, reasoning_headroom_tokens=0)
    await client.chat(task, MSGS)
    assert mock_llm.calls[0]["max_tokens"] == 500


async def test_truncated_then_ok_retries_with_doubled_budget(client, mock_llm, cfg):
    mock_llm.length_first = 1
    result = await client.chat_result(LLMTask(model="worker", max_tokens=500), MSGS)
    assert not result.truncated
    first, second = mock_llm.calls
    head = cfg.llm.reasoning_headroom_tokens
    assert first["max_tokens"] == 500 + head and second["max_tokens"] == 1000 + head


async def test_truncated_twice_is_marked(client, mock_llm):
    mock_llm.length_first = 5
    result = await client.chat_result(TASK, MSGS)
    assert result.truncated and len(mock_llm.calls) == 2
    assert (await client.chat(TASK, MSGS)).endswith(" …")


async def test_truncated_summary_not_cached_long_term(env):
    env.llm.length_first = 2
    p = {"wait_ms": 5000}
    r = await env.client.get(f"/v1/videos/{VID}/summary", params=p)
    assert r.json()["status"] == "ready" and r.json()["text"].endswith(" …")
    n = len(env.llm.calls)
    again = await env.client.get(f"/v1/videos/{VID}/summary", params=p)
    assert again.json()["text"] and not again.json()["text"].endswith(" …")
    assert len(env.llm.calls) > n


async def test_prompt_max_tokens_is_answer_budget(env):
    await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    head = env.cfg.llm.reasoning_headroom_tokens
    assert env.llm.calls[-1]["max_tokens"] == 700 + head
