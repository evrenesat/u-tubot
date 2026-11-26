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
    assert align["mode"] == "words" and align["speech_cues"] == 2 and align["cues"] == 2
    assert align["fill_cues"] == 0  # the spoken captions are never repeated next to their words
    word_timing = event(env, doc["id"], "word_timing")["detail"]
    assert word_timing["word_timing"] == "real" and word_timing["real_share"] == 1.0
    skipped = event(env, doc["id"], "sync_score")  # the test tone has no silence to compare with
    assert skipped["status"] == "skipped" and skipped["detail"]["reason"] == "no_silences"
    proofread = event(env, doc["id"], "proofread")["detail"]
    assert proofread["corrected"] == 1 and proofread["warned"] == 0
    vtt = stored_captions(env)
    assert "Hello there, my friend." in vtt and "How are you doing today?" in vtt
    # the cue timing comes from the ASR words themselves (the mock hears two phrases around a pause)
    assert "00:00:00.000 --> 00:00:01.400" in vtt
    assert "00:00:02.000 --> 00:00:04.200" in vtt
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
    assert align["mode"] == "captions_timing" and align["reason"] == "no_words"
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
        async def transcribe(
            self,
            wav,
            language,
            progress,
            *,
            priority=1,
            want_words=True,
            expected_language=None,
            klass=None,
            yield_check=None,
        ):
            return ASRResult(words=[], language=None, segments=[], engine="mock", model="mock")

    env.svc.jobs.pipeline.asr = SilentASR()
    doc = await queue_captions(env)
    asr = event(env, doc["id"], "asr", "warn")["detail"]
    assert asr["reason"] == "no_speech"
    align = event(env, doc["id"], "align")["detail"]
    assert align["mode"] == "captions_timing" and align["reason"] == "no_words"
    assert "Hello there, my friend." in stored_captions(env)


async def test_a_captions_job_keeps_the_caption_text_when_the_audio_cannot_be_fetched(env):
    from utubot.youtube import YoutubeVideoError

    env.fetcher.text = "[00:00] hello there my friend"
    env.fetcher.segments = [(0.0, 4.0, "hello there my friend")]
    respond_with_cues(env.llm, ["Hello there, my friend."])

    async def broken_downloader(vid, out, started):
        raise YoutubeVideoError("unavailable")

    env.svc.jobs.pipeline.downloader = broken_downloader
    doc = await queue_captions(env)
    asr = event(env, doc["id"], "asr", "warn")["detail"]
    assert asr["reason"] == "audio_unavailable"
    align = event(env, doc["id"], "align")["detail"]
    assert align["mode"] == "captions_timing" and align["reason"] == "no_words"
    assert "Hello there, my friend." in stored_captions(env)


async def test_the_improve_path_stores_cues_within_the_line_and_cps_limits(env):
    from utubot.captions.asr import ASRResult

    env.fetcher.text = "[00:00] big cue"
    env.fetcher.segments = [(0.0, 6.0, "big cue")]
    env.cfg.captions.proofread = False  # only the merge itself must respect the limits

    class WordyASR:
        async def transcribe(
            self,
            wav,
            language,
            progress,
            *,
            priority=1,
            want_words=True,
            expected_language=None,
            klass=None,
            yield_check=None,
        ):
            # 18 words inside the one 6 s cue window: ~125 characters, over the 2x42 limit
            words = []
            for i in range(18):
                start = 0.3 + i * 0.3
                words.append((start, start + 0.25, f"speech{i}"))
            return ASRResult(
                words=[Word(*word) for word in words],
                language="en",
                segments=[],
                engine="mock",
                model="mock",
            )

    from utubot.captions.types import Word

    asr = WordyASR()
    env.svc.jobs.pipeline.asr = asr
    doc = await queue_captions(env)
    align = event(env, doc["id"], "align")["detail"]
    assert align["mode"] == "words" and align["speech_cues"] > 1
    assert align["cues"] > 1  # the words were cut into several cues, none over the limits
    vtt = stored_captions(env)
    lines = [
        line
        for line in vtt.splitlines()
        if line and "-->" not in line and not line.isdigit() and line != "WEBVTT"
    ]
    assert lines, vtt
    assert all(len(line) <= env.cfg.captions.max_chars_per_line for line in lines)


