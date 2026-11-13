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


def test_snap_cues_moves_boundaries_to_silence():
    cues = [Cue(1.0, 3.3, ["one"]), Cue(3.3, 6.0, ["two"]), Cue(7.0, 9.0, ["three"])]
    # silence midpoints: 1.3, 3.1, 6.2, 7.3
    silences = [(1.2, 1.4), (3.0, 3.2), (6.1, 6.3), (7.2, 7.4)]
    out = snap_cues(cues, silences, CFG)
    assert (round(out[0].start, 6), round(out[0].end, 6)) == (1.3, 3.1)
    assert (round(out[1].start, 6), round(out[1].end, 6)) == (3.1, 6.2)
    assert (round(out[2].start, 6), round(out[2].end, 6)) == (7.3, 9.0)


def test_snap_cues_never_breaks_the_minimum_duration_or_the_neighbours():
    cfg = CaptionsConfig(min_cue_s=1.0, align_window_s=0.4)
    cues = [Cue(1.0, 1.2, ["tiny"]), Cue(1.2, 5.0, ["rest"])]
    silences = [(1.25, 1.35)]  # midpoint 1.3 would leave the first cue 0.3 s
    out = snap_cues(cues, silences, cfg)
    assert (out[0].start, out[0].end) == (1.0, 1.2)
    assert (out[1].start, out[1].end) == (1.3, 5.0)


def test_snap_cues_without_silences_returns_the_cues():
    cues = [Cue(1.0, 3.0, ["one"])]
    assert snap_cues(cues, [], CFG) == cues
