"""Story map validation: tiling, needs point backwards, one repair round (plan 2.3, 2.4)."""

from __future__ import annotations

import copy

import pytest

from tests import story_fixture as fx
from utubot import story

PARAMS = story.StoryParams()


def read(fn):
    return story.read_film(
        fx.units(), {"title": "T", "duration_s": fx.DURATION_S}, [], fn, PARAMS, story.Recorder()
    )


def test_read_builds_beats_with_ids_and_times():
    smap = read(fx.scripted(fx.read_answer()))
    assert len(smap.beats) == fx.BEATS
    assert [b.id for b in smap.beats] == list(range(1, fx.BEATS + 1))
    assert smap.beats[1].start == fx.BEAT_S and smap.beats[1].end == 2 * fx.BEAT_S - 1.0
    assert smap.cast[0]["name"] == "Mara"


def test_gap_is_sent_back_once_and_repaired():
    bad = fx.read_answer()
    bad["scenes"][0]["beats"][0]["to"] = 2  # leaves unit 3 uncovered
    seen = []

    def fn(messages):
        seen.append(messages)
        return fx.scripted(bad if len(seen) == 1 else fx.read_answer())(messages)

    smap = read(fn)
    assert len(seen) == 2 and "rejected" in seen[1][-1]["content"]
    assert len(smap.beats) == fx.BEATS and not smap.notes


def test_still_broken_after_repair_is_snapped_and_noted():
    bad = fx.read_answer()
    bad["scenes"][0]["beats"][0]["to"] = 2
    smap = read(fx.scripted(bad))
    assert smap.notes and "closed by code" in smap.notes[0]
    assert smap.beats[0].last == 3 or smap.beats[1].first == 3


def test_not_json_is_a_format_error_after_the_repair():
    with pytest.raises(story.StoryFormatError):
        read(fx.scripted("no json here"))


def test_long_beat_splits_at_the_largest_pause():
    us = fx.units()
    for u in us[10:]:
        u.start += 100
        u.end += 100  # a 100 s pause after unit 10
    one = story.Beat(1, 1, 1, 30, us[0].start, us[29].end, "Everything")
    by_id = {u.n: u for u in us}
    out = story.split_long([one], by_id, [u.n for u in us], story.StoryParams(beat_max_s=240))
    assert len(out) == 2 and out[0].last == 10 and out[1].first == 11
    assert out[1].what.endswith("(cont.)")


def test_music_units_are_marked_not_numbered_for_selection():
    us = fx.units()
    us[4].text = "[müzik]"
    lines = story.story_lines(us, PARAMS)
    assert "--- music ---" in lines and len(story.selectable(us)) == len(us) - 1


def test_pause_marks():
    us = fx.units()
    for u in us[5:]:
        u.start += 14
        u.end += 14
    assert any(line.startswith("--- pause 15") for line in story.story_lines(us, PARAMS))


def smap_plain():
    smap = fx.story_map()
    return smap


def test_link_needs_must_point_backwards_and_are_repaired():
    smap = smap_plain()
    bad = fx.link_answer()
    bad["beats"][4]["needs"] = [9]  # beat 5 needs a later beat
    calls = []

    def fn(messages):
        calls.append(1)
        return fx.scripted(bad if len(calls) == 1 else fx.link_answer())(messages)

    story.link_film(smap, fn, PARAMS, story.Recorder())
    assert len(calls) == 2 and smap.beats[4].needs == [2]


def test_payoff_without_needs_is_named_in_the_repair_then_accepted():
    smap = smap_plain()
    bad = copy.deepcopy(fx.link_answer())
    bad["beats"][4]["needs"] = []  # beat 5 is a payoff
    seen = []

    def fn(messages):
        seen.append(messages)
        return fx.scripted(bad)(messages)

    story.link_film(smap, fn, PARAMS, story.Recorder())
    assert len(seen) == 2 and "beat 5" in seen[1][-1]["content"]
    assert smap.notes and smap.beats[4].needs == []


def test_max_needs_is_capped():
    smap = smap_plain()
    ans = fx.link_answer()
    ans["beats"][22]["needs"] = [1, 2, 3, 4, 5, 6]
    story.apply_link(smap, story.parse_link(ans, smap, PARAMS, strict=False), PARAMS)
    assert len(smap.beats[22].needs) == PARAMS.max_needs


def test_link_needs_an_ending():
    smap = smap_plain()
    ans = fx.link_answer()
    ans["ending"] = []
    with pytest.raises(story.StoryFormatError):
        story.parse_link(ans, smap, PARAMS, strict=False)
