"""The ASR engine chain: selection, fallthrough, chunking, stitching, estimates, legacy config."""

from __future__ import annotations

import asyncio
import json
import re
import wave
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from utubot.captions import events
from utubot.captions.asr import ASRError
from utubot.captions.engines import (
    AsrRouter,
    ChunkResult,
    EngineError,
    OpenAIEngine,
    engine_enabled,
    parse_verbose_json,
)
from utubot.captions.events import JobEvents, JobTrace
from utubot.captions.types import TIMING_INTERPOLATED, TIMING_REAL, Segment, Word
from utubot.config import AsrEngineConfig, CaptionsConfig, Config
from utubot.db import Database
from utubot.llm import BACKGROUND, INTERACTIVE

RATE = 10
WORDS_PER_S = 3
WORD_S = 0.3
SEGMENT_WORDS = 8


def make_wav(path: Path, seconds: float) -> Path:
    """A WAV whose sample at frame i is i, so a chunk file tells where it starts."""
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(b"".join(i.to_bytes(2, "little") for i in range(int(seconds * RATE))))
    return path


def speech(start: float, duration: float) -> ChunkResult:
    """The words of one continuous talk (word k at k/3 s) that lie fully inside the chunk."""
    first = -(-int(start * WORDS_PER_S * 100) // 100)
    ks = [
        k
        for k in range(first, int((start + duration) * WORDS_PER_S) + 1)
        if k / WORDS_PER_S >= start and k / WORDS_PER_S + WORD_S <= start + duration
    ]
    words = [Word(k / WORDS_PER_S - start, k / WORDS_PER_S - start + WORD_S, f"w{k}") for k in ks]
    segments = [
        Segment(group[0].start, group[-1].end, " ".join(w.text for w in group))
        for i in range(0, len(words), SEGMENT_WORDS)
        for group in [words[i : i + SEGMENT_WORDS]]
    ]
    return ChunkResult(segments, words, "en")


class FakeEngine:
    def __init__(self, name: str, *, delay: float = 0.0, fail: Exception | None = None):
        self.name, self.delay, self.fail = name, delay, fail
        self.chunks: list[tuple[float, float]] = []
        self.languages: list[str | None] = []
        self.want_words: list[bool] = []
        self.active = 0
        self.peak = 0

    async def transcribe_chunk(self, wav: Path, language: str | None, want_words: bool):
        with wave.open(str(wav), "rb") as fh:
            frames = fh.getnframes()
            start = int.from_bytes(fh.readframes(1), "little") / RATE
        duration = frames / RATE
        self.chunks.append((start, duration))
        self.languages.append(language)
        self.want_words.append(want_words)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if self.fail is not None:
                raise self.fail
            return speech(start, duration)
        finally:
            self.active -= 1


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def engine_cfg(name: str, **kw) -> AsrEngineConfig:
    return AsrEngineConfig(name=name, url=f"http://{name}.example/v1/audio/transcriptions", **kw)


def router(engines: list[AsrEngineConfig], fakes: dict[str, FakeEngine], **kw) -> AsrRouter:
    cfg = CaptionsConfig(asr_engines=engines, sample_rate=RATE)
    clock = kw.pop("clock", Clock())
    return AsrRouter(
        cfg,
        engine_factory=lambda e: fakes[e.name],
        clock=clock,
        enabled=kw.pop("enabled", lambda e: True),
        **kw,
    )


def transcript_words(result) -> list[str]:
    return [w for seg in result.segments for w in seg.text.split()]


async def run(r: AsrRouter, wav: Path, language=None, *, priority=BACKGROUND, want_words=False):
    progress: list[float] = []
    result = await r.transcribe(
        wav, language, progress.append, priority=priority, want_words=want_words
    )
    return result, progress


async def test_chunks_run_in_parallel_up_to_max_parallel_and_stitch_without_gaps_or_repeats(
    tmp_path,
):
    wav = make_wav(tmp_path / "a.wav", 1740)
    fake = FakeEngine("mac", delay=0.02)
    r = router([engine_cfg("mac", max_chunk_s=600, max_parallel=3)], {"mac": fake})
    result, progress = await run(r, wav)
    assert [c[0] for c in sorted(fake.chunks)] == [0.0, 598.0, 1196.0]
    assert fake.peak == 3
    expected = [f"w{k}" for k in range(1740 * WORDS_PER_S)]
    assert transcript_words(result) == expected
    assert result.engine == "mac" and result.model == "whisper-1" and result.language == "en"
    assert sorted(progress) == pytest.approx([1 / 3, 2 / 3, 1.0])
    assert not list(tmp_path.glob("asr-*"))


async def test_max_parallel_one_runs_chunks_one_at_a_time(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 1300)
    fake = FakeEngine("box", delay=0.01)
    r = router([engine_cfg("box", max_chunk_s=540, max_parallel=1)], {"box": fake})
    result, _ = await run(r, wav)
    assert fake.peak == 1 and len(fake.chunks) == 3
    assert transcript_words(result) == [f"w{k}" for k in range(1300 * WORDS_PER_S)]


async def test_the_engine_limit_is_shared_by_concurrent_jobs(tmp_path):
    wav_a, wav_b = make_wav(tmp_path / "a.wav", 400), make_wav(tmp_path / "b.wav", 400)
    fake = FakeEngine("box", delay=0.01)
    r = router([engine_cfg("box", max_chunk_s=100, max_parallel=2)], {"box": fake})
    await asyncio.gather(run(r, wav_a), run(r, wav_b))
    assert fake.peak == 2


async def test_a_short_file_is_sent_whole_and_words_are_requested_only_when_asked(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 120)
    fake = FakeEngine("mac")
    r = router([engine_cfg("mac")], {"mac": fake})
    result, progress = await run(r, wav, want_words=True)
    assert fake.chunks == [(0.0, 120.0)] and fake.want_words == [True]
    assert len(result.words) == 120 * WORDS_PER_S and progress == [1.0]
    plain, _ = await run(r, wav)
    assert fake.want_words == [True, False] and plain.segments


async def test_a_known_language_skips_engines_that_do_not_list_it_and_unknown_prefers_open_ones(
    tmp_path,
):
    mac = engine_cfg("mac", priority=10)
    box = engine_cfg("box", languages=["en", "tr"], priority=5)
    local = engine_cfg("local", priority=30)
    r = router([mac, box, local], {})
    assert [e.name for e in r.candidates("es")] == ["mac", "local"]
    assert [e.name for e in r.candidates("tr")] == ["box", "mac", "local"]
    assert [e.name for e in r.candidates("en-US")] == ["box", "mac", "local"]
    assert [e.name for e in r.candidates(None)] == ["mac", "local", "box"]


async def test_the_language_reaches_the_engine_normalised(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    fake = FakeEngine("mac")
    r = router([engine_cfg("mac")], {"mac": fake})
    await run(r, wav, "Turkish")
    await run(r, wav, "en-US")
    await run(r, wav, None)
    assert fake.languages == ["tr", "en", None]


async def test_lower_priority_number_goes_first_and_ties_keep_config_order():
    r = router([engine_cfg("c", priority=30), engine_cfg("a", priority=10), engine_cfg("b")], {})
    assert [e.name for e in r.candidates(None)] == ["a", "c", "b"]


async def test_background_only_engines_never_take_interactive_jobs():
    r = router(
        [engine_cfg("mac", priority=20), engine_cfg("box", priority=10, background_only=True)], {}
    )
    assert [e.name for e in r.candidates(None, BACKGROUND)] == ["box", "mac"]
    assert [e.name for e in r.candidates(None, INTERACTIVE)] == ["mac"]


async def test_an_engine_is_enabled_when_its_key_variable_is_set(monkeypatch):
    keyed = engine_cfg("mac", api_key_env="UTUBOT_TEST_ASR_KEY")
    optional = engine_cfg("legacy", api_key_env="UTUBOT_TEST_ASR_KEY", key_optional=True)
    keyless = engine_cfg("lan")
    monkeypatch.delenv("UTUBOT_TEST_ASR_KEY", raising=False)
    assert not engine_enabled(keyed) and engine_enabled(optional) and engine_enabled(keyless)
    monkeypatch.setenv("UTUBOT_TEST_ASR_KEY", "secret")
    assert engine_enabled(keyed)
    monkeypatch.setenv("UTUBOT_TEST_ASR_KEY", "")
    assert not engine_enabled(keyed)


async def test_a_local_engine_needs_its_package(monkeypatch):
    local = AsrEngineConfig(name="local", kind="faster_whisper")
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert not engine_enabled(local)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    assert engine_enabled(local) and local.model == "small"


async def test_a_disabled_engine_is_never_a_candidate():
    r = router(
        [engine_cfg("mac"), engine_cfg("local", priority=50)],
        {},
        enabled=lambda e: e.name != "mac",
    )
    assert [e.name for e in r.candidates(None)] == ["local"]
    assert (
        r.available() and not router([engine_cfg("mac")], {}, enabled=lambda e: False).available()
    )


async def test_a_failing_engine_falls_through_and_is_skipped_until_it_recovers(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 90)
    clock = Clock()
    mac = FakeEngine("mac", fail=EngineError("asr http 503"))
    local = FakeEngine("local")
    r = router(
        [engine_cfg("mac", priority=10), engine_cfg("local", priority=20)],
        {"mac": mac, "local": local},
        clock=clock,
    )
    result, _ = await run(r, wav)
    assert result.engine == "local" and len(mac.chunks) == 1 and len(local.chunks) == 1
    assert not r.healthy("mac")
    assert [e.name for e in r.candidates(None)] == ["local", "mac"]

    await run(r, wav)
    assert len(mac.chunks) == 1 and len(local.chunks) == 2

    clock.t += r.cfg.asr_unhealthy_s + 1
    mac.fail = None
    result, _ = await run(r, wav)
    assert r.healthy("mac") and result.engine == "mac" and len(mac.chunks) == 2


async def test_an_input_rejection_falls_through_without_marking_the_engine_unhealthy(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    mac = FakeEngine("mac", fail=EngineError("asr http 413", penalize=False))
    local = FakeEngine("local")
    r = router(
        [engine_cfg("mac", priority=1), engine_cfg("local", priority=2)],
        {"mac": mac, "local": local},
    )
    result, _ = await run(r, wav)
    assert result.engine == "local" and r.healthy("mac")


async def test_when_every_engine_failed_recently_the_chain_is_still_tried(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    only = FakeEngine("only", fail=EngineError("asr transport error"))
    r = router([engine_cfg("only")], {"only": only})
    with pytest.raises(ASRError):
        await run(r, wav)
    assert not r.healthy("only")
    only.fail = None
    result, _ = await run(r, wav)
    assert result.engine == "only" and r.available()


async def test_all_engines_failing_is_an_asr_error(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    a = FakeEngine("a", fail=EngineError("boom"))
    b = FakeEngine("b", fail=EngineError("boom"))
    r = router([engine_cfg("a", priority=1), engine_cfg("b", priority=2)], {"a": a, "b": b})
    with pytest.raises(ASRError, match="all speech-to-text engines failed"):
        await run(r, wav)


async def test_no_candidate_is_an_asr_error(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    r = router([engine_cfg("box", languages=["en"])], {}, enabled=lambda e: True)
    with pytest.raises(ASRError, match="no speech-to-text engine"):
        await run(r, wav, "es")


async def test_a_failed_chunk_is_redone_by_the_next_engine_with_its_own_smaller_chunks(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 1200)
    mac = FakeEngine("mac", fail=EngineError("asr http 500"))
    box = FakeEngine("box")
    r = router(
        [
            engine_cfg("mac", priority=1, max_chunk_s=600),
            engine_cfg("box", priority=2, max_chunk_s=300),
        ],
        {"mac": mac, "box": box},
    )
    result, _ = await run(r, wav)
    assert max(d for _, d in box.chunks) <= 300 + 3
    assert transcript_words(result) == [f"w{k}" for k in range(1200 * WORDS_PER_S)]
    assert result.engine == "box" and result.model == "whisper-1"


async def test_chunks_of_one_file_may_end_up_on_different_engines(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 1300)

    class FlakyOnce(FakeEngine):
        async def transcribe_chunk(self, wav, language, want_words):
            if not self.chunks:
                self.chunks.append((-1.0, 0.0))
                raise EngineError("asr http 502", isolated=True)
            return await super().transcribe_chunk(wav, language, want_words)

    mac, local = FlakyOnce("mac"), FakeEngine("local")
    r = router(
        [engine_cfg("mac", priority=1, max_parallel=1), engine_cfg("local", priority=2)],
        {"mac": mac, "local": local},
    )
    result, _ = await run(r, wav)
    assert transcript_words(result) == [f"w{k}" for k in range(1300 * WORDS_PER_S)]
    assert result.engine == "local+mac"


async def test_the_language_is_the_one_most_of_the_audio_was_detected_as(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 1300)

    class Detects(FakeEngine):
        async def transcribe_chunk(self, wav, language, want_words):
            out = await super().transcribe_chunk(wav, language, want_words)
            out.language = "tr" if self.chunks[-1][0] == 0.0 else "en"
            return out

    r = router([engine_cfg("mac", max_chunk_s=600)], {"mac": Detects("mac")})
    result, _ = await run(r, wav)
    assert result.language == "en"


def test_estimate_uses_the_chosen_engine_speed_and_parallelism():
    mac = engine_cfg("mac", priority=1, speed_factor=37.5, max_parallel=3, overhead_s=1.0)
    box = engine_cfg("box", priority=2, speed_factor=3.0, max_parallel=1, overhead_s=2.0)
    r = router([mac, box], {})
    assert r.estimate_s(1740, "en") == pytest.approx(1.0 + 1740 / (37.5 * 3))
    assert r.estimate_s(500, "en") == pytest.approx(1.0 + 500 / 37.5)
    r._penalize(mac)
    assert r.estimate_s(1740, "en") == pytest.approx(2.0 + 1740 / 3.0)
    assert router([engine_cfg("x", languages=["en"])], {}).estimate_s(100, "ja") is None


def test_estimate_skips_background_only_engines_for_interactive_work():
    box = engine_cfg("box", priority=1, speed_factor=3.0, background_only=True)
    mac = engine_cfg("mac", priority=2, speed_factor=30.0, overhead_s=0.0)
    r = router([box, mac], {})
    assert r.estimate_s(600, None, INTERACTIVE) == pytest.approx(600 / 30.0)
    assert r.estimate_s(600, None, BACKGROUND) == pytest.approx(2.0 + 600 / 3.0)


def test_the_old_single_backend_keys_become_one_engine():
    cfg = CaptionsConfig(
        asr_backend="openai",
        asr_url="http://asr.example/v1/audio/transcriptions",
        asr_model="whisper-large",
        asr_api_key_env="MY_KEY",
        asr_chunk_s=300,
        asr_timeout_s=99.0,
        asr_speed_factor=4.0,
        asr_overhead_s=7,
    )
    (engine,) = cfg.engines()
    assert (engine.name, engine.kind, engine.model) == ("default", "openai", "whisper-large")
    assert engine.url == "http://asr.example/v1/audio/transcriptions"
    assert (engine.api_key_env, engine.key_optional) == ("MY_KEY", True)
    assert (engine.max_chunk_s, engine.max_parallel, engine.timeout_s) == (300, 1, 99.0)
    assert (engine.speed_factor, engine.overhead_s, engine.languages) == (4.0, 7.0, [])

    local = CaptionsConfig(asr_backend="faster_whisper", whisper_model="medium", whisper_threads=6)
    (engine,) = local.engines()
    assert (engine.kind, engine.model, engine.threads) == ("faster_whisper", "medium", 6)


def test_the_old_default_is_one_keyless_engine_that_works_without_a_key(monkeypatch):
    monkeypatch.delenv("UTUBOT_ASR_API_KEY", raising=False)
    (engine,) = CaptionsConfig().engines()
    assert engine_enabled(engine)


def test_engines_in_the_config_replace_the_old_keys():
    cfg = CaptionsConfig(
        asr_url="http://old.example/v1/audio/transcriptions",
        asr_engines=[engine_cfg("mac"), engine_cfg("box")],
    )
    assert [e.name for e in cfg.engines()] == ["mac", "box"]


def test_engines_load_from_toml_with_every_documented_field():
    from utubot.config import Config

    raw = {
        "captions": {
            "asr_engines": [
                {
                    "name": "mac",
                    "kind": "openai",
                    "url": "http://mac.example:8901/v1/audio/transcriptions",
                    "model": "whisper-large-v3-turbo-asr-fp16",
                    "api_key_env": "UTUBOT_ASR_API_KEY",
                    "max_chunk_s": 600,
                    "max_parallel": 3,
                    "timeout_s": 300,
                    "priority": 10,
                },
                {
                    "name": "box",
                    "url": "http://box.example:8788/v1/audio/transcriptions",
                    "languages": ["EN", " tr "],
                    "max_chunk_s": 540,
                    "background_only": True,
                },
                {"name": "local", "kind": "faster_whisper", "model": "small"},
            ]
        }
    }
    cfg = Config(**raw)
    mac, box, local = cfg.captions.engines()
    assert mac.max_parallel == 3 and box.languages == ["en", "tr"] and box.background_only
    assert local.url == "" and local.kind == "faster_whisper"
    with pytest.raises(ValueError, match="needs a url"):
        AsrEngineConfig(name="x", kind="openai")


# ---- the OpenAI-compatible engine over a mocked transport ---------------------------------------


def verbose(text="Hello there", language="english", segments=True, words=False) -> dict:
    body: dict = {"language": language, "text": text}
    if segments:
        body["segments"] = [{"start": 0.0, "end": 2.0, "text": f" {text}"}]
    if words:
        body["words"] = [{"word": "Hello", "start": 0.0, "end": 0.5}]
    return body


def serve(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def test_the_openai_engine_posts_the_chunk_with_model_key_and_granularities(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("UTUBOT_TEST_ASR_KEY", "sekret")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = request.content
        seen["url"] = str(request.url)
        return httpx.Response(200, json=verbose(words=True))

    cfg = engine_cfg("mac", model="m1", api_key_env="UTUBOT_TEST_ASR_KEY")
    engine = OpenAIEngine(cfg, serve(handler))
    wav = make_wav(tmp_path / "c.wav", 5)
    out = await engine.transcribe_chunk(wav, "en", want_words=True)
    assert seen["auth"] == "Bearer sekret" and seen["url"] == cfg.url
    body = seen["body"].decode("latin-1")
    assert 'name="model"\r\n\r\nm1' in body and "verbose_json" in body
    assert (
        body.count('name="timestamp_granularities[]"') == 2 and 'name="language"\r\n\r\nen' in body
    )
    assert out.language == "en" and out.segments == [Segment(0.0, 2.0, "Hello there")]
    assert out.words == [Word(0.0, 0.5, "Hello")]

    await engine.transcribe_chunk(wav, None, want_words=False)
    assert seen["body"].decode("latin-1").count('name="timestamp_granularities[]"') == 1
    assert 'name="language"' not in seen["body"].decode("latin-1")


@pytest.mark.parametrize(
    ("status", "penalize", "isolated"),
    [
        (500, True, True),
        (503, True, True),
        (429, True, False),
        (401, True, False),
        (404, True, False),
        (413, False, False),
        (422, False, False),
    ],
)
async def test_http_errors_mark_the_engine_unhealthy_except_input_rejections(
    tmp_path, status, penalize, isolated
):
    engine = OpenAIEngine(
        engine_cfg("mac"), serve(lambda request: httpx.Response(status, text="no"))
    )
    with pytest.raises(EngineError) as exc:
        await engine.transcribe_chunk(make_wav(tmp_path / "c.wav", 2), None, False)
    assert exc.value.penalize is penalize and str(status) in str(exc.value)
    assert exc.value.isolated is isolated


async def test_transport_failures_and_bad_bodies_are_engine_errors_without_leaking_the_url(
    tmp_path,
):
    def refuse(request):
        raise httpx.ConnectError("connection refused to http://mac.example/secret?token=1")

    wav = make_wav(tmp_path / "c.wav", 2)
    with pytest.raises(EngineError) as exc:
        await OpenAIEngine(engine_cfg("mac"), serve(refuse)).transcribe_chunk(wav, None, False)
    assert exc.value.penalize and "mac.example" not in str(exc.value)
    junk = OpenAIEngine(engine_cfg("mac"), serve(lambda r: httpx.Response(200, text="<html>")))
    with pytest.raises(EngineError, match="not JSON"):
        await junk.transcribe_chunk(wav, None, False)


def test_a_bare_text_answer_becomes_one_segment_and_words_are_spread_when_asked():
    out = parse_verbose_json({"text": " one two three four ", "language": "turkish"}, 12.0, True)
    assert out.segments == [Segment(0.0, 12.0, "one two three four")] and out.language == "tr"
    assert [w.text for w in out.words] == ["one", "two", "three", "four"]
    assert out.words[0].start == 0.0 and out.words[-1].end == pytest.approx(12.0)
    assert parse_verbose_json({"text": ""}, 3.0, False) == ChunkResult([], [], None)


def test_verbose_json_round_trips_through_json_text():
    raw = json.dumps(verbose(words=True))
    assert parse_verbose_json(json.loads(raw), 2.0, False).words == [Word(0.0, 0.5, "Hello")]


def test_the_documented_three_engine_chain_loads_and_routes_as_described():
    import re
    import tomllib

    from utubot.config import Config

    docs = Path(__file__).resolve().parents[2] / "docs" / "captions.md"
    blocks = re.findall(r"```toml\n(.*?)```", docs.read_text(), re.DOTALL)
    chain = next(b for b in blocks if b.count("[[captions.asr_engines]]") == 3)
    cfg = Config(captions=tomllib.loads(chain)["captions"])
    mac, box, local = cfg.captions.engines()
    assert (mac.name, mac.max_parallel, mac.max_chunk_s, mac.languages) == ("mac", 3, 600, [])
    assert mac.model == "whisper-large-v3-turbo-asr-fp16"
    assert (box.languages, box.max_chunk_s, box.max_parallel, box.background_only) == (
        ["en", "tr"],
        540,
        1,
        True,
    )
    assert (local.kind, local.priority) == ("faster_whisper", 30)
    router = AsrRouter(cfg.captions, enabled=lambda e: True)
    assert [e.name for e in router.candidates("en", INTERACTIVE)] == ["mac", "local"]
    assert [e.name for e in router.candidates("en", BACKGROUND)] == ["mac", "lan-cpu", "local"]
    assert [e.name for e in router.candidates("ja", BACKGROUND)] == ["mac", "local"]
    assert "http" in chain and "example" in chain


# ---- a failure tied to one file does not condemn the engine --------------------------------------


@pytest.mark.parametrize(
    ("error", "isolated"),
    [
        (httpx.ConnectError("refused"), False),
        (httpx.ConnectTimeout("slow"), False),
        (httpx.ReadTimeout("slow"), False),
        (httpx.ReadError("reset"), True),
        (httpx.RemoteProtocolError("closed"), True),
    ],
)
async def test_only_connect_and_timeout_failures_count_at_once(tmp_path, error, isolated):
    def fail(request):
        raise error

    engine = OpenAIEngine(engine_cfg("mac"), serve(fail))
    with pytest.raises(EngineError) as exc:
        await engine.transcribe_chunk(make_wav(tmp_path / "c.wav", 2), None, False)
    assert exc.value.penalize and exc.value.isolated is isolated


@pytest.mark.parametrize(
    "body",
    [httpx.Response(200, text="<html>"), httpx.Response(200, json={"segments": [{"text": "hi"}]})],
)
async def test_an_answer_that_does_not_parse_is_tied_to_the_file(tmp_path, body):
    engine = OpenAIEngine(engine_cfg("mac"), serve(lambda request: body))
    with pytest.raises(EngineError) as exc:
        await engine.transcribe_chunk(make_wav(tmp_path / "c.wav", 2), None, False)
    assert exc.value.penalize and exc.value.isolated


async def test_one_5xx_on_one_file_leaves_the_engine_healthy_but_the_chunk_still_moves_on(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    mac = FakeEngine("mac", fail=EngineError("asr http 503", isolated=True))
    local = FakeEngine("local")
    r = router(
        [engine_cfg("mac", priority=1), engine_cfg("local", priority=2)],
        {"mac": mac, "local": local},
    )
    result, _ = await run(r, wav)
    assert result.engine == "local" and r.healthy("mac")


async def test_two_different_files_failing_in_a_row_mark_the_engine_unhealthy(tmp_path):
    first = make_wav(tmp_path / "a.wav", 60)
    second = make_wav(tmp_path / "b.wav", 60)
    mac = FakeEngine("mac", fail=EngineError("asr http 500", isolated=True))
    r = router(
        [engine_cfg("mac", priority=1), engine_cfg("local", priority=2)],
        {"mac": mac, "local": FakeEngine("local")},
    )
    await run(r, first)
    assert r.healthy("mac")
    await run(r, second)
    assert not r.healthy("mac")


async def test_the_same_file_failing_twice_is_still_one_file(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 1300)
    mac = FakeEngine("mac", fail=EngineError("asr http 500", isolated=True))
    r = router(
        [engine_cfg("mac", priority=1, max_chunk_s=600), engine_cfg("local", priority=2)],
        {"mac": mac, "local": FakeEngine("local")},
    )
    await run(r, wav)
    assert len(mac.chunks) == 3 and r.healthy("mac")
    await run(r, wav)
    assert r.healthy("mac")


async def test_two_failures_days_apart_do_not_mark_the_engine(tmp_path):
    files = [make_wav(tmp_path / f"{n}.wav", 60) for n in "abc"]
    clock = Clock()
    mac = FakeEngine("mac", fail=EngineError("asr http 500", isolated=True))
    r = router(
        [engine_cfg("mac", priority=1), engine_cfg("local", priority=2)],
        {"mac": mac, "local": FakeEngine("local")},
        clock=clock,
    )
    window = r.cfg.asr_failure_window_s
    assert window == 600.0
    await run(r, files[0])
    clock.t += window + 1
    await run(r, files[1])
    assert r.healthy("mac")
    clock.t += window / 2
    await run(r, files[2])
    assert not r.healthy("mac")


async def test_a_success_between_two_failures_breaks_the_streak(tmp_path):
    files = [make_wav(tmp_path / f"{n}.wav", 60) for n in "abc"]
    mac = FakeEngine("mac", fail=EngineError("asr http 500", isolated=True))
    r = router(
        [engine_cfg("mac", priority=1), engine_cfg("local", priority=2)],
        {"mac": mac, "local": FakeEngine("local")},
    )
    await run(r, files[0])
    mac.fail = None
    await run(r, files[1])
    mac.fail = EngineError("asr http 500", isolated=True)
    await run(r, files[2])
    assert r.healthy("mac")


@pytest.mark.parametrize(
    "error",
    [
        EngineError("asr transport error: ReadTimeout"),
        EngineError("asr http 429"),
        EngineError("asr http 401"),
    ],
)
async def test_a_timeout_or_an_engine_wide_error_marks_it_at_once(tmp_path, error):
    r = router(
        [engine_cfg("mac", priority=1), engine_cfg("local", priority=2)],
        {"mac": FakeEngine("mac", fail=error), "local": FakeEngine("local")},
    )
    await run(r, make_wav(tmp_path / "a.wav", 60))
    assert not r.healthy("mac")


# ---- an engine that went unhealthy while a chunk waited is not waited on -------------------------


async def test_a_queued_chunk_skips_an_engine_that_failed_while_it_waited(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 1200)
    mac = FakeEngine("mac", delay=0.05, fail=EngineError("asr transport error: ReadTimeout"))
    local = FakeEngine("local")
    r = router(
        [engine_cfg("mac", priority=1, max_parallel=1), engine_cfg("local", priority=2)],
        {"mac": mac, "local": local},
    )
    result, _ = await run(r, wav)
    assert len(mac.chunks) == 1
    assert result.engine == "local" and not r.healthy("mac")
    assert transcript_words(result) == [f"w{k}" for k in range(1200 * WORDS_PER_S)]


async def test_a_job_with_no_healthy_engine_left_keeps_trying_the_last_one(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 1200)
    only = FakeEngine("only", delay=0.01)
    r = router([engine_cfg("only", max_parallel=1)], {"only": only})
    r._penalize(r.cfg.engines()[0])
    result, _ = await run(r, wav)
    assert len(only.chunks) == 2 and result.engine == "only"


async def test_a_span_stops_between_sub_chunks_when_the_engine_went_unhealthy(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 600)
    r = None

    class Breaks(FakeEngine):
        async def transcribe_chunk(self, wav, language, want_words):
            out = await super().transcribe_chunk(wav, language, want_words)
            r._penalize(r.cfg.engines()[1])
            return out

    mac = FakeEngine("mac", fail=EngineError("asr transport error: ReadTimeout"))
    box, local = Breaks("box"), FakeEngine("local")
    r = router(
        [
            engine_cfg("mac", priority=1, max_chunk_s=600),
            engine_cfg("box", priority=2, max_chunk_s=200),
            engine_cfg("local", priority=3, max_chunk_s=600),
        ],
        {"mac": mac, "box": box, "local": local},
    )
    result, _ = await run(r, wav)
    assert len(box.chunks) == 1 and len(local.chunks) == 1
    assert result.engine == "local"
    assert transcript_words(result) == [f"w{k}" for k in range(600 * WORDS_PER_S)]


# ---- unknown language: prefer engines without an allow-list, re-run when it did not fit ----------


class Detects(FakeEngine):
    def __init__(self, name: str, language: str, **kw):
        super().__init__(name, **kw)
        self.language = language

    async def transcribe_chunk(self, wav, language, want_words):
        out = await super().transcribe_chunk(wav, language, want_words)
        out.language = self.language
        return out


async def test_an_unknown_language_goes_to_an_engine_without_an_allow_list_first(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    box, mac = FakeEngine("box"), FakeEngine("mac")
    r = router(
        [engine_cfg("box", priority=1, languages=["en", "tr"]), engine_cfg("mac", priority=9)],
        {"box": box, "mac": mac},
    )
    result, _ = await run(r, wav)
    assert result.engine == "mac" and box.chunks == []
    result, _ = await run(r, wav, "tr")
    assert result.engine == "box"


async def test_a_chunk_an_allow_listed_engine_took_in_another_language_is_redone(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    box = Detects("box", "ja")
    mac = Detects("mac", "ja")
    r = router(
        [engine_cfg("box", priority=1, languages=["en", "tr"]), engine_cfg("mac", priority=9)],
        {"box": box, "mac": mac},
    )
    r._penalize(r.cfg.engines()[1])
    result, _ = await run(r, wav)
    assert len(box.chunks) == 1 and len(mac.chunks) == 1
    assert result.engine == "mac" and result.language == "ja"


async def test_a_detected_language_inside_the_list_keeps_the_chunk(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    box, mac = Detects("box", "tr"), FakeEngine("mac")
    r = router(
        [engine_cfg("box", priority=1, languages=["en", "tr"]), engine_cfg("mac", priority=9)],
        {"box": box, "mac": mac},
    )
    r._penalize(r.cfg.engines()[1])
    result, _ = await run(r, wav)
    assert result.engine == "box" and mac.chunks == []


async def test_the_misfit_is_kept_when_no_later_engine_serves_the_detected_language(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    box = Detects("box", "ja")
    other = Detects("other", "ja")
    r = router(
        [
            engine_cfg("box", priority=1, languages=["en", "tr"]),
            engine_cfg("other", priority=2, languages=["en", "de"]),
        ],
        {"box": box, "other": other},
    )
    result, _ = await run(r, wav)
    assert result.engine == "box" and other.chunks == [] and result.language == "ja"


async def test_the_misfit_is_the_last_resort_when_the_engine_that_serves_it_fails(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    box = Detects("box", "ja")
    mac = FakeEngine("mac", fail=EngineError("asr transport error: ReadTimeout"))
    r = router(
        [engine_cfg("box", priority=1, languages=["en"]), engine_cfg("mac", priority=9)],
        {"box": box, "mac": mac},
    )
    r._penalize(r.cfg.engines()[1])
    result, _ = await run(r, wav)
    assert result.engine == "box" and len(mac.chunks) == 1


async def test_a_known_language_is_never_second_guessed(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 60)
    box, mac = Detects("box", "ja"), FakeEngine("mac")
    r = router(
        [engine_cfg("box", priority=1, languages=["en"]), engine_cfg("mac", priority=9)],
        {"box": box, "mac": mac},
    )
    result, _ = await run(r, wav, "en")
    assert result.engine == "box" and mac.chunks == []


# ---- how a server is asked for word times, and what is said about the answer --------------------------

FIELD_RE = re.compile(r'name="([^"]+)"\r\n\r\n([^\r]*)')


def form_of(request: httpx.Request) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for name, value in FIELD_RE.findall(request.content.decode("latin-1")):
        fields.setdefault(name, []).append(value)
    return fields


NESTED_WORDS = [
    {"word": " Hello", "start": 0.0, "end": 0.5, "probability": 0.9},
    {"word": " there", "start": 0.6, "end": 1.2, "probability": 0.8},
]


def nested_body() -> dict:
    return {
        "language": "english",
        "text": "Hello there",
        "segments": [
            {
                "start": 0.0,
                "end": 2.0,
                "text": " Hello there",
                "no_speech_prob": 0.02,
                "avg_logprob": -0.3,
                "compression_ratio": 1.1,
                "words": NESTED_WORDS,
            }
        ],
    }


def wordless_body() -> dict:
    body = nested_body()
    del body["segments"][0]["words"]
    return body


class Recorder:
    """A transport handler that answers from `rules(fields)` and keeps every request's form."""

    def __init__(self, rules):
        self.rules, self.forms = rules, []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        fields = form_of(request)
        self.forms.append(fields)
        status, body = self.rules(fields)
        return httpx.Response(status, json=body)


def asks_flag(fields) -> bool:
    return fields.get("word_timestamps") == ["true"]


def asks_granularity(fields) -> bool:
    return "word" in fields.get("timestamp_granularities[]", [])


async def test_auto_mode_sends_both_fields_and_reads_nested_words(tmp_path):
    from tests.mock_openai import MockOpenAI

    mock = MockOpenAI()
    mock.audio_words = "flag_nested"
    engine = OpenAIEngine(engine_cfg("mac"), httpx.ASGITransport(app=mock.app))
    out = await engine.transcribe_chunk(make_wav(tmp_path / "c.wav", 5), "en", want_words=True)
    assert mock.audio_calls[0]["word_timestamps"] == "true"
    assert [w.text for w in out.words] == ["Hello", "there."] + [
        "How",
        "are",
        "you",
        "doing",
        "today?",
    ]
    assert all(w.timing == TIMING_REAL for w in out.words)
    assert out.word_timing == "real" and out.word_mode == "both" and engine.word_mode == "both"
    assert len(mock.audio_calls) == 1


async def test_auto_mode_retries_single_modes_when_both_is_rejected(tmp_path):
    def rules(fields):
        if asks_flag(fields) and asks_granularity(fields):
            return 400, {"error": "word timestamps unsupported"}
        return 200, (nested_body() if asks_granularity(fields) else wordless_body())

    server = Recorder(rules)
    engine = OpenAIEngine(engine_cfg("mac"), serve(server))
    wav = make_wav(tmp_path / "c.wav", 5)
    out = await engine.transcribe_chunk(wav, None, want_words=True)
    assert len(server.forms) == 2 and out.word_mode == "granularities"
    assert [w.text for w in out.words] == ["Hello", "there"] and out.words[0].prob == 0.9
    await engine.transcribe_chunk(wav, None, want_words=True)
    assert len(server.forms) == 3 and not asks_flag(server.forms[2])  # straight to the known mode


async def test_auto_mode_moves_on_to_the_flag_when_the_field_gives_no_words(tmp_path):
    def rules(fields):
        if asks_flag(fields) and asks_granularity(fields):
            return 400, {"error": "word timestamps unsupported"}
        return 200, (nested_body() if asks_flag(fields) else wordless_body())

    server = Recorder(rules)
    engine = OpenAIEngine(engine_cfg("mac"), serve(server))
    out = await engine.transcribe_chunk(make_wav(tmp_path / "c.wav", 5), None, want_words=True)
    assert len(server.forms) == 3 and out.word_mode == "flag" and engine.word_mode == "flag"


async def test_a_configured_mode_is_used_as_it_is_and_extra_form_fields_are_sent(tmp_path):
    server = Recorder(lambda fields: (200, nested_body()))
    cfg = engine_cfg(
        "mac", word_timestamps="flag", extra_form={"condition_on_previous_text": "false"}
    )
    engine = OpenAIEngine(cfg, serve(server))
    wav = make_wav(tmp_path / "c.wav", 5)
    await engine.transcribe_chunk(wav, None, want_words=True)
    (fields,) = server.forms
    assert fields["word_timestamps"] == ["true"] and "word" not in fields.get(
        "timestamp_granularities[]", []
    )
    assert fields["condition_on_previous_text"] == ["false"]
    await engine.transcribe_chunk(wav, None, want_words=False)
    assert "word_timestamps" not in server.forms[1]
    assert server.forms[1]["condition_on_previous_text"] == ["false"]


async def test_server_without_word_times_is_flagged_not_silent(tmp_path):
    server = Recorder(lambda fields: (200, wordless_body()))
    engine = OpenAIEngine(engine_cfg("mac"), serve(server))
    wav = make_wav(tmp_path / "c.wav", 5)
    out = await engine.transcribe_chunk(wav, None, want_words=True)
    assert len(server.forms) == 3  # both, flag, granularities
    assert out.word_timing == "interpolated" and out.words
    assert all(w.timing == TIMING_INTERPOLATED for w in out.words)
    assert engine.word_mode == "none"
    await engine.transcribe_chunk(wav, None, want_words=True)
    assert len(server.forms) == 4  # no probing again

    db = Database(":memory:")
    log = JobEvents(db, Config().captions)
    token = events.bind(JobTrace("j1", log))
    try:
        chain = AsrRouter(
            CaptionsConfig(asr_engines=[engine_cfg("mac")], sample_rate=RATE),
            transport=serve(Recorder(lambda fields: (200, wordless_body()))),
        )
        result = await chain.transcribe(wav, None, lambda f: None, want_words=True)
    finally:
        events.unbind(token)
    (chunk,) = [e["detail"] for e in log.list("j1") if e["stage"] == "asr_chunk"]
    assert chunk["word_timing"] == "interpolated" and chunk["words"] == 2
    assert result.word_timing == "interpolated"
    assert result.stats == {
        "words_real": 0,
        "words_interpolated": 2,
        "rechecked_chunks": 0,
        "unresolved_chunks": 0,
        "skipped_chunks": 0,
        "recheck_requests": 0,
        "hallucination_drops": 0,
        "dropped_s": 0,
    }
    db.close()


def test_parse_reads_nested_words_metrics_and_skips_unusable_word_entries():
    body = nested_body()
    body["segments"][0]["words"].append({"word": "x", "start": None, "end": 3})
    body["segments"][0]["words"].append({"word": "", "start": 1, "end": 2})
    out = parse_verbose_json(body, 2.0, True)
    assert [w.text for w in out.words] == ["Hello", "there"]
    seg = out.segments[0]
    assert (seg.no_speech_prob, seg.avg_logprob, seg.compression_ratio) == (0.02, -0.3, 1.1)
    top = {**body, "words": [{"word": "Top", "start": 0.0, "end": 0.4}]}
    assert [w.text for w in parse_verbose_json(top, 2.0, True).words] == ["Top"]


class WordlessEngine(FakeEngine):
    async def transcribe_chunk(self, wav, language, want_words):
        result = await super().transcribe_chunk(wav, language, want_words)
        result.words = [replace(w, timing=TIMING_INTERPOLATED) for w in result.words]
        return result


def words_router(fakes: dict[str, FakeEngine], names: list[str], **cfg) -> AsrRouter:
    chain = CaptionsConfig(
        asr_engines=[engine_cfg(name, priority=i) for i, name in enumerate(names)],
        sample_rate=RATE,
        **cfg,
    )
    return AsrRouter(chain, engine_factory=lambda e: fakes[e.name], enabled=lambda e: True)


async def test_words_required_falls_through_to_an_engine_with_word_times(tmp_path):
    db = Database(":memory:")
    log = JobEvents(db, Config().captions)
    wav = make_wav(tmp_path / "a.wav", 30)
    token = events.bind(JobTrace("j1", log))
    try:
        chain = words_router(
            {"a": WordlessEngine("a"), "b": FakeEngine("b")}, ["a", "b"], asr_words_required=True
        )
        result, _ = await run(chain, wav, want_words=True)
    finally:
        events.unbind(token)
    assert result.engine == "b" and result.word_timing == "real"
    (fallback,) = [e["detail"] for e in log.list("j1") if e["stage"] == "asr_fallback"]
    assert fallback["reason"] == "no_word_times" and fallback["engine"] == "a"
    db.close()

    alone = words_router({"a": WordlessEngine("a")}, ["a"], asr_words_required=True)
    flagged, _ = await run(alone, wav, want_words=True)
    assert flagged.engine == "a" and flagged.word_timing == "interpolated" and flagged.words

    both = words_router({"a": WordlessEngine("a"), "b": FakeEngine("b")}, ["a", "b"])
    kept, _ = await run(both, wav, want_words=True)
    assert kept.engine == "a"  # not required: the first engine's answer stands


async def test_the_word_mode_of_each_engine_is_in_the_status(tmp_path):
    chain = AsrRouter(
        CaptionsConfig(
            asr_engines=[engine_cfg("mac"), engine_cfg("pinned", word_timestamps="flag")],
            sample_rate=RATE,
        ),
        transport=serve(Recorder(lambda fields: (200, nested_body()))),
    )
    assert [s["word_times"] for s in chain.status()] == ["unknown", "flag"]
    await chain.transcribe(make_wav(tmp_path / "a.wav", 5), None, lambda f: None, want_words=True)
    assert chain.status()[0]["word_times"] == "both"


async def test_a_textless_first_chunk_does_not_decide_the_word_mode(tmp_path):
    silent = {"language": "english", "text": "", "segments": []}

    def rules(fields):
        return (200, silent) if len(server.forms) == 1 else (200, nested_body())

    server = Recorder(rules)
    engine = OpenAIEngine(engine_cfg("mac"), serve(server))
    wav = make_wav(tmp_path / "c.wav", 5)
    first = await engine.transcribe_chunk(wav, None, want_words=True)
    assert first.words == [] and len(server.forms) == 1  # no extra probes on a textless answer
    assert engine.word_mode is None
    second = await engine.transcribe_chunk(wav, None, want_words=True)
    assert second.word_timing == "real" and second.word_mode == "both"
    assert engine.word_mode == "both" and len(server.forms) == 2


async def test_a_rejection_about_the_chunk_does_not_walk_the_modes(tmp_path):
    server = Recorder(lambda fields: (413, {"error": "file too large"}))
    engine = OpenAIEngine(engine_cfg("mac"), serve(server))
    with pytest.raises(EngineError):
        await engine.transcribe_chunk(make_wav(tmp_path / "c.wav", 5), None, want_words=True)
    assert len(server.forms) == 1 and engine.word_mode is None
    plain = Recorder(lambda fields: (400, {"error": "bad audio"}))
    engine = OpenAIEngine(engine_cfg("mac"), serve(plain))
    with pytest.raises(EngineError):
        await engine.transcribe_chunk(make_wav(tmp_path / "c.wav", 5), None, want_words=True)
    assert len(plain.forms) == 1


NOT_STARTED = EngineError(
    "asr http 500: Engine not started. Call start() first.",
    isolated=True,
    code="http_500",
    transient=True,
)


class WarmingEngine(FakeEngine):
    """Answers 'engine not started' for its first `cold` requests, then works."""

    def __init__(self, name: str, cold: int):
        super().__init__(name, delay=0.01)
        self.cold, self.calls = cold, 0

    async def transcribe_chunk(self, wav, language, want_words):
        self.calls += 1
        if self.calls <= self.cold:
            await asyncio.sleep(0)
            raise NOT_STARTED
        return await super().transcribe_chunk(wav, language, want_words)


FAKE_SLEEP_S = 0.01


class FakeSleep:
    def __init__(self, clock: Clock | None = None) -> None:
        self.steps: list[float] = []
        self.clock = clock

    async def __call__(self, seconds: float) -> None:
        self.steps.append(seconds)
        if self.clock is not None:
            self.clock.t += seconds
        await asyncio.sleep(FAKE_SLEEP_S)


async def run_traced(r: AsrRouter, wav: Path):
    db = Database(":memory:")
    log = JobEvents(db, Config().captions)
    token = events.bind(JobTrace("j1", log))
    try:
        result, _ = await run(r, wav)
    except ASRError:
        result = None
    finally:
        events.unbind(token)
    rows = log.list("j1")
    db.close()
    return result, [(e["stage"], e["detail"]) for e in rows]


async def test_a_cold_engine_is_waited_for_once_and_serves_every_chunk(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 90)
    mac = WarmingEngine("mac", cold=3)
    local = FakeEngine("local")
    clock = Clock()
    sleep = FakeSleep(clock)
    r = router(
        [engine_cfg("mac", priority=1, max_chunk_s=30, max_parallel=3), engine_cfg("local")],
        {"mac": mac, "local": local},
        clock=clock,
        sleep=sleep,
    )
    result, rows = await run_traced(r, wav)
    assert result.engine == "mac" and not local.chunks
    assert len(mac.chunks) == 4  # four chunks, three at a time
    waits = [d for stage, d in rows if stage == "asr_wait"]
    assert len(waits) == 1 and waits[0]["outcome"] == "ready" and waits[0]["engine"] == "mac"
    assert sleep.steps[0] == r.cfg.asr_warmup_retry_s
    assert not [d for stage, d in rows if stage == "asr_fallback"]
    assert r.healthy("mac")


async def test_an_engine_that_stays_down_falls_through_as_unavailable(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 90)
    mac = WarmingEngine("mac", cold=10_000)
    local = FakeEngine("local")
    clock = Clock()
    sleep = FakeSleep(clock)
    r = router(
        [engine_cfg("mac", priority=1, max_chunk_s=30, max_parallel=3), engine_cfg("local")],
        {"mac": mac, "local": local},
        clock=clock,
        sleep=sleep,
    )
    result, rows = await run_traced(r, wav)
    assert result.engine == "local"
    (wait,) = [d for stage, d in rows if stage == "asr_wait"]
    assert wait["outcome"] == "gave_up" and wait["waited_s"] == r.cfg.asr_warmup_wait_s
    assert sleep.steps[:4] == [3, 6, 12, 20] and sum(sleep.steps) == r.cfg.asr_warmup_wait_s
    reasons = {d["reason"] for stage, d in rows if stage == "asr_fallback"}
    assert reasons <= {"engine_unavailable", "unhealthy"} and "engine_unavailable" in reasons


async def test_a_plain_500_falls_through_without_waiting(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 30)
    mac = FakeEngine("mac", fail=EngineError("asr http 500: boom", isolated=True, code="http_500"))
    sleep = FakeSleep()
    r = router(
        [engine_cfg("mac", priority=1), engine_cfg("local")],
        {"mac": mac, "local": FakeEngine("local")},
        sleep=sleep,
    )
    result, rows = await run_traced(r, wav)
    assert result.engine == "local" and not sleep.steps
    assert not [1 for stage, _ in rows if stage == "asr_wait"]


@pytest.mark.parametrize(
    ("status", "body", "transient"),
    [
        (500, '{"error":{"message":"Engine not started. Call start() first."}}', True),
        (500, "Model is LOADING", True),
        (502, "model is not loaded yet", True),
        (502, "upstream unavailable", False),
        (500, "Error loading audio file", False),
        (503, "", True),
        (502, "bad gateway", False),
        (500, "boom", False),
        (400, "engine not started", False),
        (404, "loading", False),
    ],
)
async def test_which_http_answers_count_as_a_starting_server(tmp_path, status, body, transient):
    engine = OpenAIEngine(engine_cfg("mac"), serve(lambda r: httpx.Response(status, text=body)))
    with pytest.raises(EngineError) as exc:
        await engine.transcribe_chunk(make_wav(tmp_path / "c.wav", 2), None, False)
    assert exc.value.transient is transient


async def test_connect_errors_are_transient_but_timeouts_are_not(tmp_path):
    def refuse(request):
        raise httpx.ConnectError("refused")

    def slow(request):
        raise httpx.ReadTimeout("slow")

    wav = make_wav(tmp_path / "c.wav", 2)
    for handler, transient in ((refuse, True), (slow, False)):
        engine = OpenAIEngine(engine_cfg("mac"), serve(handler))
        with pytest.raises(EngineError) as exc:
            await engine.transcribe_chunk(wav, None, False)
        assert exc.value.transient is transient


async def test_a_cold_server_during_the_word_mode_probe_marks_nothing_and_does_not_deadlock(
    tmp_path,
):
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) <= 2:
            return httpx.Response(500, text="Engine not started")
        return httpx.Response(200, json=verbose(words=True))

    sleep = FakeSleep()
    wav = make_wav(tmp_path / "a.wav", 60)
    chain = AsrRouter(
        CaptionsConfig(
            asr_engines=[engine_cfg("mac", max_chunk_s=30, max_parallel=2)], sample_rate=RATE
        ),
        transport=serve(handler),
        sleep=sleep,
    )
    result = await asyncio.wait_for(
        chain.transcribe(wav, None, lambda f: None, want_words=True), timeout=10
    )
    assert result.engine == "mac" and sleep.steps
    assert chain._engine(chain.cfg.asr_engines[0]).word_mode in ("both", "flag", "granularities")


async def test_a_500_about_loading_the_audio_falls_through_at_once(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 30)
    bad = EngineError("asr http 500: Error loading audio file", isolated=True, code="http_500")
    sleep = FakeSleep()
    r = router(
        [engine_cfg("mac", priority=1), engine_cfg("local")],
        {"mac": FakeEngine("mac", fail=bad), "local": FakeEngine("local")},
        sleep=sleep,
    )
    result, _ = await run_traced(r, wav)
    assert result.engine == "local" and not sleep.steps


async def test_an_engine_that_gave_up_is_not_waited_for_again(tmp_path):
    wav = make_wav(tmp_path / "a.wav", 150)
    mac = WarmingEngine("mac", cold=10_000)
    clock = Clock()
    sleep = FakeSleep(clock)
    r = router(
        [engine_cfg("mac", max_chunk_s=30, max_parallel=1)], {"mac": mac}, clock=clock, sleep=sleep
    )
    _, rows = await run_traced(r, wav)
    waits = [d for stage, d in rows if stage == "asr_wait"]
    assert len(waits) == 1 and waits[0]["waited_s"] == r.cfg.asr_warmup_wait_s
    assert sum(sleep.steps) == r.cfg.asr_warmup_wait_s

    clock.t += r.cfg.asr_unhealthy_s + 1
    mac.cold = 0
    result, _ = await run(r, wav)
    assert result.engine == "mac"