async def test_a_captions_job_says_when_separation_is_not_installed(env):
    env.fetcher.text = None
    env.cfg.captions.separation = "demucs"
    env.cfg.captions.separation_cmd = ["definitely-not-on-path-xyz"]
    env.svc.jobs.pipeline.separator = None  # what make_separator builds for a missing tool
    doc = await queue_captions(env)
    separation = event(env, doc["id"], "separation", "skipped")["detail"]
    assert separation["reason"] == "not_installed"
    assert "Hello there." in stored_captions(env)


class RecordingSeparator:
    """A separator that counts its runs and never produces a vocals stem."""

    def __init__(self):
        self.calls = 0

    async def separate(self, wav, work):
        self.calls += 1
        return None


async def test_a_retried_captions_job_skips_separation_on_the_asr_cache_hit(env):
    env.fetcher.text = None
    env.cfg.captions.separation = "demucs"
    separator = RecordingSeparator()
    env.svc.jobs.pipeline.separator = separator
    env.llm.fail_status = 500  # the translate stage fails after the ASR, forcing a retry
    queued = (
        await env.client.post(f"/v1/videos/{VID}/captions", json={"translate_to": "de"})
    ).json()
    doc = await wait_state(env.client, queued["job_id"])
    assert doc["state"] == "failed", doc["events"]
    assert separator.calls == 1  # the first job ran the separation ahead of its ASR
    separation_entries = len(
        [e for e in log_of(env, queued["job_id"]) if e["stage"] == "separation"]
    )
    env.llm.fail_status = None
    retry = await env.client.post(f"/v1/jobs/{queued['job_id']}/retry")
    assert retry.status_code == 200, retry.text
    doc = await wait_state(env.client, queued["job_id"])
    assert doc["state"] == "ready", doc["events"]
    assert event(env, queued["job_id"], "asr", "ok")["detail"]["cached"] is True
    assert separator.calls == 1  # the cached answer skipped the separation entirely
    log = log_of(env, queued["job_id"])
    assert len([e for e in log if e["stage"] == "separation"]) == separation_entries


def test_the_asr_cache_key_includes_the_separation_mode():
    from utubot.captions.pipeline import asr_cache_key

    off = asr_cache_key("sha", True, "en", "off")
    demucs = asr_cache_key("sha", True, "en", "demucs")
    assert off != demucs
    assert off == asr_cache_key("sha", True, "en", "off")


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


async def test_a_captions_job_targets_english_by_default(env):
    env.fetcher.text = None  # the track is built from the audio, like any language
    respond_with_cues(env.llm, ["Hello there, my friend.", "How are you doing today?"])
    doc = await queue_captions(env)
    row = env.svc.db.one("SELECT translate_to FROM jobs WHERE id=?", [doc["id"]])
    assert row["translate_to"] == "en"
    stages = stages_of(env, doc["id"])
    assert "translate" not in stages  # an English track needs no translation
    outcomes = [e["stage"] for e in log_of(env, doc["id"]) if e["status"] == "ok"]
    assert outcomes.count("proofread") == 1  # exactly one pass: the source text, never translated


async def test_the_config_default_is_the_translation_target(env):
    env.cfg.captions.translate_to = "de"
    env.fetcher.text = None
    respond_with_cues(env.llm, ["Hello there, my friend.", "How are you doing today?"])
    doc = await queue_captions(env)
    row = env.svc.db.one("SELECT translate_to FROM jobs WHERE id=?", [doc["id"]])
    assert row["translate_to"] == "de"
    assert "T:" in stored_captions(env)  # the English audio was translated to German


async def test_the_user_setting_is_the_translation_target(env):
    env.fetcher.text = None
    respond_with_cues(env.llm, ["Hello there, my friend.", "How are you doing today?"])
    settings = {"transcripts": {"captions_translate_to": "DE"}}
    r = await env.client.put("/v1/me/settings", json={"settings": settings})
    assert r.json()["settings"]["transcripts"]["captions_translate_to"] == "de"
    doc = await queue_captions(env)
    row = env.svc.db.one("SELECT translate_to FROM jobs WHERE id=?", [doc["id"]])
    assert row["translate_to"] == "de"
    explicit = (
        await env.client.post(f"/v1/videos/{VID}/captions", json={"translate_to": "fr"})
    ).json()
    row = env.svc.db.one("SELECT translate_to FROM jobs WHERE id=?", [explicit["job_id"]])
    assert row["translate_to"] == "fr"  # a target named by the request still wins


