"""Shot boundaries, chunk windows, the quiet-stretch rule, the grid cap and 2x2 grid writing.

Copied and adapted from `evrenesat/r2t4` (`scene-analyser/extractor_v1.py` and the grid pieces of
`frame_selector.py` at commit 29075554; by the repository owner, contributed under MIT). The CLI
and run directories are gone: the caller supplies the scratch directory, `[cuts.watched]` holds
the thresholds, and a cancel event stops the child ffmpeg. Two rules are new for YouTube:
consecutive still stretches share one grid, and every video within the length limit fits
`max_grids` by raising the chunk lengths and finally splitting the budget.
"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from ..config import GRID_PLAN_VERSION, WatchedCutsConfig
from . import ffmpeg
from .frame_selector import (
    AnalyzedFrame,
    ChunkWindow,
    SelectedFrame,
    analyze_video_lowres,
    build_adaptive_chunks,
    build_diagnostics_summary,
    derive_thresholds,
    select_chunk_frames,
    window_activity,
)

GRID_COLS = 2
GRID_ROWS = 2
GRIDS_DIRNAME = "grids"
FRAME_DIRNAME = "frames"
EXTRACT_WORKERS = 4
SCENE_CUT_PROBE_TIMEOUT_S = 1800.0
FRAME_EXTRACT_TIMEOUT_S = 120.0
ANALYSIS_TIMEOUT_S = 1800.0
GRID_DIRS = (GRIDS_DIRNAME, FRAME_DIRNAME)


@dataclass
class ManifestRow:
    grid_filename: str
    chunk_start: float
    chunk_end: float
    selected_timestamps: list[float]
    selected_scores: list[float]
    activity_class: str
    low_variation: bool
    source_scene_cut_times: list[float]
    preset: str = "balanced"

    def as_dict(self) -> dict[str, Any]:
        return {
            "grid_filename": self.grid_filename,
            "chunk_start": self.chunk_start,
            "chunk_end": self.chunk_end,
            "selected_timestamps": self.selected_timestamps,
            "selected_scores": self.selected_scores,
            "preset": self.preset,
            "activity_class": self.activity_class,
            "low_variation": self.low_variation,
            "source_scene_cut_times": self.source_scene_cut_times,
        }


@dataclass
class GridPlan:
    """The finished grid stage: chunks and manifest; grid files live under `grid_dir`."""

    duration_s: float
    scene_cuts: list[float]
    chunks: list[ChunkWindow]
    manifest: list[ManifestRow]
    grid_dir: Path
    coarse: bool = False
    cap_steps: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def row_for(self, filename: str) -> ManifestRow | None:
        return next((row for row in self.manifest if row.grid_filename == filename), None)

    def as_manifest_dict(self) -> list[dict[str, Any]]:
        return [row.as_dict() for row in self.manifest]


def settings_key(cfg: WatchedCutsConfig) -> str:
    """The grid settings an analysis was made with; a change invalidates `video_scenes`."""
    fields = (
        "scene_threshold",
        "analysis_fps",
        "analysis_width",
        "min_chunk_s",
        "max_chunk_s",
        "quiet_max_chunk_s",
        "cut_merge_s",
        "min_frame_distance",
        "black_frame_luma",
        "grid_cell_max_px",
        "max_grids",
        "cap_growth",
        "cap_steps",
    )
    payload = {"version": GRID_PLAN_VERSION, **{name: getattr(cfg, name) for name in fields}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def merge_scene_cuts(scene_cuts: list[float], merge_window_s: float) -> list[dict[str, Any]]:
    """scene-analyser's `merge_scene_cuts`: nearby cuts become one region."""
    if not scene_cuts:
        return []
    regions: list[dict[str, Any]] = []
    current = {"start": scene_cuts[0], "end": scene_cuts[0], "cuts": [scene_cuts[0]]}
    for cut in scene_cuts[1:]:
        if cut - current["end"] <= merge_window_s:
            current["end"] = cut
            current["cuts"].append(cut)
            continue
        regions.append(current)
        current = {"start": cut, "end": cut, "cuts": [cut]}
    regions.append(current)
    return regions


