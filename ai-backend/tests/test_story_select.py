"""Selection by code: closure never broken, band, quarter balance, over-target case (plan 2.5)."""

from __future__ import annotations

from tests import story_fixture as fx
from utubot import story

PARAMS = story.StoryParams()


def build(keep=None, target=0.5, params=PARAMS, **kw):
    smap = fx.story_map()
    keep = keep if keep is not None else {}
    sel = story.select_beats(smap, keep, {}, fx.DURATION_S * target, fx.DURATION_S, params, **kw)
    return smap, sel


def closed(smap, kept):
    return all(n in kept for b in smap.beats if b.id in kept for n in b.needs)


def test_must_keep_brings_its_causes_and_the_ending_its_closure():
    smap, sel = build({17: 3})
    assert {2, 3, 5, 8, 11, 14, 17, 20, 23, 24} <= sel.kept
    assert closed(smap, sel.kept)


def test_length_is_in_the_band_and_closure_holds_for_every_target():
    for frac in (0.3, 0.4, 0.5, 0.6, 0.75):
        smap, sel = build({i: 1 for i in range(1, 25)}, target=frac)
        total = story.kept_seconds(sel.kept, {b.id: b for b in smap.beats})
        assert closed(smap, sel.kept)
        assert sel.over_target or abs(total - frac * fx.DURATION_S) <= frac * fx.DURATION_S * 0.1


def test_removal_never_breaks_closure_even_when_scores_say_drop_the_cause():
    keep = {i: 3 for i in range(1, 25)}  # everything must stay: far over a 30 % target
    keep[2] = keep[3] = 0
    smap, sel = build(keep, target=0.3)
    assert closed(smap, sel.kept) and {2, 3} <= sel.kept


def test_over_target_when_the_closure_alone_exceeds_the_band():
    smap, sel = build({}, target=0.2)
    assert sel.over_target and closed(smap, sel.kept)
    assert {24, 23, 20, 17, 14, 11, 8, 5, 3, 2} <= sel.kept


def test_quarter_balance_adds_from_the_starved_quarter():
    keep = {i: (2 if i > 12 else 1) for i in range(1, 25)}  # the model likes the second half
    smap, sel = build(keep, target=0.5, params=PARAMS)
    shares = story.quarter_shares(sel.kept, smap, fx.DURATION_S, PARAMS)
    overall = story.kept_seconds(sel.kept, {b.id: b for b in smap.beats}) / fx.DURATION_S
    assert min(shares) >= PARAMS.min_quarter_ratio * overall


def test_forbidden_is_not_added_and_forced_is_kept():
    smap, sel = build({}, forced={13}, forbidden={9})
    assert 13 in sel.kept and 9 not in sel.kept


def test_long_skips_are_filled_for_half_cuts():
    params = story.StoryParams(max_skip_s=120.0)
    keep = {i: 0 for i in range(1, 25)}
    keep[1] = 3
    smap, sel = build(keep, target=0.5, params=params)
    gaps = story.skips(sel.kept, smap)
    assert all(hi - lo <= 120 + 1 for lo, hi in gaps) or sel.over_target


def test_highlights_style_target_still_closed():
    smap, sel = build({7: 3, 15: 3}, target=0.25)
    assert closed(smap, sel.kept)