async def test_the_user_setting_off_keeps_the_source_language(env):
    env.fetcher.text = None
    respond_with_cues(env.llm, ["Hello there, my friend.", "How are you doing today?"])
    for value in ("off", "none", ""):
        settings = {"transcripts": {"captions_translate_to": value}}
        r = await env.client.put("/v1/me/settings", json={"settings": settings})
        assert r.json()["settings"]["transcripts"]["captions_translate_to"] == "off", value
    queued = (await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})).json()
    row = env.svc.db.one("SELECT translate_to FROM jobs WHERE id=?", [queued["job_id"]])
    assert row["translate_to"] is None


async def test_translate_to_off_keeps_the_source_language(env):
    env.fetcher.text = None
    respond_with_cues(env.llm, ["Hello there, my friend.", "How are you doing today?"])
    for target in ("off", "none", ""):
        queued = (
            await env.client.post(f"/v1/videos/{VID}/captions", json={"translate_to": target})
        ).json()
        row = env.svc.db.one("SELECT translate_to FROM jobs WHERE id=?", [queued["job_id"]])
        assert row["translate_to"] is None, target


def test_a_bad_translate_to_config_default_is_rejected_at_startup():
    import pytest
    from pydantic import ValidationError

    from utubot.config import CaptionsConfig

    with pytest.raises(ValidationError):
        CaptionsConfig(translate_to="english")
    assert CaptionsConfig(translate_to=" EN ").translate_to == "en"
    assert CaptionsConfig(translate_to="OFF").translate_to == "off"


def test_proofread_batch_must_be_at_least_one():
    import pytest
    from pydantic import ValidationError

    from utubot.config import CaptionsConfig

    with pytest.raises(ValidationError):
        CaptionsConfig(proofread_batch=0)


def test_the_asr_cache_key_carries_a_version():
    from utubot.captions.pipeline import ASR_CACHE_VERSION, asr_cache_key

    assert asr_cache_key("sha", True, None, "off").startswith(f"v{ASR_CACHE_VERSION}:sha:1:auto")
    assert ASR_CACHE_VERSION == 4


async def test_an_old_cache_row_is_not_served(env):
    from utubot.captions.pipeline import ASR_CACHE_VERSION

    env.fetcher.text = None
    queued = (await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})).json()
    await wait_state(env.client, queued["job_id"])
    rows = env.svc.db.all("SELECT cache_key FROM stage_cache WHERE stage='asr'")
    assert rows and all(r["cache_key"].startswith(f"v{ASR_CACHE_VERSION}:") for r in rows)
    env.svc.db.execute("UPDATE stage_cache SET cache_key=substr(cache_key, 4) WHERE stage='asr'")
    before = len(env.llm.audio_calls)
    again = (await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})).json()
    await wait_state(env.client, again["job_id"])
    assert len(env.llm.audio_calls) > before  # the v1-keyed row was not read


async def test_interpolated_results_are_cached_per_engine_and_word_mode(env):
    from utubot.captions.pipeline import ASR_CACHE_VERSION
    from utubot.config import AsrEngineConfig

    env.fetcher.text = None
    env.llm.audio_words = "none"
    first = (await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})).json()
    doc = await wait_state(env.client, first["job_id"])
    assert doc["state"] == "ready", doc["events"]
    asr = event(env, first["job_id"], "asr", "ok")["detail"]
    assert asr["word_timing"] == "interpolated" and asr.get("cached") is None
    assert asr["words_real"] == 0 and asr["words_interpolated"] > 0
    assert event(env, first["job_id"], "word_timing", "warn")["detail"]["word_timing"] == (
        "interpolated"
    )
    keys = [
        r["cache_key"]
        for r in env.svc.db.all("SELECT cache_key FROM stage_cache WHERE stage='asr'")
    ]
    assert (
        len(keys) == 1
        and keys[0].startswith(f"v{ASR_CACHE_VERSION}:")
        and ":wm-default=none" in keys[0]
    )
    calls = len(env.llm.audio_calls)
    retry = (await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})).json()
    again = await wait_state(env.client, retry["job_id"])
    assert event(env, again["id"], "asr", "ok")["detail"]["cached"] is True
    assert len(env.llm.audio_calls) == calls  # a server that never gives words is not asked again

    # a new word mode is a new key: the engine is asked again, and now answers with real times
    env.llm.audio_words = "top"
    env.cfg.captions.asr_engines = [
        AsrEngineConfig(
            name="default", url=env.cfg.captions.asr_url, word_timestamps="both", key_optional=True
        )
    ]
    third = (await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})).json()
    done = await wait_state(env.client, third["job_id"])
    assert done["state"] == "ready", done["events"]
    assert len(env.llm.audio_calls) > calls
    assert event(env, done["id"], "asr", "ok")["detail"]["word_timing"] == "real"