def _with_quiet_stretches(
    chunks: list[ChunkWindow],
    frames: list[AnalyzedFrame],
    scene_cuts: list[float],
    thresholds: dict[str, float],
    cfg: WatchedCutsConfig,
) -> tuple[list[ChunkWindow], list[tuple[list[SelectedFrame], bool]]]:
    """Join consecutive low-variation chunks up to `quiet_max_chunk_s` and re-select over each.

    The original low-variation flag is the same test the copied selector uses; a stretch that is
    still joins its frames took one grid instead of one per chunk (a talking head costs about
    1.3 grids a minute instead of 4).
    """
    selections: list[tuple[list[SelectedFrame], bool]] = [
        select_chunk_frames(chunk, frames, scene_cuts, thresholds, cfg) for chunk in chunks
    ]
    out_chunks: list[ChunkWindow] = []
    out_selections: list[tuple[list[SelectedFrame], bool]] = []
    index = 0
    while index < len(chunks):
        chunk = chunks[index]
        chosen, low = selections[index]
        if not low:
            out_chunks.append(chunk)
            out_selections.append((chosen, low))
            index += 1
            continue
        end = chunk.end
        cuts = list(chunk.source_scene_cut_times)
        hard_cuts = {round(value, 6) for value in scene_cuts}
        index += 1
        while index < len(chunks) and selections[index][1] and chunks[index].start <= end + 1e-6:
            if round(chunks[index].start, 6) in hard_cuts and index > 0:
                break
            candidate_end = chunks[index].end
            if candidate_end - chunk.start > cfg.quiet_max_chunk_s:
                break
            end = candidate_end
            cuts.extend(chunks[index].source_scene_cut_times)
            index += 1
        joined = ChunkWindow(
            chunk_index=len(out_chunks) + 1,
            start=chunk.start,
            end=end,
            activity_class="calm",
            source_scene_cut_times=cuts,
        )
        picked, joined_low = select_chunk_frames(joined, frames, scene_cuts, thresholds, cfg)
        out_chunks.append(joined)
        out_selections.append((picked, joined_low))
    for number, chunk in enumerate(out_chunks, 1):
        out_chunks[number - 1] = ChunkWindow(
            chunk_index=number,
            start=chunk.start,
            end=chunk.end,
            activity_class=chunk.activity_class,
            source_scene_cut_times=chunk.source_scene_cut_times,
        )
    return out_chunks, out_selections


def _budget_split(
    duration: float,
    scene_cuts: list[float],
    frames: list[AnalyzedFrame],
    thresholds: dict[str, float],
    cfg: WatchedCutsConfig,
    limit: int,
) -> list[ChunkWindow]:
    """The last cap step: equal windows of `duration / max_grids` seconds, ends moved to a cut."""
    cuts = sorted(cut for cut in scene_cuts if 0.0 < cut < duration)
    width = duration / max(1, limit)
    chunks: list[ChunkWindow] = []
    start = 0.0
    for number in range(1, limit + 1):
        end = duration if number == limit else start + width
        if number != limit:
            near = [cut for cut in cuts if abs(cut - end) <= cfg.cut_merge_s]
            if near:
                end = min(near, key=lambda cut: abs(cut - end))
        chunk_cuts = [cut for cut in cuts if start < cut < end]
        window_frames = [frame for frame in frames if start <= frame.timestamp <= end]
        activity = "calm"
        if window_frames:
            activity = str(
                window_activity(frames, cuts, [], thresholds, start, end)["activity_class"]
            )
        chunks.append(
            ChunkWindow(
                chunk_index=number,
                start=start,
                end=end,
                activity_class=activity,
                source_scene_cut_times=chunk_cuts,
            )
        )
        start = end
    return chunks


