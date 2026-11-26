"""The per-user inbox of AI results: one item per ready result, newest first, with an
unread/read state, per user, and read/dismiss controls. See ai/CONTRACT.md "The inbox"."""

from __future__ import annotations

import time

import httpx

from tests.conftest import OTHER_TOKEN, TOKEN
from utubot.inbox import KIND_SUMMARY

VID1 = "abcdefghijk"
VID2 = "bcdefghijkl"
VID3 = "cdefghijklm"


def add_inbox(
    env,
    video_id: str,
    *,
    kind: str,
    result_id: str,
    user: str = "owner",
    created: float | None = None,
    read: bool = False,
    title: str | None = "A title",
    length_s: int | None = 900,
    label: str | None = None,
    prompt_key: str | None = None,
) -> None:
    now = created if created is not None else time.time()
    env.svc.db.execute(
        "INSERT INTO inbox(user,video_id,kind,result_id,prompt_key,title,length_s,label,"
        "created_at,read_at,dismissed) VALUES(?,?,?,?,?,?,?,?,?,?,0)",
        [
            user,
            video_id,
            kind,
            result_id,
            prompt_key,
            title,
            length_s,
            label,
            now,
            now if read else None,
        ],
    )


async def test_empty_inbox(env):
    r = await env.client.get("/v1/inbox")
    assert r.status_code == 200, r.text
    assert r.json() == {"items": [], "unread": 0}


async def test_items_are_newest_first_with_an_unread_count(env):
    base = time.time()
    add_inbox(env, VID1, kind="summary", result_id="builtin/tldr", created=base - 30)
    add_inbox(env, VID2, kind="cut", result_id="cut-1", created=base - 10)
    add_inbox(env, VID3, kind="captions", result_id="en", created=base - 5, read=True)

    body = (await env.client.get("/v1/inbox")).json()
    items = body["items"]
    assert [i["video_id"] for i in items] == [VID3, VID2, VID1]
    assert body["unread"] == 2
    assert items[0]["read"] is True
    assert items[1]["read"] is False
    assert items[1]["kind"] == "cut"
    assert items[1]["result_id"] == "cut-1"
    assert items[1]["length_s"] == 900


async def test_a_result_is_one_item_even_when_added_twice(env):
    env.svc.inbox.add("owner", VID1, KIND_SUMMARY, "builtin/tldr", title="A", length_s=900)
    env.svc.inbox.add("owner", VID1, KIND_SUMMARY, "builtin/tldr", title="A", length_s=900)

    items = (await env.client.get("/v1/inbox")).json()["items"]
    assert len(items) == 1


async def test_different_results_of_the_same_video_are_separate_items(env):
    base = time.time()
    add_inbox(env, VID1, kind="summary", result_id="builtin/tldr", created=base - 20)
    add_inbox(env, VID1, kind="summary", result_id="builtin/glance", created=base - 10)
    add_inbox(env, VID1, kind="research", result_id="en", created=base - 5)

    items = (await env.client.get("/v1/inbox")).json()["items"]
    assert len(items) == 3
    assert [i["result_id"] for i in items] == ["en", "builtin/glance", "builtin/tldr"]


async def test_mark_read_clears_the_unread_count(env):
    base = time.time()
    add_inbox(env, VID1, kind="summary", result_id="a", created=base - 20)
    add_inbox(env, VID2, kind="cut", result_id="b", created=base - 10)

    ids = [i["id"] for i in (await env.client.get("/v1/inbox")).json()["items"]]
    r = await env.client.post("/v1/inbox/read", json={"ids": [ids[0]]})
    assert r.status_code == 200 and r.json() == {"ok": True}

    items = (await env.client.get("/v1/inbox")).json()["items"]
    by_id = {i["id"]: i for i in items}
    assert by_id[ids[0]]["read"] is True
    assert by_id[ids[1]]["read"] is False
    assert (await env.client.get("/v1/inbox")).json()["unread"] == 1


async def test_read_all_marks_everything(env):
    add_inbox(env, VID1, kind="summary", result_id="a")
    add_inbox(env, VID2, kind="cut", result_id="b")

    r = await env.client.post("/v1/inbox/read-all")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert (await env.client.get("/v1/inbox")).json()["unread"] == 0


async def test_dismiss_removes_items(env):
    base = time.time()
    add_inbox(env, VID1, kind="summary", result_id="a", created=base - 20)
    add_inbox(env, VID2, kind="cut", result_id="b", created=base - 10)

    ids = [i["id"] for i in (await env.client.get("/v1/inbox")).json()["items"]]
    r = await env.client.post("/v1/inbox/dismiss", json={"ids": [ids[1]]})
    assert r.status_code == 200 and r.json() == {"ok": True}

    items = (await env.client.get("/v1/inbox")).json()["items"]
    assert [i["id"] for i in items] == [ids[0]]


