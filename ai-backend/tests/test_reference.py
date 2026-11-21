"""The agreement check against YouTube's word times (pure, on the synthetic talk)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.synth_speech import CAPTION_LEAD_S, make_timeline, youtube_rows, youtube_words
from utubot.captions import reference
from utubot.captions.types import TIMING_INTERPOLATED, Word
from utubot.config import CaptionsConfig

DURATION_S = 300.0
SHIFT_S = 1.5
SHIFT_FROM_S = 120.0
SHIFT_TO_S = 200.0
WITHIN_FLOOR = 0.95
LEAD_TOLERANCE_S = 0.02


@pytest.fixture
def cfg():
    return CaptionsConfig()


@pytest.fixture
def truth():
    return make_timeline(7, DURATION_S)


def shifted(words, begin, end, by):
    return [
        replace(w, start=w.start + by, end=w.end + by) if begin <= w.start < end else w
        for w in words
    ]


def test_agreeing_words_have_the_youtube_lead_and_no_regions(cfg, truth):
    verdict = reference.check(youtube_words(truth), [], truth, cfg)
    agreement = verdict.agreement
    assert verdict.status == reference.STATUS_OK and agreement.source == reference.SOURCE_WORDS
    assert agreement.within_s >= WITHIN_FLOOR and agreement.regions == []
    assert agreement.median_s == pytest.approx(CAPTION_LEAD_S, abs=LEAD_TOLERANCE_S)
    assert agreement.anchor_share > 0.9 and verdict.lead_s == agreement.median_s


def test_one_shifted_stretch_is_one_region(cfg, truth):
    words = shifted(truth, SHIFT_FROM_S, SHIFT_TO_S, SHIFT_S)
    verdict = reference.check(youtube_words(truth), [], words, cfg)
    assert verdict.status == reference.STATUS_WARN
    ((start, end, median),) = verdict.agreement.regions
    assert start == pytest.approx(SHIFT_FROM_S, abs=10.0) and end == pytest.approx(
        SHIFT_TO_S, abs=10.0
    )
    assert median == pytest.approx(CAPTION_LEAD_S + SHIFT_S, abs=LEAD_TOLERANCE_S)
    assert verdict.agreement.median_s == pytest.approx(CAPTION_LEAD_S, abs=LEAD_TOLERANCE_S)


def test_an_isolated_wrong_match_is_not_a_region(cfg, truth):
    words = list(truth)
    words[40] = replace(words[40], start=words[40].start + SHIFT_S, end=words[40].end + SHIFT_S)
    assert reference.check(youtube_words(truth), [], words, cfg).status == reference.STATUS_OK


def test_caption_rows_give_the_same_verdicts(cfg, truth):
    rows = youtube_rows(truth)
    verdict = reference.check(None, rows, truth, cfg)
    assert (
        verdict.status == reference.STATUS_OK and verdict.agreement.source == reference.SOURCE_ROWS
    )
    assert verdict.agreement.median_s == pytest.approx(CAPTION_LEAD_S, abs=LEAD_TOLERANCE_S)
    words = shifted(truth, SHIFT_FROM_S, SHIFT_TO_S, SHIFT_S)
    assert reference.check(None, rows, words, cfg).status == reference.STATUS_WARN


def test_another_script_is_skipped(cfg, truth):
    cyrillic = [(t, "привет" + str(i)) for i, (t, _w) in enumerate(youtube_words(truth))]
    verdict = reference.check(cyrillic, [], truth, cfg)
    assert verdict.status == reference.STATUS_SKIPPED
    assert verdict.reason == reference.REASON_OTHER_SCRIPT and verdict.lead_s == 0.0


def test_no_reference_and_too_few_anchors_are_skipped(cfg, truth):
    assert reference.check(None, [], truth, cfg).reason == reference.REASON_NO_REFERENCE
    unrelated = [(t, f"zz{i}") for i, (t, _w) in enumerate(youtube_words(truth))]
    assert reference.check(unrelated, [], truth, cfg).reason == reference.REASON_TOO_FEW


def test_interpolated_words_never_anchor(cfg, truth):
    guessed = [Word(w.start, w.end, w.text, timing=TIMING_INTERPOLATED) for w in truth]
    assert reference.anchors(youtube_words(truth), guessed, cfg) == []
    assert (
        reference.check(youtube_words(truth), [], guessed, cfg).status == reference.STATUS_SKIPPED
    )


def test_a_pair_further_apart_than_the_limit_is_dropped(cfg, truth):
    words = shifted(truth, 0.0, DURATION_S, cfg.ref_max_offset_s + 1.0)
    assert reference.anchors(youtube_words(truth), words, cfg) == []
