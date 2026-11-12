"""Automatic transcription for videos without captions: policy, priorities, estimates, storage."""

from __future__ import annotations

import asyncio
import json
import shutil
import time

import httpx
import pytest

from utubot.config import AsrEngineConfig
from utubot.llm import BACKGROUND, INTERACTIVE
from utubot.youtube import (
    CLASS_CAPTIONS,
    CLASS_MEDIA,
    REASON_RATE_LIMITED,
)

VID = "abcdefghijk"
OTHER = "bcdefghijkl"
NEEDS_FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
LEGACY_ESTIMATE_S = round(5 + 900 / 300 + 30 + 900 / 1.5)
MINUTE = 60


async def policy(env, **fields) -> None:
    resp = await env.client.put("/v1/me/policy", json=fields)
    assert resp.status_code == 200, resp.text


async def summary(env, vid: str = VID, **params):
    return (
        await env.client.get(f"/v1/videos/{vid}/summary", params={"wait_ms": 5000, **params})
    ).json()


def jobs(env) -> list[dict]:
    return [dict(r) for r in env.svc.db.all("SELECT * FROM jobs ORDER BY created_at")]


MEDIA_COOLDOWN_S = 600


def hold_media(env) -> None:
    """Keep queued jobs from starting: the media breaker is open."""
    env.svc.gate.report_block(REASON_RATE_LIMITED, MEDIA_COOLDOWN_S, CLASS_MEDIA)


async def release_media(env) -> None:
    await env.clock.advance(MEDIA_COOLDOWN_S + 1)


async def wait_ok(env, vid: str = VID, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = (await env.client.get(f"/v1/videos/{vid}/transcript")).json()
        if body.get("transcript_status") == "ok":
            return body
        await asyncio.sleep(0.05)
    pytest.fail(f"transcript never became ok, last {body}")


@pytest.fixture(autouse=True)
def no_captions(env):
    env.fetcher.text = None
    hold_media(env)


async def test_opening_a_video_without_captions_queues_the_transcription_by_default(env):
    body = await summary(env, title="A title")
    assert body["status"] == "pending" and body["transcript_status"] == "transcribing"
    assert body["progress"] == 0.0 and body["estimate_s"] == LEGACY_ESTIMATE_S
    assert body["text"] is None and "job_id" not in body and "message" not in body
    (job,) = jobs(env)
    assert (job["kind"], job["user"], job["video_id"]) == ("transcript", "owner", VID)
    assert job["priority"] == INTERACTIVE
    assert env.llm.calls == []

    again = await summary(env)
    assert again["status"] == "pending" and again["transcript_status"] == "transcribing"
    assert len(jobs(env)) == 1


async def test_the_next_request_already_knows_the_video_has_no_captions(env):
    await summary(env)
    env.fetcher.calls.clear()
    insight = (await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})).json()
    assert insight["status"] == "pending" and insight["transcript_status"] == "transcribing"
    assert env.fetcher.calls == [] and len(jobs(env)) == 1


async def test_a_known_no_captions_video_is_queued_without_asking_youtube_again(env):
    env.svc.db.execute(
        "INSERT INTO no_captions(video_id,checked_at) VALUES(?,?)", [VID, time.time()]
    )
    env.svc.transcripts.store_meta(VID, {"duration_s": 600, "title": "t"})
    body = await summary(env)
    assert body["status"] == "pending" and body["transcript_status"] == "transcribing"
    assert env.fetcher.calls == [] and len(jobs(env)) == 1


async def test_insight_and_ask_start_the_transcription_too(env):
    insight = (await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})).json()
    assert insight["status"] == "pending" and insight["transcript_status"] == "transcribing"
    (job,) = jobs(env)
    assert job["priority"] == INTERACTIVE
    env.svc.db.execute("DELETE FROM jobs")
    ask = (
        await env.client.post(f"/v1/videos/{VID}/ask", json={"question": "Why?", "wait_ms": 5000})
    ).json()
    assert ask["status"] == "pending" and ask["transcript_status"] == "transcribing"
    assert ask["answer"] is None and len(jobs(env)) == 1


async def test_an_ad_hoc_summary_also_counts_as_opening_the_video(env):
    body = (
        await env.client.post(f"/v1/videos/{VID}/summary", json={"prompt_text": "Hi {title}"})
    ).json()
    assert body["status"] == "pending" and body["transcript_status"] == "transcribing"


async def test_off_keeps_the_ask_first_answer(env):
    await policy(env, auto_transcribe="off")
    body = await summary(env)
    assert body["status"] == "needs_transcript" and body["transcript_status"] == "none"
    assert body["can_transcribe"] is True and body["estimate_s"] == LEGACY_ESTIMATE_S
    assert jobs(env) == []