async def test_mixed_and_real_results_are_cached_under_the_plain_key(env):
    env.fetcher.text = None
    queued = (await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})).json()
    await wait_state(env.client, queued["job_id"])
    keys = [
        r["cache_key"]
        for r in env.svc.db.all("SELECT cache_key FROM stage_cache WHERE stage='asr'")
    ]
    assert len(keys) == 1 and ":wm-" not in keys[0]


async def test_mixed_word_times_are_cached(tmp_path):
    from utubot.captions.asr import ASRResult
    from utubot.captions.pipeline import CaptionPipeline, word_mode_suffix
    from utubot.captions.types import TIMING_INTERPOLATED, Segment, Word
    from utubot.config import Config
    from utubot.db import Database

    class MixedAsr:
        calls = 0

        async def transcribe(
            self,
            wav,
            language,
            progress,
            *,
            priority=1,
            want_words=True,
            expected_language=None,
            klass=None,
            yield_check=None,
        ):
            self.calls += 1
            words = [Word(0.0, 0.5, "a"), Word(0.5, 1.0, "b", timing=TIMING_INTERPOLATED)]
            return ASRResult(
                words=words,
                language="en",
                segments=[Segment(0.0, 1.0, "a b")],
                word_timing="mixed",
            )

        def word_signature(self, language):
            return "x=both"

    cfg = Config()
    cfg.server.data_dir = str(tmp_path)
    asr = MixedAsr()
    pipe = CaptionPipeline(cfg, Database(tmp_path / "t.sqlite"), asr)
    for _ in range(2):
        await pipe._asr_stage(
            VID, tmp_path / "x.wav", None, lambda f: None,
            priority=1, want_words=True, optional_asr=False, key="v2:sha:1:auto:off",
        )  # fmt: skip
    assert asr.calls == 1
    assert word_mode_suffix(asr, None) == ":wm-x=both"
    assert word_mode_suffix(object(), None) == ":wm-unknown"


def test_cached_asr_keeps_timing_and_segment_metrics():
    from utubot.captions.asr import ASRResult
    from utubot.captions.pipeline import asr_from_cache, asr_to_cache
    from utubot.captions.types import TIMING_INTERPOLATED, TIMING_REPAIRED, Segment, Word

    result = ASRResult(
        words=[Word(0.0, 0.5, "hi", prob=0.9), Word(0.5, 1.0, "there", timing=TIMING_REPAIRED)],
        language="en",
        segments=[Segment(0.0, 1.0, "hi there", 0.01, -0.2, 1.3)],
        engine="mac",
        model="m",
        word_timing="real",
        stats={"words_real": 2, "words_interpolated": 0},
    )
    back = asr_from_cache(asr_to_cache(result))
    assert back == result
    old = asr_from_cache(
        {"words": [[0.0, 0.5, "hi"]], "segments": [[0.0, 1.0, "hi there"]], "language": "en"}
    )
    assert old.words == [Word(0.0, 0.5, "hi", timing=TIMING_INTERPOLATED)] and old.segments == [
        Segment(0.0, 1.0, "hi there")
    ]


async def test_a_wordless_fallback_answer_is_not_served_after_the_word_engine_recovers(tmp_path):
    from tests.test_asr_engines import FakeEngine, engine_cfg, make_wav
    from utubot.captions.engines import AsrRouter, EngineError
    from utubot.captions.pipeline import CaptionPipeline
    from utubot.captions.types import TIMING_INTERPOLATED
    from utubot.config import CaptionsConfig, Config
    from utubot.db import Database

    class Wordless(FakeEngine):
        async def transcribe_chunk(self, wav, language, want_words):
            result = await super().transcribe_chunk(wav, language, want_words)
            result.words = [replace(w, timing=TIMING_INTERPOLATED) for w in result.words]
            return result

    class Flaky(FakeEngine):
        down = True

        async def transcribe_chunk(self, wav, language, want_words):
            if self.down:
                raise EngineError("asr http 503", code="http_503", isolated=True)
            return await super().transcribe_chunk(wav, language, want_words)

    from dataclasses import replace

    good, fallback = Flaky("good"), Wordless("fallback")
    chain = AsrRouter(
        CaptionsConfig(
            asr_engines=[
                engine_cfg("good", priority=1, word_timestamps="both"),
                engine_cfg("fallback", priority=2),
            ],
            sample_rate=10,
        ),
        engine_factory=lambda e: {"good": good, "fallback": fallback}[e.name],
        enabled=lambda e: True,
    )
    cfg = Config()
    cfg.server.data_dir = str(tmp_path)
    pipe = CaptionPipeline(cfg, Database(tmp_path / "t.sqlite"), chain)
    wav = make_wav(tmp_path / "a.wav", 20)

    async def job():
        return await pipe._asr_stage(
            VID, wav, None, lambda f: None,
            priority=1, want_words=True, optional_asr=False, key="v2:sha:1:auto:off",
        )  # fmt: skip

    first = await job()
    assert first.word_timing == "interpolated" and first.engine == "fallback"
    stored = [r["cache_key"] for r in pipe.db.all("SELECT cache_key FROM stage_cache")]
    assert len(stored) == 1 and ":wm-" in stored[0]
    good.down = False
    second = await job()
    assert second.word_timing == "real" and second.engine == "good"


