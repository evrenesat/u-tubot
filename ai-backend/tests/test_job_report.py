"""The job report: the event log of every stage, who asked, who fetched the result, and what the API and UI show."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import time
import uuid
import wave
from pathlib import Path

import httpx
import pytest

from tests.conftest import OTHER_TOKEN, PASSWORD, TOKEN, anon_client
from tests.test_asr_engines import FakeEngine, engine_cfg, make_wav, router
from tests.test_webui import WEB, _resolve, asset_urls, module_imports
from utubot.auth import hash_token
from utubot.captions import events
from utubot.captions import pipeline as pipeline_mod
from utubot.captions.asr import ASRResult
from utubot.captions.engines import EngineError
from utubot.captions.events import JobEvents, JobTrace, clean
from utubot.captions.pipeline import CaptionPipeline, download_audio
from utubot.captions.types import Segment
from utubot.config import Config
from utubot.db import Database
from utubot.llm import BACKGROUND
from utubot.youtube import (
    CLASS_MEDIA,
    REASON_NETWORK,
    REASON_RATE_LIMITED,
    YoutubeDelayed,
)

VID = "abcdefghijk"
OTHER = "bcdefghijkl"
NEEDS_FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
NEEDS_NODE = pytest.mark.skipif(not shutil.which("node"), reason="node missing")
HOLD_S = 3600
SECRET_URL = (
    "https://rr1---sn-abc.googlevideo.com/videoplayback?expire=1&sig=SECRETSIG&token=SECRETTOKEN"
)
FORBIDDEN_IN_EVENTS = ("googlevideo", "SECRETSIG", "SECRETTOKEN", "http://", "https://", TOKEN)


def hold_media(env) -> None:
    """Keep queued jobs from starting: the media breaker is open."""
    env.svc.gate.report_block(REASON_RATE_LIMITED, HOLD_S, CLASS_MEDIA)


def log_of(env, job_id: str) -> list[dict]:
    return env.svc.jobs.events.list(job_id)


def stages_of(env, job_id: str) -> list[str]:
    return [e["stage"] for e in log_of(env, job_id)]


def event(env, job_id: str, stage: str, status: str | None = None) -> dict:
    found = [
        e for e in log_of(env, job_id) if e["stage"] == stage and status in (None, e["status"])
    ]
    assert found, f"no {stage}/{status} event in {stages_of(env, job_id)}"
    return found[-1]


def in_order(seen: list[str], wanted: list[str]) -> bool:
    it = iter(seen)
    return all(stage in it for stage in wanted)


async def wait_state(client, job_id: str, states=("ready", "failed"), timeout: float = 15.0):
    deadline = time.time() + timeout
    doc: dict = {}
    while time.time() < deadline:
        doc = (await client.get(f"/v1/jobs/{job_id}")).json()
        if doc.get("state") in states:
            return doc
        await asyncio.sleep(0.05)
    pytest.fail(f"job {job_id} never reached {states}, last {doc.get('state')}")


def device_client(
    env, name: str = "Living room TV", token: str = "utb_tvtoken"
) -> httpx.AsyncClient:
    env.svc.db.execute(
        "INSERT INTO device_tokens(id,user,token_sha256,device,created_at) VALUES(?,?,?,?,?)",
        [f"dev{name[:3]}", "owner", hash_token(token), name, time.time()],
    )
    return httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {token}"},
    )


def partner_client(env) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )


def add_job(env, user: str = "owner", video_id: str = VID, status: str = "ready", **fields) -> str:
    job_id = fields.pop("id", uuid.uuid4().hex[:12])
    now = time.time()
    env.svc.db.execute(
        "INSERT INTO jobs(id,user,video_id,lang,status,progress,created_at,updated_at,kind,title,"
        "finished_at,priority,error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            job_id,
            user,
            video_id,
            "auto",
            status,
            1.0 if status == "ready" else 0.0,
            now - 60,
            now - 30,
            fields.get("kind", "transcript"),
            fields.get("title", "A title"),
            None if status in ("queued", "running") else now - 30,
            fields.get("priority", BACKGROUND),
            fields.get("error"),
        ],
    )
    return job_id


# ---- the log of a whole job ---------------------------------------------------------------------------


@NEEDS_FFMPEG
async def test_a_transcript_job_logs_every_stage_and_who_asked(env):
    env.fetcher.text = None
    queued = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()
    doc = await wait_state(env.client, queued["job_id"])
    assert doc["state"] == "ready", doc["events"]
    seen = [e["stage"] for e in doc["events"]]
    assert in_order(
        seen,
        [
            "queued",
            "started",
            "caption_recheck",
            "gate_wait",
            "audio_download",
            "ffmpeg",
            "chunking",
            "asr_chunk",
            "stitching",
            "asr",
            "text",
            "stored",
            "finished",
        ],
    )
    job_id = doc["id"]
    asked = event(env, job_id, "queued")["detail"]
    assert asked["user"] == "owner" and asked["client"] == "API token"
    assert asked["trigger"] == {"kind": "explicit"} and asked["priority"] == "interactive"
    assert asked["endpoint"] == "POST /v1/videos/{video_id}/transcribe"
    assert event(env, job_id, "caption_recheck")["detail"]["result"] == "no_captions"
    assert event(env, job_id, "gate_wait")["detail"]["klass"] == "media"
    audio = event(env, job_id, "audio_download", "ok")["detail"]
    assert audio["bytes"] > 0 and audio["seconds"] >= 0 and audio["source"] == "downloaded"
    assert 1.5 < event(env, job_id, "ffmpeg", "ok")["detail"]["audio_s"] < 2.5
    chunking = event(env, job_id, "chunking")["detail"]
    assert chunking["chunks"] == 1 and chunking["engines"] == ["default"]
    chunk = event(env, job_id, "asr_chunk", "ok")["detail"]
    assert chunk["engine"] == "default" and chunk["model"] == "whisper-1" and chunk["chars"] > 0
    assert chunk["language"] == "en"
    asr = event(env, job_id, "asr", "ok")["detail"]
    assert asr["engine"] == "default" and asr["language"] == "en" and asr["seconds"] >= 0
    assert event(env, job_id, "stitching")["status"] == "skipped"
    stored = event(env, job_id, "stored")["detail"]
    assert stored["kind"] == "transcript" and stored["source"] == "asr" and stored["stored"] is True
    assert event(env, job_id, "finished")["status"] == "ok"
    out = doc["outputs"]["transcript"]
    assert out["source"] == "asr" and out["engine"] == "default" and out["from_this_job"] is True
    assert "Hello there." in out["first_lines"][0] and out["chars"] == stored["chars"]
    assert doc["delivery"]["delivered"] is False
    text = await env.client.get(out["text_url"])
    assert text.status_code == 200 and "Hello there." in text.text
    assert "attachment" in text.headers["content-disposition"]


@NEEDS_FFMPEG
async def test_the_audio_event_says_whether_the_audio_came_from_the_archive(env):
    env.fetcher.text = None
    real = env.svc.jobs.pipeline.downloader

    async def archived(video_id, out_dir, started):
        events.note(source=events.AUDIO_FROM_ARCHIVE)
        return await real(video_id, out_dir, started)

    env.svc.jobs.pipeline.downloader = archived
    job_id = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()["job_id"]
    assert (await wait_state(env.client, job_id))["state"] == "ready"
    audio = event(env, job_id, "audio_download", "ok")["detail"]
    assert audio["source"] == "from_archive" == events.AUDIO_FROM_ARCHIVE and audio["bytes"] > 0


@NEEDS_FFMPEG
async def test_a_captions_job_logs_the_cues_and_the_tv_download(env):
    tv = device_client(env)
    queued = (await tv.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})).json()
    doc = await wait_state(tv, queued["job_id"])
    assert doc["state"] == "ready", doc["events"]
    job_id = doc["id"]
    assert in_order(
        stages_of(env, job_id),
        [
            "queued",
            "started",
            "gate_wait",
            "audio_download",
            "ffmpeg",
            "chunking",
            "stitching",
            "asr",
            "diarization",
            "cues",
            "stored",
            "finished",
        ],
    )
    asked = event(env, job_id, "queued")["detail"]
    assert asked["client"] == "Living room TV" and asked["priority"] == "background"
    skipped = event(env, job_id, "diarization", "skipped")["detail"]
    assert skipped["reason"] == "off" and "off" in skipped["message"]
    cues = event(env, job_id, "cues")["detail"]
    assert cues["cues"] >= 1 and cues["max_line_chars"] <= cues["limit_line_chars"]
    stored = event(env, job_id, "stored")["detail"]
    assert (
        stored["kind"] == "captions" and stored["lang"] == "en" and stored["cues"] == cues["cues"]
    )
    assert env.svc.db.one("SELECT job_id FROM captions WHERE video_id=?", [VID])["job_id"] == job_id

    track = doc["outputs"]["captions"][0]
    assert track["lang"] == "en" and track["cues"] == cues["cues"] and track["from_this_job"]
    assert track["preview"][0]["text"].startswith("Hello there.")
    assert track["vtt_url"] == f"/v1/videos/{VID}/captions/en.vtt"

    before = (await env.client.get(f"/v1/jobs/{job_id}")).json()["delivery"]
    assert before == {"delivered": False, "count": 0, "last_ts": None, "clients": []}
    listing = await tv.get(f"/v1/videos/{VID}/captions")
    assert listing.json()["status"] == "ready"
    assert (await tv.get(track["vtt_url"])).status_code == 200
    assert (await tv.get(track["vtt_url"])).status_code == 200
    after = (await env.client.get(f"/v1/jobs/{job_id}")).json()["delivery"]
    (who,) = after["clients"]
    assert who["client"] == "Living room TV" and who["user"] == "owner"
    assert sorted(who["via"]) == ["captions_status", "vtt"] and who["count"] == 3
    delivered = [e for e in log_of(env, job_id) if e["stage"] == "delivered"]
    assert len(delivered) == 2, "repeated fetches of the same kind share one event"
    vtt = next(e for e in delivered if e["detail"]["via"] == "vtt")
    assert (
        vtt["detail"]["count"] == 2 and vtt["detail"]["bytes"] > 0 and vtt["detail"]["lang"] == "en"
    )
    assert (await env.client.get(track["text_url"])).text.startswith("Hello there.")
    clients = (await env.client.get(f"/v1/jobs/{job_id}")).json()["delivery"]["clients"]
    assert {c["client"] for c in clients} == {"Living room TV", "API token"}
    listed = (await env.client.get("/v1/jobs")).json()["jobs"][0]
    assert listed["delivered"] is True and listed["delivered_at"] >= vtt["ts"] - 1
    await tv.aclose()


async def test_a_web_session_and_a_token_are_told_apart_in_the_delivery_log(env):
    job_id = add_job(env, kind="captions")
    env.svc.db.execute(
        "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at,job_id) VALUES(?,?,?,?,?,?,?)",
        [
            VID,
            "en",
            "English (u·tubot)",
            1,
            "WEBVTT\n\n1\n00:00:01.000 --> 00:00:02.000\nHi\n",
            time.time(),
            job_id,
        ],
    )
    env.svc.webauth.set_password("owner", PASSWORD)
    web = anon_client(env)
    login = await web.post("/v1/auth/login", json={"username": "owner", "password": PASSWORD})
    assert login.status_code == 200
    url = f"/v1/videos/{VID}/captions/en.vtt"
    assert (await web.get(url)).status_code == 200
    assert (await env.client.get(url)).status_code == 200
    clients = {
        c["client"]
        for c in (await env.client.get(f"/v1/jobs/{job_id}")).json()["delivery"]["clients"]
    }
    assert clients == {"Web UI", "API token"}


async def test_a_summary_built_from_the_audio_transcript_is_logged_as_a_delivery(env):
    job_id = add_job(env)
    env.svc.transcripts.store_asr(VID, "[00:00] Hello there.", "en", engine="mac", job_id=job_id)
    tv = device_client(env, "Bedroom Fire Stick", "utb_firetoken")
    assert (await tv.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})).json()[
        "status"
    ] == "ready"
    panel = await tv.get(f"/v1/videos/{VID}/summary", params={"prompt": "panel", "wait_ms": 5000})
    assert panel.json()["status"] == "ready"
    assert (await tv.get(f"/v1/videos/{VID}/transcript")).json()["transcript_status"] == "ok"
    asked = await tv.post(f"/v1/videos/{VID}/ask", json={"question": "what?", "wait_ms": 5000})
    assert asked.json()["status"] == "ready"
    (who,) = (await env.client.get(f"/v1/jobs/{job_id}")).json()["delivery"]["clients"]
    assert who["client"] == "Bedroom Fire Stick"
    assert sorted(who["via"]) == ["answer", "summary", "summary_panel", "transcript_status"]
    await tv.aclose()


async def test_captions_from_youtube_are_not_credited_to_a_job(env):
    job_id = add_job(env)
    env.svc.transcripts.store_asr(VID, "x", "en", job_id=job_id)
    env.svc.db.execute("UPDATE transcripts SET source='youtube_captions'")
    await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert (await env.client.get(f"/v1/jobs/{job_id}")).json()["delivery"]["delivered"] is False


# ---- who asked and why --------------------------------------------------------------------------------


async def test_a_started_by_policy_job_names_the_policy_and_the_device(env):
    hold_media(env)
    env.fetcher.text = None
    tv = device_client(env, "Bedroom Fire Stick", "utb_firetoken")
    assert (
        await env.client.put("/v1/me/policy", json={"auto_transcribe": "on_dwell"})
    ).status_code == 200
    await tv.get(f"/v1/videos/{VID}/summary", params={"prompt": "panel", "wait_ms": 3000})
    (job,) = env.svc.db.all("SELECT id FROM jobs")
    asked = event(env, job["id"], "queued")["detail"]
    assert asked["client"] == "Bedroom Fire Stick" and asked["user"] == "owner"
    assert asked["trigger"] == {
        "kind": "auto",
        "mode": "on_dwell",
        "passive": True,
        "max_minutes": 30,
    }
    assert asked["priority"] == "background"
    assert asked["endpoint"] == "GET /v1/videos/{video_id}/summary"
    await tv.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 3000})
    moved = event(env, job["id"], "promoted")["detail"]
    assert moved["priority"] == "interactive" and moved["client"] == "Bedroom Fire Stick"
    await tv.aclose()


async def test_cancel_and_retry_are_logged_with_the_caller(env):
    hold_media(env)
    queued = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()
    job_id = queued["job_id"]
    assert (await env.client.post(f"/v1/jobs/{job_id}/cancel")).json() == {"ok": True}
    gone = event(env, job_id, "finished")
    assert gone["status"] == "cancelled" and gone["detail"]["by"] == "owner"
    assert gone["detail"]["client"] == "API token"
    assert (await env.client.post(f"/v1/jobs/{job_id}/retry")).json() == {"ok": True}
    again = event(env, job_id, "retry")
    assert again["detail"]["reason"] == "requested" and again["detail"]["by"] == "owner"
    assert (await env.client.get(f"/v1/jobs/{job_id}")).json()["state"] == "waiting"


async def test_a_restart_while_running_is_logged_as_a_retry(env):
    hold_media(env)
    job_id = add_job(env, status="running")
    await env.svc.jobs.stop()
    env.svc.jobs.start()
    restart = event(env, job_id, "retry")["detail"]
    assert restart["reason"] == "restart"


async def test_transient_failures_are_logged_as_retries_and_the_last_one_as_a_failure(env):
    env.fetcher.text = None

    async def flaky(video_id, out_dir, started):
        raise YoutubeDelayed(REASON_NETWORK, 30)

    env.svc.jobs.pipeline.downloader = flaky
    job_id = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()["job_id"]
    for _ in range(60):
        await asyncio.sleep(0.05)
        if env.svc.jobs.get(job_id)["status"] == "failed":
            break
        await env.clock.advance(31)
    retries = [e["detail"] for e in log_of(env, job_id) if e["stage"] == "retry"]
    assert [r["attempt"] for r in retries] == [1, 2]
    assert retries[0]["reason"] == REASON_NETWORK and retries[0]["max_attempts"] == 3
    failed = event(env, job_id, "failed")["detail"]
    assert failed["error_class"] == REASON_NETWORK and failed["stage"] == "audio_download"
    assert failed["message"] == "YouTube kept refusing the download, try again later"
    audio = event(env, job_id, "audio_download", "failed")["detail"]
    assert audio["error_class"] == REASON_NETWORK
    detail = (await env.client.get(f"/v1/jobs/{job_id}")).json()
    assert detail["state"] == "failed" and detail["can_retry"] is True and detail["attempts"] == 2


async def test_the_events_of_one_job_are_capped_but_the_milestones_are_kept(env):
    env.cfg.captions.job_events_max = 4
    log = env.svc.jobs.events
    for n in range(10):
        log.record("capped", "asr_chunk", "ok", {"n": n})
    log.record("capped", "finished", "ok", {})
    log.record("capped", "delivered", "ok", {})
    assert [e["stage"] for e in log.list("capped")] == ["asr_chunk"] * 4 + ["finished", "delivered"]


# ---- yt-dlp and the engines, mocked -------------------------------------------------------------------


def test_format_track_and_language_come_from_the_chosen_yt_dlp_format(tmp_path, monkeypatch):
    def fmt(format_id: str, abr: float, note: str, language: str) -> dict:
        return {
            "format_id": format_id,
            "format_note": note,
            "language": language,
            "acodec": "opus",
            "vcodec": "none",
            "abr": abr,
            "ext": "webm",
            "protocol": "https",
            "url": f"{SECRET_URL}&itag={format_id}",
        }

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def build_format_selector(self, selector):
            return lambda ctx: iter(())

        def extract_info(self, url, download=True):
            formats = [
                fmt("249", 40, "Spanish (United States) dubbed-auto, low", "es-US"),
                fmt("251", 48, "English (United States) original (default), low", "en-US"),
            ]
            chosen = next(self.opts["format"]({"formats": formats}))
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading"})
            Path(self.opts["outtmpl"].replace("%(ext)s", "webm")).write_bytes(b"audio")
            return {**chosen, "duration": 600, "title": "t"}

        def prepare_filename(self, info):
            return self.opts["outtmpl"].replace("%(ext)s", "webm")

    monkeypatch.setattr(pipeline_mod.yt_dlp, "YoutubeDL", FakeYDL)
    trace = JobTrace("j1", JobEvents(Database(":memory:"), Config().captions))
    token = events.bind(trace)
    try:
        asyncio.run(
            download_audio(
                VID,
                tmp_path,
                lambda: None,
                fmt="bestaudio/best",
                max_duration_s=3600,
                max_bytes=10**9,
            )
        )
    finally:
        events.unbind(token)
    assert trace.notes == {
        "format_id": "251",
        "track": "original",
        "original": True,
        "language": "en-US",
        "codec": "opus",
        "ext": "webm",
        "bitrate_kbps": 48,
        "duration_s": 600,
    }


class StubAsr:
    async def transcribe(self, wav, language, progress, *, priority=1, want_words=True):
        progress(1.0)
        return ASRResult(
            words=[],
            language="tr",
            segments=[Segment(0.0, 1.0, "Merhaba dünya")],
            engine="stub",
            model="stub-1",
        )


@NEEDS_FFMPEG
async def test_the_pipeline_logs_the_download_format_with_yt_dlp_and_the_engine_mocked(
    tmp_path, monkeypatch
):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def build_format_selector(self, selector):
            return lambda ctx: iter(())

        def extract_info(self, url, download=True):
            formats = [
                {
                    "format_id": "251",
                    "format_note": "Turkish original (default), low",
                    "language": "tr",
                    "acodec": "opus",
                    "vcodec": "none",
                    "abr": 50,
                    "protocol": "https",
                    "url": SECRET_URL,
                }
            ]
            chosen = next(self.opts["format"]({"formats": formats}))
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading"})
            path = Path(self.opts["outtmpl"].replace("%(ext)s", "wav"))
            with wave.open(str(path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(8000)
                out.writeframes(b"\0\0" * 8000)
            return {**chosen, "duration": 1, "title": "t"}

        def prepare_filename(self, info):
            return self.opts["outtmpl"].replace("%(ext)s", "wav")

    monkeypatch.setattr(pipeline_mod.yt_dlp, "YoutubeDL", FakeYDL)
    cfg = Config()
    cfg.server.data_dir = str(tmp_path)
    cfg.youtube.min_interval_s = cfg.youtube.jitter_s = 0.0
    db = Database(tmp_path / "t.sqlite")
    pipeline = CaptionPipeline(cfg, db, StubAsr())
    log = JobEvents(db, cfg.captions)
    token = events.bind(JobTrace("j1", log))
    try:
        out = await pipeline.transcribe(VID, lambda f: None)
    finally:
        events.unbind(token)
    assert out.text.endswith("Merhaba dünya") and out.engine == "stub"
    rows = {(e["stage"], e["status"]): e["detail"] for e in log.list("j1")}
    audio = rows[("audio_download", "ok")]
    assert audio["format_id"] == "251" and audio["track"] == "original" and audio["original"]
    assert audio["language"] == "tr" and audio["bytes"] > 0 and audio["duration_s"] == 1
    assert audio["source"] == "downloaded"
    assert rows[("gate_wait", "ok")]["klass"] == "media"
    assert rows[("ffmpeg", "ok")]["audio_s"] == 1.0
    assert rows[("asr", "ok")]["engine"] == "stub" and rows[("asr", "ok")]["chars"] == 13
    assert rows[("text", "ok")]["segments"] == 1
    assert ("audio_download", "running") in rows and ("ffmpeg", "running") in rows
    assert not any(
        token_text in json.dumps(list(rows.values())) for token_text in FORBIDDEN_IN_EVENTS
    )
    db.close()


async def test_the_engine_chain_logs_chunks_fallbacks_and_the_stitching(tmp_path):
    db = Database(":memory:")
    log = JobEvents(db, Config().captions)
    token = events.bind(JobTrace("j1", log))
    try:
        wav = make_wav(tmp_path / "a.wav", 1300)
        broken = FakeEngine(
            "a", fail=EngineError(f"asr http 503: down at {SECRET_URL}", code="http_503")
        )
        chain = router(
            [engine_cfg("a", max_chunk_s=600, priority=1), engine_cfg("b", max_chunk_s=600)],
            {"a": broken, "b": FakeEngine("b")},
        )
        await chain.transcribe(wav, None, lambda f: None)
    finally:
        events.unbind(token)
    rows = log.list("j1")
    chunking = next(e for e in rows if e["stage"] == "chunking")["detail"]
    assert chunking["chunks"] == 3 and chunking["engines"] == ["a", "b"]
    assert chunking["sizes_s"][:2] == [600.0, 600.0] and chunking["audio_s"] == 1300.0
    failed = [e["detail"] for e in rows if e["stage"] == "asr_chunk" and e["status"] == "failed"]
    assert failed and failed[0]["engine"] == "a" and failed[0]["error_class"] == "http_503"
    assert "[url]" in failed[0]["technical"] and "SECRET" not in failed[0]["technical"]
    fallbacks = [e["detail"] for e in rows if e["stage"] == "asr_fallback"]
    assert fallbacks and all(f["engine"] == "a" and f["next"] == "b" for f in fallbacks)
    assert fallbacks[0]["reason"] == "http_503"
    done = [e["detail"] for e in rows if e["stage"] == "asr_chunk" and e["status"] == "ok"]
    assert len(done) == 3 and {d["engine"] for d in done} == {"b"} and all(d["chars"] for d in done)
    stitching = next(e for e in rows if e["stage"] == "stitching")["detail"]
    assert stitching["chunks"] == 3 and stitching["seams"] == 2 and stitching["cut_segments"] >= 0
    assert "repeated_words" in stitching
    assert not any(bad in json.dumps(rows) for bad in FORBIDDEN_IN_EVENTS)
    db.close()


async def test_a_chunk_an_engine_heard_in_the_wrong_language_is_logged_as_a_fallback(tmp_path):
    db = Database(":memory:")
    log = JobEvents(db, Config().captions)
    token = events.bind(JobTrace("j1", log))
    try:
        wav = make_wav(tmp_path / "a.wav", 60)
        chain = router(
            [
                engine_cfg("turkish-only", languages=["tr"], priority=1),
                engine_cfg("english-only", languages=["en"], priority=2),
            ],
            {
                "turkish-only": FakeEngine("turkish-only"),
                "english-only": FakeEngine("english-only"),
            },
        )
        result = await chain.transcribe(wav, None, lambda f: None)
    finally:
        events.unbind(token)
    assert result.language == "en" and result.engine == "english-only"
    (fallback,) = [e["detail"] for e in log.list("j1") if e["stage"] == "asr_fallback"]
    assert fallback["engine"] == "turkish-only" and fallback["next"] == "english-only"
    assert fallback["reason"] == "language_mismatch" and fallback["detected"] == "en"
    db.close()


# ---- nothing secret or signed in the log --------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "gone"),
    [
        (f"download failed {SECRET_URL}", ("googlevideo", "SECRETSIG")),
        ("see www.example.com/path?x=1 for more", ("www.example.com",)),
        ("Authorization: Bearer utb_abcDEF123456789 sent", ("utb_abc", "Bearer utb")),
        ("api_key=sk-live-abcdef0123456789", ("sk-live", "abcdef0123456789")),
        ("hash " + "a" * 64 + " seen", ("a" * 40,)),
        ("random Zx9Kq2LmVb7Rt4WpYc1NdS8HgJf3Ae6Ou5", ("Zx9Kq2LmVb7Rt4WpYc1",)),
        ("cookie=SID=abc123; HSID=def456", ("abc123",)),
    ],
)
def test_clean_removes_urls_and_secrets_from_text(raw, gone):
    out = clean({"message": raw})["message"]
    assert all(bit not in out for bit in gone), out


async def test_no_test_can_reach_youtube(tmp_path):
    import yt_dlp

    with pytest.raises(AssertionError, match="never reach YouTube"):
        yt_dlp.YoutubeDL({"quiet": True}).extract_info("https://www.youtube.com/watch?v=" + VID)
    with pytest.raises(AssertionError, match="never reach YouTube"):
        await httpx.AsyncClient().get("https://rr1.googlevideo.com/videoplayback")
    with pytest.raises(AssertionError, match="never reach YouTube"):
        httpx.Client().get("https://www.youtube.com/api/timedtext")


def test_clean_drops_secret_looking_keys_and_keeps_plain_facts():
    out = clean(
        {
            "token": "x",
            "api_key": "y",
            "hf_token_env": "UTUBOT_HF_TOKEN",
            "url": "https://a.example",
            "vtt_url": "/v1/x",
            "headers": {"a": 1},
            "format_id": "251",
            "model": "whisper-large-v3-turbo+whisper-small",
            "engines": ["mac", "box"],
            "nested": {"deep": {"deeper": {"deepest": 1}}},
            "n": 3,
        }
    )
    assert out == {
        "format_id": "251",
        "model": "whisper-large-v3-turbo+whisper-small",
        "engines": ["mac", "box"],
        "nested": {"deep": {"deeper": None}},
        "n": 3,
    }


async def test_a_failing_download_leaves_no_url_or_token_in_any_event(env):
    env.fetcher.text = None

    async def broken(video_id, out_dir, started):
        raise RuntimeError(f"yt-dlp exploded on {SECRET_URL} using {TOKEN}")

    env.svc.jobs.pipeline.downloader = broken
    job_id = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()["job_id"]
    doc = await wait_state(env.client, job_id)
    assert doc["state"] == "failed"
    dump = json.dumps(doc)
    assert not any(bad in dump for bad in FORBIDDEN_IN_EVENTS), dump
    failed = event(env, job_id, "failed")["detail"]
    assert failed["error_class"] == "RuntimeError" and failed["stage"] == "audio_download"
    assert failed["message"] == "transcription failed" and "[url]" in failed["technical"]
    rows = env.svc.db.all("SELECT stage,detail FROM job_events")
    assert not any(bad in str(tuple(r)) for r in rows for bad in FORBIDDEN_IN_EVENTS)


# ---- the API: who may read a job ------------------------------------------------------------------------


async def test_a_job_report_is_for_its_owner_and_for_admins_only(env):
    hold_media(env)
    mine = add_job(env, "owner", VID, "queued")
    theirs = add_job(env, "partner", OTHER, "queued")
    partner = partner_client(env)
    anon = anon_client(env)

    assert (await env.client.get(f"/v1/jobs/{mine}")).status_code == 200
    assert (await partner.get(f"/v1/jobs/{mine}")).status_code == 404
    assert (await anon.get(f"/v1/jobs/{mine}")).status_code == 401
    assert (await partner.get(f"/v1/jobs/{theirs}")).status_code == 200
    as_admin = (await env.client.get(f"/v1/jobs/{theirs}")).json()
    assert as_admin["user"] == "partner" and as_admin["id"] == theirs
    assert as_admin["can_cancel"] is False and as_admin["can_retry"] is False
    own = (await partner.get(f"/v1/jobs/{theirs}")).json()
    assert own["can_cancel"] is True and own["can_retry"] is False
    assert (await env.client.get("/v1/jobs/nope")).status_code == 404
    assert (await partner.get(f"/v1/jobs/{mine}/transcript.txt")).status_code == 404
    assert (await anon.get(f"/v1/jobs/{mine}/transcript.txt")).status_code == 401
    env.svc.transcripts.store_asr(OTHER, "[00:00] their text", "en", job_id=theirs)
    assert (await partner.get(f"/v1/jobs/{theirs}/transcript.txt")).text == "[00:00] their text"
    assert (await env.client.get(f"/v1/jobs/{theirs}/transcript.txt")).status_code == 200
    assert (await env.client.get(f"/v1/jobs/{mine}/transcript.txt")).status_code == 404
    # an admin cancelling someone else's job is still refused: only the owner may
    assert (await env.client.post(f"/v1/jobs/{theirs}/cancel")).status_code == 404
    await partner.aclose()


async def test_the_job_list_links_every_job_to_its_report(env):
    hold_media(env)
    job_id = add_job(env, "owner", VID, "queued")
    env.svc.jobs.events.backfill()
    listed = (await env.client.get("/v1/jobs")).json()["jobs"][0]
    assert listed["id"] == job_id
    assert listed["detail_url"] == f"/#/jobs/{job_id}" and listed["api_url"] == f"/v1/jobs/{job_id}"
    assert listed["delivered"] is False and listed["stage"] == "queued"
    assert (await env.client.get(listed["api_url"])).json()["detail_url"] == listed["detail_url"]


async def test_the_report_says_what_was_requested(env):
    job_id = add_job(env, "owner", VID, "ready", kind="captions", title="My video")
    env.svc.transcripts.store_meta(
        VID, {"title": "My video", "channel": "Chan", "duration_s": 900, "language": "tr"}
    )
    doc = (await env.client.get(f"/v1/jobs/{job_id}")).json()
    assert doc["inputs"]["video_id"] == VID and doc["inputs"]["title"] == "My video"
    assert doc["inputs"]["channel"] == "Chan" and doc["inputs"]["duration_s"] == 900
    assert doc["inputs"]["language"] == "tr" and doc["inputs"]["lang"] == "auto"
    assert doc["outputs"] == {"transcript": None, "captions": []}
    assert doc["kind"] == "captions" and doc["state"] == "ready" and doc["priority"] == "background"


# ---- jobs from before the log -------------------------------------------------------------------------


def test_jobs_from_before_event_logging_get_exactly_one_synthetic_event(tmp_path):
    db = Database(tmp_path / "old.sqlite")
    now = time.time()
    for job_id, status, error in (
        ("done", "ready", None),
        ("bad", "failed", "transcription failed"),
        ("off", "cancelled", "Cancelled"),
        ("wait", "queued", None),
    ):
        db.execute(
            "INSERT INTO jobs(id,user,video_id,lang,status,progress,error,created_at,updated_at,finished_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            [job_id, "owner", VID, "auto", status, 0, error, now - 100, now - 50, now - 50],
        )
    log = JobEvents(db, Config().captions)
    assert log.backfill() == 4
    assert log.backfill() == 0, "a second start adds nothing"
    done, bad, off, wait = (log.list(j) for j in ("done", "bad", "off", "wait"))
    assert [len(x) for x in (done, bad, off, wait)] == [1, 1, 1, 1]
    assert done[0]["stage"] == "finished" and done[0]["status"] == "ok"
    assert done[0]["detail"]["message"] == (
        "finished (no detailed log, created before event logging)"
    )
    assert done[0]["detail"]["synthetic"] is True and done[0]["ts"] == pytest.approx(now - 50)
    assert bad[0]["status"] == "failed" and bad[0]["detail"]["error"] == "transcription failed"
    assert off[0]["status"] == "cancelled"
    assert wait[0]["stage"] == "queued" and wait[0]["detail"]["synthetic"] is True
    db.close()


async def test_a_job_without_any_events_still_has_a_report(env):
    job_id = add_job(env, "owner", VID, "ready")
    assert env.svc.jobs.events.list(job_id) == []
    doc = (await env.client.get(f"/v1/jobs/{job_id}")).json()
    (only,) = doc["events"]
    assert only["stage"] == "finished" and only["detail"]["synthetic"] is True
    assert "no detailed log" in only["detail"]["message"]
    assert doc["delivery"]["delivered"] is False and doc["outputs"]["transcript"] is None


# ---- the UI --------------------------------------------------------------------------------------------


async def test_the_job_report_page_is_served_under_the_csp_and_wired_in(env):
    anon = anon_client(env)
    seen: set[str] = set()
    queue = asset_urls((await anon.get("/")).text)
    while queue:
        url = queue.pop()
        if url in seen:
            continue
        seen.add(url)
        res = await anon.get(url)
        assert res.status_code == 200, url
        if url.endswith(".js"):
            queue += [_resolve(Path(url).parent, rel) for rel in module_imports(res.text)]
    assert {"/ui/js/pages/job.js", "/ui/js/jobtext.js"} <= seen
    for url in ("/ui/js/pages/job.js", "/ui/js/jobtext.js"):
        res = await anon.get(url)
        assert res.headers["content-type"].split(";")[0] == "text/javascript"
        csp = res.headers["content-security-policy"]
        assert "script-src 'self'" in csp and "unsafe-inline" not in csp
        assert "unsafe-eval" not in csp and res.headers["cache-control"] == "no-cache"
    main = (WEB / "ui/js/main.js").read_text()
    assert 'path: "jobs"' in main and "pages/job.js" in main
    listing = (WEB / "ui/js/pages/transcripts.js").read_text()
    assert "job.detail_url" in listing


def test_the_job_report_code_builds_dom_with_text_nodes_and_no_inline_style_or_urls():
    for name in ("pages/job.js", "jobtext.js", "pages/transcripts.js"):
        source = (WEB / "ui/js" / name).read_text()
        assert not re.search(
            r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", source
        )
        assert not re.search(
            r"setAttribute\(\s*[\"']style|\.style\b|cssText|<style|on[a-z]+=\"", source
        )
        assert "http://" not in source and "https://" not in source, name
        assert "localStorage" not in source and "sessionStorage" not in source


@NEEDS_NODE
def test_the_report_text_folds_running_events_and_reads_every_stage():
    script = """
    import { collapse, describe, reasonText, fmtSecs } from "__JOBTEXT__";
    const ev = (stage, status, detail = {}, ts = 0) => ({ stage, status, detail, ts });
    const log = [
      ev("queued", "ok", { user: "owner", client: "Living room TV", trigger: { kind: "explicit" }, priority: "background" }, 0),
      ev("audio_download", "running", {}, 1),
      ev("audio_download", "ok", { seconds: 3.8, format_id: "251", track: "original", original: true, language: "tr", bytes: 2048, duration_s: 600 }, 5),
      ev("asr", "running", { requested_language: null }, 6),
      ev("asr_chunk", "failed", { engine: "mac", start_s: 0, end_s: 600, error_class: "http_503" }, 7),
      ev("asr_fallback", "warn", { engine: "mac", reason: "http_503", next: "box", start_s: 0, end_s: 600 }, 8),
      ev("asr_chunk", "ok", { engine: "box", start_s: 0, end_s: 600, chars: 1200, language: "tr" }, 9),
      ev("asr", "ok", { seconds: 4, engine: "mac+box", model: "m", chars: 1200, language: "tr" }, 10),
      ev("diarization", "running", {}, 11),
      ev("diarization", "skipped", { reason: "no_hf_token", message: "No Hugging Face token was set." }, 11),
      ev("delivered", "ok", { client: "TV", via: "vtt", count: 2 }, 12),
      ev("audio_download", "running", {}, 13),
    ];
    const rows = collapse(log);
    const out = {
      stages: rows.map((r) => r.stage + ":" + r.status + (r.child ? ":child" : "")),
      audio: describe({ stage: "audio_download", status: "ok", detail: rows[1].detail }),
      queued: describe(log[0]),
      archived: describe({ stage: "audio_download", status: "ok", detail: { source: "from_archive", bytes: 2048 } }),
      fallback: describe(log[5]),
      skipped: describe({ stage: "diarization", status: "skipped", detail: log[9].detail }),
      delivered: describe(log[10]),
      reason: [reasonText("http_503"), reasonText("too_long"), fmtSecs(0.4), fmtSecs(125)],
      secs: rows[1].seconds,
    };
    console.log(JSON.stringify(out));
    """.replace("__JOBTEXT__", (WEB / "ui/js/jobtext.js").as_uri())
    done = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout)
    assert out["stages"] == [
        "queued:ok",
        "audio_download:ok",
        "asr:ok",
        "asr_chunk:failed:child",
        "asr_fallback:warn:child",
        "asr_chunk:ok:child",
        "diarization:skipped",
        "audio_download:running",
    ]
    assert out["secs"] == 3.8
    assert out["queued"] == (
        "Requested by owner on Living room TV, asked for explicitly, background priority"
    )
    assert (
        out["audio"]
        == "Downloaded, format 251, original track, language tr, 2.0 KB, 10:00 of audio"
    )
    assert out["archived"] == "From the media archive, 2.0 KB"
    assert out["fallback"] == "mac gave up on 0-600 s (HTTP 503), trying box"
    assert out["skipped"] == "Skipped: No Hugging Face token was set."
    assert out["delivered"] == "TV fetched the .vtt track (2 times)"
    assert out["reason"][:2] == ["HTTP 503", "the video is longer than the transcription limit"]
    assert out["reason"][2:] == ["400 ms", "2 min 5 s"]
