"""Low-resolution frame analysis, adaptive chunks and four-frame selection per chunk.

Copied and adapted from `evrenesat/r2t4`, `scene-analyser/frame_selector.py` at commit 29075554
(by the repository owner, contributed under MIT; see `LICENSE` and `THIRD_PARTY.md`). The module
keeps the original algorithms, drops the optional numpy path and takes every threshold from
`[cuts.watched]` instead of module constants.
"""

from __future__ import annotations

import math
import threading
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageStat

from ..config import WatchedCutsConfig
from . import ffmpeg

CUT_BONUS_DISTANCE_S = 0.75
MOTION_MEDIAN_Q = 55.0
MOTION_HIGH_Q = 85.0
NOVELTY_MEDIAN_Q = 55.0
NOVELTY_HIGH_Q = 85.0
SHARPNESS_FLOOR_Q = 20.0
SHARPNESS_HIGH_Q = 80.0
LOW_VARIATION_MOTION_Q = 30.0
LOW_VARIATION_NOVELTY_Q = 35.0
BUSY_MOTION_FLOOR = 0.15
BUSY_MOTION_CEIL = 0.5
BUSY_MOTION_MARGIN = 0.05
BUSY_ACTIVITY_SCORE = 0.52
MIXED_ACTIVITY_SHARE = 0.65
CUT_DENSITY_WINDOW_S = 2.5
REGION_DENSITY_WINDOW_S = 4.0
ACTIVITY_HIGH_MOTION_WEIGHT = 0.45
ACTIVITY_MEAN_MOTION_WEIGHT = 0.25
ACTIVITY_CUT_WEIGHT = 0.20
ACTIVITY_REGION_WEIGHT = 0.10
SCORE_MOTION_WEIGHT = 0.45
SCORE_NOVELTY_WEIGHT = 0.20
SCORE_SHARPNESS_WEIGHT = 0.15
SCORE_CUT_BONUS = 0.20
BLACK_PENALTY = 0.75
QUALITY_PENALTY = 0.30
NOVELTY_PENALTY = 0.05
FALLBACK_SCORE = -0.1
CALM_CUT_SHARE = 0.25
TAIL_MIN_SHARE = 0.5


@dataclass(frozen=True)
class AnalyzedFrame:
    index: int
    timestamp: float
    mean_luma: float
    black_frame: bool
    sharpness: float
    motion: float
    novelty: float
    dhash: int


@dataclass(frozen=True)
class ChunkWindow:
    chunk_index: int
    start: float
    end: float
    activity_class: str
    source_scene_cut_times: list[float]


@dataclass(frozen=True)
class SelectedFrame:
    timestamp: float
    score: float
    bin_index: int
    frame_index: int
    dhash: int


