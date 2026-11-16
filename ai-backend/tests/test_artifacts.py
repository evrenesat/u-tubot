"""The failure policy and the per-video artifact view.

A busy model is never remembered, other failures only for `failure_cooldown_s`, the Retry action
(`POST /v1/videos/{id}/retry`) forgets everything remembered about a video, and the admin can list
and purge what is cached per video. Nothing here reaches YouTube or a real model.
"""

from __future__ import annotations

import time

from tests.conftest import OTHER_TOKEN
from tests.test_prompts_summary import VID

ASK = {"question": "why?", "wait_ms": 3000}


async def ask(env):
    r = await env.client.post(f"/v1/videos/{VID}/ask", json=ASK)
    return r.json()


async def summary(env):
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    return r.json()


async def test_a_busy_model_is_never_remembered(env):
    env.cfg.llm.retry_max_attempts = 1
    env.llm.busy_first = 1
    first = await summary(env)
    assert first["status"] == "failed" and "busy" in first["error"]
    # the endpoint is free again: the very next request asks again and succeeds
    assert (await summary(env))["status"] == "ready"


async def test_another_failure_is_remembered_only_briefly(env):
    env.cfg.llm.retry_max_attempts = 1
    env.llm.fail_status = 400
    first = await summary(env)
    assert first["status"] == "failed"
    calls = len(env.llm.calls)
    env.llm.fail_status = None
    again = await summary(env)
    assert again["status"] == "failed", "remembered: no new model call yet"
    assert len(env.llm.calls) == calls
    env.svc.content.registry._failures = {
        k: (time.time() - env.cfg.summary.failure_cooldown_s - 1, msg)
        for k, (_t, msg) in env.svc.content.registry._failures.items()
    }
    assert (await summary(env))["status"] == "ready", "the memory expired after the cooldown"


async def test_retry_forgets_the_remembered_failure_at_once(env):
    env.cfg.llm.retry_max_attempts = 1
    env.llm.fail_status = 400
    assert (await summary(env))["status"] == "failed"
    env.llm.fail_status = None
    r = await env.client.post(f"/v1/videos/{VID}/retry")
    assert r.status_code == 200 and r.json()["ok"] and r.json()["cleared"]["tasks"] >= 1
    assert (await summary(env))["status"] == "ready"


async def test_retry_forgets_the_fetch_failure_and_the_no_captions_memory(env):
    svc = env.svc
    svc.transcripts.record_failure(VID, "private")
    svc.db.execute("INSERT INTO no_captions(video_id,checked_at) VALUES(?,?)", [VID, time.time()])
    assert svc.transcripts.hold(VID) and svc.transcripts.no_captions(VID)
    r = await env.client.post(f"/v1/videos/{VID}/retry")
    assert r.json()["cleared"]["fetch"] == 2
    assert svc.transcripts.hold(VID) is None and not svc.transcripts.no_captions(VID)


async def test_retry_keeps_stored_successes(env):
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert r.json()["status"] == "ready"
    calls = len(env.llm.calls)
    await env.client.post(f"/v1/videos/{VID}/retry")
    again = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert again.json()["status"] == "ready" and len(env.llm.calls) == calls


async def test_retry_needs_a_user_and_a_valid_id(env, client_factory=None):
    bad = await env.client.post("/v1/videos/not-an-id!/retry")
    assert bad.status_code == 400
    import httpx

    anonymous = httpx.AsyncClient(transport=env.client._transport, base_url="http://utubot")
    assert (await anonymous.post(f"/v1/videos/{VID}/retry")).status_code == 401
    await anonymous.aclose()


async def test_the_inventory_lists_what_is_cached_per_video(env):
    await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    doc = (await env.client.get(f"/v1/admin/videos/{VID}/artifacts")).json()
    kinds = {a["kind"]: a for a in doc["artifacts"]}
    assert {"transcript", "summary"} <= set(kinds)
    assert kinds["summary"]["rows"] == 1 and kinds["summary"]["bytes"] > 0
    assert doc["total_bytes"] == sum(a["bytes"] for a in doc["artifacts"])


async def test_purge_removes_the_named_kinds_only(env):
    await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    r = await env.client.delete(f"/v1/admin/videos/{VID}/artifacts", params={"kind": "summary"})
    assert r.json()["removed"] == {"summary": 1}
    doc = (await env.client.get(f"/v1/admin/videos/{VID}/artifacts")).json()
    kinds = {a["kind"] for a in doc["artifacts"]}
    assert "summary" not in kinds and "transcript" in kinds


async def test_purge_rejects_an_unknown_kind_and_spares_the_archive_by_default(env, tmp_path):
    bad = await env.client.delete(f"/v1/admin/videos/{VID}/artifacts", params={"kind": "nope"})
    assert bad.status_code == 400
    src = tmp_path / "a.webm"
    src.write_bytes(b"audio")
    env.svc.archive.store(VID, src)
    await env.client.delete(f"/v1/admin/videos/{VID}/artifacts")
    assert env.svc.archive.lookup(VID) is not None, "the archive goes only when named"
    r = await env.client.delete(f"/v1/admin/videos/{VID}/artifacts", params={"kind": "archive"})
    assert r.json()["removed"] == {"archive": 1} and env.svc.archive.lookup(VID) is None


async def test_the_artifact_routes_are_admin_only(env):
    import httpx

    other = httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    assert (await other.get(f"/v1/admin/videos/{VID}/artifacts")).status_code == 403
    assert (await other.delete(f"/v1/admin/videos/{VID}/artifacts")).status_code == 403
    await other.aclose()
