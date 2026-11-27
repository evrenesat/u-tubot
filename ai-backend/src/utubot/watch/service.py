"""The Watched build: video, grids, describing, editor, checking and the Quick offer.

Quick stays today's transcript-only path. This stage runs only when `mode = "watched"`; it
downloads a small video copy, samples 2x2 grids on a worker thread, describes them with the
configured vision model, joins the descriptions with the transcript units, asks the same
`[llm.cuts]` editor model, snaps to shot cuts and caches the result once per video and video
description. A failure leaves the request `failed` with a Quick fallback document.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import threading
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..captions import events
from ..config import Config
from ..cuts import (
    CUT_JSON_RULES,
    CUT_SYSTEM,
    CutFormatError,
    CutRefused,
    cut_document,
    finalize_parts,
    keep_guards,
    parse_chapters,
    parse_cut_answer,
    select_for_target,
    source_document,
    source_ref,
    target_band,
    transcript_hash,
)
from ..db import Database
from ..llm import INTERACTIVE, LLMClient, LLMError
from ..media_archive import MediaArchive
from ..prompts import PromptStore
from ..transcripts import Transcript, TranscriptService
from ..youtube import YoutubeError, YoutubeGate
from .describe import describe_scenes, is_watched_installed, tdt_cache_key, tdt_from_json
from .grids import GridPlan, build_grid_plan, clean_grid_dirs, settings_key
from .join import (
    WATCHED_SYSTEM_ADDITION,
    assign_unit_ids,
    scene_lines,
    snap_parts,
    watched_serialize,
    watched_units,
)
from .tdt import CATEGORIES, LABEL_VOCAB_VERSION, validate_tdt
from .video import ensure_video

if TYPE_CHECKING:
    from ..captions.jobs import JobQueue
    from ..cuts import CutService

log = logging.getLogger("utubot.watch")

STAGE_TRANSCRIPT = "transcript"
STAGE_VIDEO = "video"
STAGE_GRIDS = "grids"
STAGE_DESCRIBING = "describing"
STAGE_MODEL = "model"
STAGE_CHECKING = "checking"
NOT_INSTALLED = "Watched cuts are not installed on this server (the `watched` extra is missing)."
NOT_CONFIGURED = "Watched cuts are not configured on this server (no [llm.cuts_vision] model)."
DISABLED = "Watched cuts are switched off on this server."
TOO_LONG = "This video is longer than the watched limit; use Quick."
LIVE = "This is a live stream; live videos cannot be cut."
NO_VISION = "no vision model configured"


def watched_available(cfg: Config) -> tuple[bool, str | None]:
    """Whether this server offers Watched, and the plain reason when it does not."""
    watched = cfg.cuts.watched
    if not watched.enabled:
        return False, DISABLED
    if cfg.llm.cuts_vision is None:
        return False, NOT_CONFIGURED
    if not is_watched_installed():
        return False, NOT_INSTALLED
    return True, None


def watched_not_configured(cfg: Config) -> str | None:
    ok, reason = watched_available(cfg)
    return None if ok else reason


def _free_space(path: Path) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        try:
            return shutil.disk_usage(path.parent).free
        except OSError:
            return 0


class WatchedBuilder:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        llm: LLMClient,
        transcripts: TranscriptService,
        prompts: PromptStore,
        jobs: JobQueue,
        archive: MediaArchive,
        gate: YoutubeGate,
    ):
        self.cfg, self.db, self.llm = cfg, db, llm
        self.transcripts, self.prompts, self.jobs = transcripts, prompts, jobs
        self.archive, self.gate = archive, gate
        self.last_model_answer: dict[str, Any] = {}

    # ---- cache ---------------------------------------------------------------------------------

    @staticmethod
    def scene_cache_key(video_sha256: str, cfg: Config) -> str:
        watched = cfg.cuts.watched
        return hashlib.sha256(f"{video_sha256}|{settings_key(watched)}".encode()).hexdigest()

    @staticmethod
    def cut_cache_key(video_id: str, version: str, model: str, thash: str, desc_key: str) -> str:
        return hashlib.sha256(
            f"{video_id}|{version}|{model}|{thash}|watched|{desc_key}".encode()
        ).hexdigest()

    # ---- video and grids -----------------------------------------------------------------------

    async def _video_and_grids(
        self,
        cuts: CutService,
        request_id: str,
        row: dict[str, Any],
        trace: events.JobTrace,
        thash: str,
        duration_s: float | None,
        work: Path,
    ) -> tuple[dict[str, Any], GridPlan]:
        video_id = row["video_id"]
        if _free_space(self.cfg.archive_dir) < self.cfg.cuts.watched.min_free_bytes:
            raise CutRefused("The disk has too little free space for a watched cut.", status=409)
        if _free_space(self.cfg.media_dir) < self.cfg.cuts.watched.min_free_bytes:
            raise CutRefused("The disk has too little free space for the grid scratch.", status=409)
        with events.stage(STAGE_VIDEO) as stage_holder:
            try:
                entry = await ensure_video(
                    self.cfg,
                    self.db,
                    self.archive,
                    self.gate,
                    self.transcripts,
                    video_id,
                    work,
                    priority=INTERACTIVE,
                )
            except YoutubeError as exc:
                raise CutRefused(exc.message) from None
            stage_holder.set(
                source="from_archive" if entry else "downloaded",
                bytes=entry["size"],
                sha256=entry["sha256"][:12],
                duration_s=duration_s,
            )
        cached = self.db.one(
            "SELECT * FROM video_scenes WHERE cache_key=?",
            [self.scene_cache_key(entry["sha256"], self.cfg)],
        )
        cached_cuts = json.loads(cached["scene_cuts"]) if cached else None
        cached_manifest = json.loads(cached["manifest"]) if cached else None
        grid_dir = work / "grids_run"
        cancel = threading.Event()
        with events.stage(STAGE_GRIDS) as stage_holder:
            try:
                plan = await asyncio.to_thread(
                    build_grid_plan,
                    str(self.archive.path_of(entry)),
                    self.cfg.cuts.watched,
                    grid_dir,
                    cancel=cancel,
                    cached_scene_cuts=cached_cuts,
                    cached_manifest=cached_manifest,
                    cached_coarse=bool(cached["coarse"]) if cached else False,
                    cached_cap_steps=int(cached["cap_steps"]) if cached else 0,
                )
            except asyncio.CancelledError:
                cancel.set()
                raise
            stage_holder.set(
                grids=len(plan.manifest),
                coarse=plan.coarse,
                cap_steps=plan.cap_steps,
                seconds_stage=plan.diagnostics.get("phase_timings_sec"),
            )
            if cached is None:
                src = source_ref(row)
                self.db.execute(
                    "INSERT OR REPLACE INTO video_scenes(cache_key,video_id,source_kind,source_key,"
                    "release_key,release_duration_ms,video_sha256,settings_key,scene_cuts,manifest,"
                    "coarse,cap_steps,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        self.scene_cache_key(entry["sha256"], self.cfg),
                        video_id,
                        src["kind"],
                        src["key"],
                        src["release_key"],
                        src["release_duration_ms"],
                        entry["sha256"],
                        settings_key(self.cfg.cuts.watched),
                        json.dumps(plan.scene_cuts),
                        json.dumps(plan.as_manifest_dict()),
                        int(plan.coarse),
                        plan.cap_steps,
                        time.time(),
                    ],
                )
        return entry, plan

    # ---- describing ----------------------------------------------------------------------------

    async def _describe(
        self,
        cuts: CutService,
        request_id: str,
        row: dict[str, Any],
        trace: events.JobTrace,
        plan: GridPlan,
        entry: dict[str, Any],
        transcript: Any,
        thash: str,
        yield_check: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        task = self.cfg.llm.cuts_vision
        if task is None:
            raise LLMError(NO_VISION)
        desc_key = tdt_cache_key(self.cfg, entry["sha256"], task.model, thash)
        stored = self.db.one("SELECT * FROM scene_descriptions WHERE cache_key=?", [desc_key])
        existing = tdt_from_json(stored["json"]) if stored else None
        if (
            stored is not None
            and existing is not None
            and all(
                (segment.get("analysis_provenance") or {}).get("seen")
                for segment in existing.get("segments") or []
            )
        ):
            events.emit(STAGE_DESCRIBING, events.SKIPPED, reason="cached")
            return existing, False
        with events.stage(STAGE_DESCRIBING) as stage_holder:

            def progress(frac: float) -> None:
                watched = self.cfg.cuts.watched
                done = watched.progress_weight_video + watched.progress_weight_grids
                total = (
                    done
                    + watched.progress_weight_describing * frac
                    + watched.progress_weight_model * (1.0 if frac >= 1.0 else 0.0)
                )
                cuts._set_progress(request_id, min(1.0, total))
                stage_holder.set(grids_done=int(frac * len(plan.manifest)))

            def partial(payload: dict[str, Any]) -> None:
                self._store_description(desc_key, row, entry, task.model, thash, payload)

            try:
                result = await describe_scenes(
                    self.cfg,
                    self.llm,
                    plan,
                    transcript,
                    entry["sha256"],
                    existing_tdt=existing,
                    progress=progress,
                    on_segment=partial,
                    should_stop=lambda: cuts._dismissed(request_id),
                    yield_check=yield_check,
                )
            except LLMError as exc:
                raise CutRefused(
                    f"Watched could not describe the video: {exc}. Use Quick instead."
                ) from None
            stage_holder.set(
                seen=result.seen,
                unseen=result.unseen,
                partial=result.partial,
                grid_seconds=round(sum(result.seconds) / max(1, len(result.seconds)), 2),
            )
        self._store_description(desc_key, row, entry, task.model, thash, result.tdt)
        return result.tdt, result.partial

    def _store_description(
        self,
        desc_key: str,
        row: dict[str, Any],
        entry: dict[str, Any],
        model: str,
        thash: str,
        payload: dict[str, Any],
    ) -> None:
        task = self.cfg.llm.cuts_vision
        if task is None:
            return
        from .tdt import prompt_hash

        src = source_ref(row)
        self._store_labels(desc_key, row, payload)
        self.db.execute(
            "INSERT OR REPLACE INTO scene_descriptions(cache_key,video_id,source_kind,source_key,"
            "release_key,release_duration_ms,video_sha256,settings_key,model,prompt_hash,"
            "transcript_hash,json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                desc_key,
                row["video_id"],
                src["kind"],
                src["key"],
                src["release_key"],
                src["release_duration_ms"],
                entry["sha256"],
                settings_key(self.cfg.cuts.watched),
                model,
                prompt_hash(self.cfg.cuts.watched),
                thash,
                json.dumps(payload, ensure_ascii=False),
                time.time(),
            ],
        )

    def _store_labels(self, desc_key: str, row: dict[str, Any], payload: dict[str, Any]) -> None:
        """The optional content labels (#88) as queryable rows; absent labels write nothing."""
        self.db.execute("DELETE FROM scene_labels WHERE descriptions_key=?", [desc_key])
        for segment in payload.get("segments") or []:
            if not isinstance(segment, dict):
                continue
            labels = segment.get("labels")
            content = labels.get("content") if isinstance(labels, dict) else None
            if not isinstance(content, list):
                continue
            for entry in content:
                if not isinstance(entry, dict) or entry.get("category") not in CATEGORIES:
                    continue
                src = source_ref(row)
                self.db.execute(
                    "INSERT INTO scene_labels(descriptions_key,source_key,release_key,segment_id,"
                    "start_ms,end_ms,category,intensity,confidence,vocab_version)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    [
                        desc_key,
                        src["key"],
                        src["release_key"],
                        str(segment.get("segment_id") or ""),
                        int((segment.get("start") or 0) * 1000),
                        int((segment.get("end") or 0) * 1000),
                        entry["category"],
                        int(entry.get("intensity") or 0),
                        float(entry.get("confidence") or 0.0),
                        LABEL_VOCAB_VERSION,
                    ],
                )

    # ---- the whole build -----------------------------------------------------------------------

    async def prepare(
        self, cuts: CutService, request_id: str, row: dict[str, Any]
    ) -> tuple[Transcript, list[Any], str, dict[str, Any]]:
        """The transcript side of a build: its length, a timed transcript (waiting for the refresh
        job when there is none) and the limits. It runs before the watched slot is taken, so a
        transcript that takes minutes never holds the one slot a prime cut needs."""
        video_id = row["video_id"]
        watched = self.cfg.cuts.watched
        if not (cuts._meta(video_id).get("duration_s")):
            await self.transcripts.ensure_length(video_id, wait_s=15.0)
        with events.stage(STAGE_TRANSCRIPT, video_id=video_id) as stage_holder:
            transcript = await cuts._ensure_transcript(request_id, row)
            meta = {**transcript.meta, **cuts._meta(video_id)}
            if not meta.get("duration_s"):
                await self.transcripts.ensure_length(video_id, wait_s=15.0)
                meta = {**meta, **cuts._meta(video_id)}
            duration = meta.get("duration_s")
            if duration and float(duration) > watched.max_video_minutes * 60:
                raise CutRefused(TOO_LONG, status=409)
            if meta.get("is_live"):
                raise CutRefused(LIVE, status=409)
            thash = transcript_hash(transcript.segments or [])
            stage_holder.set(
                source=transcript.source,
                lang=transcript.lang,
                units=len(transcript.segments or []),
            )
        return transcript, transcript.segments or [], thash, meta

    async def build(
        self,
        cuts: CutService,
        request_id: str,
        row: dict[str, Any],
        trace: events.JobTrace,
        prepared: tuple[Transcript, list[Any], str, dict[str, Any]],
        yield_check: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """The Watched request from video to cached cut, after `prepare`; returns (cut document,
        cache key). Holds the watched slot: everything here is video, grids, descriptions, model."""
        video_id = row["video_id"]
        instruction, preset_id, source = cuts._instruction(row)
        work = self.cfg.media_dir / "watched" / request_id
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        watched = self.cfg.cuts.watched

        transcript, segments, thash, meta = prepared
        duration_s = float(meta["duration_s"]) if meta.get("duration_s") else None

        entry, plan = await self._video_and_grids(
            cuts, request_id, row, trace, thash, duration_s, work
        )
        tdt, partial = await self._describe(
            cuts, request_id, row, trace, plan, entry, transcript, thash, yield_check
        )
        tdt_segments = tdt.get("segments") or []
        errors = validate_tdt(tdt, plan.manifest)
        if errors:
            raise CutRefused("The scene descriptions are not a valid TDT.")

        units = watched_units(segments, tdt, watched, duration_s=duration_s, cuts_cfg=self.cfg.cuts)
        if not units:
            raise CutRefused("This video has no speech or picture to cut.")
        scenes = scene_lines(tdt)
        unit_ids = assign_unit_ids(units, tdt)
        for index, segment in enumerate(tdt_segments, 1):
            segment["unit_ids"] = unit_ids.get(index, [])
        self._store_description(
            tdt_cache_key(self.cfg, entry["sha256"], self.cfg.llm.cuts_vision.model, thash),
            row,
            entry,
            self.cfg.llm.cuts_vision.model,
            thash,
            tdt,
        )
        chapters = parse_chapters(meta.get("description"))
        model = self.cfg.llm.cuts.model if self.cfg.llm.cuts else ""
        saved = next((p for p in cuts.presets(row["user"]) if p.id == preset_id), None)
        target_s = cuts.target_for(preset_id, duration_s, instruction, saved)
        desc_key = tdt_cache_key(self.cfg, entry["sha256"], self.cfg.llm.cuts_vision.model, thash)
        version = cuts._version(preset_id, instruction, target_s)
        cache_key = self.cut_cache_key(video_id, version, model, thash, desc_key)
        hit = self.db.one("SELECT json FROM cuts WHERE cache_key=?", [cache_key])
        if hit is not None:
            events.emit(STAGE_MODEL, events.SKIPPED, reason="cached")
            doc = json.loads(hit["json"])
            clean_grid_dirs(plan.grid_dir, watched.keep_grids)
            shutil.rmtree(work, ignore_errors=True)
            return doc, cache_key

        with events.stage(STAGE_MODEL, model=model, units=len(units)) as stage_holder:
            parts = await self._ask_watched(
                units,
                scenes,
                chapters,
                meta,
                instruction,
                target_s,
                trace,
                stage_holder,
            )
            stage_holder.set(parts=len(parts), scenes=len(scenes))
        with events.stage(STAGE_CHECKING) as stage_holder:
            snapped = snap_parts(parts, plan.scene_cuts, units, watched.snap_s)
            guard, guard_max = keep_guards(self.cfg.cuts, preset_id, target_s)
            kept, _kept_s = finalize_parts(
                snapped,
                self.cfg.cuts,
                guard=guard,
                duration_s=duration_s,
                guard_max=guard_max,
            )
            doc = cut_document(
                video_id=video_id,
                thash=thash,
                model=model,
                parts=kept,
                summary=str(self.last_model_answer.get("summary") or ""),
                label=cuts._label(preset_id, row),
                duration_s=duration_s,
                source=source,
                preset_id=preset_id,
                target_s=target_s,
            )
            doc["mode"] = "watched"
            doc["watched"] = {
                "grids": len(plan.manifest),
                "model": self.cfg.llm.cuts_vision.model,
                "partial": partial,
                "coarse": plan.coarse,
            }
            stage_holder.set(
                parts=len(kept),
                kept_s=doc["kept_ms"] / 1000.0,
                duration_s=duration_s,
                partial=partial,
            )
        src = source_ref(row)
        source_obj = source_document(src)
        if source_obj is not None:
            doc["source"] = source_obj
        self.db.execute(
            "INSERT OR REPLACE INTO cuts(cache_key,video_id,version,preset_id,prompt,model,"
            "transcript_hash,json,duration_s,kept_s,created_at,mode,source_kind,source_key,"
            "release_key,release_duration_ms) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                cache_key,
                video_id,
                version,
                preset_id,
                row["prompt"],
                model,
                thash,
                json.dumps(doc, ensure_ascii=False),
                duration_s,
                doc["kept_ms"] / 1000.0,
                time.time(),
                "watched",
                src["kind"],
                src["key"],
                src["release_key"],
                src["release_duration_ms"],
            ],
        )
        self.db.execute(
            "UPDATE cut_requests SET raw_answer=?, updated_at=? WHERE id=?",
            [
                json.dumps(self.last_model_answer, ensure_ascii=False)[
                    : self.cfg.cuts.max_report_chars
                ],
                time.time(),
                request_id,
            ],
        )
        clean_grid_dirs(plan.grid_dir, watched.keep_grids)
        shutil.rmtree(work, ignore_errors=True)
        self._set_total_progress(cuts, request_id)
        return doc, cache_key

    async def _ask_watched(
        self,
        units: list[Any],
        scenes: list[Any],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None,
        trace: events.JobTrace,
        stage_holder: events._Stage,
    ) -> list[Any]:
        """The same editor model as Quick: S lines as evidence, the shared rank selection.

        One repair round for a broken answer, and with a target length one retry that names the
        measured length when the answer is below the band. Over `max_input_tokens`, the visual
        summary of collapsed `talking_head` runs is dropped first; still over, the build refuses.
        """
        task = self.cfg.llm.cuts
        if task is None:
            raise CutRefused("Cuts are not configured on this server (no [llm.cuts] model).")
        watched = self.cfg.cuts.watched
        cfg = self.cfg.cuts

        def is_over(drop: bool) -> bool:
            message = watched_serialize(
                units,
                scenes,
                chapters,
                meta,
                instruction,
                target_s,
                cfg.over_ask_frac,
                drop_talking_head_summaries=drop,
            )
            return len(message) // cfg.chars_per_token > watched.max_input_tokens

        drop = is_over(False)
        if drop and is_over(True):
            raise CutRefused("This video is too long to join in one watched pass; use Quick.")

        def messages_for(problem: str | None) -> list[dict[str, Any]]:
            message = watched_serialize(
                units,
                scenes,
                chapters,
                meta,
                instruction,
                target_s,
                cfg.over_ask_frac,
                drop_talking_head_summaries=drop,
            )
            out: list[dict[str, Any]] = [
                {"role": "system", "content": CUT_SYSTEM + WATCHED_SYSTEM_ADDITION},
                {"role": "user", "content": message},
            ]
            if problem:
                out.append(
                    {
                        "role": "user",
                        "content": f"Your previous answer was rejected: {problem} {CUT_JSON_RULES}",
                    }
                )
            return out

        async def ask(problem: str | None) -> tuple[Any, list[Any]]:
            data = await self.llm.chat_json(
                task, messages_for(problem), priority=INTERACTIVE, feature=task.feature or "cuts"
            )
            try:
                return data, parse_cut_answer(data, units)
            except CutFormatError as exc:
                trace.emit(STAGE_MODEL, events.WARN, problem=exc.problem, repair=1)
                data = await self.llm.chat_json(
                    task,
                    messages_for(exc.problem),
                    priority=INTERACTIVE,
                    feature=task.feature or "cuts",
                )
                try:
                    return data, parse_cut_answer(data, units)
                except CutFormatError as exc2:
                    raise CutRefused(
                        f"The model's answer stayed unusable ({exc2.problem}),"
                        " so no watched cut was built."
                    ) from exc2

        problem: str | None = None
        data: Any = {}
        parts: list[Any] = []
        total_s = 0.0
        for attempt in range(2 if target_s else 1):
            data, parts = await ask(problem)
            if not target_s:
                break
            parts, total_s = select_for_target(parts, units, cfg, target_s)
            low, high = target_band(target_s, cfg.length_tolerance)
            if total_s >= low:
                break
            if attempt == 0:
                trace.emit(STAGE_MODEL, events.WARN, problem="below target length", retry=1)
                problem = (
                    f"it keeps only {int(total_s)} s in total but the task needs about "
                    f"{target_s} s (between {int(low)} and {int(high)} s); keep more parts."
                )
            else:
                raise CutRefused(
                    f"The model kept only {int(total_s)} s of the {target_s} s this cut aims "
                    "for, so no watched cut was built. Try again."
                )
        self.last_model_answer = data if isinstance(data, dict) else {}
        return parts

    def _set_total_progress(self, cuts: CutService, request_id: str) -> None:
        cuts._set_progress(request_id, 1.0)
