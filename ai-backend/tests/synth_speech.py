"""Synthetic speech for the timing tests: a ground-truth word timeline and what engines make of it.

`make_timeline` is the truth. `whisper_answer` is what a Whisper server returns for one chunk of it,
with the flaws real DTW word times have (probe of the production engine, `temp/sync-design/asr-probe.md`):
the last word before a pause stretched over it, zero-length words at segment edges, a squeezed run.
`youtube_rows` are rolling caption rows 0.25 s early. `tone_wav` is audio whose sound lies exactly
where the truth's phrases are, so silence detection sees the real pauses.
"""

from __future__ import annotations

import random
import wave
from pathlib import Path
from typing import Any

from utubot.captions.asr import ASRError
from utubot.captions.chunking import Span, plan_chunks
from utubot.captions.engines import ChunkResult, parse_verbose_json
from utubot.captions.types import Word

PHRASE_GAP_S = 0.5  # intra-phrase gaps are at most 0.12 s, pauses at least 0.7 s
LONG_PAUSE_S = 25.0
STRETCH_PAUSE_S = 2.0
SQUEEZE_WORDS = 6
SQUEEZE_SPAN_S = 0.5
SEGMENT_FLAW_EVERY = 5
SEGMENT_CAP_S = 30.0
ROUND = 2
TONE_RATE = 16000
TONE_HZ = 440
TONE_AMPLITUDE = 6000
CAPTION_LEAD_S = 0.25
CAPTION_TAIL_S = 0.5
MUSIC_INSET_S = 1.0


def make_timeline(seed: int, duration_s: float) -> list[Word]:
    """Phrases of 3-9 words with unique tokens, pauses of 0.7-6 s and one pause of 25 s."""
    rng = random.Random(seed)
    words: list[Word] = []
    cursor = rng.uniform(1.0, 3.0)
    long_done = False
    number = 0
    while True:
        phrase: list[Word] = []
        for _ in range(rng.randint(3, 9)):
            number += 1
            length = rng.uniform(0.15, 0.45)
            phrase.append(Word(cursor, cursor + length, f"w{number:04d}"))
            cursor += length + rng.uniform(0.0, 0.12)
        if phrase[-1].end > duration_s:
            return words
        words.extend(phrase)
        if not long_done and cursor > duration_s / 2:
            cursor += LONG_PAUSE_S
            long_done = True
        else:
            cursor += rng.uniform(0.7, 6.0)


def phrases(words: list[Word]) -> list[list[Word]]:
    out: list[list[Word]] = []
    for word in words:
        if out and word.start - out[-1][-1].end <= PHRASE_GAP_S:
            out[-1].append(word)
        else:
            out.append([word])
    return out


def long_pause(words: list[Word]) -> tuple[float, float]:
    """(start, end) of the 25 s pause."""
    for before, after in zip(words, words[1:], strict=False):
        if after.start - before.end >= LONG_PAUSE_S:
            return before.end, after.start
    raise ValueError("no long pause in the timeline")


def _chunk_phrases(truth: list[Word], start: float, end: float) -> list[list[Word]]:
    inside = [w for w in truth if w.start >= start and w.end <= end]
    return phrases(inside)


def _flawed(groups: list[list[Word]]) -> list[list[Word]]:
    """The phrases with DTW flaws injected (copies; times still relative to the audio start)."""
    out = [[Word(w.start, w.end, w.text) for w in group] for group in groups]
    squeezed = False
    for i, group in enumerate(out):
        if i % SEGMENT_FLAW_EVERY == SEGMENT_FLAW_EVERY - 1:
            group[0].end = group[0].start
            group[-1].start = group[-1].end
        if i + 1 < len(out) and out[i + 1][0].start - group[-1].end >= STRETCH_PAUSE_S:
            group[-1].end = out[i + 1][0].start
        if not squeezed and i >= 2 and len(group) >= SQUEEZE_WORDS:
            step = SQUEEZE_SPAN_S / SQUEEZE_WORDS
            for k in range(SQUEEZE_WORDS):
                group[k].start = group[0].start + k * step
                group[k].end = group[0].start + (k + 1) * step
            squeezed = True
    return out


def _word_entry(word: Word, offset: float) -> dict[str, Any]:
    return {
        "word": f" {word.text}",
        "start": round(word.start - offset, ROUND),
        "end": round(word.end - offset, ROUND),
        "probability": 0.9,
    }


