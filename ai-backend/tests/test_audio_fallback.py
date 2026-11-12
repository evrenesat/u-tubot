"""Audio instead of waiting: YouTube limits the caption API, the audio and the speech engine still work."""

from __future__ import annotations

import asyncio
import shutil
import time

import pytest

from tests.conftest import TRANSCRIPT
from tests.fakes import settle
from utubot.captions.pipeline import AsrTranscript
from utubot.llm import BACKGROUND, INTERACTIVE
from utubot.transcripts import FetchResult, NoCaptions
from utubot.youtube import (
    CLASS_CAPTIONS,
    CLASS_MEDIA,
    FETCH_CLASSES,
    REASON_BOT_CHECK,
    REASON_NETWORK,
    REASON_RATE_LIMITED,
    STATE_CLOSED,
    STATE_HALF_OPEN,
    STATE_OPEN,
    YoutubeBlocked,
    YoutubeDelayed,
)

VID = "abcdefghijk"
OTHER = "bcdefghijkl"
NEEDS_FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
MINUTE = 60
DURATION_S = 15 * MINUTE
ESTIMATE_S = round(5 + DURATION_S / 300 + 30 + DURATION_S / 1.5)  # the legacy single engine
CAPTION_COOLDOWN_S = 1200
MEDIA_COOLDOWN_S = 3600
OFFER = f"Captions are temporarily unavailable from YouTube; transcribe the audio instead (~{ESTIMATE_S} s)?"
OFFER_WITHOUT_ESTIMATE = (
    "Captions are temporarily unavailable from YouTube; transcribe the audio instead?"
)
ASR_TEXT = "[00:00] Hello there. How are you doing today?"


async def summary(env, vid: str = VID, duration_s: int | None = DURATION_S, **params):
    if duration_s is not None:
        params["duration_s"] = duration_s
    return (
        await env.client.get(f"/v1/videos/{vid}/summary", params={"wait_ms": 5000, **params})
    ).json()


async def policy(env, **fields) -> None:
    assert (await env.client.put("/v1/me/policy", json=fields)).status_code == 200


def jobs(env) -> list[dict]:
    return [dict(r) for r in env.svc.db.all("SELECT * FROM jobs ORDER BY created_at")]


def cool_captions(env, seconds: float = CAPTION_COOLDOWN_S) -> None:
    env.svc.gate.report_block(REASON_RATE_LIMITED, seconds, CLASS_CAPTIONS)


async def half_open_captions(env) -> None:
    cool_captions(env)
    await env.clock.advance(CAPTION_COOLDOWN_S + 1)
    assert env.svc.gate.state(CLASS_CAPTIONS) == STATE_HALF_OPEN


def count(env, table: str) -> int:
    return env.svc.db.one(f"SELECT COUNT(*) AS n FROM {table}")["n"]


class Spy:
    """Records the priority and classes of every request the gate was asked to run."""

    def __init__(self, env) -> None:
        self.seen: list[tuple[int, tuple[str, ...], str | None]] = []
        self._run = env.svc.gate.run
        env.svc.gate.run = self.run

    async def run(self, fn, priority=INTERACTIVE, key=None, classes=FETCH_CLASSES):
        self.seen.append((priority, tuple(classes), key))
        return await self._run(fn, priority, key, classes)


class HeldFetcher:
    """A caption fetch that stays in flight until `release`."""

    def __init__(self, text: str | None = TRANSCRIPT) -> None:
        self.calls: list[str] = []
        self.release = asyncio.Event()
        self.text = text

    async def __call__(self, video_id: str) -> FetchResult:
        self.calls.append(video_id)
        await self.release.wait()
        meta = {"video_id": video_id, "title": "T", "duration_s": DURATION_S}
        return FetchResult(meta, self.text, "en")


@pytest.fixture(autouse=True)
async def idle_jobs(env):
    """The tests look at the answer and the queued job; nothing downloads unless a test starts it."""
    await env.svc.jobs.stop()


# ---- a cooling caption class is "no captions" for the audio ---------------------------------------


async def test_a_cooling_caption_class_starts_the_audio_transcription_at_once(env):
    cool_captions(env)
    body = await summary(env, title="A title")
    assert body["status"] == "pending" and body["transcript_status"] == "transcribing"
    assert body["progress"] == 0.0 and body["estimate_s"] == ESTIMATE_S
    assert body["text"] is None and body["error"] is None and "retry_after_s" not in body
    (job,) = jobs(env)
    assert (job["kind"], job["user"], job["video_id"], job["priority"]) == (
        "transcript",
        "owner",
        VID,
        INTERACTIVE,
    )
    assert env.fetcher.calls == [] and env.llm.calls == []

    again = await summary(env)
    assert again["status"] == "pending" and again["transcript_status"] == "transcribing"
    assert len(jobs(env)) == 1 and env.fetcher.calls == []
    state = (await env.client.get(f"/v1/videos/{VID}/transcript")).json()
    assert state["transcript_status"] == "transcribing"


