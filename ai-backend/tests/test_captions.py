from __future__ import annotations

import asyncio
import json
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


async def test_translation_skips_source_proofreading(env):
    from tests.test_proofread import proofread_calls, respond_with_cues
    from utubot.captions import events
    from utubot.captions.events import JobEvents, JobTrace
    from utubot.captions.types import Cue

    respond_with_cues(env.llm, ["Hello, world."])
    log = JobEvents(env.svc.db, env.svc.jobs.pipeline.cfg.captions)
    token = events.bind(JobTrace("jt", log))
    try:
        await env.svc.jobs.pipeline._finish(
            VID, [Cue(0, 2, ["merhaba dunya"], None)], "tr", "en", lambda _f: None
        )
    finally:
        events.unbind(token)
    skipped = next(
        e for e in log.list("jt") if e["stage"] == "proofread" and e["status"] == "skipped"
    )
    assert skipped["detail"]["reason"] == "translated"
    assert proofread_calls(env.llm) == 1  # only the translated text is proofread


async def test_source_cues_are_proofread_without_translation(env):
    from tests.test_proofread import proofread_calls, respond_with_cues
    from utubot.captions.types import Cue

    respond_with_cues(env.llm, ["Hello, world."])
    track = await env.svc.jobs.pipeline._finish(
        VID, [Cue(0, 2, ["hello world"], None)], "en", None, lambda _f: None
    )
    assert track == "en" and proofread_calls(env.llm) == 1
    row = env.svc.db.one("SELECT vtt FROM captions WHERE video_id=?", [VID])
    assert "Hello, world." in row["vtt"]


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


async def test_legacy_mode_keeps_the_old_overflow_output(env):
    from tests.test_proofread import proofreader, respond_with_cues
    from utubot.captions.types import Cue

    text = "one two three four five six seven eight"
    cue = _spoken_cue(text)
    cue = Cue(cue.start, cue.end, [text], words=cue.words)
    cfg = env.svc.jobs.pipeline.cfg.captions
    cfg.timing_mode = "legacy"
    cfg.max_chars_per_line, cfg.max_lines = 20, 1
    out = await env.svc.jobs.pipeline.translate([cue], "tr")
    assert [(c.start, c.end, c.lines) for c in out] == [
        (cue.start, cue.end, ["T:one two three four five six seven eight"])
    ]
    assert out[0].words is None
    respond_with_cues(env.llm, ["One two three four five six seven eight."])
    polished = await proofreader(
        env.llm, timing_mode="legacy", max_chars_per_line=20, max_lines=1
    ).polish(VID, [cue], "English", {})
    old = retime_split("One two three four five six seven eight.", cue.start, cue.end, cfg)
    assert [(c.start, c.end, c.lines) for c in polished] == [(c.start, c.end, c.lines) for c in old]
    assert all(c.words is None for c in polished)


def test_split_cue_stretches_a_short_last_piece_up_to_the_next_cue():
    from utubot.captions.segment import SplitStats, split_cue
    from utubot.captions.types import Cue, Word

    words = [
        Word(i * 0.4, i * 0.4 + 0.2, w) for i, w in enumerate("aaaaaa bbbbbb cccccc dd".split())
    ]
    cue = Cue(0.0, 1.4, ["aaaaaa bbbbbb cccccc dd"], words=words)
    cfg = _tight_cfg()
    text = "aaaaaa bbbbbb cccccc dd"
    open_end = split_cue(cue, text, cfg, SplitStats())
    capped = split_cue(cue, text, cfg, SplitStats(), room_end=1.6)
    assert open_end[-1].end == cue.end
    assert capped[-1].end == 1.6 and capped[-1].end - capped[-1].start < cfg.min_cue_s


def test_caption_row_splits_are_not_char_timed():
    from utubot.captions.align import caption_cues

    cues = caption_cues([(0.0, 6.0, " ".join(f"word{i}" for i in range(30)))], CFG)
    assert len(cues) > 1 and not any(c.char_timed for c in cues)


