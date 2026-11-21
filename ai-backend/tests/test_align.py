"""Alignment: YouTube caption cues, ASR words merged in, silence snapping."""

from __future__ import annotations

from utubot.captions.align import (
    caption_cues,
    cues_from_words,
    merge_words_into_cues,
    parse_silencedetect,
    snap_cues,
)
from utubot.captions.segment import build_cues, pad_cues
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


# ---- cues from the words' own times ----------------------------------------------------------------


def spoken(start: float, text: str, step: float = 0.3) -> list[Word]:
    return [
        Word(start + i * step, start + i * step + 0.25, token)
        for i, token in enumerate(text.split())
    ]


def test_cues_from_words_uses_every_word():
    # the captions are 3 s early, so no word lies in a caption window: the old rule dropped them all
    captions = [Cue(0.0, 2.0, ["caption one"]), Cue(2.0, 4.0, ["caption two"])]
    words = spoken(5.0, "alpha beta gamma delta") + spoken(9.0, "epsilon zeta")
    cues, speech, fill = cues_from_words(words, captions, CFG)
    text = " ".join(" ".join(cue.lines) for cue in cues)
    assert all(token in text for token in "alpha beta gamma delta epsilon zeta".split())
    assert merge_words_into_cues(captions, words, CFG)[1] == 0  # what the old rule did with them
    assert speech == 2 and fill == 2 and cues[0].start == 0.0  # untouched captions stay in the gaps
    spoken_cues = [cue for cue in cues if cue.words]
    assert [cue.start for cue in spoken_cues] == [5.0, 9.0]


def test_fill_cues_only_in_wordless_gaps():
    words = spoken(0.0, "one two three") + spoken(30.0, "four five six")
    captions = [
        Cue(0.0, 2.0, ["one two three"]),
        Cue(4.0, 28.0, ["[Music]"]),
        Cue(29.0, 31.0, ["four five six"]),
        Cue(1.5, 8.0, ["overlaps speech"]),
    ]
    cues, speech, fill = cues_from_words(words, sorted(captions, key=lambda c: c.start), CFG)
    music = [cue for cue in cues if cue.lines == ["[Music]"]]
    assert fill == 2 and len(music) == 1
    assert 4.0 <= music[0].start and music[0].end <= 28.0
    for before, after in zip(cues, cues[1:], strict=False):
        assert before.end <= after.start + 1e-9
    speech_cues = [cue for cue in cues if cue.words]
    for fill_cue in (cue for cue in cues if not cue.words):
        for sp in speech_cues:
            assert fill_cue.end <= sp.start + 1e-9 or fill_cue.start >= sp.end - 1e-9


def test_a_fill_cue_clipped_below_the_minimum_is_dropped():
    words = spoken(0.0, "one two three") + spoken(6.5, "four five")
    cues, _speech, fill = cues_from_words(words, [Cue(3.0, 5.2, ["tiny gap"])], CFG)
    assert fill == 1  # kept: 2.2 s of wordless gap is enough
    cues, _speech, fill = cues_from_words(words, [Cue(3.0, 3.5, ["too short"])], CFG)
    assert fill == 0 and all(cue.words for cue in cues)


def test_merge_without_retime_keeps_caption_times():
    cues = [Cue(1.0, 3.0, ["caption text"]), Cue(3.0, 6.0, ["more caption"])]
    words = spoken(1.2, "actual speech here") + spoken(4.0, "later words")
    out, from_asr = merge_words_into_cues(cues, words, CFG, retime=False)
    assert from_asr == 2
    assert [(c.start, c.end) for c in out] == [(1.0, 3.0), (3.0, 6.0)]
    assert out[0].lines == ["actual speech here"] and out[1].lines == ["later words"]
    long = spoken(1.2, " ".join(f"token{i}" for i in range(30)))
    out, _ = merge_words_into_cues([Cue(1.0, 9.0, ["x"])], long, CFG, retime=False)
    assert len(out) > 1 and out[0].start == 1.0 and out[-1].end == 9.0


def test_no_cue_spans_a_pause():
    words = (
        spoken(0.0, "one two three four")
        + spoken(4.0, "five six seven")
        + spoken(12.0, "eight nine ten")
    )
    cues, _speech, _fill = cues_from_words(words, [], CFG)
    for cue in cues:
        assert cue.words
        for before, after in zip(cue.words, cue.words[1:], strict=False):
            assert after.start - before.end <= CFG.sentence_gap_s
    assert len(cues) >= 3


