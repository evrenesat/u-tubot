from __future__ import annotations

import asyncio
import shutil
import time

import httpx
import pytest
import pytest_asyncio

from tests.fakes import settle
from utubot.config import AssessConfig, Config
from utubot.db import Database
from utubot.llm import BACKGROUND
from utubot.youtube import (
    CLASS_MEDIA,
    FETCH_CLASSES,
    REASON_FORBIDDEN_MEDIA,
    REASON_NETWORK,
    REASON_PRIVATE,
    REASON_RATE_LIMITED,
    REASON_TOO_LONG,
    YoutubeBlocked,
    YoutubeDelayed,
    YoutubeVideoError,
)

VID = "abcdefghijk"
OTHER = "bcdefghijkl"
NEEDS_FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
NO_CAPTIONS_MESSAGE = "No captions. Transcribe the audio in the background?"
ESTIMATE_S = 5 + 900 / 300 + 30 + 900 / 1.5  # download + legacy engine overhead + audio / speed


async def summary(env, vid: str = VID, **params):
    return await env.client.get(f"/v1/videos/{vid}/summary", params={"wait_ms": 5000, **params})


async def wait_transcript(env, want: str, vid: str = VID, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = (await env.client.get(f"/v1/videos/{vid}/transcript")).json()
        if body.get("transcript_status") == want:
            return body
        await asyncio.sleep(0.05)
    pytest.fail(f"timeout waiting for {want}, last {body}")


@pytest_asyncio.fixture(autouse=True)
async def ask_first(env):
    """These tests are about the ask-first flow: the owner opted out of automatic transcription."""
    assert (
        await env.client.put("/v1/me/policy", json={"auto_transcribe": "off"})
    ).status_code == 200


def rows(env, table: str) -> int:
    return env.svc.db.one(f"SELECT COUNT(*) AS n FROM {table}")["n"]


MEDIA_COOLDOWN_S = 3600


def audio_unreachable(env) -> None:
    """The audio fallback is off: the media class cools too, so a caption limit stays "delayed"."""
    env.svc.gate.report_block(REASON_RATE_LIMITED, MEDIA_COOLDOWN_S, CLASS_MEDIA)


# ---- transient failures: pending + delayed, never cached ---------------------------------------


async def test_429_is_pending_delayed_and_never_cached(env):
    audio_unreachable(env)
    env.fetcher.error = YoutubeBlocked(REASON_RATE_LIMITED, 120)
    body = (await summary(env, title="A title")).json()
    assert body["status"] == "pending" and body["transcript_status"] == "delayed"
    assert body["retry_after_s"] == 120 and body["text"] is None
    assert body["error"] == "YouTube is limiting transcript downloads; retrying in ~2 min"
    assert "429" not in str(body) and "http" not in str(body)
    assert env.llm.calls == []
    assert rows(env, "summaries") == 0 and rows(env, "transcripts") == 0
    assert rows(env, "no_captions") == 0

    again = (await summary(env)).json()
    assert again["status"] == "pending" and again["transcript_status"] == "delayed"
    assert again["retry_after_s"] == 120
    assert env.fetcher.calls == [VID]

    insight = (await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})).json()
    assert insight["status"] == "pending" and insight["transcript_status"] == "delayed"
    ask = await env.client.post(f"/v1/videos/{VID}/ask", json={"question": "Why?", "wait_ms": 5000})
    assert ask.json()["status"] == "pending" and ask.json()["transcript_status"] == "delayed"
    assert env.fetcher.calls == [VID] and env.llm.calls == []

    env.fetcher.error = None
    await env.clock.advance(60)
    mid = (await summary(env)).json()
    assert mid["transcript_status"] == "delayed" and mid["retry_after_s"] == 60
    await env.clock.advance(61)
    probing = (await summary(env)).json()
    assert probing["transcript_status"] == "delayed" and probing["retry_after_s"] == 10
    await settle()
    ready = (await summary(env)).json()
    assert ready["status"] == "ready" and ready["transcript_status"] == "ok"
    assert ready["source"] == "youtube_captions"
    assert env.fetcher.calls == [VID, VID]


