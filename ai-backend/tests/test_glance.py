from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.test_prompts_summary import pset
from utubot.config import GLANCE_MAX_TOKENS, GlanceTask, UserPolicy
from utubot.content import summary_task_key
from utubot.llm import BACKGROUND, INTERACTIVE, LLMError
from utubot.prompts import (
    BUILTIN_SET,
    DEFAULT_PANEL_KEY,
    Prompt,
    PromptError,
    validate_prompt_set,
)

VID = "abcdefghijk"
QUESTION_VID = "vid00000007"
GLANCE_MARK = "glance card"
TLDR_MARK = "TL;DR as 5 short bullet points"


def calls_with(env, mark: str) -> list[dict]:
    return [
        c
        for c in env.llm.calls
        if mark in c["messages"][0]["content"] + c["messages"][1]["content"]
    ]


async def panel(env, vid: str = VID, **params):
    return await env.client.get(
        f"/v1/videos/{vid}/summary", params={"prompt": "panel", "wait_ms": 5000, **params}
    )


def tldr_hash() -> str:
    return next(p for p in BUILTIN_SET.prompts if p.id == "tldr").content_hash()


def intercept_background(env, behaviour):
    """Run `behaviour(task, messages, kwargs)` instead of the model for background-priority calls."""
    original = env.svc.llm.chat_result

    async def wrapper(task, messages, **kwargs):
        if kwargs["priority"] == BACKGROUND:
            return await behaviour(task, messages, kwargs)
        return await original(task, messages, **kwargs)

    env.svc.llm.chat_result = wrapper


def spy_priorities(env) -> list[tuple[str, int]]:
    seen: list[tuple[str, int]] = []
    original = env.svc.llm.chat_result

    async def wrapper(task, messages, **kwargs):
        seen.append((messages[1]["content"], kwargs["priority"]))
        return await original(task, messages, **kwargs)

    env.svc.llm.chat_result = wrapper
    return seen


async def test_panel_resolves_to_glance(env):
    listing = (await env.client.get("/v1/prompts")).json()
    assert listing["default"] == "builtin/tldr"
    assert listing["panel_default"] == "builtin/glance" == DEFAULT_PANEL_KEY
    builtin = next(s for s in listing["sets"] if s["id"] == "builtin")
    by_id = {p["id"]: p for p in builtin["prompts"]}
    assert by_id["glance"]["panel_default"] and not by_id["glance"]["default"]
    assert by_id["tldr"]["default"] and not by_id["tldr"]["panel_default"]

    body = (await panel(env)).json()
    assert body["status"] == "ready" and body["prompt"] == "builtin/glance"
    call = calls_with(env, GLANCE_MARK)[-1]
    assert call["max_tokens"] == GLANCE_MAX_TOKENS + env.cfg.llm.reasoning_headroom_tokens
    assert call["reasoning_effort"] == "none"
    assert call["model"] == env.cfg.llm.summary.model
    plain = (await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})).json()
    assert plain["prompt"] == "builtin/tldr"


async def test_glance_prompt_text_and_budget():
    glance = next(p for p in BUILTIN_SET.prompts if p.id == "glance")
    assert glance.task == "glance" and glance.max_tokens == GLANCE_MAX_TOKENS
    assert "280 characters" in glance.template and "3 short lines" in glance.template
    assert "→ " in glance.template and "Not answered in the video" in glance.template
    assert "{question}" in glance.template and "{language}" in glance.system
    answer = next(p for p in BUILTIN_SET.prompts if p.id == "answer-title")
    assert "{question}" in answer.template and "curiosity" in answer.template
    assert {p.id for p in BUILTIN_SET.prompts} == {
        "glance",
        "tldr",
        "answer-title",
        "takeaways",
        "worth-it",
        "eli-new",
    }


