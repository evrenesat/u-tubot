"""A model that ranks (almost) the whole video instead of choosing (GitHub #255): the answer is
detected, asked again once, and a trim that is still needed is spread over the video."""

from __future__ import annotations

import copy

import pytest

from tests.test_cuts_api import post_cut, set_transcript, wait_ready
from utubot.config import CutsConfig, LLMTask
from utubot.cuts import (
    Unit,
    choose_problem,
    is_non_selection,
    parse_cut_answer,
    ranked_tail_in_time_order,
    select_for_target,
    trim_to_cap,
)

CFG = CutsConfig()
UNIT_S = 10
FILM_S = 4889
PARTS = 38
HEAD = 19
TARGET_S = FILM_S // 2


def film_units() -> list[Unit]:
    count = FILM_S // UNIT_S
    return [Unit(n, (n - 1) * UNIT_S, n * UNIT_S, f"unit {n}") for n in range(1, count + 1)]


def half_cut_answer(units: list[Unit]) -> dict:
    """Shaped like half cut 675edfafa45f: 38 scenes covering about 90% of the film, the first 19
    ranks scattered, ranks 20-38 simply in film order."""
    stride = len(units) // PARTS
    spans = [(i * stride + 1, i * stride + stride - 1) for i in range(PARTS)]
    scattered = [(i * 7) % HEAD + 1 for i in range(HEAD)]
    ranks = scattered + list(range(HEAD + 1, PARTS + 1))
    return {
        "parts": [
            {"from": a, "to": b, "label": f"scene {i}", "rank": r}
            for i, ((a, b), r) in enumerate(zip(spans, ranks, strict=True))
        ],
        "summary": "s",
    }


def quarter_shares(chosen, kept_ms_total=FILM_S * 1000):
    shares = []
    for q in range(4):
        lo, hi = q * kept_ms_total / 4, (q + 1) * kept_ms_total / 4
        kept = sum(max(0, min(p.end_ms, hi) - max(p.start_ms, lo)) for p in chosen)
        shares.append(kept / (hi - lo))
    return shares


def test_the_half_cut_shape_is_a_non_selection():
    units = film_units()
    parts = parse_cut_answer(half_cut_answer(units), units)
    assert ranked_tail_in_time_order(parts) >= PARTS - HEAD
    assert is_non_selection(parts, CFG, TARGET_S, FILM_S)
    assert "Choose about 2444 s" in choose_problem(parts, CFG, TARGET_S, FILM_S)


def test_a_real_choice_is_not_flagged():
    units = film_units()
    answer = half_cut_answer(units)
    keep = answer["parts"][::2]
    for i, part in enumerate(keep):
        part["rank"] = (i * 5) % len(keep) + 1
    parts = parse_cut_answer({"parts": keep}, units)
    assert not is_non_selection(parts, CFG, TARGET_S, FILM_S)
    assert choose_problem(parts, CFG, TARGET_S, FILM_S) is None


def test_the_trim_no_longer_drops_the_end_of_the_film():
    units = film_units()
    parts = parse_cut_answer(half_cut_answer(units), units)
    chosen, total = select_for_target(parts, units, CFG, TARGET_S, FILM_S)
    assert 0.85 * TARGET_S <= total <= 1.15 * TARGET_S
    assert [p.start_ms for p in chosen] == sorted(p.start_ms for p in chosen)
    first, last = chosen[0], chosen[-1]
    assert first.start_ms < 0.1 * FILM_S * 1000
    assert last.end_ms > 0.9 * FILM_S * 1000
    shares = quarter_shares(chosen)
    assert max(shares) - min(shares) < 0.25, shares
    gaps = [(b.start_ms - a.end_ms) / 1000 for a, b in zip(chosen, chosen[1:], strict=False)]
    assert max(gaps) <= CFG.max_skip_s


def test_max_skip_is_configurable():
    units = film_units()
    parts = parse_cut_answer(half_cut_answer(units), units)
    tight = CutsConfig(max_skip_s=200.0)
    chosen, _ = select_for_target(parts, units, tight, TARGET_S, FILM_S)
    gaps = [(b.start_ms - a.end_ms) / 1000 for a, b in zip(chosen, chosen[1:], strict=False)]
    assert max(gaps) <= 200.0