async def test_network_error_is_delayed_without_opening_the_breaker(env):
    env.fetcher.error = YoutubeDelayed(REASON_NETWORK, 60)
    body = (await summary(env)).json()
    assert body["status"] == "pending" and body["transcript_status"] == "delayed"
    assert body["retry_after_s"] == 60 and "retrying in ~1 min" in body["error"]
    assert env.svc.gate.healthy()
    env.fetcher.error = None
    assert (await summary(env)).json()["status"] == "ready"


async def test_background_work_is_paused_not_failed_during_cooldown(env):
    audio_unreachable(env)
    env.svc.gate.report_block(REASON_RATE_LIMITED, 300, FETCH_CLASSES)
    task = asyncio.create_task(env.svc.transcripts.get(VID, BACKGROUND))
    await settle()
    assert not task.done() and env.fetcher.calls == []
    assert not env.svc.assessor._bg.locked()
    interactive = (await summary(env)).json()
    assert interactive["transcript_status"] == "delayed"
    await env.clock.advance(301)
    transcript = await asyncio.wait_for(task, 5)
    assert transcript.source == "youtube_captions" and env.fetcher.calls == [VID]
    assert env.svc.gate.state(*FETCH_CLASSES) == "closed"


# ---- no captions: ask first, never build on the title ----------------------------------------


async def test_no_captions_needs_transcript_and_never_calls_the_llm(env):
    env.fetcher.text = None
    r = await summary(env, title="Known title", channel="Chan")
    body = r.json()
    assert body["status"] == "needs_transcript" and body["transcript_status"] == "none"
    assert body["can_transcribe"] is True and body["message"] == NO_CAPTIONS_MESSAGE
    assert body["estimate_s"] == round(ESTIMATE_S)
    assert body["text"] is None and body["source"] is None and body["error"] is None
    assert env.llm.calls == []
    assert rows(env, "summaries") == 0

    insight = (await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})).json()
    assert insight["status"] == "needs_transcript" and insight["can_transcribe"] is True
    ask = (
        await env.client.post(f"/v1/videos/{VID}/ask", json={"question": "Why?", "wait_ms": 5000})
    ).json()
    assert ask["status"] == "needs_transcript" and ask["answer"] is None
    adhoc = (
        await env.client.post(f"/v1/videos/{VID}/summary", json={"prompt_text": "Hi {title}"})
    ).json()
    assert adhoc["status"] == "needs_transcript"
    assert env.llm.calls == []
    assert env.fetcher.calls == [VID]


async def test_no_captions_status_endpoint_and_expiry(env):
    env.fetcher.text = None
    await summary(env)
    status = (await env.client.get(f"/v1/videos/{VID}/transcript")).json()
    assert status["transcript_status"] == "none" and status["can_transcribe"] is True
    old = time.time() - env.cfg.transcripts.no_captions_ttl_s - 1
    env.svc.db.execute("UPDATE no_captions SET checked_at=?", [old])
    assert (await env.client.get(f"/v1/videos/{VID}/transcript")).json()[
        "transcript_status"
    ] == "unknown"
    env.fetcher.text = "[00:00] Captions arrived. " * 5
    ready = (await summary(env)).json()
    assert ready["status"] == "ready" and ready["source"] == "youtube_captions"
    assert env.fetcher.calls == [VID, VID]


async def test_unknown_video_status_does_not_touch_youtube(env):
    body = (await env.client.get(f"/v1/videos/{VID}/transcript")).json()
    assert body["transcript_status"] == "unknown" and env.fetcher.calls == []


@pytest.mark.parametrize("meta", [{"is_live": True}, {"duration_s": 4 * 3600}])
async def test_live_or_too_long_videos_cannot_be_transcribed(env, meta):
    env.fetcher.text = None
    env.fetcher.meta_extra = meta
    body = (await summary(env)).json()
    assert body["status"] == "needs_transcript" and body["can_transcribe"] is False
    assert body["estimate_s"] is None and "Transcribe" not in body["message"]
    refused = await env.client.post(f"/v1/videos/{VID}/transcribe")
    assert refused.status_code == 400