def whisper_answer(truth: list[Word], start: float, end: float, mode: str) -> dict[str, Any]:
    """The `verbose_json` body for the chunk `[start, end]` of the truth (times relative to it).

    Modes: `flag` (words nested in the segments, `word_timestamps=true` style), `openai`
    (top-level `words`), `segments` (no words; segments are contiguous and absorb the following
    silence up to 30 s, as production did before the flag was sent).
    """
    groups = _chunk_phrases(truth, start, end)
    segments: list[dict[str, Any]] = []
    if mode == "segments":
        for i, group in enumerate(groups):
            seg_start = group[0].start
            limit = groups[i + 1][0].start if i + 1 < len(groups) else end
            seg_end = min(limit, seg_start + SEGMENT_CAP_S)
            segments.append(_segment(group, seg_start, seg_end, start))
        return _body(segments, [])
    flawed = _flawed(groups)
    top_words: list[dict[str, Any]] = []
    for group in flawed:
        entries = [_word_entry(w, start) for w in group]
        seg = _segment(group, group[0].start, group[-1].end, start)
        if mode == "flag":
            seg["words"] = entries
        else:
            top_words.extend(entries)
        segments.append(seg)
    return _body(segments, top_words)


def _segment(group: list[Word], seg_start: float, seg_end: float, offset: float) -> dict[str, Any]:
    return {
        "start": round(seg_start - offset, ROUND),
        "end": round(seg_end - offset, ROUND),
        "text": " " + " ".join(w.text for w in group),
        "no_speech_prob": 0.01,
        "avg_logprob": -0.2,
        "compression_ratio": 1.2,
    }


def _body(segments: list[dict[str, Any]], words: list[dict[str, Any]]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "language": "english",
        "text": " ".join(s["text"].strip() for s in segments),
        "segments": segments,
    }
    if words:
        body["words"] = words
    return body


def youtube_rows(truth: list[Word]) -> list[tuple[float, float, str]]:
    """Caption rows per phrase, starting 0.25 s early, plus a `[Music]` row inside the long pause."""
    rows = [
        (
            group[0].start - CAPTION_LEAD_S,
            group[-1].end + CAPTION_TAIL_S,
            " ".join(w.text for w in group),
        )
        for group in phrases(truth)
    ]
    begin, finish = long_pause(truth)
    rows.append((begin + MUSIC_INSET_S, finish - MUSIC_INSET_S, "[Music]"))
    return sorted(rows)


def tone_wav(path: Path, truth: list[Word], duration_s: float) -> Path:
    """A mono WAV with a tone wherever a phrase of the truth is and silence elsewhere."""
    tone_period = TONE_RATE // TONE_HZ
    half = tone_period // 2
    cycle = (TONE_AMPLITUDE.to_bytes(2, "little", signed=True) * half) + (
        (-TONE_AMPLITUDE).to_bytes(2, "little", signed=True) * (tone_period - half)
    )
    total = int(duration_s * TONE_RATE)
    audio = bytearray(total * 2)
    for group in phrases(truth):
        first, last = int(group[0].start * TONE_RATE), int(group[-1].end * TONE_RATE)
        count = max(last - first, 0)
        reps = count // tone_period + 1
        audio[first * 2 : last * 2] = (cycle * reps)[: count * 2]
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(TONE_RATE)
        out.writeframes(bytes(audio))
    return path


class ScriptedEngine:
    """An `AsrEngine` that answers a chunk from the truth, and records how it was asked.

    The chunk is told apart by its length: `plan_chunks(total, max_chunk_s, overlap_s)` gives chunks of
    different lengths for the tests that use it (the engine does not listen to the audio).
    """

    def __init__(
        self, truth: list[Word], mode: str, total_s: float, max_chunk_s: float, overlap_s: float
    ):
        self.truth, self.mode = truth, mode
        self.spans: list[Span] = plan_chunks(total_s, max_chunk_s, overlap_s)
        self.asked: list[dict[str, Any]] = []

    async def transcribe_chunk(
        self, wav: Path, language: str | None, want_words: bool
    ) -> ChunkResult:
        with wave.open(str(wav), "rb") as fh:
            seconds = fh.getnframes() / fh.getframerate()
        span = min(self.spans, key=lambda sp: abs(sp.duration - seconds))
        if abs(span.duration - seconds) > 1.0:
            raise ASRError(f"no planned chunk is {seconds:.1f} s long")
        self.asked.append(
            {"start": span.start, "end": span.end, "language": language, "want_words": want_words}
        )
        body = whisper_answer(self.truth, span.start, span.end, self.mode)
        result = parse_verbose_json(body, span.duration, want_words)
        result.word_mode = self.mode
        return result