def test_split_cue_pieces_stay_inside_the_cue():
    from utubot.captions.segment import SplitStats, split_cue
    from utubot.captions.types import Cue, Word

    names = "aaaaaa bbbbbb cccccc dddddd eeeeee ffffff".split()
    words = [Word(i * 0.4, i * 0.4 + 0.3, w) for i, w in enumerate(names)]
    cue = Cue(0.0, 1.0, [" ".join(names)], words=words)  # ends before its last words
    cfg = _tight_cfg()
    pieces = split_cue(cue, " ".join(names), cfg, SplitStats())
    assert len(pieces) == 2
    for piece in pieces:
        assert cue.start <= piece.start and piece.end <= cue.end
        assert piece.end - piece.start >= cfg.word_min_s
    assert all(a.start < b.start for a, b in zip(pieces, pieces[1:], strict=False))
    tiny = Cue(0.0, 0.05, cue.lines, words=words)
    spread = split_cue(tiny, " ".join(names), cfg, SplitStats())
    assert all(0.0 <= p.start < p.end <= 0.05 for p in spread)


def test_exact_split_needs_the_same_tokens_not_just_the_count():
    from utubot.captions.segment import SplitStats, split_cue, tokens_match

    cue = _spoken_cue("alpha beta gamma delta epsilon zeta eta theta")
    assert tokens_match("Alpha, beta gamma delta epsilon zeta eta theta.", cue.words)
    changed = "Alpha beta gamma delta epsilon zeta eta thetas"  # same count, one token changed
    changed = changed.replace("thetas", "iota")
    assert not tokens_match(changed, cue.words)
    stats = SplitStats()
    pieces = split_cue(cue, changed + " kappa lambda", _tight_cfg(), stats)
    assert stats.exact == 0 and stats.at_pause == 1
    assert not any(p.words_match_text for p in pieces)
    same_count = SplitStats()
    split_cue(cue, changed, _tight_cfg(), same_count)
    assert same_count.exact == 0 and same_count.at_pause == 1


async def test_proofread_that_changes_tokens_stops_exact_matching(env):
    from tests.test_proofread import proofreader, respond_with_cues
    from utubot.captions.types import Cue

    text = "alpha beta gamma delta"
    cue = _spoken_cue(text)
    cue = Cue(cue.start, cue.end, [text], words=cue.words)
    respond_with_cues(env.llm, ["Alpha beta gamma delta iota"])
    out = await proofreader(env.llm).polish(VID, [cue], "English", {})
    assert out[0].words is cue.words and not out[0].words_match_text
    respond_with_cues(env.llm, ["Alpha, beta gamma delta."])
    out = await proofreader(env.llm).polish(VID, [cue], "English", {})
    assert out[0].words_match_text


async def test_legacy_proofread_counts_character_timed_overflow(env):
    from tests.test_proofread import proofreader, respond_with_cues
    from utubot.captions import events
    from utubot.captions.events import JobEvents, JobTrace
    from utubot.captions.types import Cue

    text = "one two three four five six seven eight"
    cue = _spoken_cue(text)
    cue = Cue(cue.start, cue.end, [text], words=cue.words)
    respond_with_cues(env.llm, ["One two three four five six seven eight."])
    pr = proofreader(env.llm, timing_mode="legacy", max_chars_per_line=20, max_lines=1)
    log = JobEvents(env.svc.db, pr.cfg)
    token = events.bind(JobTrace("jl", log))
    try:
        await pr.polish(VID, [cue], "English", {})
    finally:
        events.unbind(token)
    detail = [e for e in log.list("jl") if e["stage"] == "proofread"][-1]["detail"]
    assert detail["split_by_chars"] == 1 and detail["split_exact"] == 0


def _translate_with(env, behave):
    """Route translate requests through `behave(texts, strict) -> list | str`; others stay as they are."""
    import json

    original = env.llm.respond
    seen: list[tuple[list[str], bool]] = []

    def respond(body):
        if "Translate each subtitle" not in body["messages"][0]["content"]:
            return original(body)
        strict = "Return exactly" in body["messages"][-1]["content"]
        raw = body["messages"][-1]["content"]
        texts = json.loads(raw.split("\n", 1)[1] if strict else raw)
        seen.append((texts, strict))
        out = behave(texts, strict)
        return out if isinstance(out, str) else json.dumps(out)

    env.llm.respond = respond
    return seen


