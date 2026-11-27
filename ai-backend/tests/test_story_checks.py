"""Checks A1 to A8 and the pair score (plan 2.8, 1.3)."""

from __future__ import annotations

from tests import story_fixture as fx
from utubot import story

PARAMS = story.StoryParams()


def checks(kept, target=fx.DURATION_S * 0.5):
    return story.run_checks(set(kept), fx.story_map(), target, fx.DURATION_S, PARAMS)


def test_a1_counts_missing_causes():
    c = checks({5, 20, 24, 23, 17, 14, 11, 8, 3})  # 5 without 2
    assert c["A1_closure_violations"] == 1 and not c["hard_ok"]


def test_a2_needs_the_ending_and_its_closure():
    c = checks(set(range(1, 24)))  # ending beat 24 missing
    assert c["A2_ending_kept"] is False and not c["hard_ok"]


def test_a3_length_band():
    smap = fx.story_map()
    everything = set(range(1, 25))
    assert (
        story.run_checks(everything, smap, fx.DURATION_S * 0.5, fx.DURATION_S, PARAMS)[
            "A3_length_in_band"
        ]
        is False
    )
    assert story.run_checks(
        everything, smap, fx.DURATION_S * 0.5, fx.DURATION_S, PARAMS, over_target=True
    )["A3_length_in_band"]


def test_a4_a5_a6_a7_report_numbers():
    kept = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 24, 23, 20, 17, 14}
    c = checks(kept)
    assert c["A4_quarter_shares"][0] == 1.0 and c["A4_quarter_shares"][3] <= 0.5
    assert c["A5_longest_skip_s"] == 2 * fx.BEAT_S  # beats 15 and 16
    assert c["A6_dangling_setups"] == 0
    assert c["A7_weight_ratio"] > 0


def test_a6_counts_setups_nobody_needs():
    smap = fx.story_map()
    smap.beats[0].kind = "setup"  # beat 1 is nobody's need
    c = story.run_checks({1, 24, 23, 20, 17, 14, 11, 8, 5, 3, 2}, smap, None, fx.DURATION_S, PARAMS)
    assert c["A6_dangling_setups"] == 1


def test_a8_parts_start_and_end_on_beat_boundaries():
    smap = fx.story_map()
    parts = story.parts_of({1, 2, 3, 10}, smap, PARAMS)
    starts = {b.start for b in smap.beats}
    ends = {b.end for b in smap.beats}
    assert all(s in starts and e in ends for s, e, _ in parts) and len(parts) == 2


def test_pairs_are_handled_when_both_kept_or_both_cut():
    smap = fx.story_map()
    pairs = [
        {"id": "ok-kept", "cause": [0, 30], "result": [30, 60]},
        {"id": "ok-cut", "cause": [300, 330], "result": [600, 630]},
        {"id": "broken", "cause": [300, 330], "result": [0, 30]},
    ]
    res = story.pair_results(pairs, {1, 2}, smap, PARAMS)
    assert [r["handled"] for r in res] == [True, True, False]


def test_old_style_part_list_fails_closure_and_quarters():
    """A replica of the stored half cut's shape: the first act kept, the middle causes cut,
    only late results kept."""
    smap = fx.story_map()
    kept = set(range(1, 9)) | {14, 17, 20, 23, 24}
    c = story.run_checks(kept, smap, fx.DURATION_S * 0.5, fx.DURATION_S, PARAMS)
    assert c["A1_closure_violations"] > 0 and not c["hard_ok"]