def chunk_plan(
    duration: float,
    frames: list[AnalyzedFrame],
    scene_cuts: list[float],
    thresholds: dict[str, float],
    cfg: WatchedCutsConfig,
) -> tuple[list[ChunkWindow], list[tuple[list[SelectedFrame], bool]], bool, int]:
    """Chunks that always fit `max_grids`; returns (chunks, selections, coarse, cap_steps)."""
    regions = merge_scene_cuts(scene_cuts, cfg.cut_merge_s)
    min_s, max_s, quiet_s = cfg.min_chunk_s, cfg.max_chunk_s, cfg.quiet_max_chunk_s
    steps = 0
    for steps in range(0, cfg.cap_steps + 1):
        local = cfg.model_copy(
            update={"min_chunk_s": min_s, "max_chunk_s": max_s, "quiet_max_chunk_s": quiet_s}
        )
        base = build_adaptive_chunks(duration, frames, scene_cuts, regions, local, thresholds)
        chunks, selections = _with_quiet_stretches(base, frames, scene_cuts, thresholds, local)
        if len(chunks) <= cfg.max_grids:
            return chunks, selections, False, steps
        min_s *= cfg.cap_growth
        max_s *= cfg.cap_growth
        quiet_s *= cfg.cap_growth
    budget = _budget_split(duration, scene_cuts, frames, thresholds, cfg, cfg.max_grids)
    selections = [
        select_chunk_frames(chunk, frames, scene_cuts, thresholds, cfg) for chunk in budget
    ]
    return budget, selections, True, steps


def _extract_frame(
    video_path: str, timestamp: float, output_path: Path, cfg: WatchedCutsConfig, cancel
) -> None:
    ffmpeg.run(
        [
            "-v",
            "error",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ],
        cancel=cancel,
        threads=cfg.ffmpeg_threads,
        timeout_s=FRAME_EXTRACT_TIMEOUT_S,
    )
    if not output_path.is_file():
        raise ffmpeg.FfmpegError("ffmpeg did not produce the extracted frame")


