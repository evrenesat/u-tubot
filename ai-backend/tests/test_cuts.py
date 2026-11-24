from __future__ import annotations

import pytest

from utubot.config import CutsConfig
from utubot.cuts import (
    Candidate,
    CutFormatError,
    CutRefused,
    Part,
    Unit,
    build_units,
    candidate_units,
    candidates_from,
    chapters_between,
    cut_document,
    effective_target_s,
    expand_candidate_parts,
    finalize_parts,
    keep_guards,
    merge_candidates,
    parse_chapters,
    parse_cut_answer,
    plan_chunks,
    select_for_target,
    serialize_units,
    split_candidates,
    target_band,
    transcript_hash,
    unit_line,
)
from utubot.prompts import BUILTIN_SET, TASK_CUTS, Prompt, PromptStore

CFG = CutsConfig()


def segs(*rows: tuple[float, float, str]) -> list[tuple[float, float, str]]:
    return list(rows)


class TestBuildUnits:
    def test_splits_on_sentence_end_and_pause(self):
        units = build_units(
            segs(
                (0.0, 3.0, "Welcome back."),
                (3.2, 6.0, "Today we test it"),
                (6.4, 9.0, "and it works."),
                (10.0, 12.0, "After the break, the results."),
            ),
            CFG,
        )
        # "Welcome back." ends a sentence; the 1.0 s pause after 9.0 starts a new unit.
        assert [u.text for u in units] == [
            "Welcome back.",
            "Today we test it and it works.",
            "After the break, the results.",
        ]
        assert [u.n for u in units] == [1, 2, 3]

    def test_merges_short_fragments_without_pause(self):
        units = build_units(
            segs((0.0, 1.0, "so"), (1.1, 2.0, "we"), (2.1, 3.0, "begin")),
            CFG,
        )
        assert len(units) == 1 and units[0].text == "so we begin"

    def test_caps_unit_length(self):
        # One continuous ramble of 30 s: the 15 s cap must split it.
        units = build_units(segs((0.0, 30.0, "blah " * 60)), CFG)
        assert len(units) == 2
        assert units[0].end - units[0].start <= CFG.unit_max_s + 0.001

    def test_zero_duration_segments_end_where_the_next_begins(self):
        units = build_units(
            segs((0.0, 0.0, "hello"), (4.0, 0.0, "world."), (8.0, 9.0, "bye.")), CFG
        )
        # "hello" lasts until 4.0 (json3 rows without a duration), "world." until 8.0, and the
        # sentence end after "world." starts the last unit.
        assert (units[0].start, units[0].end) == (0.0, 8.0)
        assert (units[1].start, units[1].end) == (8.0, 9.0)

    def test_skips_empty_text(self):
        units = build_units(segs((0.0, 2.0, "  "), (2.5, 4.0, "real text")), CFG)
        assert len(units) == 1 and units[0].start == 2.5

    def test_drops_rolling_caption_repeats(self):
        units = build_units(
            segs(
                (0.0, 4.0, "one two three"),
                (4.0, 8.0, "two three four five"),
                (8.0, 12.0, "three four five six"),
            ),
            CFG,
        )
        # Auto captions repeat the tail of the last fragment at the start of the next one.
        assert [u.text for u in units] == ["one two three four five six"]

    def test_a_repeated_line_after_a_pause_is_kept(self):
        units = build_units(segs((0.0, 2.0, "Yes."), (5.0, 7.0, "Yes.")), CFG)
        assert [u.text for u in units] == ["Yes.", "Yes."]

    def test_a_sentence_closed_by_a_quote_or_bracket_ends_a_unit(self):
        units = build_units(
            segs(
                (0.0, 2.0, 'He said "Done."'),
                (2.5, 4.0, "Then the demo happens."),
                (4.5, 6.0, "(That was it.)"),
                (6.5, 8.0, "The result follows."),
            ),
            CFG,
        )
        assert [u.text for u in units] == [
            'He said "Done."',
            "Then the demo happens.",
            "(That was it.)",
            "The result follows.",
        ]

    def test_numbering_is_sequential(self):
        units = build_units(
            segs((0.0, 1.0, "a."), (2.0, 3.0, "b."), (4.0, 5.0, "c."), (6.0, 7.0, "d.")), CFG
        )
        assert [u.n for u in units] == [1, 2, 3, 4]


