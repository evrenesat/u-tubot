"""The offline sync metric: cue starts against a ground-truth timeline, through the whole pipeline.

A synthetic talk (`tests/synth_speech.py`) is the truth. A scripted engine answers each chunk the way a
Whisper server does, flaws included; the audio is a tone wherever the truth has a phrase. Cues are scored
with `syncscore` the same way `utubot captions-score` scores a real track.
"""

from __future__ import annotations

import bisect
import json
import wave
from pathlib import Path

import httpx
import pytest

from tests.mock_openai import MockOpenAI
from tests.synth_speech import (
    ScriptedEngine,
    long_pause,
    make_timeline,
    phrases,
    tone_wav,
    whisper_answer,
    youtube_rows,
    youtube_words,
)
from utubot.captions import events
from utubot.captions.asr import ffmpeg_available
from utubot.captions.engines import AsrRouter, parse_verbose_json
from utubot.captions.events import JobEvents, JobTrace
from utubot.captions.pipeline import TIMING_VERSION, CaptionPipeline
from utubot.captions.syncscore import phrase_onsets, score_starts
from utubot.config import AsrEngineConfig, Config
from utubot.db import Database
from utubot.llm import LLMClient
from utubot.transcripts import parse_vtt

pytestmark = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg is not installed")

VID = "abcdefghijk"
DURATION_S = 300.0
CHUNK_S = 180
HIT_TARGET = 0.95
LATE_END_S = 0.5
LATE_END_SHARE = 0.05
SEGMENT_ONLY_HIT_CEILING = 0.7
SEED = 7
SPEECH_OVERLAP_FLOOR = 0.85
TRANSLATED_HIT_TOLERANCE = 0.02


PHANTOM = "Thank you."
LOOP_STEP_S = 30.0
LOOP_LEN_S = 7.0
HALLUCINATED_CHUNK_S = 130


