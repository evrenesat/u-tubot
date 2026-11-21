"""The sync metric: phrase onsets, the asymmetric hit window, the audio self-check."""

from __future__ import annotations

import pytest

from utubot.captions.syncscore import phrase_onsets, score_starts, self_check
from utubot.captions.types import Cue
from utubot.config import CaptionsConfig

CFG = CaptionsConfig()


def test_phrase_onsets():
    items = [(1.0, 1.4), (1.5, 1.9), (3.0, 3.4), (3.45, 3.9), (9.0, 9.5)]
    assert phrase_onsets(items, 0.5) == [1.0, 3.0, 9.0]
    assert phrase_onsets([], 0.5) == []
    # a long item does not hide the next onset behind an earlier end
    assert phrase_onsets([(0.0, 10.0), (4.0, 4.5), (11.0, 11.2)], 0.5) == [0.0, 11.0]


def test_score_starts_hit_window_is_asymmetric():
    onsets = [10.0, 20.0, 30.0, 40.0]
    # errors: -0.45 (early, hit), +0.25 (late, hit), +0.35 (too late, loose only), -0.9 (loose only)
    starts = [9.55, 20.25, 30.35, 39.1]
    score = score_starts(starts, onsets, CFG)
    assert score.onsets == 4 and score.hit == 0.5 and score.loose == 1.0
    assert score.median_s == pytest.approx(-0.1)
    assert score.p10_s <= score.median_s <= score.p90_s


def test_score_starts_uses_the_nearest_cue_start_per_onset():
    score = score_starts([0.0, 5.0, 5.1, 100.0], [5.05], CFG)
    assert score.hit == 1.0 and score.onsets == 1
    far = score_starts([0.0, 100.0], [50.0], CFG)
    assert far.hit == 0.0 and far.loose == 0.0 and far.median_s in (-50.0, 50.0)


def test_score_starts_without_data_is_zero():
    assert score_starts([], [1.0], CFG).hit == 0.0
    assert score_starts([1.0], [], CFG).onsets == 0


def test_score_detail_is_rounded():
    detail = score_starts([1.0], [1.1], CFG).as_detail()
    assert detail["hit"] == 1.0 and detail["median_s"] == pytest.approx(-0.1)


def test_self_check():
    cues = [
        Cue(1.0, 3.0, ["a"]),  # speech
        Cue(5.0, 7.0, ["b"]),  # starts 1 s into a 4 s silence: in silence
        Cue(10.0, 12.0, ["c"]),  # starts at the end of a silence: where speech begins
    ]
    silences = [(3.0, 10.0)]
    check = self_check(cues, silences, 20.0, CFG)
    assert check["cues"] == 3
    # cue b lies entirely inside the silence: 2 of the 6 cue seconds are over silence
    assert check["speech_overlap"] == pytest.approx(round(1 - 2 / 6, 3))
    assert check["starts_in_silence"] == pytest.approx(round(1 / 3, 3))
    assert check["silence_share"] == pytest.approx(0.35)
    empty = self_check([], [], 0.0, CFG)
    assert empty["speech_overlap"] is None and empty["silence_share"] is None