async def test_the_side_panel_only_triggers_on_dwell(env):
    on_open = await summary(env, prompt="panel")
    assert on_open["status"] == "needs_transcript" and jobs(env) == []

    await policy(env, auto_transcribe="on_dwell")
    dwell = await summary(env, prompt="panel")
    assert dwell["status"] == "pending" and dwell["transcript_status"] == "transcribing"
    (job,) = jobs(env)
    assert job["priority"] == BACKGROUND


async def test_the_summary_view_triggers_on_open_and_on_dwell_alike(env):
    for mode in ("on_open", "on_dwell"):
        env.svc.db.execute("DELETE FROM jobs")
        await policy(env, auto_transcribe=mode)
        body = await summary(env)
        assert body["status"] == "pending", mode
        assert [j["priority"] for j in jobs(env)] == [INTERACTIVE]


async def test_a_dwell_job_becomes_interactive_when_the_user_opens_the_video(env):
    await policy(env, auto_transcribe="on_dwell")
    await summary(env, prompt="panel")
    assert [j["priority"] for j in jobs(env)] == [BACKGROUND]
    again = await summary(env, prompt="panel")
    assert again["transcript_status"] == "transcribing"
    assert [j["priority"] for j in jobs(env)] == [BACKGROUND]
    opened = await summary(env)
    assert opened["transcript_status"] == "transcribing"
    assert [j["priority"] for j in jobs(env)] == [INTERACTIVE] and len(jobs(env)) == 1


async def test_explicit_transcribe_is_interactive_and_promotes_a_queued_background_job(env):
    await policy(env, auto_transcribe="on_dwell")
    await summary(env, prompt="panel")
    queued = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()
    assert queued["transcript_status"] == "transcribing"
    (job,) = jobs(env)
    assert job["id"] == queued["job_id"] and job["priority"] == INTERACTIVE


async def test_videos_longer_than_the_limit_still_ask(env):
    env.fetcher.meta_extra = {"duration_s": 31 * MINUTE}
    body = await summary(env)
    assert body["status"] == "needs_transcript" and body["can_transcribe"] is True
    assert body["estimate_s"] and jobs(env) == []

    await policy(env, auto_transcribe_max_minutes=60)
    assert (await summary(env))["status"] == "pending"


async def test_exactly_the_limit_is_still_automatic(env):
    env.fetcher.meta_extra = {"duration_s": 30 * MINUTE}
    assert (await summary(env))["status"] == "pending"


async def test_a_lower_limit_makes_shorter_videos_ask(env):
    await policy(env, auto_transcribe_max_minutes=10)
    env.fetcher.meta_extra = {"duration_s": 11 * MINUTE}
    assert (await summary(env))["status"] == "needs_transcript"
    env.svc.db.execute("DELETE FROM no_captions")
    env.fetcher.meta_extra = {"duration_s": 10 * MINUTE}
    assert (await summary(env))["status"] == "pending"


async def test_a_video_of_unknown_length_asks_first(env):
    env.fetcher.meta_extra = {"duration_s": None}
    body = await summary(env)
    assert body["status"] == "needs_transcript" and jobs(env) == []


@pytest.mark.parametrize("meta", [{"is_live": True}, {"duration_s": 4 * 3600}])
async def test_live_and_too_long_videos_are_never_transcribed_automatically(env, meta):
    await policy(env, auto_transcribe_max_minutes=24 * 60)
    env.fetcher.meta_extra = meta
    body = await summary(env)
    assert body["status"] == "needs_transcript" and body["can_transcribe"] is False
    assert jobs(env) == []


async def test_a_full_queue_falls_back_to_asking_instead_of_an_error(env):
    env.cfg.captions.transcribe_max_active_per_user = 1
    assert (await summary(env))["status"] == "pending"
    other = await summary(env, OTHER)
    assert other["status"] == "needs_transcript" and other["can_transcribe"] is True
    assert len(jobs(env)) == 1


async def test_another_users_running_job_is_joined_not_duplicated(env):
    partner = httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": "Bearer utb_othertoken"},
    )
    assert (await summary(env))["status"] == "pending"
    body = (await partner.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})).json()
    assert body["status"] == "pending" and body["transcript_status"] == "transcribing"
    assert len(jobs(env)) == 1
    await partner.aclose()


async def test_no_engine_for_the_language_means_no_automatic_start(env):
    env.cfg.captions.asr_engines = [
        AsrEngineConfig(
            name="box", url="http://box.example/v1/audio/transcriptions", languages=["en"]
        )
    ]
    env.fetcher.meta_extra = {"language": "ja"}
    body = await summary(env)
    assert body["status"] == "needs_transcript" and body["can_transcribe"] is False
    assert jobs(env) == []


