"""The processed-videos view: one item per video from captions jobs, cuts and summaries."""

from __future__ import annotations

import time

import httpx

from tests.conftest import OTHER_TOKEN

VID1 = "abcdefghijk"
VID2 = "bcdefghijkl"
VID3 = "cdefghijklm"


def add_caption(
    env,
    video_id: str,
    *,
    user: str = "owner",
    status: str = "ready",
    lang: str = "en",
    translate_to: str | None = "en",
    updated_at: float | None = None,
    title: str | None = None,
) -> None:
    now = updated_at if updated_at is not None else time.time()
    env.svc.db.execute(
        "INSERT INTO jobs(id,user,video_id,lang,translate_to,status,progress,created_at,"
        "updated_at,kind,title,priority) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            f"job{video_id[:4]}{int(now)}",
            user,
            video_id,
            lang,
            translate_to,
            status,
            1.0 if status == "ready" else 0.0,
            now - 60,
            now,
            "captions",
            title,
            1,
        ],
    )


def add_cut(
    env,
    video_id: str,
    *,
    user: str = "owner",
    preset: str | None = "cut-demo",
    prompt: str | None = None,
    state: str = "ready",
    updated_at: float | None = None,
) -> None:
    now = updated_at if updated_at is not None else time.time()
    env.svc.db.execute(
        "INSERT INTO cut_requests(id,user,video_id,source,preset_id,prompt,state,error,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        [
            f"cut{video_id[:4]}{int(now)}",
            user,
            video_id,
            "API token",
            preset,
            prompt,
            state,
            None,
            now - 60,
            now,
        ],
    )


def add_summary(env, video_id: str) -> None:
    now = time.time()
    env.svc.db.execute(
        "INSERT INTO summaries(video_id,prompt_key,content_hash,language,text,source,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        [video_id, "builtin/tldr", "hash", "en", "A summary.", "youtube_captions", now],
    )


def partner_client(env):
    return httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )


async def test_no_processed_videos_is_an_empty_list(env):
    r = await env.client.get("/v1/processed")
    assert r.status_code == 200, r.text
    assert r.json() == {"videos": []}


async def test_mixed_items_are_one_per_video_newest_first(env):
    base = time.time()
    env.svc.transcripts.store_meta(
        VID1, {"title": "First title", "thumbnail_url": "https://i.ytimg.com/vi/first.jpg"}
    )
    add_caption(env, VID1, lang="en", translate_to="de", updated_at=base - 10)
    add_cut(env, VID1, preset="cut-demo", updated_at=base)
    add_summary(env, VID1)
    add_caption(env, VID2, status="running", updated_at=base - 20, title="Title from the job")

    body = (await env.client.get("/v1/processed")).json()
    videos = body["videos"]
    assert [v["video_id"] for v in videos] == [VID1, VID2]

    first = videos[0]
    assert first["title"] == "First title"
    assert first["thumbnail"] == "https://i.ytimg.com/vi/first.jpg"
    assert first["updated_at"] == base
    assert first["summary"] is True
    assert len(first["captions"]) == 1
    caption = first["captions"][0]
    assert caption["state"] == "ready" and caption["lang"] == "en"
    assert caption["translate_to"] == "de" and caption["progress"] == 1.0
    assert len(first["cuts"]) == 1
    cut = first["cuts"][0]
    assert cut["state"] == "ready" and cut["preset_id"] == "cut-demo"
    assert cut["preset_label"] == "Only the demo"
    assert cut["mode"] == "quick"

    second = videos[1]
    assert second["title"] == "Title from the job"
    assert second["thumbnail"] == f"https://i.ytimg.com/vi/{VID2}/mqdefault.jpg"
    assert second["summary"] is False
    assert second["captions"][0]["state"] == "processing"
    assert second["cuts"] == []


async def test_limit_returns_that_many_videos_not_jobs(env):
    base = time.time()
    add_caption(env, VID3, updated_at=base - 30)
    add_caption(env, VID2, updated_at=base - 20)
    add_caption(env, VID1, updated_at=base - 10)
    add_cut(env, VID1, preset="cut-answer", updated_at=base - 5)

    body = (await env.client.get("/v1/processed", params={"limit": 2})).json()
    videos = body["videos"]
    assert [v["video_id"] for v in videos] == [VID1, VID2]
    assert len(videos) == 2
    assert len(videos[0]["captions"]) == 1
    assert len(videos[0]["cuts"]) == 1


async def test_another_users_items_are_not_visible(env):
    base = time.time()
    add_caption(env, VID1, updated_at=base - 10)
    add_cut(env, VID1, user="partner", preset="cut-demo", updated_at=base)
    add_caption(env, VID2, user="partner", updated_at=base + 5)
    add_summary(env, VID2)

    owner = (await env.client.get("/v1/processed")).json()["videos"]
    assert [v["video_id"] for v in owner] == [VID1]
    assert len(owner[0]["captions"]) == 1
    assert owner[0]["cuts"] == []

    partner = partner_client(env)
    try:
        theirs = (await partner.get("/v1/processed")).json()["videos"]
    finally:
        await partner.aclose()
    assert [v["video_id"] for v in theirs] == [VID2, VID1]
    assert theirs[1]["captions"] == []
    assert len(theirs[1]["cuts"]) == 1


async def test_dismissed_cuts_stay_out(env):
    base = time.time()
    add_caption(env, VID1, updated_at=base - 10)
    add_cut(env, VID1, preset="cut-demo", state="dismissed", updated_at=base)
    add_cut(env, VID2, preset="cut-demo", state="dismissed", updated_at=base + 5)

    videos = (await env.client.get("/v1/processed")).json()["videos"]
    assert [v["video_id"] for v in videos] == [VID1]
    assert videos[0]["cuts"] == []


async def test_limit_outside_the_range_is_refused(env):
    for limit in (0, 201):
        r = await env.client.get("/v1/processed", params={"limit": limit})
        assert r.status_code == 400, r.text
        assert r.json()["error"]