# ---- the ask-to-transcribe flow ---------------------------------------------------------------


@NEEDS_FFMPEG
async def test_transcribe_job_is_idempotent_and_summary_uses_the_asr_transcript(env):
    env.fetcher.text = None
    assert (await summary(env)).json()["status"] == "needs_transcript"
    first = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()
    assert first["transcript_status"] == "transcribing" and first["job_id"]
    assert first["status"] in ("queued", "running") and first["estimate_s"] == round(ESTIMATE_S)
    again = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()
    assert again["job_id"] == first["job_id"]
    done = await wait_transcript(env, "ok")
    assert done["source"] == "asr"

    body = (await summary(env)).json()
    assert body["status"] == "ready" and body["source"] == "asr"
    assert body["transcript_status"] == "ok"
    sent = " ".join(m["content"] for m in env.llm.calls[-1]["messages"])
    assert "Hello there." in sent
    assert env.fetcher.calls == [VID, VID]
    assert not (env.cfg.media_dir / VID).exists()
    assert rows(env, "jobs") == 1

    insight = (await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})).json()
    assert insight["status"] == "ready" and insight["source"] == "asr"

    finished = await env.client.post(f"/v1/videos/{VID}/transcribe")
    assert finished.json()["status"] == "ready" and finished.json()["transcript_status"] == "ok"
    assert rows(env, "jobs") == 1
    captions = (await env.client.get(f"/v1/videos/{VID}/captions")).json()
    assert captions["status"] == "none"


@NEEDS_FFMPEG
async def test_summary_reports_transcribing_with_progress_while_the_job_waits(env):
    env.fetcher.text = None
    await summary(env)
    env.svc.gate.report_block(REASON_RATE_LIMITED, 600)
    queued = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()
    await settle()
    waiting = (await summary(env)).json()
    assert waiting["status"] == "pending" and waiting["transcript_status"] == "transcribing"
    assert waiting["progress"] == 0.0 and waiting["estimate_s"] == round(ESTIMATE_S)
    assert (await env.client.get(f"/v1/videos/{VID}/transcript")).json()["job_id"] == queued[
        "job_id"
    ]
    job = (await env.client.get("/v1/jobs")).json()["jobs"][0]
    assert job["state"] == "waiting" and job["error"] is None
    assert job["retry_after_s"] == 600
    await env.clock.advance(601)
    await wait_transcript(env, "ok")
    final = (await env.client.get("/v1/jobs")).json()["jobs"][0]
    assert final["state"] == "ready" and final["progress"] == 1.0 and final["retry_after_s"] is None
    assert (await summary(env)).json()["source"] == "asr"


@NEEDS_FFMPEG
async def test_job_whose_download_is_blocked_goes_back_to_the_queue(env):
    env.fetcher.text = None
    await summary(env)
    pipeline = env.svc.jobs.pipeline
    real = pipeline.downloader
    attempts = []

    async def flaky(video_id, out_dir, started):
        attempts.append(video_id)
        if len(attempts) == 1:
            raise YoutubeBlocked(REASON_RATE_LIMITED, 300)
        return await real(video_id, out_dir, started)

    pipeline.downloader = flaky
    await env.client.post(f"/v1/videos/{VID}/transcribe")
    for _ in range(100):
        await asyncio.sleep(0.05)
        if not env.svc.gate.healthy():
            break
    assert not env.svc.gate.healthy()
    job = (await env.client.get("/v1/jobs")).json()["jobs"][0]
    assert job["state"] == "waiting" and job["error"] is None
    assert (await env.client.get(f"/v1/videos/{VID}/transcript")).json()[
        "transcript_status"
    ] == "transcribing"
    await env.clock.advance(301)
    await wait_transcript(env, "ok")
    assert len(attempts) == 2