async def test_insight_and_ask_start_the_audio_too(env):
    cool_captions(env)
    insight = (
        await env.client.get(
            f"/v1/videos/{VID}/insight", params={"wait_ms": 5000, "duration_s": DURATION_S}
        )
    ).json()
    assert insight["status"] == "pending" and insight["transcript_status"] == "transcribing"
    env.svc.db.execute("DELETE FROM jobs")
    ask = (
        await env.client.post(
            f"/v1/videos/{VID}/ask",
            params={"duration_s": DURATION_S},
            json={"question": "Why?", "wait_ms": 5000},
        )
    ).json()
    assert ask["status"] == "pending" and ask["transcript_status"] == "transcribing"
    assert len(jobs(env)) == 1 and env.fetcher.calls == []


async def test_an_ad_hoc_summary_counts_as_opening_the_video(env):
    cool_captions(env)
    body = (
        await env.client.post(
            f"/v1/videos/{VID}/summary",
            params={"duration_s": DURATION_S},
            json={"prompt_text": "Hi {title}"},
        )
    ).json()
    assert body["status"] == "pending" and body["transcript_status"] == "transcribing"


async def test_the_policy_off_offers_the_audio_with_the_estimate_and_remembers_nothing(env):
    await policy(env, auto_transcribe="off")
    cool_captions(env)
    body = await summary(env)
    assert body["status"] == "needs_transcript" and body["transcript_status"] == "none"
    assert body["can_transcribe"] is True and body["estimate_s"] == ESTIMATE_S
    assert body["message"] == OFFER and body["text"] is None
    assert jobs(env) == [] and env.fetcher.calls == []
    assert count(env, "no_captions") == 0 and count(env, "video_holds") == 0
    assert count(env, "transcripts") == 0

    state = (
        await env.client.get(f"/v1/videos/{VID}/transcript", params={"duration_s": DURATION_S})
    ).json()
    assert state["transcript_status"] == "none" and state["message"] == OFFER

    yes = (await env.client.post(f"/v1/videos/{VID}/transcribe")).json()
    assert yes["transcript_status"] == "transcribing" and len(jobs(env)) == 1


async def test_a_video_longer_than_the_automatic_limit_is_offered_not_started(env):
    cool_captions(env)
    body = await summary(env, duration_s=31 * MINUTE)
    assert body["status"] == "needs_transcript" and body["can_transcribe"] is True
    assert body["message"].startswith("Captions are temporarily unavailable from YouTube")
    assert jobs(env) == []
    await policy(env, auto_transcribe_max_minutes=60)
    assert (await summary(env, duration_s=31 * MINUTE))["status"] == "pending"


async def test_an_unknown_length_is_offered_without_an_estimate(env):
    cool_captions(env)
    body = await summary(env, duration_s=None)
    assert body["status"] == "needs_transcript" and body["can_transcribe"] is True
    assert body["message"] == OFFER_WITHOUT_ESTIMATE and body["estimate_s"] is None
    assert jobs(env) == []


async def test_the_side_panel_starts_the_audio_only_on_dwell(env):
    cool_captions(env)
    on_open = await summary(env, prompt="panel")
    assert on_open["status"] == "needs_transcript" and on_open["message"] == OFFER
    assert jobs(env) == []
    await policy(env, auto_transcribe="on_dwell")
    dwell = await summary(env, prompt="panel")
    assert dwell["status"] == "pending" and dwell["transcript_status"] == "transcribing"
    (job,) = jobs(env)
    assert job["priority"] == BACKGROUND
    opened = await summary(env)
    assert opened["transcript_status"] == "transcribing"
    assert [j["priority"] for j in jobs(env)] == [INTERACTIVE]


async def test_a_caption_429_that_just_arrived_also_starts_the_audio(env):
    env.fetcher.error = YoutubeBlocked(REASON_RATE_LIMITED, CAPTION_COOLDOWN_S, CLASS_CAPTIONS)
    body = await summary(env, title="A title")
    assert body["status"] == "pending" and body["transcript_status"] == "transcribing"
    assert env.fetcher.calls == [VID]
    assert env.svc.gate.state(CLASS_CAPTIONS) == STATE_OPEN
    assert env.svc.gate.healthy(CLASS_MEDIA)
    assert len(jobs(env)) == 1
    assert count(env, "no_captions") == 0 and count(env, "video_holds") == 0