def create_grid(image_paths: list[Path], output_path: Path, cfg: WatchedCutsConfig) -> None:
    images: list[Image.Image] = []
    for image_path in image_paths:
        image = Image.open(image_path)
        image.thumbnail((cfg.grid_cell_max_px, cfg.grid_cell_max_px), Image.Resampling.LANCZOS)
        images.append(image.copy())
        image.close()
    frame_width, frame_height = images[0].size
    grid = Image.new("RGB", (GRID_COLS * frame_width, GRID_ROWS * frame_height))
    for index, image in enumerate(images):
        grid.paste(image, ((index % GRID_COLS) * frame_width, (index // GRID_COLS) * frame_height))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    grid.save(output_path)


def _safe_label(value: float) -> str:
    return f"{value:.1f}".replace(".", "_")


def render_manifest(
    manifest: list[dict[str, Any]],
    video_path: str,
    grid_dir: Path,
    cfg: WatchedCutsConfig,
    cancel: threading.Event | None,
) -> list[ManifestRow]:
    """Write 2x2 grids for manifest rows that have no file yet; no low-resolution pass.

    A cached manifest is reused after a restart or by another preset: only the frames and the
    grids are rebuilt (they are scratch and removed after describing).
    """
    rows: list[ManifestRow] = []
    frame_dir = grid_dir / FRAME_DIRNAME
    frame_dir.mkdir(parents=True, exist_ok=True)
    for raw in manifest:
        row = ManifestRow(
            grid_filename=str(raw["grid_filename"]),
            chunk_start=float(raw["chunk_start"]),
            chunk_end=float(raw["chunk_end"]),
            selected_timestamps=[float(v) for v in raw["selected_timestamps"]],
            selected_scores=[float(v) for v in raw["selected_scores"]],
            activity_class=str(raw["activity_class"]),
            low_variation=bool(raw["low_variation"]),
            source_scene_cut_times=[float(v) for v in raw["source_scene_cut_times"]],
            preset=str(raw.get("preset") or "balanced"),
        )
        path = grid_dir / GRIDS_DIRNAME / row.grid_filename
        if not path.is_file():
            temp: list[Path] = []
            with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS) as pool:
                futures = []
                for index, at in enumerate(row.selected_timestamps):
                    target = frame_dir / f"temp_chunk{index}_frame{index}.jpg"
                    temp.append(target)
                    futures.append(pool.submit(_extract_frame, video_path, at, target, cfg, cancel))
                for future in futures:
                    future.result()
            create_grid(temp, path, cfg)
            for target in temp:
                target.unlink(missing_ok=True)
        rows.append(row)
    return rows


def build_grid_plan(
    video_path: str,
    cfg: WatchedCutsConfig,
    grid_dir: Path,
    *,
    cancel: threading.Event | None = None,
    cached_scene_cuts: list[float] | None = None,
    cached_manifest: list[dict[str, Any]] | None = None,
    cached_coarse: bool = False,
    cached_cap_steps: int = 0,
) -> GridPlan:
    """The whole grid stage, blocking (the caller runs it in one worker thread)."""
    grid_dir.mkdir(parents=True, exist_ok=True)
    duration = ffmpeg.video_duration(
        video_path, cancel=cancel, threads=cfg.ffmpeg_threads, timeout_s=SCENE_CUT_PROBE_TIMEOUT_S
    )
    if cached_scene_cuts is not None and cached_manifest is not None:
        rows = render_manifest(cached_manifest, video_path, grid_dir, cfg, cancel)
        return GridPlan(
            duration_s=duration,
            scene_cuts=list(cached_scene_cuts),
            chunks=[
                ChunkWindow(
                    chunk_index=index + 1,
                    start=row.chunk_start,
                    end=row.chunk_end,
                    activity_class=row.activity_class,
                    source_scene_cut_times=row.source_scene_cut_times,
                )
                for index, row in enumerate(rows)
            ],
            manifest=rows,
            grid_dir=grid_dir,
            coarse=cached_coarse,
            cap_steps=cached_cap_steps,
        )
    scene_cuts = ffmpeg.scene_cuts(
        video_path,
        cfg.scene_threshold,
        cancel=cancel,
        threads=cfg.ffmpeg_threads,
        timeout_s=SCENE_CUT_PROBE_TIMEOUT_S,
    )
    frames = analyze_video_lowres(video_path, cfg, cancel=cancel, timeout_s=ANALYSIS_TIMEOUT_S)
    thresholds = derive_thresholds(frames, cfg)
    chunks, selections, coarse, steps = chunk_plan(duration, frames, scene_cuts, thresholds, cfg)
    rows: list[ManifestRow] = []
    grid_root = grid_dir / GRIDS_DIRNAME
    frame_dir = grid_dir / FRAME_DIRNAME
    frame_dir.mkdir(parents=True, exist_ok=True)
    low_count = 0
    for chunk, (selected, low) in zip(chunks, selections, strict=True):
        if low:
            low_count += 1
        filename = (
            f"scene{chunk.chunk_index}_chunk1_{_safe_label(chunk.start)}s_to_"
            f"{_safe_label(chunk.end)}s.jpg"
        )
        temp: list[Path] = []
        with ThreadPoolExecutor(max_workers=EXTRACT_WORKERS) as pool:
            futures = []
            for index, frame in enumerate(selected):
                target = frame_dir / f"temp_chunk{chunk.chunk_index}_frame{index}.jpg"
                temp.append(target)
                futures.append(
                    pool.submit(_extract_frame, video_path, frame.timestamp, target, cfg, cancel)
                )
            for future in futures:
                future.result()
        create_grid(temp, grid_root / filename, cfg)
        for target in temp:
            target.unlink(missing_ok=True)
        rows.append(
            ManifestRow(
                grid_filename=filename,
                chunk_start=chunk.start,
                chunk_end=chunk.end,
                selected_timestamps=[frame.timestamp for frame in selected],
                selected_scores=[frame.score for frame in selected],
                activity_class=chunk.activity_class,
                low_variation=low,
                source_scene_cut_times=chunk.source_scene_cut_times,
            )
        )
    diagnostics = build_diagnostics_summary(chunks, thresholds, len(frames), low_count).to_dict()
    diagnostics.update(
        {
            "video_duration": duration,
            "grid_count": len(rows),
            "cap_steps": steps,
            "coarse": coarse,
            "settings_key": settings_key(cfg),
        }
    )
    return GridPlan(
        duration_s=duration,
        scene_cuts=scene_cuts,
        chunks=chunks,
        manifest=rows,
        grid_dir=grid_dir,
        coarse=coarse,
        cap_steps=steps,
        diagnostics=diagnostics,
    )


def clean_grid_dirs(grid_dir: Path, keep: bool) -> None:
    """Remove the scratch grids and frames after describing unless `keep_grids` is on."""
    if keep:
        return
    for name in GRID_DIRS:
        target = grid_dir / name
        if target.is_dir():
            for child in target.iterdir():
                child.unlink(missing_ok=True)
            target.rmdir()