def _plain_cues(n):
    from utubot.captions.types import Cue

    return [Cue(i, i + 1, [f"c{i}"], None) for i in range(n)]


async def _translated(env, cues):
    from utubot.captions import events
    from utubot.captions.events import JobEvents, JobTrace

    log = JobEvents(env.svc.db, env.svc.jobs.pipeline.cfg.captions)
    token = events.bind(JobTrace("jt", log))
    try:
        await env.svc.jobs.pipeline._finish(VID, cues, "tr", "en", lambda _f: None)
    finally:
        events.unbind(token)
    return [e for e in log.list("jt") if e["stage"] == "translate"][-1]


async def test_translate_batch_one_short_then_right_on_retry(env):
    def behave(texts, strict):
        return [f"T:{t}" for t in texts] if strict else [f"T:{t}" for t in texts[:-1]]

    seen = _translate_with(env, behave)
    ev = await _translated(env, _plain_cues(5))
    assert ev["status"] == "ok"
    assert (ev["detail"]["batches"], ev["detail"]["retried"]) == (1, 1)
    assert (ev["detail"]["split"], ev["detail"]["untranslated"]) == (0, 0)
    assert [strict for _t, strict in seen] == [False, True]
    assert "T:c4" in env.svc.db.one("SELECT vtt FROM captions WHERE video_id=?", [VID])["vtt"]


async def test_translate_batch_that_keeps_mismatching_is_split(env):
    def behave(texts, _strict):
        return [f"T:{t}" for t in texts] if len(texts) <= 3 else ["only one"]

    _translate_with(env, behave)
    ev = await _translated(env, _plain_cues(6))
    assert ev["status"] == "ok"
    assert ev["detail"]["split"] == 1 and ev["detail"]["untranslated"] == 0
    vtt = env.svc.db.one("SELECT vtt FROM captions WHERE video_id=?", [VID])["vtt"]
    assert all(f"T:c{i}" in vtt for i in range(6))


async def test_translate_single_failing_cue_keeps_source_and_warns(env):
    def behave(texts, _strict):
        return [] if "c3" in texts else [f"T:{t}" for t in texts]

    _translate_with(env, behave)
    ev = await _translated(env, _plain_cues(20))
    assert ev["status"] == "warn" and ev["detail"]["untranslated"] == 1
    vtt = env.svc.db.one("SELECT vtt FROM captions WHERE video_id=?", [VID])["vtt"]
    assert "T:c2" in vtt and "T:c3" not in vtt and "c3" in vtt


async def test_translate_fails_above_the_untranslated_share(env):
    from utubot.captions.pipeline import PipelineError

    _translate_with(env, lambda texts, _strict: [])
    with pytest.raises(PipelineError, match="translation length mismatch"):
        await env.svc.jobs.pipeline.translate(_plain_cues(4), "en")


async def test_translate_fails_fast_when_the_model_always_fails(env):
    from utubot.captions.pipeline import PipelineError

    seen = _translate_with(env, lambda texts, _strict: [])
    with pytest.raises(PipelineError, match="translation length mismatch"):
        await env.svc.jobs.pipeline.translate(_plain_cues(100), "en")
    assert (
        len(seen) < 60
    )  # 11 single cues over the 10% share, not ~2 calls per cue of the whole job