async def test_an_unattributed_429_opens_metadata_and_captions_and_still_falls_back(env):
    env.fetcher.error = YoutubeBlocked(REASON_RATE_LIMITED, 120)
    body = await summary(env)
    assert body["transcript_status"] == "transcribing" and not env.svc.gate.healthy(*FETCH_CLASSES)
    assert env.svc.gate.healthy(CLASS_MEDIA)


# ---- "delayed" is what is left when the audio cannot stand in --------------------------------------


async def test_it_stays_delayed_while_the_media_class_cools_too(env):
    cool_captions(env)
    env.svc.gate.report_block(REASON_RATE_LIMITED, MEDIA_COOLDOWN_S, CLASS_MEDIA)
    body = await summary(env)
    assert body["status"] == "pending" and body["transcript_status"] == "delayed"
    assert body["retry_after_s"] == CAPTION_COOLDOWN_S
    assert "limiting transcript downloads" in body["error"] and jobs(env) == []


async def test_it_stays_delayed_when_no_speech_engine_is_available(env):
    env.svc.transcription.engines._enabled = lambda engine: False
    cool_captions(env)
    body = await summary(env)
    assert body["status"] == "pending" and body["transcript_status"] == "delayed"
    assert body["retry_after_s"] == CAPTION_COOLDOWN_S and jobs(env) == []
    env.fetcher.error = YoutubeBlocked(REASON_RATE_LIMITED, 60, CLASS_CAPTIONS)
    env.svc.gate.report_ok()
    assert (await summary(env, OTHER))["transcript_status"] == "delayed"


async def test_a_bot_check_stays_delayed_because_it_blocks_the_audio_too(env):
    env.fetcher.error = YoutubeBlocked(REASON_BOT_CHECK, 300)
    body = await summary(env)
    assert body["status"] == "pending" and body["transcript_status"] == "delayed"
    assert not env.svc.gate.healthy(CLASS_MEDIA) and jobs(env) == []


async def test_a_network_error_is_not_a_reason_to_switch_to_the_audio(env):
    env.fetcher.error = YoutubeDelayed(REASON_NETWORK, 60)
    body = await summary(env)
    assert body["status"] == "pending" and body["transcript_status"] == "delayed"
    assert jobs(env) == []


@pytest.mark.parametrize("meta", [{"is_live": True}, {"duration_s": 4 * 3600}])
async def test_a_video_that_cannot_be_transcribed_stays_delayed(env, meta):
    cool_captions(env)
    env.svc.transcripts.store_meta(VID, {"title": "t", **meta})
    body = await summary(env, duration_s=meta.get("duration_s"))
    assert body["status"] == "pending" and body["transcript_status"] == "delayed"
    assert jobs(env) == []


async def test_a_known_no_captions_video_keeps_its_usual_answer(env):
    await policy(env, auto_transcribe="off")
    env.svc.db.execute(
        "INSERT INTO no_captions(video_id,checked_at) VALUES(?,?)", [VID, time.time()]
    )
    cool_captions(env)
    body = await summary(env)
    assert body["status"] == "needs_transcript"
    assert body["message"] == "No captions. Transcribe the audio in the background?"


async def test_a_cached_transcript_is_used_while_captions_are_limited(env):
    env.svc.transcripts.store_asr(VID, ASR_TEXT, "en", engine="mac", model="m")
    cool_captions(env)
    body = await summary(env)
    assert body["status"] == "ready" and body["source"] == "asr" and jobs(env) == []


# ---- after the cooldown: one background probe, never the user's request ------------------------------


async def test_after_the_cooldown_one_background_probe_goes_out_and_the_user_never_waits(env):
    spy = Spy(env)
    await half_open_captions(env)
    body = await summary(env, title="A title")
    assert body["status"] == "pending" and body["transcript_status"] == "transcribing"
    await settle()
    assert spy.seen == [(BACKGROUND, FETCH_CLASSES, VID)] and env.fetcher.calls == [VID]
    assert env.svc.gate.state(CLASS_CAPTIONS) == STATE_CLOSED
    ready = await summary(env)
    assert ready["status"] == "ready" and ready["source"] == "youtube_captions"
    assert env.fetcher.calls == [VID]


