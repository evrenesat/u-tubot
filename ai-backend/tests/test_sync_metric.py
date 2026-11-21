"""The offline sync metric: cue starts against a ground-truth timeline, through the whole pipeline.

A synthetic talk (`tests/synth_speech.py`) is the truth. A scripted engine answers each chunk the way a
Whisper server does, flaws included; the audio is a tone wherever the truth has a phrase. Cues are scored
with `syncscore` the same way `utubot captions-score` scores a real track.
"""

from __future__ import annotations

import bisect
from pathlib import Path

import pytest

from tests.synth_speech import (
    ScriptedEngine,
    long_pause,
    make_timeline,
    phrases,
    tone_wav,
    youtube_rows,
)
from utubot.captions import events
from utubot.captions.asr import ffmpeg_available
from utubot.captions.engines import AsrRouter
from utubot.captions.events import JobEvents, JobTrace
from utubot.captions.pipeline import CaptionPipeline
from utubot.captions.syncscore import phrase_onsets, score_starts
from utubot.config import AsrEngineConfig, Config
from utubot.db import Database
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


class Harness:
    def __init__(self, tmp_path: Path, mode: str):
        self.truth = make_timeline(SEED, DURATION_S)
        self.audio = tone_wav(tmp_path / "talk.wav", self.truth, DURATION_S)
        self.cfg = Config()
        self.cfg.server.data_dir = str(tmp_path / "data")
        self.cfg.youtube.min_interval_s = self.cfg.youtube.jitter_s = 0.0
        self.cfg.captions.asr_engines = [
            AsrEngineConfig(
                name="scripted",
                url="http://scripted.example/v1/audio/transcriptions",
                max_chunk_s=CHUNK_S,
            )
        ]
        self.cfg.captions.proofread = False
        self.engine = ScriptedEngine(
            self.truth, mode, DURATION_S, CHUNK_S, self.cfg.captions.asr_chunk_overlap_s
        )
        self.db = Database(tmp_path / "t.sqlite")
        router = AsrRouter(
            self.cfg.captions, engine_factory=lambda e: self.engine, enabled=lambda e: True
        )
        self.pipeline = CaptionPipeline(self.cfg, self.db, router, downloader=self.download)
        self.log = JobEvents(self.db, self.cfg.captions)

    async def download(self, video_id, out_dir, started):
        started()
        path = out_dir / "audio.wav"
        path.write_bytes(self.audio.read_bytes())
        return path

    async def run(self, method: str, *args):
        token = events.bind(JobTrace("j1", self.log))
        try:
            await getattr(self.pipeline, method)(VID, *args, lambda f: None)
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
    def make(mode: str) -> Harness:
        return Harness(tmp_path, mode)

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
    assert row["timing_version"] == 1 and '"word_timing": "real"' in row["timing"]


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
