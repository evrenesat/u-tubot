"""Caption tracks a client uploads are stored like a fetch and spare the server's YouTube request."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from tests.conftest import TOKEN
from tests.test_cuts_api import wait_ready
from utubot.config import LLMTask
from utubot.youtube import YoutubeDelayed

VID = "abcdefghijk"
URL = f"/v1/videos/{VID}/captions/client"
SEGMENTS = [(i * 5.0, i * 5.0 + 4.0, f"Sentence number {i} is spoken here.") for i in range(12)]


def json3(rows=SEGMENTS, offsets=False) -> str:
    events = []
    for start, end, text in rows:
        seg = {"utf8": text}
        if offsets:
            seg["tOffsetMs"] = 0
        events.append(
            {"tStartMs": int(start * 1000), "dDurationMs": int((end - start) * 1000), "segs": [seg]}
        )
    return json.dumps({"events": events})


def vtt(rows=SEGMENTS) -> str:
    def stamp(sec: float) -> str:
        return f"00:{int(sec // 60):02d}:{sec % 60:06.3f}"

    cues = [f"{stamp(a)} --> {stamp(b)}\n{t}\n" for a, b, t in rows]
    return "WEBVTT\n\n" + "\n".join(cues)


def srv3(rows=SEGMENTS) -> str:
    paras = "".join(
        f'<p t="{int(a * 1000)}" d="{int((b - a) * 1000)}"><s>{t}</s></p>' for a, b, t in rows
    )
    return f'<?xml version="1.0"?><timedtext format="3"><body>{paras}</body></timedtext>'


def track(kind="manual", fmt="json3", body=None, lang="en", offsets=False, **extra) -> dict:
    bodies = {"json3": json3, "vtt": vtt, "srv3": srv3}
    return {
        "lang": lang,
        "kind": kind,
        "name": "English",
        "format": fmt,
        "body": body
        if body is not None
        else (json3(offsets=offsets) if fmt == "json3" else bodies[fmt]()),
        **extra,
    }


@pytest.fixture
async def cuts_env(env):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.cuts.poll_s = 0.02
    env.cfg.cuts.transcript_wait_s = 60.0
    env.cfg.cuts.wait_ms_cap = 3000
    env.cfg.cuts.default_wait_ms = 0
    return env


async def upload(env, *tracks, **params):
    return await env.client.post(URL, json={"tracks": list(tracks)}, params=params)


def stored_row(env):
    return env.svc.db.one("SELECT * FROM transcripts WHERE video_id=?", [VID])


async def test_upload_is_stored_like_a_fetch_and_marked_client(env):
    reply = await upload(env, track("auto", "json3", offsets=True))
    assert reply.status_code == 200, reply.text
    assert reply.json() == {
        "stored": True,
        "reason": "stored",
        "lang": "en",
        "kind": "auto",
        "tracks": 1,
    }
    row = stored_row(env)
    assert row["source"] == "youtube_captions" and row["origin"] == "client"
    assert row["caption_kind"] == "auto" and row["lang"] == "en"
    assert json.loads(row["segments"])[0] == [0.0, 4.0, "Sentence number 0 is spoken here."]
    assert json.loads(row["words"])
    cached = env.svc.transcripts.cached(VID)
    assert cached is not None and cached.origin == "client" and cached.segments


async def test_vtt_and_srv3_tracks_are_read(env):
    for fmt in ("vtt", "srv3"):
        env.svc.db.execute("DELETE FROM transcripts")
        reply = await upload(env, track("manual", fmt))
        assert reply.json()["stored"] is True, fmt
        segments = json.loads(stored_row(env)["segments"])
        assert len(segments) == len(SEGMENTS) and segments[1][2] == SEGMENTS[1][2], fmt


async def test_a_stored_client_copy_means_no_youtube_call(env):
    await upload(env, track("manual"))
    got = await env.svc.transcripts.get(VID)
    assert got.origin == "client" and got.caption_kind == "manual"
    assert env.fetcher.calls == []


async def test_a_summary_uses_the_upload_without_the_fetcher(env):
    await upload(env, track("manual"))
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert r.json()["status"] == "ready", r.text
    assert env.fetcher.calls == []


async def test_a_cut_uses_the_upload_without_the_fetcher(cuts_env):
    cuts_env.fetcher.meta_extra = {"duration_s": 60}
    cuts_env.llm.cut_answer = {
        "parts": [{"from": 2, "to": 4, "label": "The demo"}],
        "summary": "The demo part.",
        "kept_s": 15,
    }
    assert (await upload(cuts_env, track("manual"))).json()["stored"] is True
    r = await cuts_env.client.post(f"/v1/videos/{VID}/cuts", json={"preset": "cut-demo"})
    doc = await wait_ready(cuts_env, r.json()["request_id"])
    assert doc["state"] == "ready", doc
    assert cuts_env.fetcher.calls == []


async def test_an_auto_track_never_replaces_a_manual_one(env):
    assert (await upload(env, track("manual", lang="en"))).json()["stored"] is True
    other = [(0.0, 3.0, "Auto text that must not win.")] * 3
    again = (await upload(env, track("auto", "json3", body=json3(other)))).json()
    assert again["stored"] is False and again["reason"] == "kept_manual"
    row = stored_row(env)
    assert row["caption_kind"] == "manual" and "must not win" not in row["text"]


async def test_a_manual_track_replaces_an_auto_one(env):
    await upload(env, track("auto"))
    again = (await upload(env, track("manual"))).json()
    assert again["stored"] is True
    assert stored_row(env)["caption_kind"] == "manual"


async def test_the_manual_track_of_an_upload_is_the_one_kept(env):
    reply = await upload(
        env,
        track("auto", lang="en", original=True),
        track("manual", lang="de", body=vtt([(0.0, 2.0, "Hallo Welt")] * 3), fmt="vtt"),
        track("manual", lang="en"),
    )
    assert reply.json()["lang"] == "en" and reply.json()["kind"] == "manual"
    assert reply.json()["tracks"] == 3


async def test_asr_transcripts_stay(env):
    env.svc.transcripts.store_asr(VID, "spoken words", "en", segments=[(0.0, 1.0, "spoken")])
    reply = (await upload(env, track("manual"))).json()
    assert reply["stored"] is False and reply["reason"] == "kept_asr"
    assert stored_row(env)["source"] == "asr"


async def test_real_captions_clear_the_no_captions_hold(env):
    env.fetcher.text = None
    from utubot.transcripts import NoCaptions

    try:
        await env.svc.transcripts.get(VID)
    except NoCaptions:
        pass
    assert env.svc.transcripts.no_captions(VID)
    env.svc.transcripts._record_hold(VID, "delayed", "empty_track", 600)
    assert (await upload(env, track("manual"))).json()["stored"] is True
    assert not env.svc.transcripts.no_captions(VID)
    assert env.svc.transcripts.hold(VID) is None
    assert (await env.svc.transcripts.get(VID)).origin == "client"


async def test_a_waiting_fetch_picks_the_upload_up_at_once(env):
    gate_open = asyncio.Event()

    async def slow(video_id):
        await gate_open.wait()
        raise YoutubeDelayed("network", 1.0)

    env.svc.transcripts.fetcher = slow
    waiting = asyncio.create_task(env.svc.transcripts.get(VID))
    await asyncio.sleep(0.05)
    assert not waiting.done()
    await upload(env, track("manual"))
    got = await asyncio.wait_for(waiting, 2.0)
    assert got.origin == "client" and got.segments
    gate_open.set()


async def test_refused_uploads(env):
    env.cfg.transcripts.client_max_track_bytes = 200
    big = await upload(env, track("manual", fmt="vtt", body=vtt() + " " * 400))
    assert big.status_code == 413
    env.cfg.transcripts.client_max_track_bytes = 2 * 1024 * 1024
    env.cfg.transcripts.client_max_tracks = 2
    many = await upload(env, track(), track(lang="de"), track(lang="fr"))
    assert many.status_code == 400
    env.cfg.transcripts.client_max_tracks = 10
    assert (await upload(env, track(body="x") | {"format": "ttml"})).status_code == 400
    assert (await upload(env, track(kind="dubbed"))).status_code == 400
    assert (await upload(env, track(lang="no spaces!"))).status_code == 400
    assert (await upload(env)).status_code == 400
    garbage = await upload(env, track("manual", "json3", body="not json"))
    assert garbage.status_code == 400
    empty = await upload(env, track("manual", "vtt", body="WEBVTT\n\n"))
    assert empty.status_code == 400
    assert stored_row(env) is None


async def test_the_body_cap_follows_the_track_limits(env):
    over = env.cfg.transcripts.client_max_body_bytes + 1
    r = await env.client.post(
        URL, content=b"x" * over, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413
    # a body past the global cap but within the upload cap reaches validation, not the size check
    body = {"tracks": [track("manual", fmt="vtt", body=vtt() + " " * 300_000)]}
    assert (await env.client.post(URL, json=body)).status_code == 200


async def test_auth_is_required(env):
    anon = httpx.AsyncClient(transport=env.client._transport, base_url="http://utubot")
    r = await anon.post(URL, json={"tracks": [track()]})
    assert r.status_code == 401
    bad = await anon.post(URL, json={"tracks": [track()]}, headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    ok = await anon.post(
        URL, json={"tracks": [track()]}, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert ok.status_code == 200