async def test_translate_empty_item_counts_as_failed(env):
    def behave(texts, _strict):
        return [f"T:{t}" if len(texts) == 1 else "" for t in texts]

    _translate_with(env, behave)
    ev = await _translated(env, _plain_cues(3))
    assert ev["detail"]["split"] >= 1 and ev["detail"]["untranslated"] == 0


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg missing")
async def test_forced_caption_job_skips_stored_youtube_captions(env):
    env.svc.db.execute(
        "INSERT INTO transcripts(video_id,lang,source,text,fetched_at,segments)"
        " VALUES(?,?,?,?,?,?)",
        [
            VID,
            "en",
            "youtube_captions",
            "YouTube words here.",
            time.time(),
            json.dumps([[0.0, 1.0, "YouTube words here."]]),
        ],
    )
    env.svc.db.execute(
        "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at) VALUES(?,?,?,?,?,?)",
        [
            VID,
            "en",
            "English (YouTube)",
            1,
            "WEBVTT\n\n1\n00:00:00.000 --> 00:00:01.000\nYouTube words here.\n",
            time.time(),
        ],
    )
    assert (
        env.svc.db.one("SELECT source FROM transcripts WHERE video_id=?", [VID])["source"]
        == "youtube_captions"
    )

    started = await env.client.post(
        f"/v1/videos/{VID}/captions", json={"lang": "auto", "force": True}
    )
    assert started.json()["status"] == "queued"
    job_id = started.json()["job_id"]
    assert env.svc.db.one("SELECT force FROM jobs WHERE id=?", [job_id])["force"] == 1
    body = await wait_status(env.client, {"ready", "failed"})
    assert body["status"] == "ready", body
    assert not env.fetcher.calls
    vtt = (await env.client.get(body["tracks"][0]["url"])).text
    assert "Hello there." in vtt and "YouTube words here" not in vtt
    assert env.svc.db.one("SELECT COUNT(*) AS n FROM captions WHERE video_id=?", [VID])["n"] == 1


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg missing")
async def test_force_set_while_a_caption_job_runs_wins(env):
    queue = env.svc.jobs

    async def improve(*args, **kwargs):
        raise AssertionError("the forced job must not improve YouTube captions")

    original = queue._recheck_for_captions

    async def recheck_then_force(video_id, priority):
        found = await original(video_id, priority)
        queue.db.execute("UPDATE jobs SET force=1 WHERE status='running'")
        return found

    queue.pipeline.improve = improve
    queue._recheck_for_captions = recheck_then_force
    started = await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})
    assert started.json()["status"] == "queued"
    body = await wait_status(env.client, {"ready", "failed"})
    assert body["status"] == "ready", body
    assert env.llm.audio_calls


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg missing")
async def test_non_english_automatic_captions_are_rebuilt_from_the_audio(env):
    from utubot.transcripts import CAPTION_AUTO

    env.fetcher.lang = "hi"
    env.fetcher.text = "नमस्ते दोस्त"
    env.fetcher.segments = [(0.0, 1.0, "नमस्ते दोस्त")]
    env.fetcher.caption_kind = CAPTION_AUTO
    queue = env.svc.jobs

    async def improve(*args, **kwargs):
        raise AssertionError("non-English automatic captions must not be improved as text")

    queue.pipeline.improve = improve
    started = await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})
    assert started.json()["status"] == "queued"
    body = await wait_status(env.client, {"ready", "failed"})
    assert body["status"] == "ready", body
    assert env.llm.audio_calls


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg missing")
async def test_the_release_gate_must_attest_before_a_track_is_stored(env, tmp_path):
    from utubot.captions.gate import GATE_VERSION, write_attestation

    attestation = tmp_path / "gate.json"
    env.cfg.captions.gate_required = True
    env.cfg.captions.gate_attestation = str(attestation)
    started = await env.client.post(f"/v1/videos/{VID}/captions", json={"lang": "auto"})
    assert started.json()["status"] == "queued"
    job_id = started.json()["job_id"]
    body = await wait_status(env.client, {"ready", "failed"})
    assert body["status"] == "failed"
    failed = env.svc.db.one(
        "SELECT detail FROM job_events WHERE job_id=? AND status='failed' ORDER BY id DESC LIMIT 1",
        [job_id],
    )
    assert "release gate has not passed" in json.loads(failed["detail"])["technical"]
    row = env.svc.db.one("SELECT COUNT(*) AS n FROM captions WHERE video_id=?", [VID])
    assert row["n"] == 0

    write_attestation(attestation, {"version": GATE_VERSION, "passed": True, "failures": []})
    started = await env.client.post(
        f"/v1/videos/{VID}/captions", json={"lang": "auto", "force": True}
    )
    assert started.json()["status"] == "queued"
    body = await wait_status(env.client, {"ready", "failed"})
    assert body["status"] == "ready", body
    row = env.svc.db.one("SELECT COUNT(*) AS n FROM captions WHERE video_id=?", [VID])
    assert row["n"] == 1