class TestChapters:
    def test_parses_youtube_chapter_lines(self):
        text = "Links below\n0:00 Intro\n1:05 The actual demo\n65:00 Results\nnot a chapter"
        chapters = parse_chapters(text)
        assert chapters == [(0.0, "Intro"), (65.0, "The actual demo"), (3900.0, "Results")]

    def test_ignores_empty_descriptions_and_duplicates(self):
        assert parse_chapters(None) == []
        assert parse_chapters("no timestamps here") == []
        assert parse_chapters("0:00 Intro\n0:00 Again") == [(0.0, "Intro")]


class TestParseAnswer:
    def test_accepts_sorted_ranges(self):
        units = [Unit(i, float(i), float(i + 5), "x") for i in range(1, 6)]
        parts = parse_cut_answer(
            {
                "parts": [
                    {"from": 2, "to": 3, "label": " middle "},
                    {"from": 5, "to": 5, "label": ""},
                ]
            },
            units,
        )
        assert [(p.label, p.start_ms, p.end_ms) for p in parts] == [
            ("middle", 2000, 8000),
            ("Part 2", 5000, 10000),
        ]

    def test_rejects_unknown_ids(self):
        units = [Unit(1, 0.0, 5.0, "x")]
        with pytest.raises(CutFormatError, match="1-1"):
            parse_cut_answer({"parts": [{"from": 1, "to": 9}]}, units)

    def test_rejects_overlaps(self):
        units = [Unit(i, float(i), float(i) + 5, "x") for i in range(1, 4)]
        with pytest.raises(CutFormatError, match="overlaps"):
            parse_cut_answer({"parts": [{"from": 1, "to": 2}, {"from": 2, "to": 3}]}, units)

    def test_rejects_empty_parts(self):
        units = [Unit(1, 0.0, 5.0, "x")]
        with pytest.raises(CutFormatError):
            parse_cut_answer({"parts": []}, units)
        with pytest.raises(CutFormatError):
            parse_cut_answer("nope", units)