async def test_glance_task_model_and_fallback(env):
    env.cfg.llm.summary.reasoning_effort = "high"
    env.cfg.llm.summary.model = "summary-model"
    await panel(env)
    call = calls_with(env, GLANCE_MARK)[-1]
    assert call["model"] == "summary-model" and call["reasoning_effort"] == "none"

    env.cfg.llm.glance = GlanceTask(model="fast-model")
    await panel(env, "zzzzzzzzzzz")
    call = calls_with(env, GLANCE_MARK)[-1]
    assert call["model"] == "fast-model" and call["reasoning_effort"] == "none"
    assert call["max_tokens"] == GLANCE_MAX_TOKENS + env.cfg.llm.reasoning_headroom_tokens

    env.cfg.llm.glance = GlanceTask(model="fast-model", reasoning_effort="low")
    await panel(env, "yyyyyyyyyyy")
    assert calls_with(env, GLANCE_MARK)[-1]["reasoning_effort"] == "low"

    await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    tldr = calls_with(env, TLDR_MARK)[-1]
    assert tldr["model"] == "summary-model" and tldr["reasoning_effort"] == "high"


async def test_question_variable_filled_from_triage(env):
    await env.client.post(
        "/v1/assess",
        json={
            "videos": [{"video_id": QUESTION_VID, "title": "Why is it so fast?"}],
            "wait_ms": 3000,
        },
    )
    await env.svc.assessor.drain()
    await panel(env, QUESTION_VID)
    user = calls_with(env, GLANCE_MARK)[-1]["messages"][1]["content"]
    assert "(detected earlier, may be empty): Why is it so fast?\n" in user

    await panel(env, "zzzzzzzzzzz")
    user = calls_with(env, GLANCE_MARK)[-1]["messages"][1]["content"]
    assert "(detected earlier, may be empty): \n\nTranscript" in user


async def test_condense_step_prioritises_the_curiosity_answer(env):
    env.cfg.summary.token_budget = 200
    env.cfg.summary.chunk_tokens = 100
    env.fetcher.text = "\n".join(f"[00:{i:02d}] line {i} " + "word " * 20 for i in range(40))
    await env.client.post(
        "/v1/assess",
        json={"videos": [{"video_id": VID, "title": "What happened here?"}], "wait_ms": 3000},
    )
    await env.svc.assessor.drain()
    body = (await panel(env, VID, wait_ms=10000)).json()
    assert body["status"] == "ready"
    maps = [c for c in env.llm.calls if "condense one part" in c["messages"][0]["content"]]
    assert len(maps) > 1
    assert "ANSWER:" in maps[0]["messages"][0]["content"]
    first = maps[0]["messages"][1]["content"]
    assert "Question the title poses: What happened here?" in first
    assert f"Video title: Title {VID}" in first


async def test_auto_long_off_enqueues_nothing(env):
    assert env.cfg.summary.auto_long is False
    seen = spy_priorities(env)
    assert (await panel(env)).json()["status"] == "ready"
    await env.svc.content.registry.drain()
    assert len(seen) == 1 and GLANCE_MARK in seen[0][0]
    assert not calls_with(env, TLDR_MARK)
    rows = env.svc.db.all("SELECT prompt_key FROM summaries WHERE video_id=?", [VID])
    assert [r["prompt_key"] for r in rows] == ["builtin/glance"]


async def test_auto_long_on_enqueues_one_background_job(env):
    env.cfg.summary.auto_long = True
    seen = spy_priorities(env)
    assert (await panel(env)).json()["status"] == "ready"
    await env.svc.content.registry.drain()
    long_calls = [(u, p) for u, p in seen if TLDR_MARK in u]
    assert len(long_calls) == 1 and long_calls[0][1] == BACKGROUND
    assert [p for u, p in seen if GLANCE_MARK in u] == [INTERACTIVE]
    rows = env.svc.db.all("SELECT prompt_key FROM summaries WHERE video_id=?", [VID])
    assert {r["prompt_key"] for r in rows} == {"builtin/glance", "builtin/tldr"}

    await panel(env)
    await env.svc.content.registry.drain()
    assert len(calls_with(env, TLDR_MARK)) == 1
    plain = (await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 100})).json()
    assert plain["status"] == "ready"
    assert len(calls_with(env, TLDR_MARK)) == 1


