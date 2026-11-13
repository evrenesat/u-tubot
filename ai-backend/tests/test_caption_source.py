"""Where a captions job takes its text from: the video's own captions (improved) or the audio."""

from __future__ import annotations

from tests.conftest import TRANSCRIPT
from tests.test_job_report import device_client, event, in_order, log_of, stages_of, wait_state
from tests.test_proofread import respond_with_cues

VID = "abcdefghijk"
CAPTION_SEGMENTS = [
    (0.0, 4.0, "hello there my friend"),
    (4.0, 8.0, "how are you doing today"),
]


def stored_captions(env) -> str:
    row = env.svc.db.one("SELECT vtt FROM captions WHERE video_id=?", [VID])
    assert row is not None, "no captions stored"
    return row["vtt"]


async def queue_captions(env, client=None):
    client = client or env.client
    queued = (await client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})).json()
    doc = await wait_state(client, queued["job_id"])
    assert doc["state"] == "ready", doc["events"]
    return doc


async def test_a_captions_job_improves_the_video_s_own_captions(env):
    env.fetcher.text = "[00:00] hello there my friend [00:04] how are you doing today"
    env.fetcher.segments = list(CAPTION_SEGMENTS)
    respond_with_cues(env.llm, ["Hello there, my friend.", "How are you doing today?"])
    doc = await queue_captions(env)
    assert in_order(
        stages_of(env, doc["id"]),
        [
            "caption_recheck",
            "audio_download",
            "ffmpeg",
            "asr",
            "cues",
            "align",
            "proofread",
            "stored",
            "finished",
        ],
    )
    recheck = event(env, doc["id"], "caption_recheck")["detail"]
    assert recheck["result"] == "found" and recheck["timed"] is True
    align = event(env, doc["id"], "align")["detail"]
    assert align["mode"] == "merge" and align["from_asr"] == 1 and align["cues"] == 2
    proofread = event(env, doc["id"], "proofread")["detail"]
    assert proofread["corrected"] == 2 and proofread["warned"] == 0
    vtt = stored_captions(env)
    assert "Hello there, my friend." in vtt and "How are you doing today?" in vtt
    # the cue timing comes from the ASR words inside each caption window; the second cue
    # (the ASR heard nothing there) keeps the caption timing and its corrected text
    assert "00:00:00.000 --> 00:00:04.000" in vtt
    assert "00:00:04.000 --> 00:00:08.000" in vtt
    # the caption recheck fetched the track once; no ASR engine work was wasted
    assert len(env.fetcher.calls) == 1


async def test_a_captions_job_builds_from_audio_when_there_are_no_captions(env):
    env.fetcher.text = None
    doc = await queue_captions(env)
    assert in_order(
        stages_of(env, doc["id"]),
        ["caption_recheck", "audio_download", "asr", "cues", "align", "proofread", "stored"],
    )
    recheck = event(env, doc["id"], "caption_recheck")["detail"]
    assert recheck["result"] == "no_captions"
    vtt = stored_captions(env)
    assert "Hello there." in vtt and "How are you doing today?" in vtt


async def test_a_captions_job_builds_from_audio_when_the_track_has_no_timings(env):
    env.fetcher.text = TRANSCRIPT  # an older cache row: text without timed segments
    doc = await queue_captions(env)
    recheck = event(env, doc["id"], "caption_recheck")["detail"]
    assert recheck["result"] == "found" and recheck["timed"] is False
    align = event(env, doc["id"], "align")["detail"]
    assert align["mode"] == "silence"
    assert "Hello there." in stored_captions(env)


async def test_a_captions_job_builds_from_audio_for_a_specific_other_language(env):
    env.fetcher.text = "text"
    env.fetcher.segments = list(CAPTION_SEGMENTS)
    queued = (await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "de"})).json()
    doc = await wait_state(env.client, queued["job_id"])
    assert doc["state"] == "ready", doc["events"]
    recheck = event(env, doc["id"], "caption_recheck")["detail"]
    assert recheck["result"] == "found" and recheck["timed"] is True
    assert event(env, doc["id"], "align")["detail"]["mode"] == "silence"