async def test_a_failed_transcription_is_reported_and_can_be_retried(env):
    env.fetcher.text = None
    await summary(env)

    async def broken(video_id, out_dir, started):
        raise RuntimeError("yt-dlp exploded with https://x.example/a?token=SECRET")

    env.svc.jobs.pipeline.downloader = broken
    await env.client.post(f"/v1/videos/{VID}/transcribe")
    status = await wait_transcript(env, "failed")
    assert status["error"] == "transcription failed" and status["can_transcribe"] is True
    assert "SECRET" not in str(status)
    body = (await summary(env)).json()
    assert body["status"] == "failed" and body["transcript_status"] == "failed"
    job = (await env.client.get("/v1/jobs")).json()["jobs"][0]
    assert job["state"] == "failed" and job["finished_at"] is not None
    retry = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()
    assert retry["job_id"] != job["id"]


async def test_transcribe_validates_and_limits(env):
    assert (await env.client.post("/v1/videos/short/transcribe")).status_code == 400
    anon = httpx.AsyncClient(transport=env.client._transport, base_url="http://utubot")
    assert (await anon.post(f"/v1/videos/{VID}/transcribe")).status_code == 401
    assert (await anon.get(f"/v1/videos/{VID}/transcript")).status_code == 401
    assert (await anon.get("/v1/jobs")).status_code == 401
    env.cfg.captions.transcribe_max_active_per_user = 1
    env.svc.gate.report_block(REASON_RATE_LIMITED, 600)
    assert (await env.client.post(f"/v1/videos/{VID}/transcribe")).status_code == 200
    assert (await env.client.post(f"/v1/videos/{VID}/transcribe")).status_code == 200
    limited = await env.client.post(f"/v1/videos/{OTHER}/transcribe")
    assert limited.status_code == 429


async def test_jobs_lists_only_my_jobs_with_kind_title_and_state(env):
    env.svc.gate.report_block(REASON_RATE_LIMITED, 600)
    await env.client.post(f"/v1/videos/{VID}/transcribe", params={"title": "My video"})
    await env.client.post(f"/v1/videos/{OTHER}/captions", json={"lang": "auto"})
    partner = {"Authorization": "Bearer utb_othertoken"}
    await env.client.post(
        "/v1/videos/cdefghijklm/transcribe", params={"title": "Theirs"}, headers=partner
    )
    mine = (await env.client.get("/v1/jobs")).json()["jobs"]
    assert {(j["kind"], j["video_id"], j["state"]) for j in mine} == {
        ("transcript", VID, "waiting"),
        ("captions", OTHER, "waiting"),
    }
    transcript = next(j for j in mine if j["kind"] == "transcript")
    assert transcript["title"] == "My video"
    assert set(transcript) >= {"id", "progress", "created_at", "finished_at", "error"}
    theirs = (await env.client.get("/v1/jobs", headers=partner)).json()["jobs"]
    assert [j["video_id"] for j in theirs] == ["cdefghijklm"]
    assert len((await env.client.get("/v1/jobs", params={"limit": 1})).json()["jobs"]) == 1
    assert (await env.client.get("/v1/jobs", params={"limit": 0})).status_code == 400
    old_style = (await env.client.get("/v1/captions/jobs")).json()["jobs"]
    assert [j["video_id"] for j in old_style] == [OTHER]


# ---- volume: every transcript once, tier-2 only when it pays off -----------------------------


async def test_a_transcript_is_fetched_once_across_every_path(env):
    q = {"video_id": VID, "title": "Does it work?", "duration_s": 900}
    await env.client.post("/v1/assess", json={"videos": [q], "wait_ms": 2000})
    await env.svc.assessor.drain()
    await asyncio.gather(
        summary(env),
        summary(env, prompt="builtin/takeaways"),
        summary(env, prompt="panel"),
        env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000}),
        env.client.post(f"/v1/videos/{VID}/ask", json={"question": "Why?", "wait_ms": 5000}),
    )
    await env.client.post("/v1/assess", json={"videos": [q], "wait_ms": 2000})
    await env.svc.assessor.drain()
    assert env.fetcher.calls == [VID]


async def test_tier2_default_cap_is_30():
    assert AssessConfig().tier2_daily_cap_per_user == 30


def question(vid: str = VID) -> dict:
    return {"video_id": vid, "title": "Does it work?", "duration_s": 900}