async def test_estimate_follows_the_chosen_engine_and_its_parallelism(env):
    env.cfg.captions.asr_engines = [
        AsrEngineConfig(
            name="mac",
            url="http://mac.example/v1/audio/transcriptions",
            speed_factor=37.5,
            max_parallel=3,
            overhead_s=1.0,
            priority=10,
        ),
        AsrEngineConfig(
            name="box",
            url="http://box.example/v1/audio/transcriptions",
            speed_factor=3.0,
            overhead_s=2.0,
            priority=20,
        ),
    ]
    download = 5 + 900 / 300
    assert (await summary(env))["estimate_s"] == round(download + 1 + 900 / (37.5 * 2))
    await policy(env, auto_transcribe="off")
    env.svc.transcription.engines._penalize(env.cfg.captions.asr_engines[0])
    box = await summary(env)
    assert box["estimate_s"] == round(download + 2 + 900 / 3.0)


async def test_jobs_are_claimed_interactive_first_then_oldest(env):
    await env.svc.jobs.stop()
    await release_media(env)
    queue = env.svc.jobs
    first = queue.enqueue_transcript("owner", "aaaaaaaaaaa", None, BACKGROUND)
    second = queue.enqueue_transcript("owner", "bbbbbbbbbbb", None, BACKGROUND)
    urgent = queue.enqueue_transcript("owner", "ccccccccccc", None, INTERACTIVE)
    order = [queue._claim()["id"] for _ in range(3)]
    assert order == [urgent["id"], first["id"], second["id"]]
    assert queue._claim() is None
    queue.start()


async def test_queued_jobs_wait_while_the_media_endpoint_is_limited(env):
    job = env.svc.jobs.enqueue_transcript("owner", VID, "t", INTERACTIVE)
    await asyncio.sleep(0.2)
    assert env.svc.jobs.get(job["id"])["status"] == "queued"
    listed = (await env.client.get("/v1/jobs")).json()["jobs"][0]
    assert listed["state"] == "waiting" and listed["retry_after_s"] == MEDIA_COOLDOWN_S


@NEEDS_FFMPEG
async def test_the_whole_fast_path_stores_the_segments_engine_and_model(env):
    first = await summary(env)
    assert first["status"] == "pending" and first["transcript_status"] == "transcribing"
    await release_media(env)
    done = await wait_ok(env)
    assert done["source"] == "asr" and done["engine"] == "default" and done["model"] == "whisper-1"

    ready = await summary(env)
    assert ready["status"] == "ready" and ready["source"] == "asr"
    sent = " ".join(m["content"] for m in env.llm.calls[-1]["messages"])
    assert "Hello there. How are you doing today?" in sent

    row = env.svc.db.one("SELECT * FROM transcripts WHERE video_id=?", [VID])
    assert row["source"] == "asr" and row["lang"] == "en"
    assert row["engine"] == "default" and row["model"] == "whisper-1"
    assert json.loads(row["segments"]) == [[0.0, 4.0, "Hello there. How are you doing today?"]]
    assert env.llm.audio_calls[0]["response_format"] == "verbose_json"
    assert env.llm.audio_calls[0]["timestamp_granularities[]"] == "segment"
    assert not (env.cfg.media_dir / VID).exists()
    (job,) = jobs(env)
    assert job["status"] == "ready" and job["progress"] == 1.0


@NEEDS_FFMPEG
async def test_a_transcription_runs_while_only_the_caption_endpoint_is_limited(env):
    await release_media(env)
    env.svc.gate.report_block(REASON_RATE_LIMITED, MEDIA_COOLDOWN_S, CLASS_CAPTIONS)
    env.svc.transcripts.store_meta(VID, {"duration_s": 600, "title": "t"})
    env.svc.jobs.enqueue_transcript("owner", VID, "t", INTERACTIVE)
    done = await wait_ok(env)
    assert done["source"] == "asr"
    assert env.fetcher.calls == []
    assert not env.svc.gate.healthy(CLASS_CAPTIONS) and env.svc.gate.healthy(CLASS_MEDIA)


def test_an_old_database_gains_the_new_columns_and_keeps_its_rows(tmp_path):
    import sqlite3

    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.executescript(
        """
        CREATE TABLE transcripts(video_id TEXT PRIMARY KEY, lang TEXT, source TEXT NOT NULL,
          text TEXT NOT NULL, fetched_at REAL NOT NULL);
        CREATE TABLE jobs(id TEXT PRIMARY KEY, user TEXT NOT NULL, video_id TEXT NOT NULL,
          lang TEXT NOT NULL, translate_to TEXT, status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
          error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL);
        INSERT INTO transcripts VALUES('abcdefghijk','en','asr','[00:00] old',1.0);
        INSERT INTO jobs VALUES('j1','owner','abcdefghijk','auto',NULL,'queued',0,NULL,1.0,1.0);
        """
    )
    old.commit()
    old.close()

    from utubot.db import Database

    db = Database(path)
    row = db.one("SELECT * FROM transcripts WHERE video_id='abcdefghijk'")
    assert row["text"] == "[00:00] old" and row["engine"] is None and row["segments"] is None
    job = db.one("SELECT * FROM jobs WHERE id='j1'")
    assert job["priority"] == BACKGROUND and job["kind"] == "captions"
    db.close()