async def test_only_one_caption_request_is_out_while_the_probe_runs(env):
    held = HeldFetcher()
    env.svc.transcripts.fetcher = held
    spy = Spy(env)
    await half_open_captions(env)
    assert (await summary(env))["transcript_status"] == "transcribing"
    await settle()
    others = [await summary(env, OTHER), await summary(env, "cdefghijklm")]
    assert all(o["transcript_status"] == "transcribing" for o in others)
    insight = (
        await env.client.get(
            f"/v1/videos/{OTHER}/insight", params={"wait_ms": 5000, "duration_s": DURATION_S}
        )
    ).json()
    assert insight["transcript_status"] == "transcribing"
    assert held.calls == [VID] and spy.seen == [(BACKGROUND, FETCH_CLASSES, VID)]
    assert env.svc.gate.state(CLASS_CAPTIONS) == STATE_HALF_OPEN
    held.release.set()
    await settle()
    assert env.svc.gate.state(CLASS_CAPTIONS) == STATE_CLOSED


async def test_a_probe_that_gets_429_again_keeps_the_user_on_the_audio_and_cools_longer(env):
    env.fetcher.error = YoutubeBlocked(REASON_RATE_LIMITED, None, CLASS_CAPTIONS)
    await half_open_captions(env)
    body = await summary(env)
    assert body["status"] == "pending" and body["transcript_status"] == "transcribing"
    await settle()
    assert env.fetcher.calls == [VID]
    assert env.svc.gate.state(CLASS_CAPTIONS) == STATE_OPEN
    assert env.svc.gate.cooldown_remaining(CLASS_CAPTIONS) == pytest.approx(600)
    for vid in (VID, OTHER, "cdefghijklm"):
        assert (await summary(env, vid))["transcript_status"] == "transcribing"
    assert env.fetcher.calls == [VID]


async def test_the_escalation_stops_at_thirty_minutes(env):
    env.fetcher.error = YoutubeBlocked(REASON_RATE_LIMITED, None, CLASS_CAPTIONS)
    seen = []
    cool_captions(env, 300)
    for step in range(5):
        await env.clock.advance(env.svc.gate.cooldown_remaining(CLASS_CAPTIONS) + 1)
        await summary(env, f"{step:011d}")
        await settle()
        seen.append(env.svc.gate.cooldown_remaining(CLASS_CAPTIONS))
    assert seen == pytest.approx([600, 1200, 1800, 1800, 1800])
    assert len(env.fetcher.calls) == 5


async def test_a_probe_does_not_start_for_a_video_that_cannot_teach_it_anything(env):
    transcripts = env.svc.transcripts
    assert transcripts.probe_captions(VID) is False
    await half_open_captions(env)
    transcripts.store_asr(VID, ASR_TEXT, "en")
    assert transcripts.probe_captions(VID) is False
    env.svc.db.execute(
        "INSERT INTO no_captions(video_id,checked_at) VALUES(?,?)", [OTHER, time.time()]
    )
    assert transcripts.probe_captions(OTHER) is False
    transcripts.record_failure("cdefghijklm", "private")
    assert transcripts.probe_captions("cdefghijklm") is False
    assert env.fetcher.calls == []
    assert transcripts.probe_captions("defghijklmn") is True
    assert transcripts.probe_captions("efghijklmno") is False
    await settle()
    assert env.fetcher.calls == ["defghijklmn"]


async def test_an_interactive_caption_request_is_never_sent_while_the_class_cools(env):
    cool_captions(env)
    spy = Spy(env)
    for vid in (VID, OTHER):
        await summary(env, vid)
        await env.client.get(f"/v1/videos/{vid}/insight", params={"duration_s": DURATION_S})
    assert env.fetcher.calls == [] and spy.seen == []


@pytest.mark.parametrize(
    ("state", "priority", "rechecks"),
    [
        ("closed", INTERACTIVE, True),
        ("open", INTERACTIVE, False),
        ("half_open", INTERACTIVE, False),
        ("half_open", BACKGROUND, True),
        ("open", BACKGROUND, False),
    ],
)
async def test_a_transcript_job_rechecks_captions_only_when_the_class_lets_it_through(
    env, state, priority, rechecks
):
    calls: list[tuple[int, bool]] = []

    async def get(video_id, priority=INTERACTIVE, recheck=False):
        calls.append((priority, recheck))
        raise NoCaptions(video_id)

    async def transcribe(video_id, progress, *, priority, language):
        return AsrTranscript(ASR_TEXT, "en", [], "mac", "m")

    env.svc.transcripts.get = get
    env.svc.jobs.pipeline.transcribe = transcribe
    if state == "half_open":
        await half_open_captions(env)
    elif state == "open":
        cool_captions(env)
    queue = env.svc.jobs
    queue.enqueue_transcript("owner", VID, "t", priority)
    assert await queue.run_one() is True
    assert calls == ([(priority, True)] if rechecks else [])
    assert queue.transcript_job(VID)["status"] == "ready"