async def test_tier2_runs_only_for_a_title_question_or_clickbait(env):
    plain = [{"video_id": "plain000001", "title": "A normal tutorial", "duration_s": 900}]
    await env.client.post("/v1/assess", json={"videos": plain, "wait_ms": 2000})
    await env.svc.assessor.drain()
    assert env.fetcher.calls == []
    await env.client.post("/v1/assess", json={"videos": [question()], "wait_ms": 2000})
    await env.svc.assessor.drain()
    assert env.fetcher.calls == [VID]


async def test_tier2_waits_for_a_healthy_gate_and_costs_no_slot_meanwhile(env):
    env.svc.gate.report_block(REASON_RATE_LIMITED, 300)
    await env.client.post("/v1/assess", json={"videos": [question()], "wait_ms": 2000})
    await env.svc.assessor.drain()
    assert env.fetcher.calls == [] and rows(env, "tier2_usage") == 0
    await env.clock.advance(301)
    await env.client.post("/v1/assess", json={"videos": [question()], "wait_ms": 2000})
    await env.svc.assessor.drain()
    assert env.fetcher.calls == [VID] and rows(env, "tier2_usage") == 1
    verdict = (await env.client.post("/v1/assess", json={"videos": [question()]})).json()
    assert verdict["results"][0]["answer_short"] == "Yes, since v3."


async def test_tier2_skips_videos_known_to_have_no_captions(env):
    env.fetcher.text = None
    await env.client.post("/v1/assess", json={"videos": [question()], "wait_ms": 2000})
    await env.svc.assessor.drain()
    assert env.fetcher.calls == [VID] and rows(env, "tier2_usage") == 1
    await env.client.post("/v1/assess", json={"videos": [question()], "wait_ms": 2000})
    await env.svc.assessor.drain()
    assert env.fetcher.calls == [VID] and rows(env, "tier2_usage") == 1
    assert env.llm.calls and not any(
        "analyse a YouTube video" in c["messages"][0]["content"] for c in env.llm.calls
    )


async def test_tier2_is_not_scheduled_while_the_background_fetch_queue_is_full(env):
    env.cfg.youtube.max_background_queue = 0
    await env.client.post("/v1/assess", json={"videos": [question()], "wait_ms": 2000})
    await env.svc.assessor.drain()
    assert env.fetcher.calls == [] and rows(env, "tier2_usage") == 0


async def test_a_paused_tier2_fetch_does_not_hold_the_triage_slots(env):
    env.svc.gate.report_block(REASON_RATE_LIMITED, 300)
    assessor = env.svc.assessor
    task = asyncio.create_task(assessor._deep_analysis(VID, {"title_question": "Why?"}, 900))
    await settle()
    assert not task.done() and not assessor._bg.locked()
    r = await env.client.post(
        "/v1/assess", json={"videos": [{"video_id": OTHER, "title": "Another one"}]}
    )
    assert r.json()["results"][0]["status"] == "ready"
    await env.clock.advance(301)
    await asyncio.wait_for(task, 5)
    assert env.svc.db.one("SELECT 1 FROM deep WHERE video_id=?", [VID]) is not None


# ---- legacy rows -----------------------------------------------------------------------------


def test_title_only_rows_from_before_are_purged_on_start(tmp_path):
    path = tmp_path / "old.sqlite"
    db = Database(path)
    now = time.time()
    db.execute(
        "INSERT INTO transcripts(video_id,lang,source,text,fetched_at) VALUES(?,?,?,?,?)",
        [VID, None, "metadata_only", "", now],
    )
    db.execute(
        "INSERT INTO transcripts(video_id,lang,source,text,fetched_at) VALUES(?,?,?,?,?)",
        [OTHER, "en", "youtube_captions", "real text", now],
    )
    for key, src in (("a", "metadata_only"), ("b", "youtube_captions")):
        db.execute(
            "INSERT INTO summaries(video_id,prompt_key,content_hash,language,text,source,"
            "created_at) VALUES(?,?,?,?,?,?,?)",
            [VID, key, "h", "en", "vague bullets", src, now],
        )
    for vid, src in ((VID, "metadata_only"), (OTHER, "asr")):
        db.execute(
            "INSERT INTO insights(video_id,language,json,created_at) VALUES(?,?,?,?)",
            [vid, "en", f'{{"summary": "x", "source": "{src}"}}', now],
        )
    db.close()
    fresh = Database(path)
    assert [r["video_id"] for r in fresh.all("SELECT video_id FROM transcripts")] == [OTHER]
    assert [r["prompt_key"] for r in fresh.all("SELECT prompt_key FROM summaries")] == ["b"]
    assert [r["video_id"] for r in fresh.all("SELECT video_id FROM insights")] == [OTHER]