async def test_a_result_with_unresolved_rechecks_is_not_cached(tmp_path):
    from utubot.captions import events
    from utubot.captions.asr import ASRResult
    from utubot.captions.events import JobEvents, JobTrace
    from utubot.captions.pipeline import CaptionPipeline, asr_from_cache, asr_to_cache
    from utubot.captions.types import Segment, Word
    from utubot.config import Config
    from utubot.db import Database

    class Unresolved:
        calls = 0
        hint = None

        async def transcribe(
            self,
            wav,
            language,
            progress,
            *,
            priority=1,
            want_words=True,
            expected_language=None,
            klass=None,
            yield_check=None,
        ):
            self.calls += 1
            self.hint = expected_language
            return ASRResult(
                words=[Word(0.0, 0.5, "a")],
                language="en",
                segments=[Segment(0.0, 1.0, "a")],
                word_timing="real",
                stats={"unresolved_chunks": 1},
                dropped=[[3.0, 9.0, "phantom"]],
                chunks=[[0.0, 600.0, "en"]],
            )

    cfg = Config()
    cfg.server.data_dir = str(tmp_path)
    db = Database(tmp_path / "t.sqlite")
    db.execute(
        "INSERT INTO video_meta(video_id,json,fetched_at) VALUES(?,?,?)",
        [VID, '{"language": "tr"}', 0.0],
    )
    asr = Unresolved()
    pipe = CaptionPipeline(cfg, db, asr)
    log = JobEvents(db, cfg.captions)
    token = events.bind(JobTrace("j1", log))
    try:
        for _ in range(2):
            await pipe._asr_stage(
                VID, tmp_path / "x.wav", None, lambda f: None,
                priority=1, want_words=True, optional_asr=False, key="v3:sha:1:auto:off",
            )  # fmt: skip
    finally:
        events.unbind(token)
    assert asr.calls == 2 and asr.hint == "tr"
    assert not db.all("SELECT 1 FROM stage_cache WHERE stage='asr'")
    asr_events = [e for e in log.list("j1") if e["stage"] == "asr"]
    assert any(e["detail"].get("cache") == "not_stored_unresolved" for e in asr_events)
    result = await asr.transcribe(None, None, None)
    back = asr_from_cache(asr_to_cache(result))
    assert back.dropped == [[3.0, 9.0, "phantom"]] and back.chunks == [[0.0, 600.0, "en"]]


async def test_a_budget_skipped_result_is_cached(tmp_path):
    from utubot.captions.asr import ASRResult
    from utubot.captions.pipeline import CaptionPipeline
    from utubot.captions.types import Segment, Word
    from utubot.config import Config
    from utubot.db import Database

    class Skipped:
        async def transcribe(
            self,
            wav,
            language,
            progress,
            *,
            priority=1,
            want_words=True,
            expected_language=None,
            klass=None,
            yield_check=None,
        ):
            return ASRResult(
                words=[Word(0.0, 0.5, "a")],
                language="en",
                segments=[Segment(0.0, 1.0, "a")],
                word_timing="real",
                stats={"unresolved_chunks": 0, "skipped_chunks": 2},
            )

    cfg = Config()
    cfg.server.data_dir = str(tmp_path)
    db = Database(tmp_path / "t.sqlite")
    pipe = CaptionPipeline(cfg, db, Skipped())
    await pipe._asr_stage(
        VID, tmp_path / "x.wav", None, lambda f: None,
        priority=1, want_words=True, optional_asr=False, key="v3:sha:1:auto:off",
    )  # fmt: skip
    assert len(db.all("SELECT 1 FROM stage_cache WHERE stage='asr'")) == 1