def test_a_cap_trim_spreads_too():
    units = film_units()
    parts = parse_cut_answer(half_cut_answer(units), units)
    chosen = trim_to_cap(parts, units, CFG, TARGET_S)
    assert chosen[-1].end_ms > 0.9 * FILM_S * 1000
    assert sum(p.end_ms - p.start_ms for p in chosen) / 1000 <= TARGET_S * 1.15


@pytest.fixture
async def cuts_env(env):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.cuts.poll_s = 0.02
    env.cfg.cuts.transcript_wait_s = 60.0
    env.cfg.cuts.default_wait_ms = 0
    env.cfg.captions.job_poll_s = 0.02
    return env


def small_answer() -> dict:
    """The half cut's shape on a 2500 s video of 5 s units: 20 scenes, 5 unit gaps."""
    units = [Unit(n, (n - 1) * 5.0, n * 5.0, "u") for n in range(1, 501)]
    answer = half_cut_answer_for(units, parts=20, head=5)
    return answer


def half_cut_answer_for(units, *, parts: int, head: int) -> dict:
    stride = len(units) // parts
    ranks = [(i * 3) % head + 1 for i in range(head)] + list(range(head + 1, parts + 1))
    return {
        "parts": [
            {"from": i * stride + 1, "to": i * stride + stride - 5, "label": f"s{i}", "rank": r}
            for i, r in enumerate(ranks)
        ],
        "summary": "s",
    }


class TestInTheBuild:
    async def test_a_non_selection_is_asked_again_once_to_choose(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=500)  # 2500 s
        chosen_answer = copy.deepcopy(small_answer())
        chosen_answer["parts"] = [
            {**p, "rank": (i * 5) % 13 + 1} for i, p in enumerate(chosen_answer["parts"][:13])
        ]
        cuts_env.llm.cut_answers = [small_answer(), chosen_answer]
        r = await post_cut(cuts_env, prompt="make it half as long")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc
        assert len(cuts_env.llm.cut_calls) == 2
        assert "Choose about 1250 s" in cuts_env.llm.cut_followups[1]
        assert 1062 <= doc["cut"]["kept_s"] <= 1438

    async def test_a_second_non_selection_is_spread_not_cut_at_the_end(self, cuts_env):
        cuts_env.cfg.cuts.max_skip_s = 400.0
        set_transcript(cuts_env.fetcher, n=500)
        cuts_env.llm.cut_answer = small_answer()
        r = await post_cut(cuts_env, prompt="make it half as long")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc
        assert len(cuts_env.llm.cut_calls) == 2
        cut = doc["cut"]
        assert 1062 <= cut["kept_s"] <= 1438
        skips = cut["skip_ranges_ms"] if "skip_ranges_ms" in cut else cut["skips"]
        assert max(b - a for a, b in skips) / 1000 <= 400 + 100
        assert skips[-1][0] > 2500 * 1000 * 0.85

    async def test_a_normal_answer_is_asked_once(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=500)
        answer = small_answer()
        answer["parts"] = [
            {**p, "rank": (i * 3) % 13 + 1} for i, p in enumerate(answer["parts"][:13])
        ]
        cuts_env.llm.cut_answer = answer
        r = await post_cut(cuts_env, prompt="make it half as long")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc
        assert len(cuts_env.llm.cut_calls) == 1


class TestMapReduce:
    async def test_excerpts_and_the_reduce_are_asked_again_to_choose(self, cuts_env):
        from tests.test_cuts_longvideo import three_hours

        model = three_hours(cuts_env)
        cuts_env.cfg.cuts.non_selection_factor = CutsConfig().non_selection_factor
        cuts_env.cfg.cuts.rank_tail_min = CutsConfig().rank_tail_min
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        doc = await wait_ready(cuts_env, r.json()["request_id"], wait_ms=20000)
        assert doc["state"] == "ready", doc
        assert len(model.reduces) == 2
        assert sum(1 for i, _, _ in model.maps if i == 1) == 2
        asked = [f for f in cuts_env.llm.cut_followups if f]
        assert asked and all("Choose about" in f for f in asked)
        assert 255 <= doc["cut"]["kept_s"] <= 345
