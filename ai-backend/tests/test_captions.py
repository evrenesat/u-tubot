from __future__ import annotations

import asyncio
import re
import time

import pytest

from utubot.captions.diarize import assign_speakers
from utubot.captions.segment import build_cues, fmt_vtt_time, retime_split, to_vtt
from utubot.captions.types import Word
from utubot.config import CaptionsConfig

VID = "abcdefghijk"
CFG = CaptionsConfig()


def words_from(text: str, start=0.0, per=0.35, speaker=None, gap_after=None):
    out, t = [], start
    for w in text.split():
        out.append(Word(t, t + per - 0.05, w, speaker))
        t += per
    return out


def test_vtt_time_format():
    assert fmt_vtt_time(3661.5) == "01:01:01.500"
    assert fmt_vtt_time(0.0004) == "00:00:00.000"


def test_cue_constraints_long_monologue():
    text = " ".join(f"word{i}" for i in range(120))
    cues = build_cues(words_from(text), CFG)
    assert len(cues) > 3
    for cue in cues:
        assert len(cue.lines) <= CFG.max_lines
        assert all(len(line) <= CFG.max_chars_per_line for line in cue.lines)
        assert cue.end - cue.start <= CFG.max_cue_s + 1e-6
        assert cue.end - cue.start >= CFG.min_cue_s - 1e-6 or cue is cues[-1]
    for a, b in zip(cues, cues[1:], strict=False):
        assert a.end <= b.start + 1e-6


def test_sentence_split_and_min_duration():
    ws = words_from("Hi there my friend.", 0.0) + words_from(
        "This is the second sentence here.", 1.6
    )
    cues = build_cues(ws, CFG)
    assert cues[0].lines == ["Hi there my friend."]
    assert cues[0].end - cues[0].start >= CFG.min_cue_s - 1e-6
    assert cues[0].end <= cues[1].start + 1e-6


def test_cps_cuts_cues_that_would_run_too_fast():
    cfg = CaptionsConfig(max_cps=20.0)
    # five-character words every 0.2 s: 25 characters per second, faster than the ceiling
    text = " ".join("abcde" for _ in range(30))
    ws = words_from(text, per=0.2)
    fast = build_cues(ws, cfg)
    dense = build_cues(ws, CaptionsConfig(max_cps=0.0))
    assert max(len(" ".join(cue.lines)) for cue in fast) < max(
        len(" ".join(cue.lines)) for cue in dense
    )
    for cue in fast:
        chars = sum(len(line) for line in cue.lines)
        duration = cue.end - cue.start
        # the cue is cut as soon as adding the next word would run faster than the ceiling, so it
        # carries at most a couple of words beyond what the ceiling allows for its duration
        assert chars <= cfg.max_cps * duration + 2 * len("abcde") + 2


def test_retime_split_spreads_long_text_over_timed_cues():
    text = " ".join(f"word{i}" for i in range(40))
    out = retime_split(text, 10.0, 40.0, CFG)
    assert len(out) > 1
    assert out[0].start == 10.0 and out[-1].end == 40.0
    for cue in out:
        assert len(cue.lines) <= CFG.max_lines
        assert all(len(line) <= CFG.max_chars_per_line for line in cue.lines)
    for a, b in zip(out, out[1:], strict=False):
        assert a.end <= b.start + 1e-9


def test_speaker_prefixes_only_on_turns():
    ws = (
        words_from("Hello there my friend.", 0.0, speaker="A")
        + words_from("Nice to see you again today.", 3.0, speaker="B")
        + words_from("Likewise.", 6.0, speaker="A")
    )
    ws2 = words_from("And one more thought from me.", 6.4, speaker="A")
    cues = build_cues(ws + ws2, CFG)
    vtt = to_vtt(cues)
    assert vtt.startswith("WEBVTT\n")
    firsts = [c.lines[0] for c in cues]
    assert firsts[0].startswith("[S1] ")
    assert any(f.startswith("[S2] ") for f in firsts)
    assert sum(f.startswith("[S1] ") for f in firsts) == 2
    assert re.search(r"\d\d:\d\d:\d\d\.\d{3} --> \d\d:\d\d:\d\d\.\d{3}", vtt)


def test_assign_speakers_nearest_turn():
    ws = [Word(0.0, 0.4, "a"), Word(5.2, 5.5, "b")]
    assign_speakers(ws, [(0.0, 1.0, "X"), (5.0, 6.0, "Y")])
    assert [w.speaker for w in ws] == ["X", "Y"]