async def test_auto_long_uses_the_users_default_prompt(env):
    env.cfg.summary.auto_long = True
    await env.client.put("/v1/prompts/sets/mine", json=pset(template="LONG {transcript}"))
    await env.client.put("/v1/prompts/default", json={"key": "mine/p1"})
    await panel(env)
    await env.svc.content.registry.drain()
    assert len(calls_with(env, "LONG ")) == 1 and not calls_with(env, TLDR_MARK)

    await env.client.put("/v1/prompts/default", json={"key": "builtin/glance"})
    seen = spy_priorities(env)
    await panel(env, "zzzzzzzzzzz")
    await env.svc.content.registry.drain()
    assert len(seen) == 1


async def test_auto_long_policy_overrides_config(env):
    env.cfg.summary.auto_long = True
    r = await env.client.put("/v1/me/policy", json={"auto_long": False})
    assert r.status_code == 200 and r.json()["auto_long"] is False
    await panel(env)
    await env.svc.content.registry.drain()
    assert not calls_with(env, TLDR_MARK)

    env.cfg.summary.auto_long = False
    await env.client.put("/v1/me/policy", json={"auto_long": True})
    await panel(env, "zzzzzzzzzzz")
    await env.svc.content.registry.drain()
    assert len(calls_with(env, TLDR_MARK)) == 1


async def test_auto_long_only_for_panel_requests(env):
    env.cfg.summary.auto_long = True
    r = await env.client.get(
        f"/v1/videos/{VID}/summary", params={"prompt": "builtin/glance", "wait_ms": 5000}
    )
    assert r.json()["status"] == "ready"
    await env.svc.content.registry.drain()
    assert not calls_with(env, TLDR_MARK)


async def test_panel_default_put_and_resolution(env):
    r = await env.client.put("/v1/prompts/panel-default", json={"key": "builtin/takeaways"})
    assert r.status_code == 200 and r.json() == {"panel_default": "builtin/takeaways"}
    listing = (await env.client.get("/v1/prompts")).json()
    assert listing["panel_default"] == "builtin/takeaways" and listing["default"] == "builtin/tldr"
    assert (await panel(env)).json()["prompt"] == "builtin/takeaways"
    missing = await env.client.put("/v1/prompts/panel-default", json={"key": "mine/nope"})
    assert missing.status_code == 404
    assert (await env.client.put("/v1/prompts/panel-default", json={})).status_code == 400
    other = await env.client.get(
        f"/v1/videos/{VID}/summary",
        params={"prompt": "panel", "wait_ms": 5000},
        headers={"Authorization": "Bearer utb_othertoken"},
    )
    assert other.json()["prompt"] == "builtin/glance"

    await env.client.put("/v1/prompts/sets/mine", json=pset())
    await env.client.put("/v1/prompts/panel-default", json={"key": "mine/p1"})
    assert (await panel(env)).json()["prompt"] == "mine/p1"
    await env.client.delete("/v1/prompts/sets/mine")
    assert (await env.client.get("/v1/prompts")).json()["panel_default"] == "builtin/glance"


async def test_panel_prompt_config_is_the_fallback(env):
    env.cfg.summary.panel_prompt = "builtin/worth-it"
    assert (await panel(env)).json()["prompt"] == "builtin/worth-it"
    env.cfg.summary.panel_prompt = "gone/missing"
    assert (await panel(env)).json()["prompt"] == "builtin/glance"
    env.cfg.summary.panel_prompt = "builtin/worth-it"
    await env.client.put("/v1/prompts/panel-default", json={"key": "builtin/eli-new"})
    assert (await panel(env)).json()["prompt"] == "builtin/eli-new"


async def test_custom_prompt_can_use_the_glance_task(env):
    data = pset()
    data["prompts"][0]["task"] = "glance"
    assert (await env.client.put("/v1/prompts/sets/mine", json=data)).status_code == 200
    env.cfg.llm.glance = GlanceTask(model="fast-model")
    await env.client.get(f"/v1/videos/{VID}/summary", params={"prompt": "mine/p1", "wait_ms": 5000})
    assert env.llm.calls[-1]["model"] == "fast-model"
    bad = pset()
    bad["prompts"][0]["task"] = "turbo"
    assert (await env.client.put("/v1/prompts/sets/mine", json=bad)).status_code == 400


