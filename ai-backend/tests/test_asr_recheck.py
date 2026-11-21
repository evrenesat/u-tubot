"""The re-listen ladder of `AsrRouter`: forced language, smaller windows, next engine, drops."""

from __future__ import annotations

import wave
from pathlib import Path

from tests.test_asr_engines import RATE, engine_cfg, make_wav, speech
from utubot.captions import events
from utubot.captions.engines import AsrRouter, ChunkResult
from utubot.captions.events import JobEvents, JobTrace
from utubot.captions.types import Segment, Word
from utubot.config import CaptionsConfig, Config
from utubot.db import Database

TOTAL_S = 1740
LONG_S = 3600  # seven chunks: one bad chunk is a small minority
CHUNK_S = 600
LOOP_STEP_S = 30.0
LOOP_LEN_S = 7.0
LOOP_SEGMENTS = 20
TURKISH = "tr"
SMALL_WINDOW_S = 120.0
SECOND_CHUNK_START_S = 598.0  # chunks of 600 s overlap by 2 s


def loop_answer(duration: float, language: str) -> ChunkResult:
    steps = int(duration // LOOP_STEP_S)
    segments = [
        Segment(i * LOOP_STEP_S, i * LOOP_STEP_S + LOOP_LEN_S, "Thank you.")
        for i in range(min(steps, LOOP_SEGMENTS))
    ]
    return ChunkResult(segments, [], language)


class Scripted:
    """Answers every chunk with the talk, except those `broken(start, duration, language)` says are a loop."""

    def __init__(self, name: str, broken=None, language: str = TURKISH):
        self.name, self.broken, self.language = name, broken, language
        self.asked: list[tuple[float, float, str | None]] = []

    async def transcribe_chunk(self, wav: Path, language, want_words):
        with wave.open(str(wav), "rb") as fh:
            frames = fh.getnframes()
            start = int.from_bytes(fh.readframes(1), "little") / RATE
        duration = frames / RATE
        self.asked.append((start, duration, language))
        if self.broken and self.broken(start, duration, language):
            return loop_answer(duration, "en")
        result = speech(start, duration)
        result.language = language or self.language
        return result


def first_chunk_loops_unless_forced(start, duration, language):
    return start == 0 and language is None


def first_chunk_always_loops(start, duration, language):
    return start < SECOND_CHUNK_START_S


def build(engines: list, fakes: dict, **cfg) -> AsrRouter:
    chain = CaptionsConfig(asr_engines=engines, sample_rate=RATE, **cfg)
    return AsrRouter(chain, engine_factory=lambda e: fakes[e.name], enabled=lambda e: True)


async def transcribe(router: AsrRouter, wav: Path, **kw):
    db = Database(":memory:")
    log = JobEvents(db, Config().captions)
    token = events.bind(JobTrace("j1", log))
    try:
        result = await router.transcribe(wav, kw.pop("language", None), lambda f: None, **kw)
    finally:
        events.unbind(token)
    rechecks = [e for e in log.list("j1") if e["stage"] == "asr_recheck"]
    db.close()
    return result, rechecks


def texts(result) -> list[str]:
    return [seg.text for seg in result.segments]


async def test_mislabelled_chunk_is_redone_with_the_expected_language(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    fake = Scripted("mac", first_chunk_loops_unless_forced)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert "Thank you." not in texts(result)
    assert result.language == TURKISH and result.stats["rechecked_chunks"] == 1
    assert result.stats["hallucination_drops"] == 0
    (event,) = rechecks
    detail = event["detail"]
    assert event["status"] == "ok"
    assert detail["action"] == "forced_language" and detail["outcome"] == "replaced"
    assert detail["detected"] == "en" and detail["expected"] == "tr"
    assert (detail["start_s"], detail["end_s"]) == (0.0, 600.0)
    assert len(result.words) == len({(w.start, w.text) for w in result.words})


async def test_a_dominant_language_is_the_expected_one_without_a_hint(tmp_path):
    wav = make_wav(tmp_path / "a.wav", LONG_S)
    fake = Scripted("mac", first_chunk_loops_unless_forced)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    result, rechecks = await transcribe(router, wav, want_words=True)
    assert result.language == TURKISH and rechecks[0]["detail"]["expected"] == "tr"


async def test_a_wrong_metadata_language_yields_to_the_audio(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    fake = Scripted("mac")
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="en")
    assert rechecks == [] and len(fake.asked) == 3 and result.language == TURKISH


async def test_healthy_chunks_are_never_rechecked(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    fake = Scripted("mac")
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert rechecks == [] and len(fake.asked) == 3
    assert all(language is None for _s, _d, language in fake.asked)
    assert result.stats["rechecked_chunks"] == 0


async def test_smaller_window_is_tried_when_forcing_does_not_help(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)

    def loops_until_windowed(start, duration, language):
        return start == 0 and duration > SMALL_WINDOW_S + 1

    fake = Scripted("mac", loops_until_windowed)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    actions = [(e["detail"]["action"], e["detail"]["outcome"]) for e in rechecks]
    assert actions == [("forced_language", "kept"), ("smaller_window", "replaced")]
    windows = [d for s, d, lang in fake.asked if s < CHUNK_S and lang == "tr"]
    assert SMALL_WINDOW_S in windows[1:] and max(windows[1:]) <= SMALL_WINDOW_S + 3
    assert "Thank you." not in texts(result) and result.stats["hallucination_drops"] == 0


async def test_next_engine_is_tried_last(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    bad = Scripted("mac", first_chunk_always_loops)
    good = Scripted("box")
    router = build(
        [
            engine_cfg("mac", max_chunk_s=CHUNK_S, priority=10),
            engine_cfg("box", max_chunk_s=CHUNK_S, priority=50),
        ],
        {"mac": bad, "box": good},
    )
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert [e["detail"]["action"] for e in rechecks] == [
        "forced_language",
        "smaller_window",
        "next_engine",
    ]
    assert rechecks[-1]["detail"]["outcome"] == "replaced"
    assert "Thank you." not in texts(result) and result.stats["hallucination_drops"] == 0
    assert set(result.engine.split("+")) == {"mac", "box"}


async def test_unrecoverable_loop_is_dropped_not_shown(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    fake = Scripted("mac", first_chunk_always_loops)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert not [t for t in texts(result) if "Thank" in t]
    assert not [w for w in result.words if "Thank" in w.text]
    drops = result.stats["hallucination_drops"]
    assert drops >= LOOP_SEGMENTS // 2
    assert result.stats["dropped_s"] == drops * LOOP_LEN_S
    dropped = [e for e in rechecks if e["detail"]["action"] == "dropped"]
    assert len(dropped) == 1 and dropped[0]["status"] == "warn"
    assert dropped[0]["detail"]["dropped_segments"] == drops
    assert any(seg.text.startswith("w") for seg in result.segments)


async def test_review_can_be_switched_off_for_a_reference_transcript(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    fake = Scripted("mac", first_chunk_always_loops)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    result, rechecks = await transcribe(
        router, wav, want_words=True, expected_language="tr", review=False
    )
    assert rechecks == [] and len(fake.asked) == 3 and "Thank you." in texts(result)
    off = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake}, asr_recheck=False)
    _result, rechecks = await transcribe(off, wav, want_words=True, expected_language="tr")
    assert rechecks == []


async def test_plain_transcripts_are_reviewed_too(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    fake = Scripted("mac", first_chunk_loops_unless_forced)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    result, rechecks = await transcribe(router, wav, want_words=False, expected_language="tr")
    assert "Thank you." not in texts(result) and rechecks[0]["detail"]["outcome"] == "replaced"


async def test_a_failing_retry_keeps_the_first_answer(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)

    class Flaky(Scripted):
        async def transcribe_chunk(self, wav, language, want_words):
            if language is not None:
                from utubot.captions.engines import EngineError

                raise EngineError("boom", penalize=False, code="http_400")
            return await super().transcribe_chunk(wav, language, want_words)

    fake = Flaky("mac", first_chunk_always_loops)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert {e["detail"]["outcome"] for e in rechecks if "outcome" in e["detail"]} == {"failed"}
    assert result.stats["hallucination_drops"] == LOOP_SEGMENTS
    assert result.stats["unresolved_chunks"] == 1  # every rung failed with an engine error


async def test_a_sparse_chunk_is_listened_to_again(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)

    class Sparse(Scripted):
        async def transcribe_chunk(self, wav, language, want_words):
            result = await super().transcribe_chunk(wav, language, want_words)
            if self.asked[-1][0] == 0 and language is None:
                result.segments = result.segments[:1]
                result.words = result.words[:3]
            return result

    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": Sparse("mac")})
    result, rechecks = await transcribe(router, wav, want_words=True)
    assert rechecks and rechecks[0]["detail"]["reason"] == "sparse"
    assert rechecks[0]["detail"]["outcome"] == "replaced"


async def test_retries_do_not_wait_on_the_first_request_lock_of_an_auto_engine(tmp_path):
    """An `auto` OpenAI engine holds a lock while it resolves its word mode; the ladder runs after."""
    import asyncio

    import httpx

    from tests.test_asr_engines import form_of, nested_body

    def loop_body() -> dict:
        body = nested_body()
        body["language"] = "english"
        body["segments"] = [
            {
                "start": i * LOOP_STEP_S,
                "end": i * LOOP_STEP_S + LOOP_LEN_S,
                "text": " Thank you.",
                "words": [
                    {"word": " Thank", "start": i * LOOP_STEP_S, "end": i * LOOP_STEP_S + 1},
                    {"word": " you.", "start": i * LOOP_STEP_S + 2, "end": i * LOOP_STEP_S + 3},
                ],
            }
            for i in range(LOOP_SEGMENTS)
        ]
        return body

    calls: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        forced = "language" in form_of(request)
        calls.append(forced)
        body = nested_body()
        body["language"] = "turkish"
        if not forced and len(calls) == 1:
            body = loop_body()
        return httpx.Response(200, json=body)

    wav = make_wav(tmp_path / "a.wav", LONG_S)
    chain = CaptionsConfig(asr_engines=[engine_cfg("mac", max_chunk_s=CHUNK_S)], sample_rate=RATE)
    router = AsrRouter(chain, transport=httpx.MockTransport(handler))
    result, rechecks = await asyncio.wait_for(
        transcribe(router, wav, want_words=True, expected_language="tr"), timeout=20
    )
    assert any(e["detail"]["action"] == "forced_language" for e in rechecks)
    assert "Thank you." not in texts(result) and result.language == TURKISH


# --- review round 1: code-switching, repeats, budget, ranking, seams ---

from dataclasses import replace as dc_replace  # noqa: E402

from utubot.captions.types import TIMING_INTERPOLATED  # noqa: E402

SEAM_S = 598.0
FIVE_CHUNKS_S = 2990


class ByChunk:
    """An engine whose answer comes from `answer(index, start, duration, language)`."""

    name = "mac"

    def __init__(self, answer):
        self.answer = answer
        self.asked: list[tuple[float, float, str | None]] = []

    async def transcribe_chunk(self, wav: Path, language, want_words):
        with wave.open(str(wav), "rb") as fh:
            frames = fh.getnframes()
            start = int.from_bytes(fh.readframes(1), "little") / RATE
        duration = frames / RATE
        self.asked.append((start, duration, language))
        return self.answer(int(start // SEAM_S), start, duration, language)


def talk(start, duration, language, logprob=-0.2):
    result = speech(start, duration)
    result.language = language
    result.segments = [
        dc_replace(seg, no_speech_prob=0.01, avg_logprob=logprob, compression_ratio=1.1)
        for seg in result.segments
    ]
    return result


def rechecks_of(rechecks, key="action"):
    return [e["detail"].get(key) for e in rechecks]


async def test_a_code_switched_video_with_a_correct_hint_is_left_alone(tmp_path):
    langs = ["en", "hi", "en", "hi", "en"]
    fake = ByChunk(lambda i, s, d, language: talk(s, d, language or langs[i]))
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    wav = make_wav(tmp_path / "a.wav", FIVE_CHUNKS_S)
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="hi")
    assert rechecks == [] and len(fake.asked) == 5
    assert [c[2] for c in result.chunks] == langs


async def test_an_english_stretch_inside_a_hindi_video_is_not_forced_to_hindi(tmp_path):
    def answer(index, start, duration, language):
        if index == 3:  # a genuine English interview; forcing Hindi garbles it
            return talk(start, duration, language or "en", -0.2 if language is None else -1.0)
        return talk(start, duration, language or "hi")

    fake = ByChunk(answer)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    wav = make_wav(tmp_path / "a.wav", LONG_S)
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="hi")
    assert rechecks and {e["detail"]["outcome"] for e in rechecks} == {"kept"}
    assert result.chunks[3][2] == "en" and result.stats["rechecked_chunks"] == 1
    assert not result.dropped


async def test_forced_languages_only_for_a_language_mismatch(tmp_path):
    def answer(index, start, duration, language):
        if index == 2 and (language is None or duration > SMALL_WINDOW_S + 1):
            return ChunkResult([Segment(0.0, 1.0, "hm")], [], "tr")
        return talk(start, duration, language or "tr")

    fake = ByChunk(answer)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    wav = make_wav(tmp_path / "a.wav", LONG_S)
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert rechecks_of(rechecks) == [
        "smaller_window"
    ]  # sparse only: one rung, in the language heard
    langs = {lang for s, d, lang in fake.asked if 1196 <= s < 1796 and d <= SMALL_WINDOW_S + 1}
    assert langs == {"tr"} and rechecks[0]["detail"]["outcome"] == "replaced"


async def test_a_repeated_chant_that_the_relisten_hears_again_is_kept(tmp_path):
    def chant(start, duration):
        confident = duration <= SMALL_WINDOW_S + 1  # the windowed pass hears it with confidence
        logprob, compression = (-0.3, 1.1) if confident else (-1.3, 2.7)
        steps = int(duration // LOOP_STEP_S)
        return ChunkResult(
            [
                Segment(
                    i * LOOP_STEP_S, (i + 1) * LOOP_STEP_S, "la la la", 0.02, logprob, compression
                )
                for i in range(steps)
            ],
            [],
            "tr",
        )

    fake = ByChunk(lambda i, s, d, language: chant(s, d) if i == 1 else talk(s, d, "tr"))
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert rechecks and result.stats["hallucination_drops"] == 0
    assert sum(1 for seg in result.segments if seg.text == "la la la") >= 15


async def test_a_confident_chorus_is_never_rechecked(tmp_path):
    def chorus(start, duration):
        return ChunkResult(
            [
                Segment(i * 5.0, i * 5.0 + 4.0, "oh oh oh", 0.02, -0.3, 1.1)
                for i in range(int(duration // 5))
            ],
            [],
            "tr",
        )

    fake = ByChunk(lambda i, s, d, language: chorus(s, d) if i == 1 else talk(s, d, "tr"))
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert result.stats["hallucination_drops"] == 0
    assert sum(1 for seg in result.segments if seg.text == "oh oh oh") >= 100


async def test_the_recheck_budget_takes_the_worst_chunks_and_reports_the_rest(tmp_path):
    def answer(index, start, duration, language):
        if index in (0, 1, 2) and language is None:
            return loop_answer(duration, "en")
        return talk(start, duration, language or "tr")

    fake = ByChunk(answer)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    wav = make_wav(tmp_path / "a.wav", LONG_S)
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    skipped = [e for e in rechecks if e["status"] == "skipped"]
    assert len(skipped) == 2 and {e["detail"]["skipped"] for e in skipped} == {"budget"}
    assert result.stats["rechecked_chunks"] == 1 and result.stats["skipped_chunks"] == 2
    assert result.stats["unresolved_chunks"] == 0  # a budget skip is deterministic: cached
    assert 0 < result.stats["recheck_requests"] <= 12


async def test_the_request_cap_stops_further_rungs(tmp_path):
    fake = Scripted("mac", first_chunk_always_loops)
    router = build(
        [engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake}, asr_recheck_max_requests=1
    )
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert result.stats["recheck_requests"] == 1
    assert [e["detail"]["skipped"] for e in rechecks if e["status"] == "skipped"] == ["requests"]
    assert result.stats["unresolved_chunks"] == 0 and result.stats["skipped_chunks"] == 1
    assert len(fake.asked) == 3 + 1


async def test_a_sparse_chunk_gets_one_rung_even_with_a_second_engine(tmp_path):
    def sparse(index, start, duration, language):
        if index == 1:
            return ChunkResult([Segment(0.0, 1.0, "hm")], [], "tr")
        return talk(start, duration, language or "tr")

    mac, box = ByChunk(sparse), ByChunk(sparse)
    router = build(
        [
            engine_cfg("mac", max_chunk_s=CHUNK_S, priority=10),
            engine_cfg("box", max_chunk_s=CHUNK_S),
        ],
        {"mac": mac, "box": box},
    )
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    _result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert set(rechecks_of(rechecks)) == {"smaller_window"} and not box.asked


async def test_an_attempt_with_estimated_word_times_does_not_replace_real_ones(tmp_path):
    def answer(index, start, duration, language):
        if index == 1 and duration <= SMALL_WINDOW_S + 1:
            result = talk(start, duration, "tr")
            result.words = [dc_replace(w, timing=TIMING_INTERPOLATED) for w in result.words]
            return result
        if index == 1:
            return ChunkResult([Segment(0.0, 1.0, "hm")], [Word(0.0, 0.5, "hm")], "tr")
        return talk(start, duration, "tr")

    fake = ByChunk(answer)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert rechecks_of(rechecks, "outcome") == ["kept"]
    assert not any(w.timing == TIMING_INTERPOLATED for w in result.words)


async def test_a_phantom_in_the_overlap_of_a_neighbour_goes_too(tmp_path):
    def answer(index, start, duration, language):
        if index == 0 and language is None:
            result = loop_answer(duration, "en")
            result.segments.append(Segment(596.0, 599.0, "you"))
            return result
        result = talk(start, duration, language or "tr")
        if index == 1 and start == SEAM_S:
            result.segments.insert(0, Segment(0.2, 3.2, "you"))
        return result

    fake = ByChunk(answer)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    result, _ = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert not [seg for seg in result.segments if seg.text in ("you", "Thank you.")]
    assert result.stats["rechecked_chunks"] >= 1


async def test_no_attempt_on_an_engine_that_does_not_serve_the_language(tmp_path):
    def answer(index, start, duration, language):
        return loop_answer(duration, "en") if index == 0 else talk(start, duration, "tr")

    fake = ByChunk(answer)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S, languages=["en"])], {"mac": fake})
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert rechecks == [] and len(fake.asked) == 3 and not result.stats["rechecked_chunks"]


async def test_dropped_spans_and_chunk_languages_are_reported(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    fake = Scripted("mac", first_chunk_always_loops)
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    result, _ = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert result.dropped and all(len(row) == 3 and row[2] for row in result.dropped)
    assert len(result.chunks) == 3


async def test_a_deterministic_engine_loop_is_dropped_though_the_windows_repeat_it(tmp_path):
    def loop(duration):
        return ChunkResult(
            [
                Segment(i * LOOP_STEP_S, (i + 1) * LOOP_STEP_S, "Altyazı M.K.", 0.02, -1.3, 2.7)
                for i in range(int(duration // LOOP_STEP_S))
            ],
            [],
            "tr",
        )

    fake = ByChunk(lambda i, s, d, language: loop(d) if i == 1 else talk(s, d, "tr"))
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    result, _ = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert not [seg for seg in result.segments if "Altyaz" in seg.text]
    assert result.stats["hallucination_drops"] >= 15


async def test_without_avg_logprob_a_forced_language_must_keep_most_of_the_text(tmp_path):
    def answer_with(ratio):
        def answer(index, start, duration, language):
            result = speech(start, duration)
            result.language = language or ("en" if index == 1 else "tr")
            if index == 1 and language:
                result.segments = result.segments[: int(len(result.segments) * ratio)]
            return result

        return answer

    outcomes = {}
    for ratio in (0.6, 0.9):
        router = build(
            [engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": ByChunk(answer_with(ratio))}
        )
        wav = make_wav(tmp_path / f"{ratio}.wav", LONG_S)
        _r, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
        outcomes[ratio] = rechecks_of(rechecks, "outcome")[0]
    assert outcomes == {0.6: "kept", 0.9: "replaced"}


CREDIT = "Altyazı M.K."
CREDIT_AT_S = (2.0, 5.0)


class Crediting(Scripted):
    """A healthy talk with a made-up credit line over the intro music of the first chunk."""

    async def transcribe_chunk(self, wav: Path, language, want_words):
        result = await super().transcribe_chunk(wav, language, want_words)
        if self.asked[-1][0] == 0:
            result.segments.insert(0, Segment(*CREDIT_AT_S, CREDIT, 0.1, -0.3, 1.0))
            result.words.insert(0, Word(CREDIT_AT_S[0], CREDIT_AT_S[1], CREDIT))
        return result


async def test_a_credit_line_is_dropped_even_in_a_healthy_chunk(tmp_path):
    wav = make_wav(tmp_path / "a.wav", TOTAL_S)
    fake = Crediting("mac")
    router = build([engine_cfg("mac", max_chunk_s=CHUNK_S)], {"mac": fake})
    result, rechecks = await transcribe(router, wav, want_words=True, expected_language="tr")
    assert CREDIT not in texts(result) and all(w.text != CREDIT for w in result.words)
    assert result.stats["hallucination_drops"] == 1 and result.stats["rechecked_chunks"] == 0
    assert len(fake.asked) == 3  # no re-listen: the chunk is fine
    (drop,) = rechecks
    assert drop["detail"]["action"] == "dropped" and drop["detail"]["dropped_segments"] == 1