def test_jobs_table_gains_the_new_columns_on_an_old_database(tmp_path):
    import sqlite3

    path = tmp_path / "older.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE jobs(id TEXT PRIMARY KEY, user TEXT NOT NULL, video_id TEXT NOT NULL,"
        " lang TEXT NOT NULL, translate_to TEXT, status TEXT NOT NULL,"
        " progress REAL NOT NULL DEFAULT 0, error TEXT, created_at REAL NOT NULL,"
        " updated_at REAL NOT NULL)"
    )
    conn.execute(
        "INSERT INTO jobs VALUES('j1','owner','abcdefghijk','auto',NULL,'ready',1,NULL,1,1)"
    )
    conn.commit()
    conn.close()
    db = Database(path)
    row = db.one("SELECT kind, title, finished_at FROM jobs WHERE id='j1'")
    assert row["kind"] == "captions" and row["title"] is None and row["finished_at"] is None


def test_config_defaults_match_the_incident_fix():
    cfg = Config()
    assert cfg.youtube.max_concurrent == 1
    assert cfg.youtube.min_interval_s == 3.0
    assert (cfg.youtube.cooldown_base_s, cfg.youtube.cooldown_max_s) == (300.0, 3600.0)
    assert cfg.transcripts.no_captions_ttl_s == 3 * 86400


# ---- review fixes ------------------------------------------------------------------------------


def job_row(env, vid: str = VID) -> dict:
    return dict(
        env.svc.db.one("SELECT * FROM jobs WHERE video_id=? ORDER BY created_at DESC", [vid])
    )


async def run_until(env, done, step: float = 400.0, rounds: int = 60) -> None:
    """Let the job worker run, moving the fake clock past each retry delay, until `done()`."""
    for _ in range(rounds):
        await asyncio.sleep(0.05)
        if done():
            return
        await env.clock.advance(step)
    pytest.fail("condition not reached")


def job_finished(env, vid: str = VID):
    return lambda: job_row(env, vid)["status"] in ("ready", "failed")


async def test_a_403_on_the_media_url_fails_the_one_video_and_leaves_the_breaker_alone(env):
    env.fetcher.text = None
    await summary(env)
    calls = []

    async def forbidden(video_id, out_dir, started):
        calls.append(video_id)
        raise YoutubeVideoError(REASON_FORBIDDEN_MEDIA)

    env.svc.jobs.pipeline.downloader = forbidden
    await env.client.post(f"/v1/videos/{VID}/transcribe")
    await run_until(env, job_finished(env))
    job = job_row(env)
    assert job["status"] == "failed" and job["attempts"] == 0 and len(calls) == 1
    assert job["error"] == "YouTube refused the download for this video."
    assert env.svc.gate.healthy() and env.svc.gate.state() == "closed"
    env.fetcher.text = "[00:00] Plenty of captions here. " * 5
    other = (await summary(env, OTHER)).json()
    assert other["status"] == "ready"
    failed = (await summary(env)).json()
    assert failed["status"] == "failed" and failed["transcript_status"] == "failed"
    assert failed["reason"] == "forbidden" and failed["can_transcribe"] is True
    status = (await env.client.get(f"/v1/videos/{VID}/transcript")).json()
    assert status["transcript_status"] == "failed" and status["reason"] == "forbidden"


