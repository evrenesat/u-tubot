from __future__ import annotations

import pytest

from utubot.config import CutsConfig
from utubot.cuts import (
    CutFormatError,
    Part,
    Unit,
    build_units,
    cut_document,
    finalize_parts,
    parse_chapters,
    parse_cut_answer,
    transcript_hash,
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
        # a and b are 1.8 s apart (minus padding) -> one part; c is 2 s -> dropped.
        assert len(parts) == 1 and parts[0].start_ms == 0 and parts[0].end_ms == 30500

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