# ---- the stored transcript: the first one stays ------------------------------------------------------


async def test_a_later_caption_fetch_does_not_replace_an_asr_transcript(env):
    transcripts = env.svc.transcripts
    transcripts.store_asr(
        VID, ASR_TEXT, "en", engine="mac", model="whisper", segments=[(0.0, 4.0, "Hello")]
    )
    hit = await transcripts.get(VID)
    assert hit.source == "asr" and env.fetcher.calls == []
    assert (await transcripts.get(VID, recheck=True)).source == "asr" and env.fetcher.calls == []

    kept = await transcripts._fetch(VID, BACKGROUND)
    assert env.fetcher.calls == [VID] and kept.source == "asr" and kept.text == ASR_TEXT
    row = env.svc.db.one("SELECT * FROM transcripts WHERE video_id=?", [VID])
    assert (row["source"], row["text"], row["engine"], row["model"]) == (
        "asr",
        ASR_TEXT,
        "mac",
        "whisper",
    )
    assert row["segments"] is not None


async def test_captions_stored_first_stay_too(env):
    transcripts = env.svc.transcripts
    assert (await transcripts.get(VID)).source == "youtube_captions"
    assert transcripts.store_asr(VID, ASR_TEXT, "en") is False
    assert env.svc.db.one("SELECT source FROM transcripts")["source"] == "youtube_captions"


async def test_caption_text_still_refreshes_older_caption_text_and_clears_engine_columns(env):
    transcripts = env.svc.transcripts
    await transcripts.get(VID)
    env.svc.db.execute("UPDATE transcripts SET engine='x', model='y', segments='[]'")
    env.fetcher.text = "[00:00] New text"
    await transcripts._fetch(VID, BACKGROUND)
    row = env.svc.db.one("SELECT * FROM transcripts")
    assert row["text"] == "[00:00] New text" and row["engine"] is None and row["segments"] is None


@NEEDS_FFMPEG
async def test_the_audio_job_finishes_while_the_probe_is_out_and_the_late_captions_do_not_replace_it(
    env,
):
    held = HeldFetcher()
    env.svc.transcripts.fetcher = held
    env.svc.gate._limit = 2  # the slow probe must not hold the audio download back
    await half_open_captions(env)
    body = await summary(env)
    assert body["status"] == "pending" and body["transcript_status"] == "transcribing"
    await settle()
    assert held.calls == [VID]

    env.svc.jobs.start()
    deadline = time.time() + 15
    state: dict = {}
    while time.time() < deadline:
        state = (await env.client.get(f"/v1/videos/{VID}/transcript")).json()
        if state.get("transcript_status") == "ok":
            break
        await asyncio.sleep(0.05)
    assert state["transcript_status"] == "ok"
    assert state["source"] == "asr"
    assert held.calls == [VID]

    held.release.set()
    await settle()
    assert env.svc.gate.state(CLASS_CAPTIONS) == STATE_CLOSED
    row = env.svc.db.one("SELECT * FROM transcripts WHERE video_id=?", [VID])
    assert row["source"] == "asr" and row["engine"] == "default"
    ready = await summary(env)
    assert ready["status"] == "ready" and ready["source"] == "asr"
    await env.svc.jobs.stop()


@NEEDS_FFMPEG
async def test_the_fallback_transcript_is_stored_with_source_asr_and_used_for_summaries(env):
    cool_captions(env)
    body = await summary(env)
    assert body["transcript_status"] == "transcribing"
    env.svc.jobs.start()
    deadline = time.time() + 15
    ready: dict = {}
    while time.time() < deadline:
        ready = await summary(env)
        if ready["status"] == "ready":
            break
        await asyncio.sleep(0.05)
    assert ready["status"] == "ready" and ready["source"] == "asr"
    assert env.fetcher.calls == []
    row = env.svc.db.one("SELECT source, engine FROM transcripts WHERE video_id=?", [VID])
    assert row["source"] == "asr" and row["engine"] == "default"
    assert not env.svc.gate.healthy(CLASS_CAPTIONS)
    await env.svc.jobs.stop()
