from __future__ import annotations

import asyncio

from utubot.llm import extract_json


def vid(i, title, **kw):
    return {"video_id": f"vid{i:08d}", "title": title, **kw}


async def test_assess_policy_actions(env):
    videos = [
        vid(1, "A normal tutorial"),
        vid(2, "SHOCKING truth they hide"),
        vid(3, "Funny reaction video"),
        vid(4, "A BIT misleading title"),
    ]
    r = await env.client.post(
        "/v1/assess", json={"videos": videos, "section": "home", "wait_ms": 2000}
    )
    assert r.status_code == 200
    res = r.json()["results"]
    assert [x["video_id"] for x in res] == [v["video_id"] for v in videos]
    assert res[0]["action"] == "none" and res[0]["status"] == "ready"
    assert res[1]["action"] == "hide"
    assert res[2]["action"] == "hide"
    assert any(f["kind"] == "topic" for f in res[2]["flags"])
    assert res[3]["action"] == "mark" and res[3]["mark_label"] == "Clickbait"


async def test_assess_policy_is_per_user(env):
    videos = [vid(3, "Funny reaction video")]
    await env.client.post("/v1/assess", json={"videos": videos, "wait_ms": 2000})
    other = await env.client.post(
        "/v1/assess",
        json={"videos": videos, "wait_ms": 2000},
        headers={"Authorization": "Bearer utb_othertoken"},
    )
    assert other.json()["results"][0]["action"] == "none"


async def test_assess_batches_at_most_25(env):
    videos = [vid(i, f"Video number {i}") for i in range(60)]
    env.cfg.assess.max_videos_per_request = 60
    r = await env.client.post("/v1/assess", json={"videos": videos, "wait_ms": 3000})
    assert r.status_code == 200
    triage_calls = [c for c in env.llm.calls if "triage YouTube" in c["messages"][0]["content"]]
    assert len(triage_calls) == 3
    assert all(c.get("reasoning_effort") == "none" for c in triage_calls)
    assert all(c["model"] == "fast" for c in triage_calls)


async def test_assess_too_many_rejected(env):
    r = await env.client.post("/v1/assess", json={"videos": [vid(i, "t") for i in range(51)]})
    assert r.status_code == 400


async def test_assess_pending_then_ready_and_dedupe(env):
    env.llm.delay_s = 0.4
    videos = [vid(1, "Slow one")]
    first = await env.client.post("/v1/assess", json={"videos": videos, "wait_ms": 50})
    assert first.json()["results"][0]["status"] == "pending"
    second = await env.client.post("/v1/assess", json={"videos": videos, "wait_ms": 50})
    assert second.json()["results"][0]["status"] == "pending"
    await asyncio.sleep(0.8)
    done = await env.client.post("/v1/assess", json={"videos": videos, "wait_ms": 50})
    assert done.json()["results"][0]["status"] == "ready"
    triage_calls = [c for c in env.llm.calls if "triage YouTube" in c["messages"][0]["content"]]
    assert len(triage_calls) == 1


async def test_assess_wait_ms_capped(env):
    env.llm.delay_s = 3.6
    loop = asyncio.get_running_loop()
    started = loop.time()
    r = await env.client.post("/v1/assess", json={"videos": [vid(1, "x")], "wait_ms": 60000})
    assert loop.time() - started < 3.4
    assert r.json()["results"][0]["status"] == "pending"
    await env.svc.assessor.drain()


async def test_json_robustness_think_and_fence(env):
    for mode in ("think", "fence"):
        env.llm.mode = mode
        r = await env.client.post(
            "/v1/assess",
            json={"videos": [vid(hash(mode) % 1000, "SHOCKING " + mode)], "wait_ms": 2000},
        )
        assert r.json()["results"][0]["action"] == "hide", mode


async def test_json_retry_once(env):
    env.llm.bad_json_first = 1
    r = await env.client.post(
        "/v1/assess", json={"videos": [vid(7, "SHOCKING retry")], "wait_ms": 2000}
    )
    assert r.json()["results"][0]["action"] == "hide"
    env.llm.calls.clear()
    env.llm.bad_json_first = 5
    r = await env.client.post(
        "/v1/assess", json={"videos": [vid(8, "SHOCKING dead")], "wait_ms": 2000}
    )
    assert r.json()["results"][0]["status"] == "pending"


async def test_tier2_answer_and_inflation(env):
    videos = [vid(1, "Does it work?", duration_s=900)]
    r = await env.client.post("/v1/assess", json={"videos": videos, "wait_ms": 2000})
    v = r.json()["results"][0]
    assert v["title_question"] == "Does it work?"
    await env.svc.assessor.drain()
    r = await env.client.post("/v1/assess", json={"videos": videos, "wait_ms": 2000})
    v = r.json()["results"][0]
    assert v["answer_short"] == "Yes, since v3."
    assert v["action"] == "mark"
    assert v["mark_label"] == "Inflated · 15m≈2m"
    assert any(f["kind"] == "inflated" for f in v["flags"])


async def test_tier2_daily_cap(env):
    env.cfg.assess.tier2_daily_cap_per_user = 1
    videos = [vid(1, "Why one?", duration_s=900), vid(2, "Why two?", duration_s=900)]
    await env.client.post("/v1/assess", json={"videos": videos, "wait_ms": 2000})
    await env.svc.assessor.drain()
    assert len(env.fetcher.calls) == 1


def test_extract_json_variants():
    assert extract_json('<think>x {"a":2}</think>{"a":1}') == {"a": 1}
    assert extract_json('```json\n{"a":1}\n```') == {"a": 1}
    assert extract_json("prefix text [1,2] suffix") == [1, 2]
