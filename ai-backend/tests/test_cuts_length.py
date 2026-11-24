"""Length of saved presets and typed prompts (issue 100): the parser, the explicit length and the
target band applied to a cut that has no built-in target."""

from __future__ import annotations

import pytest

from tests.test_cuts_api import post_cut, set_transcript, wait_ready
from utubot.config import CutsConfig, LLMTask
from utubot.cuts import LENGTH_FRACTION, LENGTH_SECONDS, effective_target_s, parse_length_intent


@pytest.fixture
async def cuts_env(env):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.cuts.poll_s = 0.02
    env.cfg.cuts.transcript_wait_s = 60.0
    env.cfg.cuts.default_wait_ms = 0
    env.cfg.captions.job_poll_s = 0.02
    return env


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("make it half as long", (LENGTH_FRACTION, 0.5)),
        ("half", (LENGTH_FRACTION, 0.5)),
        ("shorter by half", (LENGTH_FRACTION, 0.5)),
        ("keep a third", (LENGTH_FRACTION, 0.3333)),
        ("a quarter of it", (LENGTH_FRACTION, 0.25)),
        ("shorten it by a third", (LENGTH_FRACTION, 0.6667)),
        ("30%", (LENGTH_FRACTION, 0.3)),
        ("keep 40 percent", (LENGTH_FRACTION, 0.4)),
        ("trim it by 25%", (LENGTH_FRACTION, 0.75)),
        ("10 minutes", (LENGTH_SECONDS, 600.0)),
        ("about 7.5 min please", (LENGTH_SECONDS, 450.0)),
        ("under 12 minutes", (LENGTH_SECONDS, 720.0)),
        ("a 5-minute version", (LENGTH_SECONDS, 300.0)),
        ("half an hour", (LENGTH_SECONDS, 1800.0)),
    ],
)
def test_parse_length_intent(text, want):
    assert parse_length_intent(text) == want


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Keep only the dessert.",
        "keep the first half",
        "only the second half and the last third",
        "skip the first 5 minutes",
        "keep the first 5 minutes",
        "half and 10 minutes",
        "10 minutes or 20 minutes",
        "remove the intro at 3 minutes",
    ],
)
def test_ambiguous_text_has_no_length(text):
    assert parse_length_intent(text) is None


def test_effective_target_uses_the_band_and_the_duration():
    cfg = CutsConfig()
    half = (LENGTH_FRACTION, 0.5)
    assert effective_target_s(cfg, None, 4960, half) == 2480
    assert effective_target_s(cfg, None, None, half) is None
    assert effective_target_s(cfg, None, 4960, None) is None
    assert effective_target_s(cfg, None, 500, (LENGTH_SECONDS, 600)) is None  # already short
    assert effective_target_s(cfg, "cut-highlights-5", 4960, half) == 300  # built-in wins


def ranked_parts(units_per_part: int = 10, count: int = 20):
    return {
        "parts": [
            {
                "from": i * units_per_part + 1,
                "to": (i + 1) * units_per_part,
                "label": f"P{i}",
                "rank": count - i,
            }
            for i in range(count)
        ],
        "summary": "s",
    }


class TestLengthInCuts:
    async def test_half_in_a_typed_prompt_lands_in_the_band(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=200)  # 1000 s
        cuts_env.llm.cut_answer = ranked_parts()
        r = await post_cut(cuts_env, prompt="make it half as long")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc
        cut = doc["cut"]
        assert cut["target_s"] == 500
        assert 425 <= cut["kept_s"] <= 575
        assert "Target length: 500 s" in cuts_env.llm.cut_calls[0]

    async def test_minutes_and_percent(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=200)
        cuts_env.llm.cut_answer = ranked_parts()
        r = await post_cut(cuts_env, prompt="about 10 minutes")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["cut"]["target_s"] == 600 and 510 <= doc["cut"]["kept_s"] <= 690
        r = await post_cut(cuts_env, prompt="keep 30%")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["cut"]["target_s"] == 300 and 255 <= doc["cut"]["kept_s"] <= 345

    async def test_no_length_words_keeps_todays_behaviour(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=200)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 6, "label": "A"}, {"from": 20, "to": 120, "label": "B"}],
            "summary": "s",
        }
        r = await post_cut(cuts_env, prompt="Keep the intro and the demo")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready" and doc["cut"]["target_s"] is None
        assert "Target length" not in cuts_env.llm.cut_calls[0]

    async def test_saved_preset_length_wins_over_text(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=200)
        cuts_env.llm.cut_answer = ranked_parts()
        saved = await cuts_env.client.post(
            "/v1/cut-presets",
            json={"label": "Short", "prompt": "make it half as long", "length_min": 5},
        )
        assert saved.status_code == 200, saved.text
        preset = saved.json()["preset"]
        assert preset["length_min"] == 5
        r = await post_cut(cuts_env, preset=preset["id"])
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc
        assert doc["cut"]["target_s"] == 300 and 255 <= doc["cut"]["kept_s"] <= 345

    async def test_saved_preset_reads_the_text_and_fraction(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=200)
        cuts_env.llm.cut_answer = ranked_parts()
        text = (
            await cuts_env.client.post("/v1/cut-presets", json={"label": "Half", "prompt": "half"})
        ).json()["preset"]
        assert "length_min" not in text and "length_frac" not in text
        r = await post_cut(cuts_env, preset=text["id"])
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["cut"]["target_s"] == 500
        frac = (
            await cuts_env.client.post(
                "/v1/cut-presets",
                json={"label": "Quarter", "prompt": "half", "length_frac": 0.25},
            )
        ).json()["preset"]
        assert frac["length_frac"] == 0.25
        r = await post_cut(cuts_env, preset=frac["id"])
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["cut"]["target_s"] == 250

    async def test_picker_shows_a_targeted_cut_as_ready(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=200)
        cuts_env.llm.cut_answer = ranked_parts()
        preset = (
            await cuts_env.client.post("/v1/cut-presets", json={"label": "Half", "prompt": "half"})
        ).json()["preset"]
        r = await post_cut(cuts_env, preset=preset["id"])
        await wait_ready(cuts_env, r.json()["request_id"])
        listing = (await cuts_env.client.get("/v1/videos/abcdefghijk/cuts")).json()
        entry = next(p for p in listing["presets"] if p["id"] == preset["id"])
        assert entry["state"] == "ready" and entry["cut"]["target_s"] == 500

    async def test_bad_lengths_are_refused(self, cuts_env):
        for extra in (
            {"length_min": 0},
            {"length_frac": 0.99},
            {"length_min": 5, "length_frac": 0.5},
        ):
            r = await cuts_env.client.post(
                "/v1/cut-presets", json={"label": "X", "prompt": "Keep it", **extra}
            )
            if extra == {"length_min": 0}:
                assert r.status_code == 200  # zero means no length
            else:
                assert r.status_code == 400, extra
