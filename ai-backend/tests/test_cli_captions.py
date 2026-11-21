"""`utubot captions-regen` and `utubot captions-score`: offline, with the mock engine."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from tests.synth_speech import make_timeline, phrases, tone_wav
from utubot.captions.asr import ffmpeg_available
from utubot.captions.engines import ChunkResult, parse_verbose_json
from utubot.captions.pipeline import TIMING_VERSION
from utubot.captions.score import ScoreError, score_track, window_starts
from utubot.captions.segment import fmt_vtt_time
from utubot.cli import main
from utubot.config import AsrEngineConfig, Config, load_config
from utubot.db import Database
from utubot.media_archive import MediaArchive

VID = "abcdefghijk"
CURRENT = "bcdefghijkl"
TRACK_S = 90.0
WINDOW_S = 20.0
WINDOWS = 3
HIT_FLOOR = 0.9


@pytest.fixture
def cfg_path(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        f'[server]\ndata_dir = "{tmp_path}/d"\n[[users]]\nname = "owner"\nadmin = true\n'
        '[[captions.asr_engines]]\nname = "ref"\nurl = "http://ref.example/v1/audio/transcriptions"\n'
    )
    return path


def add_track(db, video_id, version, job_id=None, lang="en"):
    db.execute(
        "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at,job_id,timing_version)"
        " VALUES(?,?,?,?,?,?,?,?)",
        [video_id, lang, "l", 0, "WEBVTT\n", 1.0, job_id, version],
    )


def test_regen_dry_run_lists_a_legacy_track_and_not_a_current_one(cfg_path, capsys):
    cfg = load_config(cfg_path)
    db = Database(cfg.db_path)
    add_track(db, VID, None)
    add_track(db, CURRENT, TIMING_VERSION)
    assert main(["--config", str(cfg_path), "captions-regen", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert VID in out and CURRENT not in out and "would queue" in out
    assert db.one("SELECT COUNT(*) c FROM jobs")["c"] == 0


def test_regen_queues_a_background_job_with_the_original_language_and_target(cfg_path, capsys):
    cfg = load_config(cfg_path)
    db = Database(cfg.db_path)
    db.execute(
        "INSERT INTO jobs(id,user,video_id,lang,translate_to,status,progress,created_at,updated_at,kind)"
        " VALUES('old1','partner',?, 'hi','en','ready',1,1,1,'captions')",
        [VID],
    )
    add_track(db, VID, None, job_id="old1")
    add_track(db, CURRENT, 0)  # older than the current scheme, no job on record
    assert main(["--config", str(cfg_path), "captions-regen"]) == 0
    jobs = db.all("SELECT * FROM jobs WHERE id!='old1' ORDER BY video_id")
    assert [j["video_id"] for j in jobs] == [VID, CURRENT]
    assert (jobs[0]["user"], jobs[0]["lang"], jobs[0]["translate_to"]) == ("partner", "hi", "en")
    assert jobs[1]["user"] == "owner" and jobs[1]["lang"] == "auto" and jobs[1]["priority"] == 1
    queued = db.one(
        "SELECT detail FROM job_events WHERE job_id=? AND stage='queued'", [jobs[0]["id"]]
    )
    assert json.loads(queued["detail"])["trigger"] == {"via": "regen"}
    assert main(["--config", str(cfg_path), "captions-regen", "--video", VID, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert out.count("would queue") == 1 and CURRENT not in out.split("would queue")[-1]


def test_regen_options_select_and_limit(cfg_path, capsys):
    cfg = load_config(cfg_path)
    db = Database(cfg.db_path)
    add_track(db, VID, None)
    add_track(db, CURRENT, 0)
    capsys.readouterr()
    main(["--config", str(cfg_path), "captions-regen", "--dry-run", "--legacy"])
    legacy = capsys.readouterr().out
    assert VID in legacy and CURRENT not in legacy
    main(["--config", str(cfg_path), "captions-regen", "--dry-run", "--limit", "1"])
    assert "1 track(s)" in capsys.readouterr().out


def test_window_starts_are_evenly_spaced_inside_the_audio():
    assert window_starts(60.0, 4, 120.0) == [0.0]
    starts = window_starts(1000.0, 4, 100.0)
    assert len(starts) == 4 and starts[0] > 0 and starts[-1] + 100.0 < 1000.0
    gaps = {round(b - a, 3) for a, b in zip(starts, starts[1:], strict=False)}
    assert len(gaps) == 1


class WindowEngine:
    """Answers the windows in order from the truth, as a perfect reference engine would."""

    def __init__(self, truth, begins):
        self.truth, self.begins, self.calls = truth, list(begins), 0

    async def transcribe_chunk(self, wav: Path, language, want_words) -> ChunkResult:
        begin = self.begins[self.calls]
        self.calls += 1
        with wave.open(str(wav), "rb") as fh:
            length = fh.getnframes() / fh.getframerate()
        inside = [w for w in self.truth if w.start >= begin and w.end <= begin + length]
        words = [
            {"word": w.text, "start": w.start - begin, "end": w.end - begin, "probability": 0.9}
            for w in inside
        ]
        body = {
            "language": "english",
            "text": " ".join(w.text for w in inside),
            "segments": [{"start": 0.0, "end": length, "text": " ".join(w.text for w in inside)}],
            "words": words,
        }
        return parse_verbose_json(body, length, want_words)


def vtt_of(truth, shift=0.0):
    lines = ["WEBVTT", ""]
    for group in phrases(truth):
        start, end = group[0].start + shift, group[-1].end + shift
        lines += [
            f"{fmt_vtt_time(start)} --> {fmt_vtt_time(end)}",
            " ".join(w.text for w in group),
            "",
        ]
    return "\n".join(lines)


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg is not installed")
async def test_captions_score_matches_a_track_to_the_reference_windows(tmp_path):
    truth = make_timeline(3, TRACK_S)
    audio = tone_wav(tmp_path / "talk.wav", truth, TRACK_S)
    cfg = Config()
    cfg.server.data_dir = str(tmp_path / "data")
    cfg.captions.asr_engines = [
        AsrEngineConfig(name="ref", url="http://ref.example/v1/audio/transcriptions")
    ]
    db = Database(tmp_path / "t.sqlite")
    begins = window_starts(TRACK_S, WINDOWS, WINDOW_S)
    engine = WindowEngine(truth, begins)

    with pytest.raises(ScoreError, match="no stored captions"):
        await score_track(cfg, db, VID, reference="ref", engine_factory=lambda e: engine)
    db.execute(
        "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at) VALUES(?,?,?,?,?,?)",
        [VID, "en", "l", 0, vtt_of(truth), 1.0],
    )
    with pytest.raises(ScoreError, match="not archived"):
        await score_track(cfg, db, VID, reference="ref", engine_factory=lambda e: engine)
    MediaArchive(cfg, db).store(VID, audio, format_id="1", codec="pcm")

    doc = await score_track(
        cfg, db, VID, reference="ref", windows=WINDOWS, window_s=WINDOW_S,
        engine_factory=lambda e: engine,
    )  # fmt: skip
    assert len(doc["windows"]) == WINDOWS and engine.calls == WINDOWS
    assert doc["overall"]["onsets"] > 3 and doc["overall"]["hit"] >= HIT_FLOOR
    assert doc["reference"] == "ref" and doc["windows"][0]["word_timing"] == "real"
    track = doc["track"]
    assert track["lang"] == "en" and track["cues"] > 3 and track["max_cue_s"] > 0
    assert track["first_cue_start_s"] == pytest.approx(truth[0].start, abs=0.01)

    engine.calls = 0
    db.execute("UPDATE captions SET vtt=?", [vtt_of(truth, shift=0.8)])
    late = await score_track(
        cfg, db, VID, reference="ref", windows=WINDOWS, window_s=WINDOW_S,
        engine_factory=lambda e: engine,
    )  # fmt: skip
    assert late["overall"]["hit"] < doc["overall"]["hit"] and late["overall"]["median_s"] > 0.5

    with pytest.raises(ScoreError, match="no engine named"):
        await score_track(cfg, db, VID, reference="nope", engine_factory=lambda e: engine)
    with pytest.raises(ScoreError, match="does not run from tests"):
        await score_track(cfg, db, VID, reference="ref")


def test_captions_score_refuses_without_archived_audio(cfg_path, capsys, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("CI", raising=False)
    cfg = load_config(cfg_path)
    db = Database(cfg.db_path)
    db.execute(
        "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at) VALUES(?,?,?,?,?,?)",
        [VID, "en", "l", 0, "WEBVTT\n", 1.0],
    )
    code = main(["--config", str(cfg_path), "captions-score", VID, "--reference", "ref"])
    assert code == 1 and "not archived" in capsys.readouterr().err


def test_regen_default_limit_legacy_mode_and_termination(cfg_path, capsys):
    cfg = load_config(cfg_path)
    db = Database(cfg.db_path)
    for i in range(cfg.captions.regen_limit_default + 5):
        add_track(db, f"v{i:010d}", None)
    # a video whose regenerated job stored another language: the newer current track ends the listing
    db.execute(
        "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at,timing_version)"
        " VALUES('done0000000','tr','l',0,'WEBVTT',1.0,NULL)"
    )
    db.execute(
        "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at,timing_version)"
        " VALUES('done0000000','en','l',0,'WEBVTT',2.0,?)",
        [TIMING_VERSION],
    )
    main(["--config", str(cfg_path), "captions-regen", "--dry-run"])
    out = capsys.readouterr().out
    assert f"{cfg.captions.regen_limit_default} track(s)" in out and "done0000000" not in out
    main(["--config", str(cfg_path), "captions-regen", "--dry-run", "--limit", "3"])
    assert "3 track(s)" in capsys.readouterr().out
    cfg_path.write_text(cfg_path.read_text() + '[captions]\ntiming_mode = "legacy"\n')
    assert main(["--config", str(cfg_path), "captions-regen", "--dry-run"]) == 0
    assert "skipped" in capsys.readouterr().out


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg is not installed")
async def test_captions_score_picks_the_track_and_the_window_starts(tmp_path):
    truth = make_timeline(3, TRACK_S)
    audio = tone_wav(tmp_path / "talk.wav", truth, TRACK_S)
    cfg = Config()
    cfg.server.data_dir = str(tmp_path / "data")
    cfg.captions.asr_engines = [
        AsrEngineConfig(name="ref", url="http://ref.example/v1/audio/transcriptions")
    ]
    db = Database(tmp_path / "t.sqlite")
    for lang, version, created in (("en", 1, 1.0), ("tr", None, 2.0)):
        db.execute(
            "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at,timing_version)"
            " VALUES(?,?,?,?,?,?,?)",
            [VID, lang, "l", 0, vtt_of(truth), created, version],
        )
    MediaArchive(cfg, db).store(VID, audio, format_id="1", codec="pcm")
    begins = [10.0, 50.0]
    engine = WindowEngine(truth, begins)
    doc = await score_track(
        cfg, db, VID, reference="ref", at=begins, window_s=WINDOW_S,
        engine_factory=lambda e: engine,
    )  # fmt: skip
    assert doc["track"]["lang"] == "en"  # the newer track has no timing version
    assert [w["start_s"] for w in doc["windows"]] == begins
    engine.calls = 0
    other = await score_track(
        cfg, db, VID, reference="ref", lang="tr", at=begins, window_s=WINDOW_S,
        engine_factory=lambda e: engine,
    )  # fmt: skip
    assert other["track"]["lang"] == "tr" and other["track"]["timing_version"] is None