async def test_a_private_video_is_reported_as_failed_with_a_reason_and_cannot_be_transcribed(env):
    env.fetcher.error = YoutubeVideoError(REASON_PRIVATE)
    body = (await summary(env)).json()
    assert body["status"] == "failed" and body["transcript_status"] == "failed"
    assert body["reason"] == "private" and body["error"] == "This video is private."
    assert body["can_transcribe"] is False and body["text"] is None
    assert env.svc.gate.healthy() and env.llm.calls == []
    again = (await summary(env)).json()
    assert again["reason"] == "private" and env.fetcher.calls == [VID]
    insight = (await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})).json()
    assert insight["status"] == "failed" and insight["reason"] == "private"
    refused = await env.client.post(f"/v1/videos/{VID}/transcribe")
    assert refused.status_code == 400 and "private" in refused.json()["error"]
    status = (await env.client.get(f"/v1/videos/{VID}/transcript")).json()
    assert status["transcript_status"] == "failed" and status["can_transcribe"] is False


async def test_a_job_hitting_a_transient_error_is_requeued_up_to_the_attempt_cap(env):
    env.fetcher.text = None
    await summary(env)
    calls = []

    async def flaky(video_id, out_dir, started):
        calls.append(video_id)
        raise YoutubeDelayed(REASON_NETWORK, 30)

    env.svc.jobs.pipeline.downloader = flaky
    await env.client.post(f"/v1/videos/{VID}/transcribe")
    await asyncio.sleep(0.3)
    job = job_row(env)
    assert job["status"] == "queued" and job["attempts"] == 1 and len(calls) == 1
    listed = (await env.client.get("/v1/jobs")).json()["jobs"][0]
    assert listed["state"] == "waiting" and 0 < listed["retry_after_s"] <= 30
    await run_until(env, job_finished(env), step=31.0)
    job = job_row(env)
    assert job["status"] == "failed" and job["attempts"] == 2 and len(calls) == 3
    assert job["error"] == "YouTube kept refusing the download, try again later"
    assert env.cfg.captions.job_max_attempts == 3
    assert env.svc.gate.healthy()


async def test_a_job_that_keeps_being_blocked_gives_up_instead_of_looping_forever(env):
    env.fetcher.text = None
    await summary(env)
    calls = []

    async def blocked(video_id, out_dir, started):
        calls.append(video_id)
        raise YoutubeBlocked(REASON_RATE_LIMITED, 300)

    env.svc.jobs.pipeline.downloader = blocked
    await env.client.post(f"/v1/videos/{VID}/transcribe")
    await run_until(env, job_finished(env), step=400.0)
    job = job_row(env)
    assert job["status"] == "failed" and len(calls) == 3
    assert job["error"] == "YouTube kept refusing the download, try again later"


async def test_a_job_over_the_duration_limit_fails_that_video_only(env):
    env.fetcher.text = None
    await summary(env)

    async def too_long(video_id, out_dir, started):
        raise YoutubeVideoError(REASON_TOO_LONG)

    env.svc.jobs.pipeline.downloader = too_long
    await env.client.post(f"/v1/videos/{VID}/transcribe")
    await run_until(env, job_finished(env))
    assert job_row(env)["error"] == "This video is too long to transcribe."
    refused = await env.client.post(f"/v1/videos/{VID}/transcribe")
    assert refused.status_code == 400
    body = (await summary(env)).json()
    assert body["status"] == "failed" and body["reason"] == "too_long"
    assert env.svc.gate.healthy()


# ---- ASR must not replace or ignore real captions ----------------------------------------------


async def test_a_transcribe_job_uses_captions_that_appeared_and_skips_the_asr(env):
    env.fetcher.text = None
    assert (await summary(env)).json()["status"] == "needs_transcript"
    env.fetcher.text = "[00:00] Real captions arrived. " * 5
    await env.client.post(f"/v1/videos/{VID}/transcribe")
    await run_until(env, job_finished(env), step=1.0)
    assert job_row(env)["status"] == "ready"
    assert env.llm.audio_calls == []
    status = (await env.client.get(f"/v1/videos/{VID}/transcript")).json()
    assert status["transcript_status"] == "ok" and status["source"] == "youtube_captions"
    assert (await summary(env)).json()["source"] == "youtube_captions"