async def wait_status(client, want, timeout=15.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = (await client.get(f"/v1/videos/{VID}/captions")).json()
        if body["status"] in want:
            return body
        await asyncio.sleep(0.1)
    pytest.fail(f"timeout waiting for {want}, last {body}")


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg missing")
async def test_caption_job_end_to_end(env):
    assert (await env.client.get(f"/v1/videos/{VID}/captions")).json()["status"] == "none"
    q = await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})
    assert q.json()["status"] == "queued"
    dup = await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})
    assert dup.json()["job_id"] == q.json()["job_id"]
    body = await wait_status(env.client, {"ready", "failed"})
    assert body["status"] == "ready", body
    track = body["tracks"][0]
    assert track["lang"] == "en" and track["label"] == "English (u·tubot)"
    vtt = await env.client.get(track["url"])
    assert vtt.headers["content-type"].startswith("text/vtt")
    assert "Hello there." in vtt.text and "How are you doing today?" in vtt.text
    assert env.llm.audio_calls[0]["response_format"] == "verbose_json"
    assert not (env.cfg.media_dir / VID).exists()
    verdict = await env.client.post(
        "/v1/assess", json={"videos": [{"video_id": VID, "title": "x"}]}
    )
    assert verdict.json()["results"][0]["captions_ready"] is True


async def test_vtt_token_query_auth(env):
    env.svc.db.execute(
        "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at) VALUES(?,?,?,?,?,?)",
        [VID, "en", "English (u·tubot)", 1, "WEBVTT\n\n", time.time()],
    )
    import httpx

    anon = httpx.AsyncClient(transport=env.client._transport, base_url="http://utubot")
    url = f"/v1/videos/{VID}/captions/en.vtt"
    assert (await anon.get(url)).status_code == 401
    assert (await anon.get(url, params={"token": "utb_testtoken"})).status_code == 200
    assert (await anon.get(url, params={"token": "bad"})).status_code == 401
    ok = await anon.get(url, headers={"Authorization": "Bearer utb_testtoken"})
    assert ok.status_code == 200
    assert (await anon.get(url, headers={"Authorization": "Bearer bad"})).status_code == 401
    assert (await env.client.get(f"/v1/videos/{VID}/captions/xx.vtt")).status_code == 404


async def test_job_failure_reported_and_restart_recovery(env):
    env.cfg.captions.asr_url = "http://mock/nope"
    await env.client.post(f"/v1/videos/{VID}/captions", json={})
    body = await wait_status(env.client, {"failed", "ready"})
    assert body["status"] == "failed"
    assert "mock" not in str(body) and "http" not in str(body.get("error"))
    env.svc.db.execute(
        "INSERT INTO jobs(id,user,video_id,lang,translate_to,status,progress,created_at,updated_at)"
        " VALUES('stuck','owner','zzzzzzzzzzz','auto',NULL,'running',0.5,?,?)",
        [time.time(), time.time()],
    )
    await env.svc.jobs.stop()
    env.svc.jobs.start()
    env.cfg.captions.asr_url = "http://mock/v1/audio/transcriptions"
    deadline = time.time() + 15
    while time.time() < deadline:
        row = env.svc.db.one("SELECT status FROM jobs WHERE id='stuck'")
        if row["status"] == "ready":
            break
        await asyncio.sleep(0.1)
    assert row["status"] == "ready"


async def test_translate_cues(env):
    from utubot.captions.types import Cue

    cues = [Cue(0, 2, ["[S1] Hello world"], "S1"), Cue(2, 4, ["Second one"], None)]
    out = await env.svc.jobs.pipeline.translate(cues, "tr")
    assert out[0].lines == ["[S1] T:Hello world"] and out[1].lines == ["T:Second one"]


async def test_translated_cues_are_proofread_again(env):
    from tests.test_proofread import proofread_calls, respond_with_cues
    from utubot.captions.types import Cue

    respond_with_cues(env.llm, ["Hello, world."])
    cues = [Cue(0, 2, ["merhaba dunya"], None)]
    track = await env.svc.jobs.pipeline._finish(VID, cues, "tr", "en", lambda _f: None)
    assert track == "en"
    kinds = [
        "translate" if "Translate each subtitle" in c["messages"][0]["content"] else "proofread"
        for c in env.llm.calls
        if "Translate each subtitle" in c["messages"][0]["content"]
        or "proofread subtitle cues" in c["messages"][0]["content"]
    ]
    assert kinds == ["translate", "proofread"]  # the English text is proofread after translation
    row = env.svc.db.one("SELECT lang,vtt FROM captions WHERE video_id=?", [VID])
    assert row["lang"] == "en" and "Hello, world." in row["vtt"]
    assert proofread_calls(env.llm) == 1


async def test_pyannote_skips_without_token(monkeypatch, tmp_path):
    from utubot.captions.diarize import PyannoteDiarizer

    monkeypatch.delenv("UTUBOT_HF_TOKEN", raising=False)
    assert await PyannoteDiarizer(CFG).diarize(tmp_path / "x.wav") == []


async def test_pyannote_uses_community_pipeline(monkeypatch, tmp_path):
    import sys
    import types

    from utubot.captions.diarize import PyannoteDiarizer

    seen = {}

    class Seg:
        start, end = 0.0, 1.5

    class Annotation:
        def itertracks(self, yield_label=True):
            return [(Seg(), None, "SPEAKER_00")]

    class Out:
        speaker_diarization = Annotation()

    class Pipeline:
        @staticmethod
        def from_pretrained(name, token=None):
            seen["name"], seen["token"] = name, token
            return lambda path: Out()

    mod = types.ModuleType("pyannote.audio")
    mod.Pipeline = Pipeline
    monkeypatch.setitem(sys.modules, "pyannote", types.ModuleType("pyannote"))
    monkeypatch.setitem(sys.modules, "pyannote.audio", mod)
    monkeypatch.setenv("UTUBOT_HF_TOKEN", "hf_test")
    turns = await PyannoteDiarizer(CFG).diarize(tmp_path / "x.wav")
    assert turns == [(0.0, 1.5, "SPEAKER_00")]
    assert seen == {"name": "pyannote/speaker-diarization-community-1", "token": "hf_test"}