class TestFinalize:
    def test_pads_boundaries(self):
        parts, _kept = finalize_parts([Part("a", 10000, 20000)], CFG, guard=False, duration_s=None)
        assert (parts[0].start_ms, parts[0].end_ms) == (10000 - 300, 20000 + 500)

    def test_the_last_part_never_pads_past_the_video_end(self):
        parts, _ = finalize_parts([Part("a", 10000, 20000)], CFG, guard=False, duration_s=20.2)
        assert parts[0].end_ms == 20_200  # clamped to the duration, not 20500

    def test_merges_small_gaps_and_drops_short_parts(self):
        parts, _ = finalize_parts(
            [Part("a", 0, 5000), Part("b", 6800, 30000), Part("c", 40000, 42000)],
            CFG,
            guard=False,
            duration_s=None,
        )
        # a and b are 1.8 s apart -> one part; c is 2 s -> dropped; then the part is padded.
        assert len(parts) == 1 and parts[0].start_ms == 0 and parts[0].end_ms == 30500

    def test_padding_does_not_merge_a_gap_the_model_dropped(self):
        parts, _ = finalize_parts(
            [Part("a", 10000, 20000), Part("b", 22500, 30000)],
            CFG,
            guard=False,
            duration_s=None,
        )
        # The gap is 2.5 s, over the 2 s merge budget. Padding both sides would shrink it to
        # 1.7 s and pull the dropped material back into one part.
        assert [p.label for p in parts] == ["a", "b"]
        assert (parts[0].start_ms, parts[0].end_ms) == (9700, 20500)
        assert (parts[1].start_ms, parts[1].end_ms) == (22200, 30500)

    def test_padding_does_not_keep_a_part_under_the_minimum(self):
        parts, _ = finalize_parts(
            [Part("short", 10000, 13500), Part("long", 20000, 30000)],
            CFG,
            guard=False,
            duration_s=None,
        )
        # The short part is 3.5 s on the model's own boundaries; padding would make it 4.2 s.
        assert [p.label for p in parts] == ["long"]

    def test_keep_guard(self):
        with pytest.raises(Exception, match="remove almost everything"):
            finalize_parts([Part("a", 0, 5000)], CFG, guard=True, duration_s=600.0)
        with pytest.raises(Exception, match="Nothing to cut"):
            finalize_parts([Part("a", 0, 590_000)], CFG, guard=True, duration_s=600.0)
        # The highlights presets skip the guard.
        parts, _ = finalize_parts([Part("a", 0, 590_000)], CFG, guard=False, duration_s=600.0)
        assert parts[0].end_ms == 590_500

    def test_nothing_kept_is_refused(self):
        with pytest.raises(Exception, match="Nothing was worth keeping"):
            finalize_parts([Part("a", 0, 1000)], CFG, guard=False, duration_s=None)

    def test_guard_messages_say_what_was_found_and_what_to_try(self):
        with pytest.raises(CutRefused) as low:
            finalize_parts([Part("a", 0, 5000)], CFG, guard=True, duration_s=600.0)
        assert "0:06 of 10:00" in low.value.message
        assert "1 %" in low.value.message and "Try" in low.value.message
        with pytest.raises(CutRefused) as high:
            finalize_parts([Part("a", 0, 590_000)], CFG, guard=True, duration_s=600.0)
        assert "Nothing to cut" in high.value.message
        assert "9:50 of 10:00" in high.value.message and "Try" in high.value.message

    def test_the_upper_guard_can_be_off_while_the_lower_guard_stays(self):
        parts, _ = finalize_parts(
            [Part("a", 0, 590_000)],
            CFG,
            guard=True,
            guard_max=False,
            duration_s=600.0,
        )
        assert parts[0].end_ms == 590_500
        with pytest.raises(CutRefused, match="remove almost everything"):
            finalize_parts(
                [Part("a", 0, 5000)],
                CFG,
                guard=True,
                guard_max=False,
                duration_s=600.0,
            )

    def test_a_targeted_cut_may_keep_less_than_the_broad_guard(self):
        # "Just the answer" on a long video: a short answer is the point, not a broken cut.
        with pytest.raises(Exception, match="remove almost everything"):
            finalize_parts([Part("a", 0, 5000)], CFG, guard=True, duration_s=600.0)
        parts, _ = finalize_parts(
            [Part("a", 0, 5000)], CFG, guard=True, duration_s=600.0, min_guard=False
        )
        assert parts[0].start_ms == 0 and parts[0].end_ms == 5500

    def test_keep_guards_follow_the_preset(self):
        assert keep_guards("cut-no-filler") == (True, False)
        assert keep_guards("cut-answer") == (False, False)
        assert keep_guards("cut-demo") == (False, False)
        assert keep_guards("cut-highlights-5") == (False, False)
        assert keep_guards(None) == (False, True)
        assert keep_guards("cut-mine-abc") == (False, False)


class TestDocument:
    def test_skip_ranges_are_the_complement(self):
        doc = cut_document(
            video_id="v",
            thash="h",
            model="m",
            parts=[Part("a", 2000, 8000), Part("b", 10000, 12000)],
            summary="s",
            label="No filler",
            duration_s=20.0,
            source="preset",
            preset_id="cut-no-filler",
        )
        assert doc["skip_ranges_ms"] == [[0, 2000], [8000, 10000], [12000, 20000]]
        assert doc["kept_ms"] == 8000 and doc["duration_ms"] == 20000
        assert doc["parts"][0] == {"label": "a", "start_ms": 2000, "end_ms": 8000}

    def test_duration_falls_back_to_the_last_part(self):
        doc = cut_document(
            video_id="v",
            thash="h",
            model="m",
            parts=[Part("a", 5000, 9000)],
            summary="",
            label="l",
            duration_s=None,
            source="prompt",
            preset_id=None,
        )
        assert doc["duration_ms"] == 9000 and doc["skip_ranges_ms"] == [[0, 5000]]

    def test_transcript_hash_tracks_segments(self):
        a = transcript_hash([(0.0, 1.0, "x")])
        b = transcript_hash([(0.0, 1.0, "y")])
        assert a != b and a == transcript_hash([(0.0, 1.0, "x")])

    def test_transitions_are_an_optional_additive_field(self):
        transitions = [{"after_part": 0, "type": "fade", "duration_ms": 500, "status": "ready"}]
        doc = cut_document(
            video_id="v",
            thash="h",
            model="m",
            parts=[Part("a", 0, 1000)],
            summary="",
            label="l",
            duration_s=10.0,
            source="preset",
            preset_id=None,
            transitions=transitions,
        )
        assert doc["transitions"] == transitions
        plain = cut_document(
            video_id="v",
            thash="h",
            model="m",
            parts=[Part("a", 0, 1000)],
            summary="",
            label="l",
            duration_s=10.0,
            source="preset",
            preset_id=None,
        )
        assert "transitions" not in plain


