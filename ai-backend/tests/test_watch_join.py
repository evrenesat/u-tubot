from __future__ import annotations

from utubot.config import CutsConfig, WatchedCutsConfig
from utubot.cuts import Part, build_units
from utubot.watch.join import (
    NO_SPEECH,
    assign_unit_ids,
    scene_lines,
    snap_parts,
    watched_serialize,
    watched_units,
)


def tdt(segments: list[dict]) -> dict:
    return {"format": "tdt", "format_version": "1.0-utubot", "segments": segments}


def segment(start: float, end: float, kind: str, summary: str, same: bool = False) -> dict:
    return {
        "segment_id": f"S{start}",
        "grid_filename": f"scene{start}.jpg",
        "start": start,
        "end": end,
        "visual_summary": summary,
        "labels": {
            "kind": kind,
            "on_screen_text": "",
            "same_as_previous": same,
        },
    }


class TestWatchedUnits:
    def test_silent_gaps_become_units(self):
        segments = [(0.0, 2.0, "intro."), (10.0, 12.0, "then it works."), (20.0, 22.0, "bye.")]
        doc = tdt(
            [
                segment(0.0, 5.0, "talking_head", "A person talks."),
                segment(5.0, 10.0, "demo", "A terminal runs a build."),
                segment(10.0, 15.0, "screen", "The build stops."),
                segment(15.0, 22.0, "other", "A desk."),
            ]
        )
        units = watched_units(segments, doc, WatchedCutsConfig(), duration_s=22.0, cuts_cfg=CutsConfig())
        numbers = [unit.n for unit in units]
        assert numbers == list(range(1, len(units) + 1))
        assert any(unit.text == NO_SPEECH for unit in units)
        silent = [unit for unit in units if unit.text == NO_SPEECH]
        assert silent[0].start == 2.0 and silent[0].end > 2.0

    def test_scene_lines_collapse_same_kind(self):
        doc = tdt(
            [
                segment(0.0, 5.0, "screen", "A slide."),
                segment(5.0, 10.0, "screen", "The same slide.", same=True),
                segment(10.0, 15.0, "demo", "A demo."),
            ]
        )
        lines = scene_lines(doc)
        assert lines[0].start == 0.0 and lines[0].end == 10.0
        assert [line.kind for line in lines] == ["screen", "demo"]

    def test_serialize_interleaves_scenes_and_units(self):
        segments = [(1.0, 3.0, "hello there.")]
        doc = tdt([segment(0.0, 5.0, "screen", "A slide.", False)])
        units = watched_units(segments, doc, WatchedCutsConfig(), duration_s=5.0, cuts_cfg=CutsConfig())
        text = watched_serialize(units, scene_lines(doc), [], {"title": "T", "duration_s": 5}, "Keep it")
        lines = text.splitlines()
        scene_at = next(index for index, line in enumerate(lines) if line.startswith("S1 "))
        unit_at = next(index for index, line in enumerate(lines) if line.startswith("#1 "))
        assert scene_at < unit_at
        assert "A slide." in lines[scene_at]

    def test_assigns_each_unit_to_the_segment_it_overlaps_most(self):
        segments = [(2.0, 4.0, "spoken.")]
        doc = tdt(
            [
                segment(0.0, 3.0, "screen", "First."),
                segment(3.0, 6.0, "screen", "Second."),
            ]
        )
        units = build_units(segments, CutsConfig())
        ids = assign_unit_ids(units, doc)
        assert ids[1] == [1] and ids[2] == []


class TestSnap:
    def test_moves_outward_to_a_cut_without_crossing_speech(self):
        cfg = CutsConfig()
        units = build_units([(10.0, 12.0, "the demo works.")], cfg)
        parts = [Part("Demo", 10000, 12000)]
        snapped = snap_parts(parts, [9.5, 12.5, 11.0], units, 1.0)
        assert (snapped[0].start_ms, snapped[0].end_ms) == (9500, 12500)

    def test_never_moves_across_a_speech_unit(self):
        cfg = CutsConfig()
        units = build_units([(8.0, 12.0, "the demo works.")], cfg)
        parts = [Part("Demo", 10000, 12000)]
        snapped = snap_parts(parts, [9.5, 12.5], units, 1.0)
        assert (snapped[0].start_ms, snapped[0].end_ms) == (10000, 12000)