@dataclass(frozen=True)
class DiagnosticsSummary:
    candidate_frame_count: int
    thresholds_used: dict[str, float]
    low_variation_chunk_count: int
    chunk_duration_stats: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def percentile(values: list[float], q: float, fallback: float = 0.0) -> float:
    if not values:
        return float(fallback)
    sorted_values = sorted(float(value) for value in values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (q / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[lower]
    fraction = rank - lower
    return (sorted_values[lower] * (1.0 - fraction)) + (sorted_values[upper] * fraction)


def normalize_band(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return float(max(0.0, min(1.0, (value - low) / (high - low))))


def hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def estimate_sharpness(frame: Image.Image) -> float:
    edges = frame.filter(ImageFilter.FIND_EDGES)
    return float(ImageStat.Stat(edges).mean[0])


def compute_dhash(frame: Image.Image) -> int:
    resized = frame.resize((9, 8), Image.Resampling.BILINEAR)
    pixels = list(resized.getdata())
    value = 0
    for row in range(8):
        offset = row * 9
        for col in range(8):
            left = pixels[offset + col]
            right = pixels[offset + col + 1]
            value = (value << 1) | int(right > left)
    return value


def _scaled_dimensions(cfg: WatchedCutsConfig, frame: tuple[int, int]) -> tuple[int, int]:
    width, height = frame
    if width <= cfg.analysis_width:
        return width, height
    target_height = max(1, round(height * cfg.analysis_width / width))
    return cfg.analysis_width, target_height


def analyze_video_lowres(
    video_path: str,
    cfg: WatchedCutsConfig,
    *,
    cancel: threading.Event | None,
    timeout_s: float,
) -> list[AnalyzedFrame]:
    width, height = _scaled_dimensions(
        cfg,
        ffmpeg.video_dimensions(
            video_path, cancel=cancel, threads=cfg.ffmpeg_threads, timeout_s=timeout_s
        ),
    )
    frame_size = width * height
    vf = f"fps={cfg.analysis_fps},scale={width}:{height}:flags=lanczos,format=gray"
    frames: list[AnalyzedFrame] = []
    previous_pixels: Image.Image | None = None
    previous_hash: int | None = None
    index = 0
    for raw in ffmpeg.stream_raw(
        ["-v", "error", "-i", video_path, "-vf", vf, "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        frame_size=frame_size,
        cancel=cancel,
        threads=cfg.ffmpeg_threads,
        timeout_s=timeout_s,
    ):
        pixels = Image.frombytes("L", (width, height), raw)
        frame_hash = compute_dhash(pixels)
        mean_luma = float(ImageStat.Stat(pixels).mean[0])
        sharpness = estimate_sharpness(pixels)
        if previous_pixels is None:
            motion = 0.0
            novelty = 0.0
        else:
            diff_image = ImageChops.difference(pixels, previous_pixels)
            motion = float(ImageStat.Stat(diff_image).mean[0])
            novelty = float(hamming_distance(previous_hash or 0, frame_hash))
        frames.append(
            AnalyzedFrame(
                index=index,
                timestamp=index / cfg.analysis_fps,
                mean_luma=mean_luma,
                black_frame=mean_luma <= cfg.black_frame_luma,
                sharpness=sharpness,
                motion=motion,
                novelty=novelty,
                dhash=frame_hash,
            )
        )
        previous_pixels = pixels
        previous_hash = frame_hash
        index += 1
    return frames


def derive_thresholds(frames: list[AnalyzedFrame], cfg: WatchedCutsConfig) -> dict[str, float]:
    motions = [frame.motion for frame in frames]
    novelties = [frame.novelty for frame in frames]
    sharpness = [frame.sharpness for frame in frames]
    min_distance = float(cfg.min_frame_distance)
    motion_medium = percentile(motions, MOTION_MEDIAN_Q, 0.0)
    motion_high = percentile(motions, MOTION_HIGH_Q, motion_medium)
    novelty_medium = percentile(novelties, NOVELTY_MEDIAN_Q, 0.0)
    novelty_high = max(min_distance, percentile(novelties, NOVELTY_HIGH_Q, min_distance))
    quality_floor = percentile(sharpness, SHARPNESS_FLOOR_Q, 0.0)
    sharpness_high = percentile(sharpness, SHARPNESS_HIGH_Q, quality_floor)
    high_motion_fraction = (
        float(sum(value >= motion_high for value in motions) / len(motions)) if motions else 0.0
    )
    return {
        "motion_medium": motion_medium,
        "motion_high": max(motion_high, motion_medium + 1e-6),
        "novelty_medium": novelty_medium,
        "novelty_high": max(novelty_high, novelty_medium + 1e-6),
        "quality_floor": quality_floor,
        "sharpness_high": max(sharpness_high, quality_floor + 1e-6),
        "busy_motion_fraction": max(
            BUSY_MOTION_FLOOR, min(BUSY_MOTION_CEIL, high_motion_fraction + BUSY_MOTION_MARGIN)
        ),
        "busy_activity_score": BUSY_ACTIVITY_SCORE,
        "low_variation_motion": percentile(motions, LOW_VARIATION_MOTION_Q, 0.0),
        "low_variation_novelty": max(
            min_distance * 0.75, percentile(novelties, LOW_VARIATION_NOVELTY_Q, min_distance * 0.5)
        ),
    }


def _timestamps(frames: list[AnalyzedFrame]) -> list[float]:
    return [frame.timestamp for frame in frames]


def _slice_frames(
    frames: list[AnalyzedFrame], timestamps: list[float], start: float, end: float
) -> list[AnalyzedFrame]:
    left = bisect_left(timestamps, start)
    right = bisect_right(timestamps, end)
    return frames[left:right]


def _count_intersecting_regions(regions: list[dict[str, Any]], start: float, end: float) -> int:
    return sum(1 for region in regions if region["end"] > start and region["start"] < end)


def window_activity(
    frames: list[AnalyzedFrame],
    cuts: list[float],
    regions: list[dict[str, Any]],
    thresholds: dict[str, float],
    start: float,
    end: float,
) -> dict[str, float | str]:
    duration = max(end - start, 1e-6)
    window_frames = [frame for frame in frames if start <= frame.timestamp <= end]
    window_cuts = [cut for cut in cuts if start < cut < end]
    if not window_frames:
        return {
            "activity_score": 0.0,
            "mean_motion_norm": 0.0,
            "high_motion_fraction": 0.0,
            "activity_class": "calm",
            "cut_count": float(len(window_cuts)),
        }
    motion_norms = [
        normalize_band(frame.motion, thresholds["motion_medium"], thresholds["motion_high"])
        for frame in window_frames
    ]
    mean_motion_norm = sum(motion_norms) / len(motion_norms)
    high_motion_fraction = (
        sum(frame.motion >= thresholds["motion_high"] for frame in window_frames)
        / len(window_frames)
    )
    region_count = _count_intersecting_regions(regions, start, end)
    cut_density = min(1.0, len(window_cuts) / max(1.0, duration / CUT_DENSITY_WINDOW_S))
    region_density = min(1.0, region_count / max(1.0, duration / REGION_DENSITY_WINDOW_S))
    activity_score = (
        ACTIVITY_HIGH_MOTION_WEIGHT * high_motion_fraction
        + ACTIVITY_MEAN_MOTION_WEIGHT * mean_motion_norm
        + ACTIVITY_CUT_WEIGHT * cut_density
        + ACTIVITY_REGION_WEIGHT * region_density
    )
    if activity_score >= thresholds["busy_activity_score"] or (
        high_motion_fraction >= thresholds["busy_motion_fraction"] and len(window_cuts) >= 1
    ):
        activity_class = "busy"
    elif activity_score >= thresholds["busy_activity_score"] * MIXED_ACTIVITY_SHARE:
        activity_class = "mixed"
    else:
        activity_class = "calm"
    return {
        "activity_score": activity_score,
        "mean_motion_norm": mean_motion_norm,
        "high_motion_fraction": high_motion_fraction,
        "activity_class": activity_class,
        "cut_count": float(len(window_cuts)),
    }


def build_adaptive_chunks(
    video_duration: float,
    frames: list[AnalyzedFrame],
    cuts: list[float],
    regions: list[dict[str, Any]],
    cfg: WatchedCutsConfig,
    thresholds: dict[str, float],
) -> list[ChunkWindow]:
    if video_duration <= 0:
        return []
    cuts = sorted(cut for cut in cuts if 0.0 < cut < video_duration)
    timestamps = _timestamps(frames)
    chunks: list[ChunkWindow] = []
    chunk_index = 1
    start = 0.0
    while start < video_duration - 1e-6:
        remaining = video_duration - start
        if remaining <= cfg.max_chunk_s:
            end = video_duration
        else:
            min_end = start + cfg.min_chunk_s
            max_end = min(video_duration, start + cfg.max_chunk_s)
            cut_candidates = [cut for cut in cuts if min_end <= cut <= max_end]
            end: float | None = None
            for cut in cut_candidates:
                metrics = window_activity(frames, cuts, regions, thresholds, start, cut)
                if metrics["activity_class"] == "busy":
                    end = cut
                    break
            if end is None:
                for frame in _slice_frames(frames, timestamps, min_end, max_end):
                    metrics = window_activity(
                        frames, cuts, regions, thresholds, start, frame.timestamp
                    )
                    if metrics["activity_class"] == "busy":
                        end = frame.timestamp
                        break
            if end is None:
                calm_cuts = [
                    cut
                    for cut in cut_candidates
                    if cut >= max_end - max(1.0, cfg.min_chunk_s * CALM_CUT_SHARE)
                ]
                end = calm_cuts[-1] if calm_cuts else max_end
            tail = video_duration - end
            if 0.0 < tail < cfg.min_chunk_s * TAIL_MIN_SHARE and remaining <= (
                cfg.max_chunk_s + cfg.min_chunk_s * TAIL_MIN_SHARE
            ):
                end = video_duration
        chunk_cuts = [cut for cut in cuts if start < cut < end]
        metrics = window_activity(frames, cuts, regions, thresholds, start, end)
        chunks.append(
            ChunkWindow(
                chunk_index=chunk_index,
                start=start,
                end=end,
                activity_class=str(metrics["activity_class"]),
                source_scene_cut_times=chunk_cuts,
            )
        )
        chunk_index += 1
        start = end
    return chunks


def _candidate_score(
    frame: AnalyzedFrame,
    cuts: list[float],
    thresholds: dict[str, float],
    cfg: WatchedCutsConfig,
) -> float:
    motion_score = normalize_band(
        frame.motion, thresholds["motion_medium"], thresholds["motion_high"]
    )
    novelty_score = normalize_band(
        frame.novelty, thresholds["novelty_medium"], thresholds["novelty_high"]
    )
    sharpness_score = normalize_band(
        frame.sharpness, thresholds["quality_floor"], thresholds["sharpness_high"]
    )
    cut_bonus = (
        1.0 if any(abs(frame.timestamp - cut) <= CUT_BONUS_DISTANCE_S for cut in cuts) else 0.0
    )
    black_penalty = BLACK_PENALTY if frame.black_frame else 0.0
    quality_penalty = QUALITY_PENALTY if frame.sharpness < thresholds["quality_floor"] else 0.0
    return (
        SCORE_MOTION_WEIGHT * motion_score
        + SCORE_NOVELTY_WEIGHT * novelty_score
        + SCORE_SHARPNESS_WEIGHT * sharpness_score
        + SCORE_CUT_BONUS * cut_bonus
        - black_penalty
        - quality_penalty
        - (NOVELTY_PENALTY if frame.novelty < cfg.min_frame_distance * 0.5 else 0.0)
    )


def collect_chunk_candidates(
    chunk: ChunkWindow,
    frames: list[AnalyzedFrame],
    cuts: list[float],
    thresholds: dict[str, float],
    cfg: WatchedCutsConfig,
) -> list[tuple[AnalyzedFrame, float]]:
    timestamps = _timestamps(frames)
    window_frames = _slice_frames(frames, timestamps, chunk.start, chunk.end)
    candidate_by_index = {frame.index: frame for frame in window_frames}
    for cut in cuts:
        if not (chunk.start < cut < chunk.end):
            continue
        position = bisect_left(timestamps, cut)
        if position < len(frames):
            candidate = frames[position]
            if candidate.timestamp <= chunk.end + 1e-6:
                candidate_by_index[candidate.index] = candidate
        elif position > 0:
            candidate_by_index[frames[position - 1].index] = frames[position - 1]
    candidates = sorted(candidate_by_index.values(), key=lambda frame: frame.timestamp)
    valid = [
        frame
        for frame in candidates
        if not frame.black_frame and frame.sharpness >= thresholds["quality_floor"]
    ]
    if len(valid) >= 4:
        candidates = valid
    elif len(valid) >= max(1, len(candidates) // 2):
        kept = {frame.index for frame in valid}
        candidates = valid + [frame for frame in candidates if frame.index not in kept]
    chunk_cuts = [cut for cut in cuts if chunk.start < cut < chunk.end]
    return [(frame, _candidate_score(frame, chunk_cuts, thresholds, cfg)) for frame in candidates]


def _fallback_timestamp(chunk: ChunkWindow, bin_index: int) -> float:
    duration = max(chunk.end - chunk.start, 1e-6)
    bin_width = duration / 4.0
    return chunk.start + (bin_index * bin_width) + (bin_width / 2.0)


def select_chunk_frames(
    chunk: ChunkWindow,
    frames: list[AnalyzedFrame],
    cuts: list[float],
    thresholds: dict[str, float],
    cfg: WatchedCutsConfig,
) -> tuple[list[SelectedFrame], bool]:
    candidates = collect_chunk_candidates(chunk, frames, cuts, thresholds, cfg)
    duration = max(chunk.end - chunk.start, 1e-6)
    bin_width = duration / 4.0
    bins: list[list[tuple[AnalyzedFrame, float]]] = [[] for _ in range(4)]
    for frame, score in candidates:
        raw_bin = (frame.timestamp - chunk.start) / duration
        bin_index = min(3, max(0, int(raw_bin * 4)))
        bins[bin_index].append((frame, score))
    for bin_index, bucket in enumerate(bins):
        center = chunk.start + (bin_index * bin_width) + (bin_width / 2.0)
        bucket.sort(key=lambda item: (-item[1], abs(item[0].timestamp - center), item[0].timestamp))
    used: set[int] = set()
    selections: list[SelectedFrame] = []
    for bin_index, bucket in enumerate(bins):
        chosen: tuple[AnalyzedFrame, float] | None = None
        for candidate in bucket:
            if candidate[0].index not in used:
                chosen = candidate
                break
        if chosen is None:
            center = _fallback_timestamp(chunk, bin_index)
            pool = sorted(
                candidates,
                key=lambda item: (
                    item[0].index in used,
                    abs(item[0].timestamp - center),
                    -item[1],
                ),
            )
            for candidate in pool:
                if candidate[0].index not in used:
                    chosen = candidate
                    break
        if chosen is None:
            selections.append(
                SelectedFrame(
                    timestamp=_fallback_timestamp(chunk, bin_index),
                    score=-0.1,
                    bin_index=bin_index,
                    frame_index=-1,
                    dhash=0,
                )
            )
            continue
        frame, score = chosen
        used.add(frame.index)
        selections.append(
            SelectedFrame(
                timestamp=frame.timestamp,
                score=score,
                bin_index=bin_index,
                frame_index=frame.index,
                dhash=frame.dhash,
            )
        )

    def replacement(target_index: int) -> SelectedFrame | None:
        target = selections[target_index]
        others = [
            sel for index, sel in enumerate(selections) if index != target_index
        ]
        for frame, score in bins[target.bin_index]:
            if frame.index == target.frame_index or frame.index in used:
                continue
            if all(
                sel.frame_index < 0
                or hamming_distance(frame.dhash, sel.dhash) >= cfg.min_frame_distance
                for sel in others
            ):
                return SelectedFrame(
                    timestamp=frame.timestamp,
                    score=score,
                    bin_index=target.bin_index,
                    frame_index=frame.index,
                    dhash=frame.dhash,
                )
        return None

    for left in range(len(selections)):
        for right in range(left + 1, len(selections)):
            if selections[left].frame_index < 0 or selections[right].frame_index < 0:
                continue
            if (
                hamming_distance(selections[left].dhash, selections[right].dhash)
                >= cfg.min_frame_distance
            ):
                continue
            index = left if selections[left].score <= selections[right].score else right
            new = replacement(index)
            if new is None:
                continue
            if selections[index].frame_index >= 0:
                used.discard(selections[index].frame_index)
            used.add(new.frame_index)
            selections[index] = new

    low_variation = False
    for left in range(len(selections)):
        for right in range(left + 1, len(selections)):
            if selections[left].frame_index < 0 or selections[right].frame_index < 0:
                continue
            if (
                hamming_distance(selections[left].dhash, selections[right].dhash)
                < cfg.min_frame_distance
            ):
                low_variation = True
                break
        if low_variation:
            break
    selections.sort(key=lambda selection: selection.timestamp)
    return selections, low_variation


def build_diagnostics_summary(
    chunks: list[ChunkWindow],
    thresholds: dict[str, float],
    candidate_frame_count: int,
    low_variation_chunk_count: int,
) -> DiagnosticsSummary:
    durations = [chunk.end - chunk.start for chunk in chunks]
    if not durations:
        stats = {"min": 0.0, "median": 0.0, "mean": 0.0, "max": 0.0}
    else:
        stats = {
            "min": float(min(durations)),
            "median": percentile(durations, 50, 0.0),
            "mean": float(sum(durations) / len(durations)),
            "max": float(max(durations)),
        }
    return DiagnosticsSummary(
        candidate_frame_count=candidate_frame_count,
        thresholds_used={key: float(value) for key, value in thresholds.items()},
        low_variation_chunk_count=low_variation_chunk_count,
        chunk_duration_stats=stats,
    )


__all__ = [
    "AnalyzedFrame",
    "ChunkWindow",
    "DiagnosticsSummary",
    "SelectedFrame",
    "analyze_video_lowres",
    "build_adaptive_chunks",
    "build_diagnostics_summary",
    "derive_thresholds",
    "select_chunk_frames",
    "window_activity",
]
