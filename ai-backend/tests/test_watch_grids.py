from __future__ import annotations

import pytest
from PIL import Image

from tests.synth_video import CUTS, DURATION_S, ffmpeg_available, make_video
from utubot.config import CutsConfig
from utubot.watch.frame_selector import AnalyzedFrame, derive_thresholds
from utubot.watch.grids import _budget_split, build_grid_plan, chunk_plan

NINETY_MINUTES = 90 * 60


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg is required")
class TestSyntheticGrids:
    def test_every_hard_cut_is_a_chunk_end_or_recorded(self, tmp_path):
        video = make_video(tmp_path)
        cfg = CutsConfig().watched
        plan = build_grid_plan(str(video), cfg, tmp_path / "run")
        assert plan.duration_s == pytest.approx(DURATION_S, abs=1.0)
        for cut in CUTS:
            found = [
                chunk
                for chunk in plan.chunks
                if chunk.start <= cut <= chunk.end
                and (
                    abs(chunk.end - cut) <= 0.5
                    or any(abs(value - cut) <= 0.5 for value in chunk.source_scene_cut_times)
                )
            ]
            assert found, f"hard cut at {cut} is neither a chunk end nor in a chunk's cut list"

    def test_grids_are_two_by_two_with_512_cells(self, tmp_path):
        video = make_video(tmp_path)
        cfg = CutsConfig().watched
        plan = build_grid_plan(str(video), cfg, tmp_path / "run")
        assert plan.manifest, "a 60 s clip must produce grids"
        for row in plan.manifest:
            path = plan.grid_dir / "grids" / row.grid_filename
            with Image.open(path) as image:
                assert image.width <= 2 * cfg.grid_cell_max_px
                assert image.height <= 2 * cfg.grid_cell_max_px
            assert len(row.selected_timestamps) == 4
            assert row.chunk_start < row.chunk_end
            assert row.chunk_end - row.chunk_start <= cfg.quiet_max_chunk_s + 1e-6

    def test_cap_split_keeps_a_90_minute_video_under_240_grids(self):
        cfg = CutsConfig().watched.model_copy(update={"cap_steps": 0})
        frames = [
            AnalyzedFrame(
                index=index,
                timestamp=index / cfg.analysis_fps,
                mean_luma=90.0,
                black_frame=False,
                sharpness=12.0,
                motion=0.0,
                novelty=0.0,
                dhash=0,
            )
            for index in range(int(NINETY_MINUTES * cfg.analysis_fps))
        ]
        cuts = [float(at) for at in range(4, NINETY_MINUTES, 4)]
        thresholds = derive_thresholds(frames, cfg)
        chunks, selections, coarse, steps = chunk_plan(
            float(NINETY_MINUTES), frames, cuts, thresholds, cfg
        )
        assert len(chunks) <= cfg.max_grids
        assert coarse in (True, False)
        assert steps >= 0
        assert len(selections) == len(chunks)
        assert chunks[0].start == 0.0 and chunks[-1].end == pytest.approx(NINETY_MINUTES)
        assert all(right.start == left.end for left, right in zip(chunks, chunks[1:], strict=False))
        budget = _budget_split(float(NINETY_MINUTES), cuts, frames, thresholds, cfg, cfg.max_grids)
        assert len(budget) == cfg.max_grids
        assert budget[0].start == 0.0 and budget[-1].end == pytest.approx(NINETY_MINUTES)