def _spoken_cue(text: str, gap_after: int | None = None, gap_s: float = 1.2):
    """A cue over `text` whose words are 0.3 s long, with an extra pause after word `gap_after`."""
    from utubot.captions.types import Cue

    out, t = [], 0.0
    for i, w in enumerate(text.split()):
        out.append(Word(t, t + 0.3, w))
        t += 0.35 + (gap_s if gap_after is not None and i == gap_after else 0.0)
    return Cue(out[0].start, out[-1].end, [text], words=out)


def _tight_cfg(**kw):
    return CaptionsConfig(max_chars_per_line=20, max_lines=1, **kw)


def test_split_cue_exact_uses_word_times():
    from utubot.captions.segment import SplitStats, split_cue

    cue = _spoken_cue("alpha beta gamma delta epsilon zeta eta theta")
    stats = SplitStats()
    pieces = split_cue(
        cue, "Alpha beta, gamma delta, epsilon zeta, eta theta.", _tight_cfg(), stats
    )
    assert (stats.exact, stats.at_pause, stats.by_chars) == (1, 0, 0)
    assert len(pieces) > 1
    first_words = [p.words[0] for p in pieces]
    for piece, word in zip(pieces[1:], first_words[1:], strict=True):
        assert piece.start == word.start
    for piece, nxt in zip(pieces, pieces[1:], strict=False):
        assert piece.words[-1] is cue.words[cue.words.index(nxt.words[0]) - 1]
        assert piece.end >= piece.words[-1].end and piece.end <= nxt.start
    assert pieces[0].start == cue.start and pieces[-1].end == cue.end
    assert sum(len(p.words) for p in pieces) == len(cue.words)


def test_split_cue_prefers_the_pause():
    from utubot.captions.segment import SplitStats, split_cue

    text = "one two three four five six seven eight nine ten eleven twelve"
    cue = _spoken_cue(text, gap_after=5)
    gap_start, gap_end = cue.words[5].end, cue.words[6].start
    stats = SplitStats()
    cfg = CaptionsConfig(max_chars_per_line=40, max_lines=1)
    # a translation of another length: the tokens no longer map onto the words
    cue.words_match_text = False
    pieces = split_cue(
        cue, "uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece", cfg, stats
    )
    assert stats.at_pause == 1 and stats.by_chars == 0
    assert len(pieces) == 2
    assert pieces[0].end <= gap_start + cfg.cue_linger_s + 1e-9
    assert pieces[1].start == gap_end
    assert not any(p.start < gap_end and p.end > gap_start + cfg.cue_linger_s for p in pieces)


def test_split_cue_without_words_counts_by_chars():
    from utubot.captions.segment import SplitStats, split_cue
    from utubot.captions.types import Cue

    stats = SplitStats()
    cue = Cue(0.0, 6.0, ["[Music]"])
    pieces = split_cue(cue, "one two three four five six seven eight nine ten", _tight_cfg(), stats)
    assert stats.by_chars == 1 and stats.exact == stats.at_pause == 0
    assert len(pieces) > 1 and all(p.char_timed for p in pieces)
    assert pieces[0].start == 0.0 and pieces[-1].end >= 6.0


def test_split_cue_keeps_the_speaker_prefix_out_of_the_word_map():
    from utubot.captions.segment import SplitStats, split_cue
    from utubot.captions.types import Cue

    cue = _spoken_cue("alpha beta gamma delta epsilon zeta eta theta")
    cue = Cue(cue.start, cue.end, cue.lines, "S1", words=cue.words)
    stats = SplitStats()
    pieces = split_cue(cue, "[S1] " + " ".join(w.text for w in cue.words), _tight_cfg(), stats)
    assert stats.exact == 1
    assert sum(len(p.words) for p in pieces) == len(cue.words)
    assert all(p.speaker == "S1" for p in pieces)


async def test_translation_overflow_is_split_not_one_long_line(env):
    cue = _spoken_cue("one two three four five six seven eight", gap_after=3)
    cue = type(cue)(
        cue.start, cue.end, ["one two three four five six seven eight"], words=cue.words
    )
    env.svc.jobs.pipeline.cfg.captions.max_chars_per_line = 20
    env.svc.jobs.pipeline.cfg.captions.max_lines = 1
    out = await env.svc.jobs.pipeline.translate([cue], "tr")
    assert len(out) > 1
    assert all(len(line) <= 20 for piece in out for line in piece.lines)
    assert out[0].start == cue.start and out[-1].end == cue.end
