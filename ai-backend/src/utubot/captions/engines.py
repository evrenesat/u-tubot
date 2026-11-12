"""Speech-to-text engine chain: select by health, language and priority; chunk; stitch; fall through.

`AsrRouter` is the `ASRBackend` the pipeline uses. Each audio file is cut into overlapping chunks
sized for the best available engine; chunks run in parallel up to that engine's `max_parallel`
(shared by every job, so a "one job at a time" box really gets one). A chunk whose engine fails goes
to the next engine of the chain, which may cut it further if its own chunk limit is smaller.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import tempfile
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from ..config import (
    ASR_KIND_FASTER_WHISPER,
    ASR_KIND_OPENAI,
    AsrEngineConfig,
    CaptionsConfig,
)
from ..llm import BACKGROUND, INTERACTIVE, PriorityLimiter
from .asr import (
    ASRError,
    ASRResult,
    ProgressFn,
    normalize_language,
    wav_duration,
    words_from_segment,
)
from .chunking import Span, plan_chunks, shift, stitch_segments, stitch_words, write_chunk
from .types import Segment, Word

log = logging.getLogger("utubot.asr")

STATUS_INPUT_REJECTED = frozenset({400, 413, 415, 422})
HTTP_ERROR_FLOOR = 400
ERROR_TEXT_CHARS = 200
CONNECT_TIMEOUT_S = 10.0
ENGINE_SEPARATOR = "+"
MIN_SPEED_FACTOR = 0.01


class EngineError(ASRError):
    """An engine could not transcribe one chunk. `penalize` marks the engine unhealthy."""

    def __init__(self, message: str, *, penalize: bool = True):
        super().__init__(message)
        self.penalize = penalize


@dataclass
class ChunkResult:
    """One chunk as an engine returned it; times are relative to the chunk start."""

    segments: list[Segment] = field(default_factory=list)
    words: list[Word] = field(default_factory=list)
    language: str | None = None


class AsrEngine(Protocol):
    async def transcribe_chunk(
        self, wav: Path, language: str | None, want_words: bool
    ) -> ChunkResult: ...


EngineFactory = Callable[[AsrEngineConfig], AsrEngine]


def parse_verbose_json(data: dict[str, Any], duration_s: float, want_words: bool) -> ChunkResult:
    """OpenAI `verbose_json` into segments and words.

    A bare `text` becomes one segment spanning the chunk; when words are wanted but the server sent
    none, they are spread over each segment.
    """
    segments = [
        Segment(float(seg["start"]), float(seg["end"]), str(seg.get("text", "")).strip())
        for seg in data.get("segments") or []
        if str(seg.get("text", "")).strip()
    ]
    text = str(data.get("text") or "").strip()
    if not segments and text:
        segments = [Segment(0.0, duration_s, text)]
    words = [
        Word(float(w["start"]), float(w["end"]), str(w.get("word", w.get("text", ""))).strip())
        for w in data.get("words") or []
    ]
    if want_words and not words:
        words = [w for seg in segments for w in words_from_segment(seg.start, seg.end, seg.text)]
    return ChunkResult(segments, words, normalize_language(data.get("language")))


class OpenAIEngine:
    """Any server with `POST /v1/audio/transcriptions` (OpenAI, mlx-audio, whisper.cpp, vLLM ...)."""

    def __init__(self, cfg: AsrEngineConfig, transport: httpx.AsyncBaseTransport | None = None):
        self.cfg = cfg
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        key = os.environ.get(self.cfg.api_key_env or "")
        return {"Authorization": f"Bearer {key}"} if key else {}

    async def transcribe_chunk(
        self, wav: Path, language: str | None, want_words: bool
    ) -> ChunkResult:
        data: dict[str, Any] = {
            "model": self.cfg.model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["word", "segment"] if want_words else ["segment"],
        }
        if language:
            data["language"] = language
        timeout = httpx.Timeout(
            self.cfg.timeout_s, connect=min(CONNECT_TIMEOUT_S, self.cfg.timeout_s)
        )
        try:
            async with httpx.AsyncClient(timeout=timeout, transport=self._transport) as http:
                with wav.open("rb") as fh:
                    resp = await http.post(
                        self.cfg.url,
                        data=data,
                        files={"file": (wav.name, fh, "audio/wav")},
                        headers=self._headers(),
                    )
        except httpx.HTTPError as exc:
            raise EngineError(f"asr transport error: {type(exc).__name__}") from None
        if resp.status_code >= HTTP_ERROR_FLOOR:
            raise EngineError(
                f"asr http {resp.status_code}: {resp.text[:ERROR_TEXT_CHARS]}",
                penalize=resp.status_code not in STATUS_INPUT_REJECTED,
            )
        try:
            body = resp.json()
        except ValueError:
            raise EngineError("asr answered something that is not JSON") from None
        return parse_verbose_json(body, wav_duration(wav), want_words)


class FasterWhisperEngine:
    """Local CPU faster-whisper (`uv sync --extra asr`); the model loads on first use."""

    def __init__(self, cfg: AsrEngineConfig, default_compute_type: str, default_threads: int):
        self.cfg = cfg
        self._compute_type = cfg.compute_type or default_compute_type
        self._threads = cfg.threads or default_threads
        self._model: Any = None
        self._lock = asyncio.Lock()

    def _load(self) -> Any:
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise EngineError("faster-whisper is not installed (uv sync --extra asr)") from exc
            self._model = WhisperModel(
                self.cfg.model,
                device="cpu",
                compute_type=self._compute_type,
                cpu_threads=self._threads,
            )
        return self._model

    def _run(self, wav: Path, language: str | None, want_words: bool) -> ChunkResult:
        segments_out: list[Segment] = []
        words_out: list[Word] = []
        stream, info = self._load().transcribe(
            str(wav), language=language, word_timestamps=want_words, vad_filter=True
        )
        for seg in stream:
            text = seg.text.strip()
            if text:
                segments_out.append(Segment(seg.start, seg.end, text))
            if want_words:
                if seg.words:
                    words_out.extend(Word(w.start, w.end, w.word.strip()) for w in seg.words)
                else:
                    words_out.extend(words_from_segment(seg.start, seg.end, seg.text))
        return ChunkResult(segments_out, words_out, normalize_language(info.language))

    async def transcribe_chunk(
        self, wav: Path, language: str | None, want_words: bool
    ) -> ChunkResult:
        async with self._lock:
            return await asyncio.to_thread(self._run, wav, language, want_words)


@dataclass
class _Job:
    wav: Path
    language: str | None
    want_words: bool
    priority: int
    scratch: Path
    total_s: float


@dataclass
class SpanResult:
    segments: list[Segment]
    words: list[Word]
    languages: list[tuple[str | None, float]]
    engines: list[AsrEngineConfig]


def _base(code: str | None) -> str | None:
    return code.split("-")[0].lower() if code else None


def engine_enabled(cfg: AsrEngineConfig) -> bool:
    """An engine runs when its key variable is set (or it needs none) and, for local ones, its package."""
    if cfg.kind == ASR_KIND_FASTER_WHISPER:
        return importlib.util.find_spec("faster_whisper") is not None
    if cfg.api_key_env and not cfg.key_optional and not os.environ.get(cfg.api_key_env):
        return False
    return bool(cfg.url)


def serves(cfg: AsrEngineConfig, language: str | None) -> bool:
    """False only when the language is known and the engine has an allow-list without it."""
    return not (language and cfg.languages and _base(language) not in map(_base, cfg.languages))


class AsrRouter:
    """The engine chain as an `ASRBackend`."""

    def __init__(
        self,
        cfg: CaptionsConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        engine_factory: EngineFactory | None = None,
        clock: Callable[[], float] = time.monotonic,
        enabled: Callable[[AsrEngineConfig], bool] = engine_enabled,
    ):
        self.cfg = cfg
        self._transport = transport
        self._factory = engine_factory or self._build
        self._clock = clock
        self._enabled = enabled
        self._unhealthy_until: dict[str, float] = {}
        self._limiters: dict[str, PriorityLimiter] = {}
        self._engines: dict[str, tuple[str, AsrEngine]] = {}

    def _build(self, engine: AsrEngineConfig) -> AsrEngine:
        if engine.kind == ASR_KIND_OPENAI:
            return OpenAIEngine(engine, self._transport)
        return FasterWhisperEngine(engine, self.cfg.whisper_compute_type, self.cfg.whisper_threads)

    def _engine(self, engine: AsrEngineConfig) -> AsrEngine:
        fingerprint = engine.model_dump_json()
        cached = self._engines.get(engine.name)
        if cached is None or cached[0] != fingerprint:
            cached = self._engines[engine.name] = (fingerprint, self._factory(engine))
        return cached[1]

    def _limiter(self, engine: AsrEngineConfig) -> PriorityLimiter:
        limiter = self._limiters.get(engine.name)
        if limiter is None or limiter.limit != engine.max_parallel:
            limiter = self._limiters[engine.name] = PriorityLimiter(engine.max_parallel)
        return limiter

    def healthy(self, name: str) -> bool:
        return self._unhealthy_until.get(name, 0.0) <= self._clock()

    def _penalize(self, engine: AsrEngineConfig) -> None:
        self._unhealthy_until[engine.name] = self._clock() + self.cfg.asr_unhealthy_s
        log.warning(
            "asr engine %s unhealthy for %d s", engine.name, round(self.cfg.asr_unhealthy_s)
        )

    def candidates(self, language: str | None, priority: int = BACKGROUND) -> list[AsrEngineConfig]:
        """Engines that may take this job: healthy ones first, then by priority (lower first).

        Disabled engines, engines that do not serve a known `language` and (for interactive work)
        background-only engines never appear. Unhealthy engines come last, not never, so a chain whose
        engines all failed recently is still tried.
        """
        usable = [
            e
            for e in self.cfg.engines()
            if self._enabled(e)
            and serves(e, language)
            and not (e.background_only and priority == INTERACTIVE)
        ]
        return sorted(usable, key=lambda e: (not self.healthy(e.name), e.priority))

    def available(self, language: str | None = None) -> bool:
        return bool(self.candidates(language, BACKGROUND))

    def estimate_s(
        self, duration_s: float, language: str | None = None, priority: int = INTERACTIVE
    ) -> float | None:
        """Seconds of transcription for `duration_s` of audio on the engine that would take it."""
        chosen = self.candidates(language, priority)
        if not chosen:
            return None
        engine = chosen[0]
        chunks = len(plan_chunks(duration_s, engine.max_chunk_s, self.cfg.asr_chunk_overlap_s))
        parallel = max(1, min(engine.max_parallel, chunks))
        return engine.overhead_s + duration_s / (
            max(engine.speed_factor, MIN_SPEED_FACTOR) * parallel
        )

    def status(self) -> list[dict[str, Any]]:
        now = self._clock()
        return [
            {
                "name": e.name,
                "kind": e.kind,
                "model": e.model,
                "enabled": self._enabled(e),
                "healthy": self.healthy(e.name),
                "unhealthy_for_s": max(0, round(self._unhealthy_until.get(e.name, 0.0) - now)),
                "languages": e.languages,
                "priority": e.priority,
                "max_parallel": e.max_parallel,
                "background_only": e.background_only,
            }
            for e in self.cfg.engines()
        ]

    async def _chunk_on(self, engine: AsrEngineConfig, span: Span, job: _Job) -> ChunkResult:
        limiter = self._limiter(engine)
        await limiter.acquire(job.priority)
        try:
            if span.start <= 0 and span.end >= job.total_s:
                return await self._engine(engine).transcribe_chunk(
                    job.wav, job.language, job.want_words
                )
            part = job.scratch / f"{engine.name}-{span.index}-{int(span.start * 1000)}.wav"
            await asyncio.to_thread(write_chunk, job.wav, span, part)
            try:
                return await self._engine(engine).transcribe_chunk(
                    part, job.language, job.want_words
                )
            finally:
                part.unlink(missing_ok=True)
        finally:
            limiter.release()

    async def _span_on(self, engine: AsrEngineConfig, span: Span, job: _Job) -> SpanResult:
        subspans = plan_chunks(span.duration, engine.max_chunk_s, self.cfg.asr_chunk_overlap_s)
        segments: list[list[Segment]] = []
        words: list[list[Word]] = []
        languages: list[tuple[str | None, float]] = []
        placed: list[Span] = []
        for sub in subspans:
            absolute = Span(sub.index, span.start + sub.start, span.start + sub.end)
            result = await self._chunk_on(engine, absolute, job)
            placed.append(absolute)
            segments.append(shift(result.segments, absolute.start))
            words.append(shift(result.words, absolute.start))
            languages.append((result.language, absolute.duration))
        return SpanResult(
            stitch_segments(segments, placed), stitch_words(words, placed), languages, [engine]
        )

    async def _span(self, chain: list[AsrEngineConfig], span: Span, job: _Job) -> SpanResult:
        failure: EngineError | None = None
        for position, engine in enumerate(chain):
            rest = chain[position + 1 :]
            if not self.healthy(engine.name) and any(self.healthy(e.name) for e in rest):
                continue
            try:
                return await self._span_on(engine, span, job)
            except EngineError as exc:
                failure = exc
                if exc.penalize:
                    self._penalize(engine)
                log.warning("asr engine %s failed a chunk: %s", engine.name, exc)
        raise ASRError("all speech-to-text engines failed") from failure

    async def transcribe(
        self,
        wav: Path,
        language: str | None,
        progress: ProgressFn,
        *,
        priority: int = BACKGROUND,
        want_words: bool = True,
    ) -> ASRResult:
        language = normalize_language(language)
        chain = self.candidates(language, priority)
        if not chain:
            raise ASRError(
                "no speech-to-text engine is available (is an api_key_env variable unset, or the asr extra missing?)"
            )
        total = wav_duration(wav, self.cfg.sample_rate)
        spans = plan_chunks(total, chain[0].max_chunk_s, self.cfg.asr_chunk_overlap_s)
        done = 0

        async def run(span: Span, job: _Job) -> SpanResult:
            nonlocal done
            result = await self._span(chain, span, job)
            done += 1
            progress(done / len(spans))
            return result

        with tempfile.TemporaryDirectory(prefix="asr-", dir=wav.parent) as scratch:
            job = _Job(wav, language, want_words, priority, Path(scratch), total)
            results = await gather_all([run(span, job) for span in spans])
        return self._merge(results, spans)

    @staticmethod
    def _merge(results: list[SpanResult], spans: list[Span]) -> ASRResult:
        segments = stitch_segments([r.segments for r in results], spans)
        words = stitch_words([r.words for r in results], spans)
        votes: dict[str, float] = {}
        for result in results:
            for code, seconds in result.languages:
                if code:
                    votes[code] = votes.get(code, 0.0) + seconds
        language = max(votes, key=votes.__getitem__) if votes else None
        used = list(dict.fromkeys(e.name for r in results for e in r.engines))
        models = list(dict.fromkeys(e.model for r in results for e in r.engines))
        return ASRResult(
            words=words,
            language=language,
            segments=segments,
            engine=ENGINE_SEPARATOR.join(used) or None,
            model=ENGINE_SEPARATOR.join(models) or None,
        )


async def gather_all(coros: list[Awaitable[Any]]) -> list[Any]:
    """Run all; the first failure cancels the rest and is re-raised as itself."""
    tasks = [asyncio.ensure_future(c) for c in coros]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