def test_old_prompt_set_files_still_validate():
    legacy = pset()
    assert "task" not in legacy["prompts"][0]
    parsed = validate_prompt_set(legacy)
    assert parsed.prompts[0].task == "summary"
    example = Path(__file__).parent.parent / "prompts" / "example-set.json"
    assert validate_prompt_set(json.loads(example.read_text())).prompts


def test_task_field_keeps_old_content_hashes():
    import hashlib

    prompt = Prompt(id="p", label="P", system="s", template="t {title}", max_tokens=200)
    legacy = json.dumps(["s", "t {title}", 200, None], ensure_ascii=False)
    assert prompt.content_hash() == hashlib.sha256(legacy.encode()).hexdigest()
    glance = prompt.model_copy(update={"task": "glance"})
    assert glance.content_hash() != prompt.content_hash()
    with pytest.raises(PromptError):
        validate_prompt_set(pset(extra={"prompts": [{**pset()["prompts"][0], "task": "x"}]}))


def test_example_config_has_glance_defaults():
    from utubot.config import load_config

    cfg = load_config(Path(__file__).parent.parent / "config.example.toml")
    assert cfg.summary.panel_prompt == "builtin/glance" and cfg.summary.auto_long is False
    assert cfg.llm.glance is None
    task = cfg.llm.glance_task()
    assert task.model == cfg.llm.summary.model and task.reasoning_effort == "none"


async def test_background_failure_never_fails_an_interactive_request(env):
    env.cfg.summary.auto_long = True

    async def boom(task, messages, kwargs):
        raise LLMError("boom")

    intercept_background(env, boom)
    await panel(env)
    await env.svc.content.registry.drain()
    registry = env.svc.content.registry
    bg_key = summary_task_key(VID, "builtin/tldr", tldr_hash(), "en", BACKGROUND)
    assert registry.recent_failure(bg_key)

    seen = spy_priorities(env)
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert r.json()["status"] == "ready" and r.json()["prompt"] == "builtin/tldr"
    assert [p for _, p in seen if TLDR_MARK in _] == [INTERACTIVE]
    before = len(env.llm.calls)
    await panel(env)
    await env.svc.content.registry.drain()
    assert len(env.llm.calls) == before


async def test_interactive_request_takes_over_a_running_background_job(env):
    env.cfg.summary.auto_long = True
    started = asyncio.Event()

    async def hang(task, messages, kwargs):
        started.set()
        await asyncio.sleep(60)

    intercept_background(env, hang)
    await panel(env)
    await asyncio.wait_for(started.wait(), 2)
    registry = env.svc.content.registry
    bg_key = summary_task_key(VID, "builtin/tldr", tldr_hash(), "en", BACKGROUND)
    assert registry.running(bg_key)

    seen = spy_priorities(env)
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert r.json()["status"] == "ready"
    assert [p for u, p in seen if TLDR_MARK in u] == [INTERACTIVE]
    await asyncio.sleep(0.05)
    assert not registry.running(bg_key) and registry.recent_failure(bg_key) is None
    assert env.svc.content._auto_long_active == 0
    rows = env.svc.db.all(
        "SELECT prompt_key FROM summaries WHERE video_id=? AND prompt_key=?", [VID, "builtin/tldr"]
    )
    assert len(rows) == 1


async def test_auto_long_concurrency_is_capped(env):
    env.cfg.summary.auto_long = True
    content = env.svc.content
    assert env.cfg.summary.auto_long_max_concurrent == 2
    policy = UserPolicy()
    videos = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]
    queued = [content.schedule_long("owner", policy, v, {}, "builtin/glance") for v in videos]
    assert queued == [True, True, False]
    assert content._auto_long_active == 2
    await content.registry.drain()
    assert content._auto_long_active == 0
    assert content.schedule_long("owner", policy, videos[2], {}, "builtin/glance") is True
    await content.registry.drain()
    rows = env.svc.db.all("SELECT video_id FROM summaries WHERE prompt_key='builtin/tldr'")
    assert {r["video_id"] for r in rows} == set(videos)

    env.cfg.summary.auto_long_max_concurrent = 0
    assert content.schedule_long("owner", policy, VID, {}, "builtin/glance") is False
