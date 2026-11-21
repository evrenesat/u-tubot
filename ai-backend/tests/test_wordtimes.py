"""Repair of engine word times: stretched, zero-length, squeezed and out-of-order words."""

from __future__ import annotations

from utubot.captions.types import (
    TIMING_INTERPOLATED,
    TIMING_REAL,
    TIMING_REPAIRED,
    TIMING_SUSPECT,
    Word,
)
from utubot.captions.wordtimes import classify, repair_words
from utubot.config import CaptionsConfig

CFG = CaptionsConfig()


def w(start: float, end: float, text: str = "word", **kw) -> Word:
    return Word(start, end, text, **kw)


def test_stretched_last_word_ends_at_the_silence():
    words = [w(1.3, 1.8, "one"), w(2.0, 2.5, "two"), w(3.58, 7.12, "three")]
    out, stats = repair_words(words, [(3.9, 7.0)], CFG)
    assert out[2].end == 3.9 and out[2].start == 3.58 and out[2].timing == TIMING_REPAIRED
    assert stats.stretched == 1
    assert words[2].end == 7.12  # the input is never mutated


def test_stretched_word_without_silence_gets_nominal_length():
    out, stats = repair_words([w(1.0, 1.4, "a"), w(2.0, 5.0, "hello")], [], CFG)
    nominal = max(len("hello") * CFG.word_char_s, CFG.word_nominal_min_s)
    assert out[1].start == 2.0 and out[1].end == 2.0 + nominal and stats.stretched == 1


def test_head_stretch_moves_the_start():
    out, stats = repair_words([w(0.0, 5.0, "hello")], [(0.0, 4.2)], CFG)
    assert out[0].start == 4.2 and out[0].end == 5.0 and stats.stretched == 1
    # no silence, the next word follows at once: the word started late, not early
    out, _ = repair_words([w(1.0, 4.0, "hello"), w(4.0, 4.3, "x")], [], CFG)
    assert out[0].end == 4.0 and out[0].start > 3.0


def test_zero_length_words_borrow_from_gaps():
    words = [w(1.0, 1.0, "alpha"), w(1.5, 1.9, "beta"), w(2.4, 2.4, "gamma"), w(3.0, 3.3, "d")]
    out, stats = repair_words(words, [], CFG)
    assert stats.zero_length == 2
    for word in out:
        assert word.end - word.start >= CFG.word_min_s
    for before, after in zip(out, out[1:], strict=False):
        assert before.end <= after.start + 1e-9
    assert out[0].timing == TIMING_REPAIRED


def test_zero_length_word_after_a_close_neighbour_pulls_its_start_back():
    out, _ = repair_words([w(1.0, 1.3, "ab"), w(1.5, 1.5, "cdefgh"), w(1.52, 1.9, "x")], [], CFG)
    assert out[1].end - out[1].start >= CFG.word_min_s
    assert out[1].start >= out[0].end - 1e-9 and out[1].end <= out[2].start + 1e-9


def test_squeezed_run_is_respread_and_marked():
    squeezed = [w(18.14 + i * 0.085, 18.14 + (i + 1) * 0.085, f"w{i}x") for i in range(7)]
    tail = w(19.5, 19.9, "after")
    out, stats = repair_words([*squeezed, tail], [], CFG)
    assert stats.squeezed == 7
    assert all(x.timing == TIMING_SUSPECT for x in out[:7])
    span = out[6].end - out[0].start
    assert 7 / span <= CFG.word_rate_max or out[6].end == tail.start
    assert out[6].end <= tail.start + 1e-9
    assert [x.text for x in out[:7]] == [x.text for x in squeezed]


def test_a_squeezed_run_that_cannot_grow_stays_inside_its_gap():
    words = [
        w(0.0, 0.05, "aa"),
        w(0.05, 0.1, "bb"),
        w(0.1, 0.15, "cc"),
        w(0.15, 0.2, "dd"),
        w(0.2, 0.6),
    ]
    out, _ = repair_words(words, [], CFG)
    assert out[3].end <= out[4].start + 1e-9


def test_nonmonotonic_starts_are_clamped():
    out, stats = repair_words([w(5.0, 5.4, "a"), w(4.0, 4.3, "b"), w(5.5, 5.9, "c")], [], CFG)
    assert stats.nonmonotonic == 1
    assert [x.start for x in out] == sorted(x.start for x in out)
    assert all(x.end >= x.start for x in out)


def test_interpolated_words_pass_through():
    words = [
        w(0.0, 5.0, "slowly", timing=TIMING_INTERPOLATED),
        w(5.0, 5.0, "x", timing=TIMING_INTERPOLATED),
    ]
    out, stats = repair_words(words, [(0.5, 4.0)], CFG)
    assert [(x.start, x.end) for x in out] == [(0.0, 5.0), (5.0, 5.0)]
    assert all(x.timing == TIMING_INTERPOLATED for x in out)
    assert stats.interpolated == 2 and stats.real == 0 and stats.stretched == 0
    assert stats.zero_length == 0


def test_empty_text_is_dropped_and_good_words_are_untouched():
    words = [w(1.0, 1.4, "fine"), w(1.5, 1.5, "  "), w(2.0, 2.5, "also")]
    out, stats = repair_words(words, [], CFG)
    assert [x.text for x in out] == ["fine", "also"]
    assert [(x.start, x.end) for x in out] == [(1.0, 1.4), (2.0, 2.5)]
    assert all(x.timing == TIMING_REAL for x in out) and stats.words == 2
    detail = stats.as_detail()
    assert detail["real_share"] == 1.0 and detail["speech_s"] > 0 and detail["words_per_s"] > 0


def test_classify_real_mixed_interpolated():
    real = w(0, 1, "a")
    fake = w(0, 1, "b", timing=TIMING_INTERPOLATED)
    assert classify([], 0.9) is None
    assert classify([fake, fake], 0.9) == "interpolated"
    assert classify([real] * 9 + [fake], 0.9) == "real"
    assert classify([real, fake], 0.9) == "mixed"