@NEEDS_FFMPEG
async def test_a_transcribe_job_never_overwrites_captions_stored_meanwhile(env):
    env.fetcher.text = None
    await summary(env)
    real = env.svc.jobs.pipeline.downloader

    async def downloader(video_id, out_dir, started):
        env.svc.db.execute(
            "INSERT OR REPLACE INTO transcripts(video_id,lang,source,text,fetched_at)"
            " VALUES(?,?,?,?,?)",
            [video_id, "en", "youtube_captions", "[00:00] real captions", time.time()],
        )
        return await real(video_id, out_dir, started)

    env.svc.jobs.pipeline.downloader = downloader
    await env.client.post(f"/v1/videos/{VID}/transcribe")
    await run_until(env, job_finished(env), step=1.0)
    row = env.svc.db.one("SELECT source, text FROM transcripts WHERE video_id=?", [VID])
    assert row["source"] == "youtube_captions" and row["text"] == "[00:00] real captions"


# ---- tier-2 slot refunds -------------------------------------------------------------------------


def tier2_count(env) -> int:
    row = env.svc.db.one("SELECT SUM(count) AS n FROM tier2_usage")
    return row["n"] or 0


async def test_tier2_gives_the_daily_slot_back_when_the_fetch_is_delayed(env):
    env.fetcher.error = YoutubeDelayed(REASON_NETWORK, 60)
    await env.client.post("/v1/assess", json={"videos": [question()], "wait_ms": 2000})
    await env.svc.assessor.drain()
    assert env.fetcher.calls == [VID] and tier2_count(env) == 0
    env.fetcher.error = None
    await env.client.post("/v1/assess", json={"videos": [question()], "wait_ms": 2000})
    await env.svc.assessor.drain()
    assert tier2_count(env) == 1


async def test_tier2_refunds_when_the_fetch_hits_a_cooldown_and_keeps_the_slot_otherwise(env):
    assessor = env.svc.assessor
    day = assessor._take_tier2_slot("owner")
    assert day and tier2_count(env) == 1
    env.fetcher.error = YoutubeBlocked(REASON_RATE_LIMITED, 300)
    with pytest.raises(YoutubeBlocked):
        await assessor._tier2_job("owner", day, VID, {"title_question": "Why?"}, 900)
    assert tier2_count(env) == 0
    assessor._refund_tier2_slot("owner", day)
    assert tier2_count(env) == 0
    env.fetcher.error = None
    env.fetcher.text = None
    await env.clock.advance(301)
    day = assessor._take_tier2_slot("owner")
    await assessor._tier2_job("owner", day, OTHER, {"title_question": "Why?"}, 900)
    assert tier2_count(env) == 1


# ---- privacy of job ids --------------------------------------------------------------------------


async def test_the_transcript_endpoint_only_exposes_the_callers_own_job_id(env):
    env.svc.gate.report_block(REASON_RATE_LIMITED, 600)
    partner = {"Authorization": "Bearer utb_othertoken"}
    queued = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()
    mine = (await env.client.get(f"/v1/videos/{VID}/transcript")).json()
    assert mine["transcript_status"] == "transcribing" and mine["job_id"] == queued["job_id"]
    theirs = (await env.client.get(f"/v1/videos/{VID}/transcript", headers=partner)).json()
    assert theirs["transcript_status"] == "transcribing" and "job_id" not in theirs
    assert queued["job_id"] not in str(theirs)
    body = (await env.client.get(f"/v1/videos/{VID}/summary", headers=partner)).json()
    assert body["transcript_status"] == "transcribing" and queued["job_id"] not in str(body)
    other = (await env.client.post(f"/v1/videos/{VID}/transcribe", headers=partner)).json()
    assert other["job_id"] != queued["job_id"]


async def test_an_empty_caption_track_hold_answers_delayed_everywhere(env):
    env.svc.transcripts._record_hold(VID, "delayed", "empty_track", 3600)
    body = (await summary(env)).json()
    assert body["status"] == "pending" and body["transcript_status"] == "delayed"
    assert body["retry_after_s"] == 3600 and "retrying in ~60 min" in body["error"]
    status = (await env.client.get(f"/v1/videos/{VID}/transcript")).json()
    assert status["transcript_status"] == "delayed" and status["retry_after_s"] == 3600
    assert env.fetcher.calls == [] and env.llm.calls == []