async def test_a_captions_job_keeps_the_caption_text_when_the_asr_fails(env):
    env.fetcher.text = "[00:00] hello there my friend"
    env.fetcher.segments = [(0.0, 4.0, "hello there my friend")]
    respond_with_cues(env.llm, ["Hello there, my friend."])
    env.cfg.captions.asr_url = "http://mock/nope"
    doc = await queue_captions(env)
    asr = event(env, doc["id"], "asr", "warn")["detail"]
    assert asr["reason"] == "engines_unavailable"
    align = event(env, doc["id"], "align")["detail"]
    assert align["mode"] == "merge" and align["from_asr"] == 0
    assert "Hello there, my friend." in stored_captions(env)


async def test_an_automatic_caption_track_sends_the_base_language_to_asr(env):
    env.fetcher.text = "text"
    env.fetcher.lang = "en-orig"
    env.fetcher.segments = list(CAPTION_SEGMENTS)
    doc = await queue_captions(env)
    asr = event(env, doc["id"], "asr")["detail"]
    assert asr["language"] == "en"
    assert env.llm.audio_calls[0]["language"] == "en"
    track = env.svc.db.one("SELECT lang,label FROM captions WHERE video_id=?", [VID])
    assert track["lang"] == "en" and track["label"] == "English (u·tubot)"


async def test_a_captions_job_keeps_the_caption_text_when_the_audio_has_no_speech(env):
    from utubot.captions.asr import ASRResult

    env.fetcher.text = "[00:00] hello there my friend"
    env.fetcher.segments = [(0.0, 4.0, "hello there my friend")]
    respond_with_cues(env.llm, ["Hello there, my friend."])

    class SilentASR:
        async def transcribe(self, wav, language, progress, *, priority=1, want_words=True):
            return ASRResult(words=[], language=None, segments=[], engine="mock", model="mock")

    env.svc.jobs.pipeline.asr = SilentASR()
    doc = await queue_captions(env)
    asr = event(env, doc["id"], "asr", "warn")["detail"]
    assert asr["reason"] == "no_speech"
    align = event(env, doc["id"], "align")["detail"]
    assert align["mode"] == "merge" and align["from_asr"] == 0
    assert "Hello there, my friend." in stored_captions(env)


async def test_a_captions_job_says_when_separation_is_not_installed(env):
    env.fetcher.text = None
    env.cfg.captions.separation = "demucs"
    env.cfg.captions.separation_cmd = ["definitely-not-on-path-xyz"]
    env.svc.jobs.pipeline.separator = None  # what make_separator builds for a missing tool
    doc = await queue_captions(env)
    separation = event(env, doc["id"], "separation", "skipped")["detail"]
    assert separation["reason"] == "not_installed"
    assert "Hello there." in stored_captions(env)


async def test_a_retried_captions_job_reuses_the_cached_asr(env):
    env.fetcher.text = None
    env.llm.fail_status = 500  # the translate stage of a `translate_to` job fails after the ASR
    queued = (
        await env.client.post(f"/v1/videos/{VID}/captions", json={"translate_to": "de"})
    ).json()
    doc = await wait_state(env.client, queued["job_id"])
    assert doc["state"] == "failed", doc["events"]
    first_asr = event(env, queued["job_id"], "asr", "ok")["detail"]
    assert first_asr.get("cached") is None
    env.llm.fail_status = None
    retry = await env.client.post(f"/v1/jobs/{queued['job_id']}/retry")
    assert retry.status_code == 200, retry.text
    doc = await wait_state(env.client, queued["job_id"])
    assert doc["state"] == "ready", doc["events"]
    again = event(env, queued["job_id"], "asr", "ok")["detail"]
    assert again["cached"] is True
    audio = log_of(env, queued["job_id"])
    assert [e for e in audio if e["stage"] == "audio_download"][-1]["detail"]["source"] == (
        "from_archive"
    )
    vtt = stored_captions(env)
    assert "Hello there." in vtt and "T:" in vtt  # the translate stage answered at last


async def test_captions_status_reports_the_track_kind(env):
    env.fetcher.text = "[00:00] hello there my friend [00:04] how are you doing today"
    env.fetcher.segments = list(CAPTION_SEGMENTS)
    respond_with_cues(env.llm, ["Hello there, my friend.", "How are you doing today?"])
    await queue_captions(env, device_client(env))
    body = (await env.client.get(f"/v1/videos/{VID}/captions")).json()
    assert body["status"] == "ready" and body["tracks"][0]["label"] == "English (u·tubot)"
