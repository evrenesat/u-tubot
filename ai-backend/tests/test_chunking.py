from __future__ import annotations

import wave

import pytest

from utubot.captions.chunking import (
    MIN_TAIL_S,
    Span,
    plan_chunks,
    shift,
    stitch_segments,
    stitch_words,
    write_chunk,
)
from utubot.captions.types import Segment, Word

OVERLAP = 2.0


def test_short_audio_is_one_chunk_and_a_zero_limit_disables_chunking():
    assert plan_chunks(300, 600, OVERLAP) == [Span(0, 0.0, 300)]
    assert plan_chunks(3000, 0, OVERLAP) == [Span(0, 0.0, 3000)]
    assert plan_chunks(0, 600, OVERLAP) == []


def test_chunks_overlap_and_cover_the_whole_file_without_exceeding_the_limit():
    spans = plan_chunks(1740, 600, OVERLAP)
    assert [(s.start, s.end) for s in spans] == [(0, 600), (598, 1198), (1196, 1740)]
    for a, b in zip(spans, spans[1:], strict=False):
        assert a.end - b.start == OVERLAP
    assert all(s.duration <= 600 for s in spans)
    assert [s.index for s in spans] == [0, 1, 2]


def test_a_tiny_tail_is_folded_into_the_last_chunk():
    spans = plan_chunks(600 + MIN_TAIL_S - 1, 600, OVERLAP)
    assert spans == [Span(0, 0.0, 600 + MIN_TAIL_S - 1)]
    spans = plan_chunks(1198 + 1.5, 600, OVERLAP)
    assert spans[-1].end == 1198 + 1.5 and len(spans) == 2


def seg(start: float, end: float, text: str) -> Segment:
    return Segment(start, end, text)


def test_stitching_keeps_each_chunk_to_its_side_of_the_overlap_midpoint():
    spans = [Span(0, 0.0, 10.0), Span(1, 8.0, 18.0)]
    first = [seg(0, 4, "alpha beta gamma delta"), seg(4, 9.5, "epsilon zeta eta theta iota")]
    second = [seg(8.5, 12, "kappa lambda mu"), seg(12, 17, "nu xi omicron pi rho")]
    # segment mids: 6.75 (first) < 9 (cut); 10.25 (second) >= cut
    stitched = stitch_segments([first, second], spans)
    assert [s.text for s in stitched] == [
        "alpha beta gamma delta",
        "epsilon zeta eta theta iota",
        "kappa lambda mu",
        "nu xi omicron pi rho",
    ]


def test_overlap_text_said_by_both_chunks_is_removed_once():
    spans = [Span(0, 0.0, 10.0), Span(1, 8.0, 20.0)]
    first = [
        seg(0, 6, "so the first thing you need"),
        seg(6, 10, "is to open the settings menu"),
    ]
    second = [
        seg(8.0, 14.0, "open the settings menu and click advanced"),
        seg(14.0, 20.0, "then restart the application"),
    ]
    stitched = stitch_segments([first, second], spans)
    text = " ".join(s.text for s in stitched)
    assert text == (
        "so the first thing you need is to open the settings menu"
        " and click advanced then restart the application"
    )


def test_a_segment_that_is_entirely_a_repeat_is_dropped():
    spans = [Span(0, 0.0, 10.0), Span(1, 8.0, 20.0)]
    first = [seg(0, 9, "we will meet again tomorrow at noon")]
    second = [seg(8.8, 9.8, "meet again tomorrow at noon"), seg(10, 20, "bring the documents")]
    stitched = stitch_segments([first, second], spans)
    assert [s.text for s in stitched] == [
        "we will meet again tomorrow at noon",
        "bring the documents",
    ]


def test_short_coincidental_repeats_across_a_boundary_are_kept():
    spans = [Span(0, 0.0, 10.0), Span(1, 8.0, 20.0)]
    first = [seg(0, 9, "it was very very")]
    second = [seg(10, 20, "very good indeed")]
    stitched = stitch_segments([first, second], spans)
    assert " ".join(s.text for s in stitched) == "it was very very very good indeed"


def test_a_two_word_repeat_inside_the_overlap_is_removed():
    spans = [Span(0, 0.0, 10.0), Span(1, 8.0, 20.0)]
    first = [seg(0, 9.5, "and that is all, thank you")]
    second = [seg(8.9, 11.0, "thank you"), seg(11, 20, "next question please")]
    assert [s.text for s in stitch_segments([first, second], spans)] == [
        "and that is all, thank you",
        "next question please",
    ]


def test_punctuation_and_case_do_not_hide_a_repeat():
    spans = [Span(0, 0.0, 10.0), Span(1, 8.0, 20.0)]
    first = [seg(0, 9.5, "Thanks for watching, see you next time.")]
    second = [seg(9.0, 12.0, "See you next time! Bye."), seg(12, 20, "Subscribe now")]
    stitched = stitch_segments([first, second], spans)
    assert [s.text for s in stitched] == [
        "Thanks for watching, see you next time.",
        "Bye.",
        "Subscribe now",
    ]


def test_an_empty_chunk_does_not_break_stitching():
    spans = [Span(0, 0.0, 10.0), Span(1, 8.0, 20.0), Span(2, 18.0, 30.0)]
    parts = [[seg(0, 5, "intro words here")], [], [seg(20, 29, "closing words here")]]
    assert [s.text for s in stitch_segments(parts, spans)] == [
        "intro words here",
        "closing words here",
    ]


def test_words_are_stitched_the_same_way():
    spans = [Span(0, 0.0, 10.0), Span(1, 8.0, 20.0)]
    first = [Word(7.0, 7.4, "open"), Word(8.2, 8.5, "the"), Word(8.6, 9.0, "menu")]
    second = [Word(8.2, 8.5, "the"), Word(8.6, 9.0, "menu"), Word(9.2, 9.6, "now")]
    stitched = stitch_words([first, second], spans)
    assert [w.text for w in stitched] == ["open", "the", "menu", "now"]


def test_shift_moves_times_without_touching_the_input():
    original = [seg(1.0, 2.0, "a")]
    moved = shift(original, 10.0)
    assert (moved[0].start, moved[0].end) == (11.0, 12.0) and original[0].start == 1.0
    assert shift([Word(0.5, 1.0, "w", "S1")], 2.0)[0].speaker == "S1"


def test_write_chunk_cuts_the_requested_span_of_a_wav(tmp_path):
    rate = 16000
    source = tmp_path / "in.wav"
    with wave.open(str(source), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(b"".join((i % 200).to_bytes(2, "little") for i in range(rate * 10)))
    target = write_chunk(source, Span(1, 2.0, 5.5), tmp_path / "part.wav")
    with wave.open(str(target), "rb") as part:
        assert part.getframerate() == rate and part.getnchannels() == 1
        assert part.getnframes() == int(3.5 * rate)
        first = int.from_bytes(part.readframes(1), "little")
    assert first == (2 * rate) % 200


@pytest.mark.parametrize("total", [601.0, 1200.0, 3599.0, 10800.0])
def test_every_second_of_audio_is_covered(total):
    spans = plan_chunks(total, 540, OVERLAP)
    assert spans[0].start == 0 and spans[-1].end == total
    assert all(b.start < a.end for a, b in zip(spans, spans[1:], strict=False))
    assert all(s.duration <= 540 + MIN_TAIL_S for s in spans)