async def test_a_dismissed_result_can_be_added_again(env):
    now = time.time()
    add_inbox(env, VID1, kind="summary", result_id="a", created=now - 40)
    ids = [i["id"] for i in (await env.client.get("/v1/inbox")).json()["items"]]
    await env.client.post("/v1/inbox/dismiss", json={"ids": ids})
    assert (await env.client.get("/v1/inbox")).json()["items"] == []

    # Dismiss is a read-only flag (CONTRACT.md), so a dismissed row does not block a re-add: the
    # result reported ready again comes back as one fresh item, deduped by its identity.
    env.svc.inbox.add("owner", VID1, KIND_SUMMARY, "a", title="A", length_s=900)

    items = (await env.client.get("/v1/inbox")).json()["items"]
    assert len(items) == 1
    assert items[0]["result_id"] == "a"


async def test_the_inbox_is_per_user_and_shared_across_clients(env):
    base = time.time()
    add_inbox(env, VID1, kind="summary", result_id="a", user="owner", created=base - 20)
    add_inbox(env, VID2, kind="cut", result_id="b", user="owner", created=base - 10)
    add_inbox(env, VID3, kind="captions", result_id="en", user="partner", created=base - 5)

    # A second client for the same user (the phone) sees the same items as the TV, and marks its
    # inbox read; the TV then sees the same items read: the state is on the server, per user, so
    # the phone and the extension share it.
    phone = httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )
    try:
        phone_items = (await phone.get("/v1/inbox")).json()["items"]
        read = await phone.post("/v1/inbox/read-all")
    finally:
        await phone.aclose()

    assert [i["video_id"] for i in phone_items] == [VID2, VID1]
    assert read.status_code == 200 and read.json() == {"ok": True}

    tv = await env.client.get("/v1/inbox")
    assert all(i["read"] for i in tv.json()["items"])
    assert tv.json()["unread"] == 0

    # A different user sees only their own item, still unread.
    partner = httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    try:
        partner_body = (await partner.get("/v1/inbox")).json()
    finally:
        await partner.aclose()
    assert [i["video_id"] for i in partner_body["items"]] == [VID3]
    assert partner_body["unread"] == 1


async def test_the_route_requires_auth(env):
    client = httpx.AsyncClient(transport=env.client._transport, base_url="http://utubot")
    try:
        r = await client.get("/v1/inbox")
        assert r.status_code == 401
    finally:
        await client.aclose()


async def test_limit_outside_the_range_is_refused(env):
    for limit in (0, 201):
        r = await env.client.get("/v1/inbox", params={"limit": limit})
        assert r.status_code == 400, r.text
        assert r.json()["error"]


async def test_done_captions_become_an_inbox_item(env):
    env.svc.db.execute(
        "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at) VALUES(?,?,?,?,?,?)",
        [VID1, "en", "English (u·tubot)", 1, "[00:00] hi", time.time()],
    )

    r = await env.client.get(f"/v1/videos/{VID1}/captions")
    assert r.json()["status"] == "ready"

    items = (await env.client.get("/v1/inbox")).json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "captions"
    assert items[0]["result_id"] == "en"
    assert items[0]["label"] == "English (u·tubot)"


async def test_a_caption_added_twice_is_one_inbox_item(env):
    env.svc.db.execute(
        "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at) VALUES(?,?,?,?,?,?)",
        [VID1, "en", "English", 1, "[00:00] hi", time.time()],
    )
    await env.client.get(f"/v1/videos/{VID1}/captions")
    await env.client.get(f"/v1/videos/{VID1}/captions")

    items = (await env.client.get("/v1/inbox")).json()["items"]
    assert len(items) == 1


async def test_a_requested_summary_becomes_an_inbox_item(env):
    r = await env.client.get(
        f"/v1/videos/{VID1}/summary",
        params={"wait_ms": 5000, "duration_s": 900, "title": "A summary"},
    )
    assert r.json()["status"] == "ready"

    items = (await env.client.get("/v1/inbox")).json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "summary"
    assert items[0]["result_id"] == "builtin/tldr"
    assert items[0]["prompt_key"] == "builtin/tldr"  # the summary's prompt key (CONTRACT.md)
    assert items[0]["title"] == "A summary"
    assert items[0]["length_s"] == 900


async def test_a_requested_insight_becomes_an_inbox_item(env):
    r = await env.client.get(f"/v1/videos/{VID1}/insight", params={"wait_ms": 5000})
    assert r.json()["status"] == "ready"

    items = (await env.client.get("/v1/inbox")).json()["items"]
    assert len(items) == 1
    assert items[0]["kind"] == "research"
    assert items[0]["result_id"] == "en"  # research's result id is the language