class HallucinatingEngine(ScriptedEngine):
    """A scripted engine whose first chunk, asked without a language, is the EQWLxadmae0 failure:
    labelled English, a phantom "Thank you." every 30 s over continuous speech."""

    def __init__(self, truth, total_s, max_chunk_s, overlap_s, audio: Path):
        super().__init__(truth, "flag", total_s, max_chunk_s, overlap_s)
        with wave.open(str(audio), "rb") as fh:
            self.source = fh.readframes(fh.getnframes())

    async def transcribe_chunk(self, wav, language, want_words):
        with wave.open(str(wav), "rb") as fh:
            frames = fh.readframes(fh.getnframes())
            rate = fh.getframerate()
        start = self.source.find(frames) / 2 / rate
        end = start + len(frames) / 2 / rate
        self.asked.append(
            {
                "start": round(start, 1),
                "end": round(end, 1),
                "language": language,
                "want_words": want_words,
            }
        )
        body = whisper_answer(self.truth, start, end, "flag")
        if start == 0 and language is None:
            body["language"] = "english"
            body["segments"] = [
                {
                    "start": i * LOOP_STEP_S,
                    "end": i * LOOP_STEP_S + LOOP_LEN_S,
                    "text": " " + PHANTOM,
                    "no_speech_prob": 0.1,
                    "avg_logprob": -0.9,
                    "compression_ratio": 0.8,
                }
                for i in range(int(end // LOOP_STEP_S))
            ]
        else:
            body["language"] = "turkish"
        result = parse_verbose_json(body, end - start, want_words)
        result.word_mode = "flag"
        return result


class Harness:
    def __init__(
        self,
        tmp_path: Path,
        mode: str,
        chunk_s: int = CHUNK_S,
        hallucinate: bool = False,
        llm: MockOpenAI | None = None,
    ):
        self.truth = make_timeline(SEED, DURATION_S)
        self.audio = tone_wav(tmp_path / "talk.wav", self.truth, DURATION_S)
        self.cfg = Config()
        self.cfg.server.data_dir = str(tmp_path / "data")
        self.cfg.youtube.min_interval_s = self.cfg.youtube.jitter_s = 0.0
        self.cfg.captions.asr_engines = [
            AsrEngineConfig(
                name="scripted",
                url="http://scripted.example/v1/audio/transcriptions",
                max_chunk_s=chunk_s,
            )
        ]
        self.cfg.captions.proofread = False
        overlap = self.cfg.captions.asr_chunk_overlap_s
        if hallucinate:
            self.engine = HallucinatingEngine(self.truth, DURATION_S, chunk_s, overlap, self.audio)
        else:
            self.engine = ScriptedEngine(self.truth, mode, DURATION_S, chunk_s, overlap)
        self.db = Database(tmp_path / "t.sqlite")
        self.db.execute(
            "INSERT INTO video_meta(video_id,json,fetched_at) VALUES(?,?,?)",
            [VID, '{"language": "tr"}', 0.0],
        )
        router = AsrRouter(
            self.cfg.captions, engine_factory=lambda e: self.engine, enabled=lambda e: True
        )
        client = None
        if llm is not None:
            conf = Config()
            conf.llm.providers["default"].base_url = "http://mock/v1"
            client = LLMClient(conf, transport=httpx.ASGITransport(app=llm.app))
        self.pipeline = CaptionPipeline(
            self.cfg, self.db, router, llm=client, downloader=self.download
        )
        self.log = JobEvents(self.db, self.cfg.captions)

    async def download(self, video_id, out_dir, started):
        started()
        path = out_dir / "audio.wav"
        path.write_bytes(self.audio.read_bytes())
        return path

    async def run(self, method: str, *args, **kw):
        token = events.bind(JobTrace("j1", self.log))
        try:
            await getattr(self.pipeline, method)(VID, *args, lambda f: None, **kw)
        finally:
            events.unbind(token)

    def event(self, stage: str, status: str | None = None) -> dict:
        rows = [e for e in self.log.list("j1") if e["stage"] == stage]
        rows = [e for e in rows if status is None or e["status"] == status]
        assert rows, (stage, [e["stage"] for e in self.log.list("j1")])
        return rows[-1]

    def cues(self) -> list[tuple[float, float, str]]:
        row = self.db.one("SELECT vtt FROM captions WHERE video_id=?", [VID])
        return parse_vtt(row["vtt"])

    def score(self):
        onsets = phrase_onsets([(w.start, w.end) for w in self.truth], 0.5)
        return score_starts([start for start, _e, _t in self.cues()], onsets, self.cfg.captions)

    def late_end_share(self) -> float:
        """Share of cues ending over `LATE_END_S` after their last truth word.

        A cue held on screen for `min_cue_s` (a one-word cue the cps rule cut off) is not counted:
        that wait is the reading-time floor, not a timing error.
        """
        ends = sorted((w.end, w.start) for w in self.truth)
        floor = self.cfg.captions.min_cue_s
        late = 0
        cues = self.cues()
        for start, end, _text in cues:
            inside = [e for e, s in ends if s >= start - 0.01 and s <= end]
            if inside and end - max(inside) > LATE_END_S and end - start > floor + 0.01:
                late += 1
        return late / len(cues)


@pytest.fixture
def harness(tmp_path):
    def make(mode: str, **kw) -> Harness:
        return Harness(tmp_path, mode, **kw)

    return make


async def test_real_words_reach_the_sync_target(harness):
    h = harness("flag")
    await h.run("run", "auto", None)
    score = h.score()
    assert score.hit >= HIT_TARGET and score.loose == 1.0, score
    assert h.late_end_share() <= LATE_END_SHARE
    timing = h.event("word_timing")
    assert timing["status"] == "ok" and timing["detail"]["word_timing"] == "real"
    assert timing["detail"]["stretched"] >= 1 and timing["detail"]["squeezed"] >= 1
    assert len(h.engine.asked) == 2 and all(a["want_words"] for a in h.engine.asked)
    check = h.event("sync_score")["detail"]
    assert check["speech_overlap"] > SPEECH_OVERLAP_FLOOR and check["starts_in_silence"] < 0.1
    row = h.db.one("SELECT timing_version, timing FROM captions WHERE video_id=?", [VID])
    assert row["timing_version"] == TIMING_VERSION and '"word_timing": "real"' in row["timing"]


async def test_improve_with_real_words_reaches_the_sync_target(harness):
    h = harness("flag")
    await h.run("improve", youtube_rows(h.truth), "en", None)
    assert h.score().hit >= HIT_TARGET
    cues = h.cues()
    text = " ".join(t for _s, _e, t in cues)
    assert all(w.text in text for w in h.truth), "a spoken word was dropped"
    begin, finish = long_pause(h.truth)
    music = [c for c in cues if c[2] == "[Music]"]
    assert music and begin <= music[0][0] and music[0][1] <= finish
    align = h.event("align")["detail"]
    assert align["mode"] == "words" and align["fill_cues"] == 1
    assert max(e - s for s, e, _t in cues) <= h.cfg.captions.max_cue_s + 1e-6


async def test_segment_only_engine_is_reported_and_scores_low(harness):
    h = harness("segments")
    await h.run("run", "auto", None)
    timing = h.event("word_timing")
    assert timing["status"] == "warn" and timing["detail"]["word_timing"] == "interpolated"
    assert "estimates" in timing["detail"]["message"]
    assert h.score().hit < SEGMENT_ONLY_HIT_CEILING


async def test_segment_only_engine_keeps_caption_text_and_times_in_improve(harness):
    h = harness("segments")
    rows = youtube_rows(h.truth)
    await h.run("improve", rows, "en", None)
    align = h.event("align")
    assert align["detail"]["mode"] == "captions_timing"
    assert align["detail"]["reason"] == "word_times_estimated" and align["status"] == "skipped"
    starts = [s for s, _e, _t in rows]
    cues = h.cues()
    assert all(any(abs(s - r) < 0.002 for r in starts) for s, _e, _t in cues)
    text = " ".join(t for _s, _e, t in cues)
    assert all(w.text in text for w in h.truth), "a caption token vanished"
    assert len(cues) >= len(rows) - 2


async def test_legacy_mode_keeps_the_old_path(harness):
    h = harness("flag")
    h.cfg.captions.timing_mode = "legacy"
    await h.run("improve", youtube_rows(h.truth), "en", None)
    assert h.event("align")["detail"]["mode"] == "merge"
    assert not any(e["stage"] in ("word_timing", "sync_score") for e in h.log.list("j1"))
    row = h.db.one("SELECT timing_version FROM captions WHERE video_id=?", [VID])
    assert row["timing_version"] is None


def test_the_truth_has_the_pauses_the_tests_rely_on():
    truth = make_timeline(SEED, DURATION_S)
    assert len(phrases(truth)) > 30 and bisect.bisect(truth, 0, key=lambda w: w.start) == 0
    begin, finish = long_pause(truth)
    assert finish - begin >= 25.0


async def test_improve_never_shows_a_spoken_phrase_twice(harness):
    import re

    h = harness("flag")
    await h.run("improve", youtube_rows(h.truth), "en", None)
    text = [t for _s, _e, t in h.cues() if t != "[Music]"]
    tokens = " ".join(text).split()
    assert len(tokens) == len(set(tokens)), "a token was shown twice"
    assert not re.search(r"(w\d{4})\b.*\b\1\b", " ".join(text))


async def test_hallucinated_chunk_recovers(harness):
    h = harness("flag", chunk_s=HALLUCINATED_CHUNK_S, hallucinate=True)
    await h.run("run", "auto", None)
    recheck = h.event("asr_recheck")["detail"]
    assert recheck["action"] == "forced_language" and recheck["outcome"] == "replaced"
    assert (recheck["start_s"], recheck["end_s"]) == (0.0, float(HALLUCINATED_CHUNK_S))
    assert len(h.engine.asked) == 4 and h.engine.asked[-1]["language"] == "tr"
    assert all(text.strip() != PHANTOM.strip() for _s, _e, text in h.cues())
    score = h.score()
    assert score.hit >= HIT_TARGET and score.loose == 1.0, score
    asr = h.event("asr", "ok")["detail"]
    assert asr["rechecked_chunks"] == 1 and asr["hallucination_drops"] == 0


class DoublingTranslator(MockOpenAI):
    """A mock LLM whose translation is twice as long as the source line."""

    def respond(self, body):
        system = body["messages"][0]["content"]
        if "Translate each subtitle" in system:
            lines = json.loads(body["messages"][-1]["content"])
            return json.dumps([f"{line} {line}" for line in lines])
        return super().respond(body)


async def test_translated_track_keeps_the_sync_score(harness, tmp_path):
    plain = harness("flag")
    await plain.run("run", "tr", None)
    (tmp_path / "translated").mkdir()
    doubled = Harness(tmp_path / "translated", "flag", llm=DoublingTranslator())
    await doubled.run("run", "tr", "de")
    assert abs(doubled.score().hit - plain.score().hit) <= TRANSLATED_HIT_TOLERANCE
    translate = doubled.event("translate")["detail"]
    assert translate["split_by_chars"] == 0 and translate["split_at_pause"] > 0
    limit = doubled.cfg.captions.max_chars_per_line
    row = doubled.db.one("SELECT timing, vtt FROM captions WHERE video_id=?", [VID])
    text_lines = [ln for ln in row["vtt"].splitlines() if ln and "-->" not in ln]
    assert all(len(line) <= limit for line in text_lines if not line.isdigit() and line != "WEBVTT")
    assert json.loads(row["timing"])["char_timed_cues"] == 0


REF_SHIFT_S = 1.5
REF_LEAD_S = 0.25
REF_TOLERANCE_S = 0.05


class ShiftedChunkEngine(ScriptedEngine):
    """A scripted engine whose chunks starting at or after `from_s` answer `by` seconds late."""

    def __init__(self, *args, from_s: float, by: float):
        super().__init__(*args)
        self.from_s, self.by = from_s, by

    async def transcribe_chunk(self, wav, language, want_words):
        result = await super().transcribe_chunk(wav, language, want_words)
        if self.asked[-1]["start"] >= self.from_s:
            for item in [*result.words, *result.segments]:
                item.start += self.by
                item.end += self.by
        return result


async def test_improve_checks_the_engine_against_youtube_word_times(harness):
    h = harness("flag")
    rows = youtube_rows(h.truth)
    await h.run("improve", rows, "en", None, ref_words=youtube_words(h.truth), caption_kind="auto")
    check = h.event("ref_check")
    assert check["status"] == "ok", check
    detail = check["detail"]
    assert detail["within_s"] >= HIT_TARGET and detail["regions"] == []
    assert detail["median_s"] == pytest.approx(REF_LEAD_S, abs=REF_TOLERANCE_S)
    stored = json.loads(h.db.one("SELECT timing FROM captions")["timing"])["ref_check"]
    assert stored["regions"] == 0 and stored["anchors"] > 100
    assert h.score().hit >= HIT_TARGET  # the check changes no times


async def test_improve_without_youtube_words_falls_back_to_the_rows(harness):
    h = harness("flag")
    await h.run("improve", youtube_rows(h.truth), "en", None)
    check = h.event("ref_check")
    assert check["status"] == "ok" and check["detail"]["source"] == "rows"


async def test_improve_locates_a_chunk_the_engine_has_wrong(harness):
    h = harness("flag")
    h.engine = ShiftedChunkEngine(
        h.truth, "flag", DURATION_S, CHUNK_S, h.cfg.captions.asr_chunk_overlap_s,
        from_s=CHUNK_S - h.cfg.captions.asr_chunk_overlap_s, by=REF_SHIFT_S,
    )  # fmt: skip
    await h.run("improve", youtube_rows(h.truth), "en", None, ref_words=youtube_words(h.truth))
    check = h.event("ref_check")
    assert check["status"] == "warn" and len(check["detail"]["regions"]) == 1
    start, end, median = check["detail"]["regions"][0]
    assert start >= CHUNK_S - 15 and end <= DURATION_S
    assert median == pytest.approx(REF_LEAD_S + REF_SHIFT_S, abs=REF_TOLERANCE_S)


MISSED_PHRASE = 12
FILL_START_TOLERANCE_S = 0.15


class DeafEngine(ScriptedEngine):
    """A scripted engine that does not hear one phrase (its words are missing from every answer)."""

    def __init__(self, *args, deaf: tuple[float, float]):
        super().__init__(*args)
        self.deaf = deaf

    async def transcribe_chunk(self, wav, language, want_words):
        result = await super().transcribe_chunk(wav, language, want_words)
        span = self.spans[
            min(
                range(len(self.spans)),
                key=lambda i: abs(self.spans[i].start - self.asked[-1]["start"]),
            )
        ]
        lo, hi = self.deaf[0] - span.start, self.deaf[1] - span.start
        result.words = [w for w in result.words if not (lo - 0.01 <= w.start <= hi + 0.01)]
        return result


async def test_improve_shows_a_phrase_only_youtube_heard_from_its_word_times(harness):
    h = harness("flag")
    group = phrases(h.truth)[MISSED_PHRASE]
    h.engine = DeafEngine(
        h.truth, "flag", DURATION_S, CHUNK_S, h.cfg.captions.asr_chunk_overlap_s,
        deaf=(group[0].start, group[-1].end),
    )  # fmt: skip
    await h.run(
        "improve",
        youtube_rows(h.truth),
        "en",
        None,
        ref_words=youtube_words(h.truth),
        caption_kind="auto",
    )
    cues = h.cues()
    text = " ".join(t for _s, _e, t in cues)
    assert all(w.text in text for w in group), "the phrase only YouTube heard was dropped"
    shown = [c for c in cues if group[0].text in c[2]]
    assert shown and abs(shown[0][0] - group[0].start) <= FILL_START_TOLERANCE_S
    align = h.event("align")["detail"]
    assert align["fill_from_words"] >= 1
    assert h.score().hit >= HIT_TARGET
    timing = json.loads(h.db.one("SELECT timing FROM captions")["timing"])
    assert timing["reference"] == len(group) and timing["real_share"] == 1.0
