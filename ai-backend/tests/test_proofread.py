"""The LLM proofreading pass: batching, guards, cache, skip conditions."""

from __future__ import annotations

import json

import httpx

from tests.mock_openai import MockOpenAI
from utubot.captions.proofread import PROOFREAD_SYSTEM, Proofreader
from utubot.captions.stages import StageCache
from utubot.captions.types import Cue
from utubot.config import CaptionsConfig, Config, LLMTask
from utubot.db import Database
from utubot.llm import LLMClient

VID = "abcdefghijk"
CONTEXT = {"title": "A title", "description": "A description"}
CFG = CaptionsConfig()


def cues(*texts: str) -> list[Cue]:
    return [Cue(float(i) * 2.0, float(i) * 2.0 + 2.0, [text]) for i, text in enumerate(texts)]


def proofreader(mock_llm: MockOpenAI, cache: StageCache | None = None, **overrides) -> Proofreader:
    cfg = CaptionsConfig(**overrides)
    client = LLMClient(_llm_config(), transport=httpx.ASGITransport(app=mock_llm.app))
    return Proofreader(client, cfg, LLMTask(model="worker", max_tokens=2000), cache)


def _llm_config() -> Config:
    conf = Config()
    conf.llm.providers["default"].base_url = "http://mock/v1"
    return conf


def respond_with_cues(mock_llm, texts: list[str]) -> None:
    """Make the mock LLM answer each proofread request with the next `texts`, one per cue."""
    original = mock_llm.respond
    state = {"i": 0}

    def respond(body):
        if "proofread subtitle cues" in body["messages"][0]["content"]:
            asked = len(json.loads(body["messages"][-1]["content"])["cues"])
            out = texts[state["i"] : state["i"] + asked]
            state["i"] += asked
            return json.dumps(out)
        return original(body)

    mock_llm.respond = respond


def proofread_calls(mock_llm) -> int:
    return sum(
        1 for call in mock_llm.calls if "proofread subtitle cues" in call["messages"][0]["content"]
    )


async def test_proofread_corrects_cues_and_sends_the_context(mock_llm):
    respond_with_cues(mock_llm, ["Hello there, my friend.", "How are you today?"])
    out = await proofreader(mock_llm).polish(
        VID, cues("hello there my friend", "how are you today"), "English", CONTEXT
    )
    assert [cue.lines for cue in out] == [["Hello there, my friend."], ["How are you today?"]]
    assert out[0].start == 0.0 and out[0].end == 2.0
    call = mock_llm.calls[-1]
    assert "proofread subtitle cues" in call["messages"][0]["content"]
    body = json.loads(call["messages"][-1]["content"])
    assert body["video"] == CONTEXT
    assert body["cues"] == ["hello there my friend", "how are you today"]


async def test_proofread_batches_cues(mock_llm):
    respond_with_cues(mock_llm, ["One.", "Two.", "Four."])
    out = await proofreader(mock_llm, proofread_batch=2).polish(
        VID, cues("one", "two", "three"), "English", CONTEXT
    )
    assert [cue.lines for cue in out] == [["One."], ["Two."], ["Four."]]
    assert proofread_calls(mock_llm) == 2


async def test_proofread_keeps_the_original_when_the_text_shrinks_too_much(mock_llm):
    respond_with_cues(mock_llm, ["x"])
    out = await proofreader(mock_llm).polish(
        VID, cues("one fairly long cue text"), "English", CONTEXT
    )
    assert [cue.lines for cue in out] == [["one fairly long cue text"]]


async def test_proofread_re_splits_corrected_text_that_no_longer_fits_one_cue(mock_llm):
    long_text = " ".join(f"word{i}" for i in range(18))
    respond_with_cues(mock_llm, [long_text])
    out = await proofreader(mock_llm).polish(VID, cues(long_text), "English", CONTEXT)
    assert len(out) > 1
    for cue in out:
        assert len(cue.lines) <= CFG.max_lines
        assert all(len(line) <= CFG.max_chars_per_line for line in cue.lines)
    assert out[-1].end == 2.0
    for a, b in zip(out, out[1:], strict=False):
        assert a.end <= b.start + 1e-6


async def test_proofread_keeps_the_original_on_a_length_mismatch(mock_llm):
    respond_with_cues(mock_llm, ["only one answer"])
    out = await proofreader(mock_llm).polish(VID, cues("one", "two"), "English", CONTEXT)
    assert [cue.lines for cue in out] == [["one"], ["two"]]


async def test_proofread_keeps_the_original_when_the_text_grows_too_much(mock_llm):
    respond_with_cues(mock_llm, ["invented " * 12])
    out = await proofreader(mock_llm).polish(VID, cues("short"), "English", CONTEXT)
    assert [cue.lines for cue in out] == [["short"]]


async def test_proofread_survives_an_llm_failure(mock_llm):
    mock_llm.fail_status = 500
    out = await proofreader(mock_llm).polish(VID, cues("one"), "English", CONTEXT)
    assert [cue.lines for cue in out] == [["one"]]


async def test_proofread_skips_without_an_llm():
    out = await Proofreader(None, CaptionsConfig(), LLMTask(model="worker")).polish(
        VID, cues("one"), "English", CONTEXT
    )
    assert [cue.lines for cue in out] == [["one"]]


async def test_proofread_skips_when_off(mock_llm):
    out = await proofreader(mock_llm, proofread=False).polish(VID, cues("one"), "English", CONTEXT)
    assert [cue.lines for cue in out] == [["one"]]
    assert not mock_llm.calls


async def test_proofread_uses_the_stage_cache(mock_llm):
    cache = StageCache(Database(":memory:"))
    respond_with_cues(mock_llm, ["Fixed text."])
    pr = proofreader(mock_llm, cache)
    first = await pr.polish(VID, cues("original text"), "English", CONTEXT)
    assert [cue.lines for cue in first] == [["Fixed text."]]
    calls = proofread_calls(mock_llm)
    second = await pr.polish(VID, cues("original text"), "English", CONTEXT)
    assert [cue.lines for cue in second] == [["Fixed text."]]
    assert proofread_calls(mock_llm) == calls


async def test_proofread_cache_is_keyed_by_the_texts(mock_llm):
    cache = StageCache(Database(":memory:"))
    respond_with_cues(mock_llm, ["Fixed text."])
    pr = proofreader(mock_llm, cache)
    await pr.polish(VID, cues("original text"), "English", CONTEXT)
    await pr.polish(VID, cues("different text"), "English", CONTEXT)
    assert proofread_calls(mock_llm) == 2


def test_proofread_system_prompt_demands_the_same_cues():
    assert "same length and order" in PROOFREAD_SYSTEM
    assert "never merge, split, reorder" in PROOFREAD_SYSTEM
