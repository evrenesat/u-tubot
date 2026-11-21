"""Chunk review rules (`captions/sanity.py`): which segments are not speech, which chunks need a second listen."""

from __future__ import annotations

from utubot.captions.sanity import (
    FLAG_COMPRESSED,
    FLAG_LOW_CONF,
    FLAG_NO_SPEECH,
    FLAG_PHANTOM,
    FLAG_REPEAT,
    REASON_HALLUCINATION,
    REASON_LANGUAGE,
    REASON_SPARSE,
    chunk_health,
    drop_flagged,
    flag_segments,
    review,
)
from utubot.captions.types import Segment, Word
from utubot.config import CaptionsConfig

CFG = CaptionsConfig()
CHUNK_S = 600.0
LOOP_STEP_S = 30.0
LOOP_LEN_S = 7.0
LOOP_SEGMENTS = 20


def loop() -> list[Segment]:
    return [
        Segment(i * LOOP_STEP_S, i * LOOP_STEP_S + LOOP_LEN_S, "Thank you.")
        for i in range(LOOP_SEGMENTS)
    ]


def test_repeat_loop_is_flagged():
    flags = flag_segments(loop(), CFG)
    assert all({FLAG_REPEAT, FLAG_PHANTOM} <= found for found in flags)


def test_a_single_spoken_thank_you_is_kept():
    spoken = [Segment(10.0, 10.8, "Thank you.", 0.02, -0.2, 1.1)]
    assert flag_segments(spoken, CFG) == [set()]


def test_two_equal_segments_are_not_a_loop():
    segments = [Segment(0, 3, "Yes, yes."), Segment(4, 7, "Yes, yes.")]
    assert flag_segments(segments, CFG) == [set(), set()]


def test_no_speech_rule_needs_both_signals():
    quiet_but_sure = Segment(0, 4, "hello there", 0.9, -0.2, 1.0)
    unsure_but_audible = Segment(4, 8, "hello there again", 0.1, -1.5, 1.0)
    made_up = Segment(8, 12, "hello there once more", 0.9, -1.5, 1.0)
    flags = flag_segments([quiet_but_sure, unsure_but_audible, made_up], CFG)
    assert FLAG_NO_SPEECH not in flags[0] and FLAG_NO_SPEECH not in flags[1]
    assert FLAG_NO_SPEECH in flags[2]
    assert FLAG_LOW_CONF in flags[1]


def test_compressed_and_low_confidence_are_counted_never_dropped_alone():
    segments = [Segment(0, 5, "la la la la", 0.01, -1.5, 3.0)]
    flags = flag_segments(segments, CFG)
    assert {FLAG_COMPRESSED, FLAG_LOW_CONF} <= flags[0]
    kept, _words, dropped = drop_flagged(segments, [], flags)
    assert kept == segments and dropped == []


def test_drop_removes_the_words_inside_dropped_segments_only():
    segments = loop()[:3] + [Segment(100.0, 104.0, "a real sentence here", 0.01, -0.3, 1.2)]
    words = [Word(1.0, 1.3, "Thank"), Word(1.4, 1.7, "you."), Word(100.5, 100.9, "a")]
    kept, kept_words, dropped = drop_flagged(segments, words, flag_segments(segments, CFG))
    assert [s.text for s in kept] == ["a real sentence here"] and len(dropped) == 3
    assert [w.text for w in kept_words] == ["a"]


def test_health_counts_flagged_seconds_and_names_the_reasons():
    health = chunk_health(loop(), CHUNK_S, "en", "en", CFG)
    assert health.flagged_s == LOOP_SEGMENTS * LOOP_LEN_S
    assert round(health.flagged_share, 2) == 0.23 and health.reasons == []
    heavy = chunk_health(loop(), CHUNK_S / 4, "tr", "en", CFG)
    assert heavy.reasons == [REASON_LANGUAGE, REASON_HALLUCINATION]


def test_language_mismatch_uses_base_codes():
    segments = [Segment(0, 5, "merhaba dünya", 0.01, -0.2, 1.0)]
    assert chunk_health(segments, 5.0, "tr", "tr-TR", CFG).language_ok
    assert chunk_health(segments, 5.0, "en", "tr-TR", CFG).reasons == [REASON_LANGUAGE]
    assert chunk_health(segments, 5.0, None, "tr", CFG).language_ok
    assert chunk_health(segments, 5.0, "en", None, CFG).language_ok


def test_rank_prefers_language_then_less_made_up_text_then_more_text():
    right = chunk_health([Segment(0, 5, "merhaba")], 5.0, "tr", "tr", CFG)
    wrong = chunk_health([Segment(0, 5, "merhaba dünya, nasılsın")], 5.0, "en", "tr", CFG)
    assert right.rank() > wrong.rank()


def healthy(chars: int):
    return chunk_health([Segment(0, 100, "x" * chars, 0.01, -0.2, 1.0)], 100.0, "tr", "tr", CFG)


def test_sparse_chunk_needs_enough_chunks():
    chunks = [healthy(1500), healthy(1500), healthy(30)]
    assert review(chunks, CFG) == [[], [], [REASON_SPARSE]]
    assert review(chunks[1:], CFG) == [[], []]
    assert review([healthy(1500), healthy(1400), healthy(1000)], CFG) == [[], [], []]


def test_a_silent_file_has_no_sparse_chunks():
    assert review([healthy(0), healthy(0), healthy(0)], CFG) == [[], [], []]
