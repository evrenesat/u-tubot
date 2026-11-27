"""The four-step build with a scripted model: critic repair, rendering, no network (plan 2.6)."""

from __future__ import annotations

import json

from tests import story_fixture as fx
from utubot import story

PARAMS = story.StoryParams()


def select_answer(keep_all=1, musts=(24,)):
    return {
        "threads": [{"id": "t1", "decision": "keep", "reason": "x"}],
        "beats": [{"id": i, "keep": 3 if i in musts else keep_all} for i in range(1, 25)],
    }


def critic(c, d, g, problems=()):
    return {"consistency": c, "density": d, "goal": g, "problems": list(problems)}


def run(select_fn, critic_fn):
    return story.run_selection(
        fx.story_map(),
        fx.units(),
        "Follow the story.",
        int(fx.DURATION_S * 0.5),
        fx.DURATION_S,
        select_fn,
        critic_fn,
        PARAMS,
        story.Recorder(),
    )


def test_accepted_first_round():
    res = run(fx.scripted(select_answer()), fx.scripted(critic(9, 8, 8)))
    assert res.passed and len(res.rounds) == 1 and res.checks["hard_ok"]
    assert [c.step for c in res.calls] == ["select", "critic"]


def test_critic_problem_is_repaired_by_adding_the_named_beat():
    problem = {"at_beat": 9, "type": "missing_cause", "note": "n", "add": [13], "drop": []}
    seen = []

    def critic_fn(messages):
        seen.append(messages)
        answer = critic(5, 7, 7, [problem]) if len(seen) == 1 else critic(9, 8, 8)
        return story.Reply(json.dumps(answer), 1, 1, 0.1)

    res = run(fx.scripted(select_answer()), critic_fn)
    assert len(res.rounds) == 2 and 13 in res.kept and 13 not in res.rounds[0].kept
    assert res.passed


def test_repair_stops_after_the_configured_rounds_and_keeps_the_best():
    answers = [critic(4, 5, 5), critic(6, 5, 5), critic(5, 5, 5)]
    n = []

    def critic_fn(messages):
        n.append(1)
        return story.Reply(json.dumps(answers[len(n) - 1]), 1, 1, 0.1)

    res = run(fx.scripted(select_answer()), critic_fn)
    assert len(res.rounds) == 3 and not res.passed and res.review["consistency"] == 6


def test_a_planted_missing_cause_is_not_possible_the_closure_adds_it():
    res = run(fx.scripted(select_answer(keep_all=0, musts=(24, 5))), fx.scripted(critic(9, 8, 8)))
    assert {2, 5} <= res.kept and res.checks["A1_closure_violations"] == 0


def test_renders_text_and_html_without_script_injection():
    res = run(fx.scripted(select_answer()), fx.scripted(critic(9, 8, 8)))
    res.smap.beats[0].what = "<script>x</script>"
    text = story.render_text(res, PARAMS, "m")
    page = story.render_html([("m", res)], PARAMS, "Paper cuts")
    assert "KEEP" in text and "&lt;script&gt;x" in page and "<script>x</script>" not in page


def test_skip_notes_follow_long_skips():
    smap = fx.story_map()
    smap.beats[5].weight = 5
    notes = story.skip_notes({1, 2, 24}, smap, PARAMS)
    assert 24 in notes and "Event 6" in notes[24]