class TestPromptFiltering:
    def test_builtin_set_carries_cut_presets(self):
        by_id = {p.id: p for p in BUILTIN_SET.prompts}
        assert set(p.id for p in by_id.values() if p.task == TASK_CUTS) == {
            "cut-no-filler",
            "cut-answer",
            "cut-demo",
            "cut-highlights-5",
        }

    def test_describe_hides_cut_presets_from_summary_pickers(self, tmp_path):
        from utubot.config import Config
        from utubot.db import Database

        store = PromptStore(Config(), Database(tmp_path / "db.sqlite"))
        doc = store.describe("owner")
        shown = {p["id"] for s in doc["sets"] for p in s["prompts"]}
        assert "cut-no-filler" not in shown and "tldr" in shown

    def test_cut_presets_are_listed_for_the_cut_engine(self, tmp_path):
        from utubot.config import Config
        from utubot.db import Database

        store = PromptStore(Config(), Database(tmp_path / "db.sqlite"))
        ids = [p.id for p in store.cut_prompts("owner")]
        assert ids == ["cut-no-filler", "cut-answer", "cut-demo", "cut-highlights-5"]

    def test_user_set_can_override_a_preset_and_add_one(self, tmp_path):
        from utubot.config import Config
        from utubot.db import Database
        from utubot.prompts import validate_prompt_set

        store = PromptStore(Config(), Database(tmp_path / "db.sqlite"))
        pset = validate_prompt_set(
            {
                "tubeai_prompt_set": 1,
                "id": "mine",
                "name": "Mine",
                "prompts": [
                    {
                        "id": "cut-demo",
                        "label": "Only the demo, strict",
                        "template": "Only the demo, nothing else at all.",
                        "task": "cuts",
                    },
                    {
                        "id": "cut-lectures",
                        "label": "Lectures only",
                        "template": "Keep the lecture segments.",
                        "task": "cuts",
                    },
                ],
            }
        )
        store.save_set("owner", pset)
        mine = {p.id: p for p in store.cut_prompts("owner")}
        assert mine["cut-demo"].label == "Only the demo, strict"
        assert "cut-lectures" in mine

    def test_a_cut_preset_cannot_become_a_summary_default(self, tmp_path):
        from utubot.config import Config
        from utubot.db import Database
        from utubot.prompts import PromptError

        store = PromptStore(Config(), Database(tmp_path / "db.sqlite"))
        with pytest.raises(PromptError, match="cut preset"):
            store.set_default("owner", "builtin/cut-no-filler")
        with pytest.raises(PromptError, match="panel prompt"):
            store.set_panel_default("owner", "builtin/cut-no-filler")

    def test_preset_content_hash_changes_with_the_instruction(self):
        from utubot.prompts import cut_preset_prompt

        base = cut_preset_prompt("no-filler")
        changed = base.model_copy(update={"template": base.template + " Also cut teasers."})
        assert base.content_hash() != changed.content_hash()

    def test_user_cannot_set_an_unknown_task_on_a_prompt(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Prompt(id="x", label="x", template="t", task="nope")


def eleven_minute_units() -> list[Unit]:
    """66 units of 10 s (11 min), one unit per number, back to back."""
    return [Unit(n, (n - 1) * 10.0, n * 10.0, f"unit {n}") for n in range(1, 67)]


def ranked(units: list[Unit], spans: list[tuple[int, int, int | None]]) -> list[Part]:
    answer = {
        "parts": [
            {"from": a, "to": b, "label": f"p{a}", **({"rank": r} if r is not None else {})}
            for a, b, r in spans
        ]
    }
    return parse_cut_answer(answer, units)


class TestTargetLength:
    def test_band_is_target_plus_minus_tolerance(self):
        assert target_band(300, 0.15) == (255.0, 345.0)

    def test_eleven_minutes_for_a_five_minute_preset_lands_in_the_band(self):
        units = eleven_minute_units()
        # 11 parts of 60 s, importance not in video order.
        spans = [
            (i * 6 + 1, i * 6 + 6, r) for i, r in enumerate([5, 1, 9, 3, 11, 2, 8, 4, 10, 6, 7])
        ]
        chosen, total = select_for_target(ranked(units, spans), units, CFG, 300)
        low, high = target_band(300, CFG.length_tolerance)
        assert low <= total <= high
        assert [p.start_ms for p in chosen] == sorted(p.start_ms for p in chosen)

    def test_lowest_ranked_parts_go_first(self):
        units = eleven_minute_units()
        spans = [
            (i * 6 + 1, i * 6 + 6, r) for i, r in enumerate([5, 1, 9, 3, 11, 2, 8, 4, 10, 6, 7])
        ]
        chosen, _ = select_for_target(ranked(units, spans), units, CFG, 300)
        kept_ranks = {p.rank for p in chosen}
        assert {1, 2, 3, 4}.issubset(kept_ranks)
        assert not kept_ranks & {9, 10, 11}

    def test_last_selected_part_is_trimmed_at_a_unit_boundary(self):
        units = eleven_minute_units()
        # Two 200 s parts: the second (rank 2) must shrink to fit the 345 s ceiling.
        parts = ranked(units, [(1, 20, 1), (31, 50, 2)])
        chosen, total = select_for_target(parts, units, CFG, 300)
        assert total <= 345.0
        assert chosen[1].last < 50 and chosen[1].end_ms == int(units[chosen[1].last - 1].end * 1000)
        assert chosen[1].first == 31

    def test_old_format_without_ranks_counts_in_video_order(self):
        units = eleven_minute_units()
        spans = [(i * 6 + 1, i * 6 + 6, None) for i in range(11)]
        chosen, total = select_for_target(ranked(units, spans), units, CFG, 300)
        low, high = target_band(300, CFG.length_tolerance)
        assert low <= total <= high
        assert chosen[0].first == 1  # the earliest parts survive

    def test_duplicate_ranks_keep_video_order(self):
        units = eleven_minute_units()
        ranks = [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4]
        spans = [(i * 6 + 1, i * 6 + 6, r) for i, r in enumerate(ranks)]
        chosen, _ = select_for_target(ranked(units, spans), units, CFG, 300)
        # The three rank-1 parts come in video order, then the first two rank-2 parts.
        assert [p.first for p in chosen] == [1, 7, 13, 19, 25]

    def test_out_of_range_ranks_still_make_a_banded_selection(self):
        units = eleven_minute_units()
        ranks = [0, -3, 999, 500, 2, 4, 3, 6, 5, 8, 7]
        spans = [(i * 6 + 1, i * 6 + 6, r) for i, r in enumerate(ranks)]
        chosen, total = select_for_target(ranked(units, spans), units, CFG, 300)
        low, high = target_band(300, CFG.length_tolerance)
        assert low <= total <= high
        assert [p.start_ms for p in chosen] == sorted(p.start_ms for p in chosen)

    def test_many_close_parts_finalize_inside_the_band(self):
        units = [Unit(n, n - 1.0, float(n), f"u{n}") for n in range(1, 661)]
        # 5 s parts with 2 s gaps: padding turns the gaps under merge_gap_s, so finalization
        # merges them and adds the gaps back to the kept length.
        spans = [(i * 7 + 1, i * 7 + 5, i + 1) for i in range(93)]
        chosen, total = select_for_target(ranked(units, spans), units, CFG, 300, duration_s=660.0)
        kept, kept_s = finalize_parts(chosen, CFG, guard=False, duration_s=660.0)
        low, high = target_band(300, CFG.length_tolerance)
        assert kept and low <= kept_s <= high
        assert total == kept_s

    def test_a_video_at_the_top_of_the_band_needs_no_target(self):
        assert effective_target_s(CFG, "cut-highlights-5", 345.0) is None
        assert effective_target_s(CFG, "cut-highlights-5", 345.1) == 300

    def test_an_answer_below_the_band_comes_back_whole_and_short(self):
        units = eleven_minute_units()
        parts = ranked(units, [(1, 6, 1), (11, 16, 2)])
        chosen, total = select_for_target(parts, units, CFG, 300)
        assert len(chosen) == 2 and total < target_band(300, CFG.length_tolerance)[0]

    def test_prompt_names_the_target_and_asks_for_ranks(self):
        units = eleven_minute_units()
        text = serialize_units(units, [], {"duration_s": 660}, "Highlights", 300, 0.2)
        assert "Target length: 300 s" in text and "360 s" in text and "rank" in text
        assert "Target length" not in serialize_units(units, [], {}, "Highlights")

    def test_cut_document_carries_target_and_kept_seconds(self):
        doc = cut_document(
            video_id="v",
            thash="h",
            model="m",
            parts=[Part("a", 0, 305_000)],
            summary="",
            label="Highlights",
            duration_s=660,
            source="preset",
            preset_id="cut-highlights-5",
            target_s=300,
        )
        assert doc["target_s"] == 300 and doc["kept_s"] == 305.0


def long_units(n: int, seconds: float = 10.0) -> list[Unit]:
    return [
        Unit(i + 1, i * seconds, (i + 1) * seconds, f"Sentence number {i + 1}.") for i in range(n)
    ]


class TestChunks:
    def test_every_unit_lands_in_exactly_one_core_and_the_overlap_repeats_the_tail(self):
        units = long_units(200)
        chunks = plan_chunks(units, [], 2000, 3)
        assert len(chunks) > 3
        cores = [u.n for c in chunks for u in c.core]
        assert cores == [u.n for u in units]
        for prev, chunk in zip(chunks, chunks[1:], strict=False):
            shared = [u.n for u in chunk.units if u.n < chunk.core_first]
            assert shared == [u.n for u in prev.units][-3:]
        assert [u.n for u in chunks[0].units][0] == 1

    def test_no_excerpt_is_over_the_budget(self):
        units = long_units(300)
        budget = 2500
        for chunk in plan_chunks(units, [], budget, 4):
            assert sum(len(unit_line(u)) + 1 for u in chunk.units) <= budget

    def test_chunks_start_on_chapter_boundaries(self):
        units = long_units(120)  # 1200 s
        chapters = [(0.0, "Intro"), (400.0, "Middle"), (800.0, "End")]
        # Room for about 45 units: each 40-unit chapter fits alone, two together do not.
        cost = len(unit_line(units[0])) + 1
        chunks = plan_chunks(units, chapters, cost * 45, 0)
        assert [c.core_first for c in chunks] == [1, 41, 81]
        for chunk in chunks:
            assert chunk.units[0].n == chunk.core_first

    def test_small_chapters_are_packed_together(self):
        units = long_units(120)
        chapters = [(i * 100.0, f"C{i}") for i in range(12)]
        cost = len(unit_line(units[0])) + 1
        chunks = plan_chunks(units, chapters, cost * 45, 0)
        assert len(chunks) == 3
        assert all(c.core_first - 1 in (0, 40, 80) for c in chunks)

    def test_a_chapter_over_the_budget_is_split_evenly(self):
        units = long_units(100)
        cost = len(unit_line(units[0])) + 1
        chunks = plan_chunks(units, [(0.0, "All")], cost * 30, 0)
        sizes = [len(c.units) for c in chunks]
        assert len(chunks) >= 4 and max(sizes) <= 30 and min(sizes) >= 20

    def test_chapters_between_keeps_the_running_one(self):
        chapters = [(0.0, "A"), (100.0, "B"), (200.0, "C"), (300.0, "D")]
        assert chapters_between(chapters, 150.0, 250.0) == [(100.0, "B"), (200.0, "C")]
        assert chapters_between([], 0.0, 10.0) == []


class TestCandidates:
    def parts(self):
        return [
            Part("Late", 0, 1000, 2, 1, 2),
            Part("Best", 2000, 3000, 1, 3, 4),
            Part("Unranked", 4000, 5000, None, 5, 6),
        ]

    def test_ranks_count_inside_the_excerpt(self):
        cands = candidates_from(self.parts())
        assert [(c.label, c.rank, c.of) for c in cands] == [
            ("Late", 2, 3),
            ("Best", 1, 3),
            ("Unranked", 3, 3),
        ]

    def test_overlapping_candidates_of_neighbouring_excerpts_become_one(self):
        a = Candidate(10, 20, "Weak", 3, 4)
        b = Candidate(18, 30, "Strong", 1, 4)
        c = Candidate(40, 45, "Other", 2, 4)
        merged = merge_candidates([c, b, a])
        assert [(m.first, m.last, m.label) for m in merged] == [
            (10, 30, "Strong"),
            (40, 45, "Other"),
        ]

    def test_candidate_lines_show_range_label_rank_and_a_short_text(self):
        units = long_units(10)
        shown = candidate_units([Candidate(2, 4, "Demo", 1, 5)], units, 20)
        assert [u.n for u in shown] == [1]
        assert (shown[0].start, shown[0].end) == (10.0, 40.0)
        assert "Demo (rank 1 of 5 in its excerpt)" in shown[0].text
        assert shown[0].text.endswith("...")

    def test_a_reduce_answer_expands_to_one_part_per_candidate(self):
        units = long_units(20)
        cands = [
            Candidate(1, 2, "A", 1, 3),
            Candidate(5, 6, "B", 2, 3),
            Candidate(9, 10, "C", 3, 3),
        ]
        shown = candidate_units(cands, units, 50)
        data = {"parts": [{"from": 1, "to": 2, "rank": 1}, {"from": 3, "to": 3, "rank": 2}]}
        parts = expand_candidate_parts(parse_cut_answer(data, shown), cands, units)
        assert [(p.label, p.start_ms, p.end_ms, p.rank) for p in parts] == [
            ("A", 0, 20000, 1),
            ("B", 40000, 60000, 1),
            ("C", 80000, 100000, 2),
        ]  # the gap between A and B is not kept

    def test_candidates_split_into_groups_that_fit(self):
        units = long_units(100)
        cands = [Candidate(i * 2 + 1, i * 2 + 2, "P", 1, 1) for i in range(40)]
        groups = split_candidates(cands, units, 600, 30)
        assert sum(len(g) for g in groups) == 40 and len(groups) > 3
        assert [c for g in groups for c in g] == cands


class TestExcerptParsing:
    def test_an_excerpt_answer_uses_the_transcript_ids(self):
        units = long_units(50)[20:30]  # ids 21..30
        parts = parse_cut_answer({"parts": [{"from": 22, "to": 24, "rank": 1}]}, units)
        assert (parts[0].first, parts[0].last, parts[0].start_ms) == (22, 24, 210_000)
        with pytest.raises(CutFormatError, match="21-30"):
            parse_cut_answer({"parts": [{"from": 5, "to": 8}]}, units)

    def test_an_excerpt_may_have_nothing_to_propose(self):
        units = long_units(5)
        assert parse_cut_answer({"parts": []}, units, allow_empty=True) == []
        with pytest.raises(CutFormatError):
            parse_cut_answer({"parts": []}, units)

    def test_the_excerpt_note_and_scope_reach_the_prompt(self):
        text = serialize_units(
            long_units(3),
            [],
            {},
            "Highlights",
            60,
            0.2,
            note="EXCERPT NOTE",
            scope="from this excerpt",
        )
        assert "EXCERPT NOTE" in text and "Target length: 60 s kept from this excerpt" in text
