from __future__ import annotations

import pytest

from utubot.config import WatchedCutsConfig
from utubot.watch.grids import ManifestRow
from utubot.watch.tdt import (
    DescribeFormatError,
    SceneAnalysis,
    assemble,
    parse_description,
    validate_tdt,
)


def row(start: float, end: float, name: str = "a.jpg") -> ManifestRow:
    return ManifestRow(
        grid_filename=name,
        chunk_start=start,
        chunk_end=end,
        selected_timestamps=[start, start + 1, start + 2, start + 3],
        selected_scores=[0.1, 0.2, 0.3, 0.4],
        activity_class="calm",
        low_variation=False,
        source_scene_cut_times=[],
    )


class TestDescribeAnswer:
    def test_parses_the_watched_format(self):
        scene = parse_description(
            {
                "visual_summary": "A terminal shows a failed linker.",
                "kind": "screen",
                "on_screen_text": "error: linker failed",
                "same_as_previous": False,
            }
        )
        assert scene.kind == "screen" and scene.visual_summary
        assert scene.seen

    def test_rejects_an_unknown_kind_and_long_text(self):
        with pytest.raises(DescribeFormatError):
            parse_description(
                {"visual_summary": "x", "kind": "film", "on_screen_text": "", "same_as_previous": False}
            )
        with pytest.raises(DescribeFormatError):
            parse_description(
                {
                    "visual_summary": "x" * 241,
                    "kind": "other",
                    "on_screen_text": "",
                    "same_as_previous": False,
                }
            )


class TestTdt:
    def test_assembles_aligned_segments_and_validates(self):
        rows = [row(0.0, 5.0), row(5.0, 10.0, "b.jpg")]
        analyses = {
            "a.jpg": SceneAnalysis("A slide.", "slide", "Title", False),
            "b.jpg": SceneAnalysis("A demo.", "demo", "", True),
        }
        payload = assemble(
            video_sha256="sha",
            settings_key="set",
            model="vision",
            prompt_hash="ph",
            scene_cuts=[5.0],
            rows=rows,
            analyses=analyses,
        )
        assert validate_tdt(payload, rows) == []
        assert [segment["start"] for segment in payload["segments"]] == [0.0, 5.0]
        assert [segment["labels"]["kind"] for segment in payload["segments"]] == ["slide", "demo"]

    def test_an_unseen_segment_is_valid_but_empty(self):
        rows = [row(0.0, 5.0)]
        payload = assemble(
            video_sha256="sha",
            settings_key="set",
            model="vision",
            prompt_hash="ph",
            scene_cuts=[],
            rows=rows,
            analyses={},
        )
        assert validate_tdt(payload, rows) == []
        provenance = payload["segments"][0]["analysis_provenance"]
        assert provenance["seen"] is False

    def test_validator_rejects_a_misaligned_segment(self):
        rows = [row(0.0, 5.0)]
        payload = assemble(
            video_sha256="sha",
            settings_key="set",
            model="vision",
            prompt_hash="ph",
            scene_cuts=[],
            rows=rows,
            analyses={"a.jpg": SceneAnalysis("x", "other", "", False)},
        )
        payload["segments"][0]["start"] = 1.0
        assert any("start does not match" in error for error in validate_tdt(payload, rows))
