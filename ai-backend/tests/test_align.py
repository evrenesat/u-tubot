"""Alignment: YouTube caption cues, ASR words merged in, silence snapping."""

from __future__ import annotations

from utubot.captions.align import (
    caption_cues,
    merge_words_into_cues,
    parse_silencedetect,
    snap_cues,
)
from utubot.captions.types import Cue, Word
from utubot.config import CaptionsConfig

CFG = CaptionsConfig()


def test_caption_cues_keep_timing_and_drop_rolling_repeats():
    segments = [
        (0.0, 4.0, "Hello there my friend"),
        (4.0, 8.0, "Hello there my friend"),  # rolling window repeat, overlaps the previous
        (8.0, 12.0, "How are you doing today?"),
        (12.0, 12.0, "Without an end"),  # no duration: ends where the next begins
        (16.0, 20.0, "The last one."),
    ]
    cues = caption_cues(segments, CFG)
    assert [cue.start for cue in cues] == [0.0, 8.0, 12.0, 16.0]
    assert cues[2].end == 16.0
    assert cues[-1].lines == ["The last one."]


def test_caption_cues_re_break_text_that_is_too_long():
    text = " ".join(f"word{i}" for i in range(30))
    cues = caption_cues([(0.0, 30.0, text)], CFG)
    assert len(cues) > 1
    for cue in cues:
        assert len(cue.lines) <= CFG.max_lines
        assert all(len(line) <= CFG.max_chars_per_line for line in cue.lines)
    for a, b in zip(cues, cues[1:], strict=False):
        assert a.end <= b.start + 1e-6


def test_merge_words_replaces_text_and_refines_boundaries():
    cues = [Cue(1.0, 3.0, ["caption text"]), Cue(3.0, 6.0, ["more caption"])]
    words = [
        Word(1.2, 1.6, "actual"),
        Word(1.6, 2.1, "speech"),
        Word(2.1, 2.6, "here"),
        Word(4.0, 4.5, "later"),
        Word(4.5, 5.0, "words"),
    ]
    out, from_asr = merge_words_into_cues(cues, words, CFG)
    assert from_asr == 2
    assert out[0].lines == ["actual speech here"]
    assert out[0].start == 1.2 and out[0].end == 2.6
    assert out[1].lines == ["later words"]
    assert out[1].start == 4.0 and out[1].end == 5.0
    for a, b in zip(out, out[1:], strict=False):
        assert a.end <= b.start + 1e-6


def test_merge_words_keeps_caption_text_where_the_asr_heard_nothing():
    cues = [Cue(1.0, 3.0, ["caption text"]), Cue(3.0, 6.0, ["more caption"])]
    words = [Word(10.0, 10.4, "far"), Word(10.4, 10.9, "away")]
    out, from_asr = merge_words_into_cues(cues, words, CFG)
    assert from_asr == 0
    assert [cue.lines for cue in out] == [["caption text"], ["more caption"]]
    assert [(cue.start, cue.end) for cue in out] == [(1.0, 3.0), (3.0, 6.0)]


def test_merge_words_outside_the_margin_are_dropped():
    cues = [Cue(1.0, 3.0, ["caption text"])]
    words = [Word(0.0, 0.4, "early"), Word(3.0, 3.3, "edge"), Word(4.5, 4.9, "late")]
    out, from_asr = merge_words_into_cues(cues, words, CFG)
    # "edge" straddles the end: its midpoint is inside the window, so it belongs to the cue,
    # and the short cue is stretched to the minimum duration afterwards
    assert from_asr == 1
    assert out[0].lines == ["edge"]
    assert out[0].start == 3.0 and out[0].end == 4.0


def test_parse_silencedetect():
    output = (
        "[silencedetect @ 0x0] silence_start: -0.01\n"
        "[silencedetect @ 0x0] silence_end: 1.5 | silence_duration: 1.51\n"
        "[silencedetect @ 0x0] silence_start: 7.25\n"
        "[silencedetect @ 0x0] silence_end: 8 | silence_duration: 0.75\n"
        "[silencedetect @ 0x0] silence_start: 9\n"
    )
    assert parse_silencedetect(output) == [(0.0, 1.5), (7.25, 8.0)]


def test_snap_cues_moves_boundaries_outward_to_silence():
    cues = [Cue(2.0, 5.0, ["one"]), Cue(5.0, 8.0, ["two"])]
    # silence midpoints: 1.7 (before the first cue) and 8.2 (after the last one)
    silences = [(1.5, 1.9), (8.0, 8.4)]
    out = snap_cues(cues, silences, CFG)
    assert (out[0].start, out[0].end) == (1.7, 5.0)
    assert (out[1].start, out[1].end) == (5.0, 8.2)


def test_snap_cues_never_moves_a_boundary_into_the_cue():
    cfg = CaptionsConfig()
    cues = [Cue(10.0, 13.0, ["one"])]
    # a silence inside the cue near its start: snapping to 10.35 would cut the first word
    out = snap_cues(cues, [(10.2, 10.5)], cfg)
    assert (out[0].start, out[0].end) == (10.0, 13.0)
    # a silence inside the cue near its end: snapping to 12.6 would hide the last word
    out = snap_cues(cues, [(12.4, 12.8)], cfg)
    assert (out[0].start, out[0].end) == (10.0, 13.0)


def test_snap_cues_picks_the_nearest_outward_silence():
    cfg = CaptionsConfig(align_window_s=0.4)
    cues = [Cue(10.0, 13.0, ["one"])]
    # midpoints 9.0, 9.8, 13.1, 13.55: the nearest outward one wins on both sides
    silences = [(8.9, 9.1), (9.7, 9.9), (13.05, 13.15), (13.4, 13.7)]
    out = snap_cues(cues, silences, cfg)
    assert (out[0].start, round(out[0].end, 6)) == (9.8, 13.1)


def test_snap_cues_never_breaks_the_minimum_duration_or_the_neighbours():
    cfg = CaptionsConfig(min_cue_s=1.0, align_window_s=0.4)
    cues = [Cue(1.0, 1.2, ["tiny"]), Cue(1.2, 5.0, ["rest"]), Cue(5.15, 9.0, ["next"])]
    # midpoints: 1.3 sits inside the tiny and the rest cue (no inward snapping); 5.3 is within
    # the window of the rest cue's end but past the neighbour's start; 5.05 is the free gap
    # midpoint both neighbouring boundaries meet at
    silences = [(1.25, 1.35), (5.0, 5.1), (5.2, 5.4)]
    out = snap_cues(cues, silences, cfg)
    assert (out[0].start, out[0].end) == (1.0, 1.2)
    assert (out[1].start, out[1].end) == (1.2, 5.05)
    assert (out[2].start, out[2].end) == (5.05, 9.0)


def test_snap_cues_without_silences_returns_the_cues():
    cues = [Cue(1.0, 3.0, ["one"])]
    assert snap_cues(cues, [], CFG) == cues