def test_pad_cues_lingers_without_touching_the_next_cue():
    words = spoken(0.0, "one two three") + spoken(1.9, "four five six")
    cues = build_cues(words, CFG)
    padded = pad_cues(cues, CFG)
    assert padded[0].end <= padded[1].start + 1e-9
    last = padded[-1]
    assert last.end == max(last.words[-1].end + CFG.cue_linger_s, last.end)


def test_snapping_before_the_linger_keeps_cues_close_to_their_last_word():
    words = spoken(0.0, "one two three") + spoken(3.0, "four five six")
    silences = [(0.9, 2.9)]
    cues, _s, _f = cues_from_words(words, [], CFG, silences)
    assert cues[0].end - cues[0].words[-1].end <= CFG.align_window_s + 1e-9


def test_an_applause_cue_next_to_speech_survives_clipped_to_the_gap():
    words = spoken(0.0, "one two three") + spoken(13.8, "four five six")
    captions = [Cue(0.0, 2.0, ["one two three"]), Cue(0.3, 14.0, ["[Applause]"])]
    cues, speech, fill = cues_from_words(words, captions, CFG)
    applause = [cue for cue in cues if cue.lines == ["[Applause]"]]
    assert fill == 1 and len(applause) == 1
    assert applause[0].start >= speech_end(cues[0]) - 1e-9 and applause[0].end <= 13.8 + 1e-9


def speech_end(cue: Cue) -> float:
    return cue.words[-1].end if cue.words else cue.end


def test_a_caption_with_a_stray_word_overlap_is_still_a_fill_cue():
    # one short word inside a 10 s music row covers far less than the share: the row survives
    words = spoken(0.0, "one two three") + [Word(5.0, 5.2, "oh")] + spoken(20.0, "four five six")
    cues, _speech, fill = cues_from_words(words, [Cue(2.0, 12.0, ["[Music]"])], CFG)
    assert fill == 1 and any(cue.lines == ["[Music]"] for cue in cues)
    covered = cues_from_words(words, [Cue(0.0, 2.0, ["one two three"])], CFG)
    assert covered[2] == 0


def test_fill_cues_are_clipped_against_each_other():
    words = spoken(0.0, "one two three") + spoken(30.0, "four five six")
    rolling = [Cue(5.0, 15.0, ["[Music]"]), Cue(10.0, 24.0, ["[Music] again"])]
    cues, _speech, fill = cues_from_words(words, rolling, CFG)
    fills = [cue for cue in cues if not cue.words]
    assert fill == 2 and len(fills) == 2
    for before, after in zip(cues, cues[1:], strict=False):
        assert before.end <= after.start + 1e-9
    assert fills[1].start >= 15.0 - 1e-9


def test_a_spoken_caption_next_to_its_words_is_not_repeated_in_the_gap():
    # the reproduced case: the caption row outlasts the words by 6 s, but it is their own text
    words = spoken(10.2, "so that's the plan", step=0.45) + spoken(18.0, "next thing here")
    caption = Cue(10.4, 17.8, ["so that's the plan"])
    cues, _speech, fill = cues_from_words(words, [caption], CFG)
    assert fill == 0
    texts = [" ".join(cue.lines) for cue in cues]
    assert texts.count("so that's the plan") == 1


def test_non_speech_tags_and_music_notes_beside_speech_are_kept():
    words = spoken(0.0, "one two three") + spoken(20.0, "four five six")
    for tag in ("[Applause]", "(applause)", "♪♪", "♪ ♫ ♪", "[Music] ♪"):
        cues, _speech, fill = cues_from_words(words, [Cue(0.5, 19.0, [tag])], CFG)
        assert fill == 1 and any(cue.lines == [tag] for cue in cues), tag
    spoken_tag, _s, fill = cues_from_words(
        words, [Cue(5.0, 19.0, ["[Music] and then speech"])], CFG
    )
    assert (
        fill == 1
    )  # the words do not overlap it (widened by the window): a speech caption in a gap


def test_a_speech_caption_in_a_truly_wordless_gap_is_kept():
    words = spoken(0.0, "one two three") + spoken(30.0, "four five six")
    cues, _speech, fill = cues_from_words(
        words, [Cue(10.0, 14.0, ["she said nothing at all"])], CFG
    )
    assert fill == 1 and any(cue.lines == ["she said nothing at all"] for cue in cues)
    near = cues_from_words(words, [Cue(1.2, 14.0, ["overlapped by speech"])], CFG)
    assert near[2] == 0
