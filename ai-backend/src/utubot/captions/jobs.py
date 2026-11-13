from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from ..config import Config
from ..db import Database
from ..errors import MSG_JOB, MSG_JOB_RETRIES, MSG_TRANSCRIBE
from ..llm import BACKGROUND, INTERACTIVE
from ..media_archive import MediaArchiveError, MediaArchiveFull
from ..transcripts import SOURCE_ASR, SOURCE_CAPTIONS, NoCaptions, TranscriptService
from ..youtube import CLASS_MEDIA, FETCH_CLASSES, YoutubeDelayed, YoutubeVideoError
from . import events
from .asr import normalize_language
from .pipeline import CaptionPipeline, PipelineError, sweep_media

log = logging.getLogger("utubot.jobs")
ACTIVE = ("queued", "running")
KIND_CAPTIONS = "captions"
KIND_TRANSCRIPT = "transcript"
LANG_AUTO = "auto"
JOB_STATES = {
    "queued": "waiting",
    "running": "processing",
    "ready": "ready",
    "failed": "failed",
    "cancelled": "cancelled",
}
CANCELLED_MESSAGE = "Cancelled"
DETAIL_PAGE = "/#/jobs/{}"
DETAIL_API = "/v1/jobs/{}"
TRIGGER_EXPLICIT = {"kind": "explicit"}
UNKNOWN_CLIENT = "server"


class JobRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class JobQueue:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        pipeline: CaptionPipeline,
        transcripts: TranscriptService,
    ):
        self.cfg, self.db, self.pipeline, self.transcripts = cfg, db, pipeline, transcripts
        self.events = events.JobEvents(db, cfg.captions)
        self.events.backfill()
        self._wake = asyncio.Event()
        self._workers: list[asyncio.Task] = []
        self._stopping = False

    def start(self) -> None:
        if not self.cfg.captions.keep_media:
            removed = sweep_media(self.cfg.media_dir, self.cfg.captions.media_orphan_age_s)
            if removed:
                log.info("removed %d orphaned media directories", removed)
        self.pipeline.archive.sweep_scratch()
        interrupted = self.db.all("SELECT id FROM jobs WHERE status='running'")
        self.db.execute(
            "UPDATE jobs SET status='queued', progress=0, updated_at=? WHERE status='running'",
            [time.time()],
        )
        for row in interrupted:
            self.events.record(
                row["id"],
                events.RETRY,
                events.WARN,
                {
                    "reason": "restart",
                    "message": "The server restarted while this ran; queued again.",
                },
            )
        self._stopping = False
        for _ in range(max(1, self.cfg.captions.job_concurrency)):
            self._workers.append(asyncio.create_task(self._worker()))

    async def stop(self) -> None:
        self._stopping = True
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    def enqueue(
        self,
        user: str,
        video_id: str,
        lang: str,
        translate_to: str | None,
        trigger: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM jobs WHERE kind=? AND video_id=? AND lang=?"
            " AND IFNULL(translate_to,'')=? AND status IN ('queued','running')"
            " ORDER BY created_at DESC LIMIT 1",
            [KIND_CAPTIONS, video_id, lang, translate_to or ""],
        )
        if row:
            return dict(row)
        return self._insert(
            user, video_id, KIND_CAPTIONS, lang, translate_to, None, trigger=trigger
        )

    def find_active_transcript(self, user: str, video_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT * FROM jobs WHERE kind=? AND user=? AND video_id=?"
            " AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1",
            [KIND_TRANSCRIPT, user, video_id],
        )
        return dict(row) if row else None

    def own_transcript_job(self, user: str, video_id: str) -> dict[str, Any] | None:
        """The caller's active transcript job for a video, else their newest one."""
        row = self.db.one(
            "SELECT * FROM jobs WHERE kind=? AND user=? AND video_id=?"
            " ORDER BY (status IN ('queued','running')) DESC, created_at DESC LIMIT 1",
            [KIND_TRANSCRIPT, user, video_id],
        )
        return dict(row) if row else None

    def enqueue_transcript(
        self,
        user: str,
        video_id: str,
        title: str | None,
        priority: int = BACKGROUND,
        trigger: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Queue an ASR transcript; the same user asking again gets the job already queued.

        `INTERACTIVE` jobs (someone is waiting on the transcript) are claimed before background ones.
        """
        existing = self.find_active_transcript(user, video_id)
        if existing is not None:
            return existing
        return self._insert(
            user, video_id, KIND_TRANSCRIPT, LANG_AUTO, None, title, priority, trigger
        )

    def promote_transcript(self, video_id: str) -> None:
        """Someone now waits on this video's transcript: queued work goes first, a running download too."""
        raised = self.db.all(
            "SELECT id FROM jobs WHERE kind=? AND video_id=? AND priority>?"
            " AND status IN ('queued','running')",
            [KIND_TRANSCRIPT, video_id, INTERACTIVE],
        )
        self.db.execute(
            "UPDATE jobs SET priority=? WHERE kind=? AND video_id=? AND priority>?"
            " AND status IN ('queued','running')",
            [INTERACTIVE, KIND_TRANSCRIPT, video_id, INTERACTIVE],
        )
        origin = events.current_origin()
        for row in raised:
            self.events.record(
                row["id"],
                events.PROMOTED,
                events.INFO,
                {
                    "priority": events.priority_name(INTERACTIVE),
                    "client": origin.client if origin else UNKNOWN_CLIENT,
                    "user": origin.user if origin else None,
                    "message": "Someone is waiting on this video, so the job now goes first.",
                },
            )
        self.pipeline.gate.promote(f"audio:{video_id}")
        self._wake.set()

    def _insert(
        self,
        user: str,
        video_id: str,
        kind: str,
        lang: str,
        translate_to: str | None,
        title: str | None,
        priority: int = BACKGROUND,
        trigger: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.execute(
            "INSERT INTO jobs(id,user,video_id,lang,translate_to,status,progress,created_at,"
            "updated_at,kind,title,priority) VALUES(?,?,?,?,?,'queued',0,?,?,?,?,?)",
            [job_id, user, video_id, lang, translate_to, now, now, kind, title, priority],
        )
        origin = events.current_origin()
        self.events.record(
            job_id,
            events.QUEUED,
            events.OK,
            {
                "kind": kind,
                "user": user,
                "client": origin.client if origin else UNKNOWN_CLIENT,
                "endpoint": origin.endpoint if origin else None,
                "trigger": trigger or TRIGGER_EXPLICIT,
                "priority": events.priority_name(priority),
                "video_id": video_id,
                "title": title,
                "lang": lang,
                "translate_to": translate_to,
            },
            ts=now,
        )
        self._wake.set()
        return dict(self.db.one("SELECT * FROM jobs WHERE id=?", [job_id]))

    def active_count(self, user: str, kind: str) -> int:
        row = self.db.one(
            "SELECT COUNT(*) AS n FROM jobs WHERE user=? AND kind=? AND status IN ('queued','running')",
            [user, kind],
        )
        return int(row["n"])

    def transcript_job(self, video_id: str) -> dict[str, Any] | None:
        """The active ASR transcript job for a video, else its most recent failed one (if newest)."""
        row = self.db.one(
            "SELECT id, status, progress, error, updated_at, priority FROM jobs WHERE kind=? AND video_id=?"
            " ORDER BY (status IN ('queued','running')) DESC, created_at DESC LIMIT 1",
            [KIND_TRANSCRIPT, video_id],
        )
        return dict(row) if row else None

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM jobs WHERE id=?", [job_id])
        return dict(row) if row else None

    def status(self, video_id: str) -> dict[str, Any]:
        tracks = [
            {
                "lang": r["lang"],
                "label": r["label"],
                "url": f"/v1/videos/{video_id}/captions/{r['lang']}.vtt",
                "speakers": r["speakers"],
            }
            for r in self.db.all(
                "SELECT lang,label,speakers FROM captions WHERE video_id=? ORDER BY lang",
                [video_id],
            )
        ]
        active = self.db.one(
            "SELECT status, progress FROM jobs WHERE kind=? AND video_id=?"
            " AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1",
            [KIND_CAPTIONS, video_id],
        )
        if active:
            return {"status": active["status"], "progress": active["progress"], "tracks": tracks}
        if tracks:
            return {"status": "ready", "progress": 1.0, "tracks": tracks}
        last = self.db.one(
            "SELECT status, error FROM jobs WHERE kind=? AND video_id=?"
            " ORDER BY created_at DESC LIMIT 1",
            [KIND_CAPTIONS, video_id],
        )
        if last and last["status"] == "failed":
            return {"status": "failed", "progress": 0.0, "tracks": [], "error": last["error"]}
        return {"status": "none", "progress": 0.0, "tracks": []}

    def recent(self, user: str, limit: int) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT id,video_id,lang,translate_to,status,progress,error,updated_at FROM jobs"
            " WHERE user=? AND kind=? ORDER BY created_at DESC LIMIT ?",
            [user, KIND_CAPTIONS, limit],
        )
        return [dict(r) for r in rows]

    def listing(self, user: str, limit: int) -> list[dict[str, Any]]:
        """The user's jobs of every kind, newest first, in the shape of `GET /v1/jobs`."""
        rows = self.db.all(
            "SELECT id,kind,video_id,title,status,progress,error,created_at,finished_at,not_before"
            " FROM jobs WHERE user=? ORDER BY created_at DESC LIMIT ?",
            [user, limit],
        )
        deliveries = self.delivery_summary([r["id"] for r in rows])
        stages = self.last_stages([r["id"] for r in rows])
        out = []
        for r in rows:
            title = r["title"] or (self.transcripts.cached_meta(r["video_id"]) or {}).get("title")
            state = JOB_STATES.get(r["status"], r["status"])
            delivered = deliveries.get(r["id"])
            out.append(
                {
                    "id": r["id"],
                    "kind": r["kind"],
                    "video_id": r["video_id"],
                    "title": title,
                    "state": state,
                    "progress": r["progress"],
                    "error": r["error"],
                    "created_at": r["created_at"],
                    "finished_at": r["finished_at"],
                    "retry_after_s": self.retry_after(r, state),
                    "stage": stages.get(r["id"]),
                    "delivered": bool(delivered),
                    "delivered_at": delivered["last_ts"] if delivered else None,
                    "detail_url": DETAIL_PAGE.format(r["id"]),
                    "api_url": DETAIL_API.format(r["id"]),
                }
            )
        return out

    def retry_after(self, row: Any, state: str) -> int | None:
        """Seconds a waiting job is expected to wait (YouTube cooldown or its own back-off), else None."""
        retry = max(
            self.pipeline.gate.cooldown_remaining(CLASS_MEDIA),
            (row["not_before"] or 0) - self.pipeline.gate.now(),
        )
        return round(retry) if retry > 0 and state == "waiting" else None

    def last_stages(self, job_ids: list[str]) -> dict[str, str]:
        """The stage of each job's newest event that is not a delivery (what it is doing, or did last)."""
        if not job_ids:
            return {}
        marks = ",".join("?" * len(job_ids))
        rows = self.db.all(
            f"SELECT job_id, stage FROM job_events WHERE id IN (SELECT MAX(id) FROM job_events"
            f" WHERE job_id IN ({marks}) AND stage!=? GROUP BY job_id)",
            [*job_ids, events.DELIVERED],
        )
        return {r["job_id"]: r["stage"] for r in rows}

    def delivery_summary(self, job_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Per job that was fetched: how many fetches and when the last one was."""
        if not job_ids:
            return {}
        marks = ",".join("?" * len(job_ids))
        rows = self.db.all(
            f"SELECT job_id, ts, detail FROM job_events WHERE stage=? AND job_id IN ({marks})",
            [events.DELIVERED, *job_ids],
        )
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            entry = out.setdefault(r["job_id"], {"count": 0, "last_ts": 0.0})
            entry["count"] += int(json.loads(r["detail"] or "{}").get("count", 1))
            entry["last_ts"] = max(entry["last_ts"], r["ts"])
        return out

    def cancel(self, user: str, job_id: str) -> dict[str, Any]:
        """Cancel the caller's queued job. A running job cannot be stopped from here."""
        job = self.get(job_id)
        if job is None or job["user"] != user:
            raise JobRefused(404, "unknown job")
        if job["status"] != "queued":
            raise JobRefused(409, "only a waiting job can be cancelled")
        now = time.time()
        rc = self.db.execute_rc(
            "UPDATE jobs SET status='cancelled', error=?, updated_at=?, finished_at=?"
            " WHERE id=? AND status='queued'",
            [CANCELLED_MESSAGE, now, now, job_id],
        )
        if rc != 1:
            raise JobRefused(409, "only a waiting job can be cancelled")
        origin = events.current_origin()
        self.events.record(
            job_id,
            events.FINISHED,
            events.CANCELLED,
            {
                "by": user,
                "client": origin.client if origin else UNKNOWN_CLIENT,
                "message": "Cancelled while waiting in the queue.",
            },
        )
        return self.get(job_id) or job

    def retry(self, user: str, job_id: str) -> dict[str, Any]:
        """Queue a failed or cancelled job of the caller again."""
        job = self.get(job_id)
        if job is None or job["user"] != user:
            raise JobRefused(404, "unknown job")
        if job["status"] not in ("failed", "cancelled"):
            raise JobRefused(409, "only a failed or cancelled job can be retried")
        if job["kind"] == KIND_TRANSCRIPT:
            if self.find_active_transcript(user, job["video_id"]):
                raise JobRefused(409, "this video is already being transcribed")
            if (
                self.active_count(user, KIND_TRANSCRIPT)
                >= self.cfg.captions.transcribe_max_active_per_user
            ):
                raise JobRefused(429, "too many transcriptions are already queued")
        self.db.execute(
            "UPDATE jobs SET status='queued', progress=0, error=NULL, attempts=0, not_before=NULL,"
            " finished_at=NULL, updated_at=? WHERE id=?",
            [time.time(), job_id],
        )
        origin = events.current_origin()
        self.events.record(
            job_id,
            events.RETRY,
            events.INFO,
            {
                "reason": "requested",
                "by": user,
                "client": origin.client if origin else UNKNOWN_CLIENT,
                "message": f"Queued again after it {job['status']}.",
            },
        )
        self._wake.set()
        return self.get(job_id) or job

    # ---- delivery: which client fetched a result ------------------------------------------------

    def captions_job_for(self, video_id: str, lang: str) -> str | None:
        """The job that made the stored captions track (older tracks: the video's newest ready job)."""
        row = self.db.one(
            "SELECT job_id FROM captions WHERE video_id=? AND lang=?", [video_id, lang]
        )
        if row is None:
            return None
        if row["job_id"]:
            return row["job_id"]
        newest = self.db.one(
            "SELECT id FROM jobs WHERE kind=? AND video_id=? AND status='ready'"
            " ORDER BY finished_at DESC LIMIT 1",
            [KIND_CAPTIONS, video_id],
        )
        return newest["id"] if newest else None

    def transcript_job_for(self, video_id: str) -> str | None:
        """The job that made the stored transcript, when that came from audio."""
        row = self.db.one("SELECT source, job_id FROM transcripts WHERE video_id=?", [video_id])
        if row is None or row["source"] != SOURCE_ASR:
            return None
        if row["job_id"]:
            return row["job_id"]
        newest = self.db.one(
            "SELECT id FROM jobs WHERE kind=? AND video_id=? AND status='ready'"
            " ORDER BY finished_at DESC LIMIT 1",
            [KIND_TRANSCRIPT, video_id],
        )
        return newest["id"] if newest else None

    def record_captions_delivery(
        self, video_id: str, langs: list[str], via: str, client: str, user: str, **detail: Any
    ) -> None:
        """A client read captions (the status list or a `.vtt`): note it on the job of each track."""
        for lang in dict.fromkeys(langs):
            job_id = self.captions_job_for(video_id, lang)
            if job_id:
                self.events.deliver(job_id, via, client, user, lang=lang, **detail)

    def record_transcript_delivery(
        self, video_id: str, via: str, client: str, user: str, **detail: Any
    ) -> None:
        """A client got something built from the transcript the audio produced."""
        job_id = self.transcript_job_for(video_id)
        if job_id:
            self.events.deliver(job_id, via, client, user, **detail)

    def _claim(self) -> dict[str, Any] | None:
        """Next queued job, interactive first; none while the media breaker is open (work waits)."""
        if not self.pipeline.gate.healthy(CLASS_MEDIA):
            return None
        row = self.db.one(
            "SELECT * FROM jobs WHERE status='queued' AND (not_before IS NULL OR not_before<=?)"
            " AND NOT EXISTS"
            " (SELECT 1 FROM jobs r WHERE r.video_id=jobs.video_id AND r.status='running')"
            " ORDER BY priority, created_at LIMIT 1",
            [self.pipeline.gate.now()],
        )
        if not row:
            return None
        self.db.execute(
            "UPDATE jobs SET status='running', updated_at=? WHERE id=?", [time.time(), row["id"]]
        )
        return dict(row)

    def _set_progress(self, job_id: str, value: float) -> None:
        self.db.execute(
            "UPDATE jobs SET progress=?, updated_at=? WHERE id=?", [value, time.time(), job_id]
        )

    async def _run_captions(self, job: dict[str, Any]) -> None:
        """HQ captions, lean: captions of the video are improved, missing ones are made from audio.

        Case 1 (the video has captions): their timing is kept, the text is re-aligned to ASR words
        and proofread (`CaptionPipeline.improve`). Case 2 (no captions, or YouTube will not answer
        the check right now): the track is built from the audio (`CaptionPipeline.run`). The check
        never holds the audio back: a limited caption or metadata endpoint goes straight to case 2.
        """
        video_id = job["video_id"]
        priority = job["priority"]
        gate = self.pipeline.gate
        check = (
            gate.interactive_ok(*FETCH_CLASSES)
            if priority == INTERACTIVE
            else gate.healthy(*FETCH_CLASSES)
        )
        if not check:
            events.emit(
                events.CAPTION_RECHECK,
                events.SKIPPED,
                reason="youtube_limited",
                message="The caption or metadata endpoint of YouTube is limited right now; the track is built from the audio.",
            )
            await self.pipeline.run(
                video_id,
                job["lang"],
                job["translate_to"],
                lambda f: self._set_progress(job["id"], f),
                priority,
            )
            return
        found = await self._recheck_for_captions(video_id, priority)
        if (
            found is not None
            and found.source == SOURCE_CAPTIONS
            and found.segments
            and self._lang_matches(job["lang"], found.lang)
        ):
            await self.pipeline.improve(
                video_id,
                found.segments,
                found.lang,
                job["translate_to"],
                lambda f: self._set_progress(job["id"], f),
                priority,
            )
            return
        await self.pipeline.run(
            video_id,
            job["lang"],
            job["translate_to"],
            lambda f: self._set_progress(job["id"], f),
            priority,
        )

    @staticmethod
    def _lang_matches(lang: str, track_lang: str | None) -> bool:
        """The requested language matches the track ("auto" always matches; base codes compare)."""
        if lang == LANG_AUTO or not track_lang:
            return True
        return lang.split("-")[0].lower() == track_lang.split("-")[0].lower()

    async def _recheck_for_captions(self, video_id: str, priority: int):
        """Ask once more what captions exist; a Transcript, or None to build from audio."""
        began = time.monotonic()

        def took() -> float:
            return round(time.monotonic() - began, 2)

        try:
            found = await self.transcripts.get(video_id, priority, recheck=True)
        except NoCaptions:
            events.emit(events.CAPTION_RECHECK, events.OK, result="no_captions", seconds=took())
            return None
        except YoutubeDelayed as exc:
            events.emit(
                events.CAPTION_RECHECK,
                events.WARN,
                result="delayed",
                reason=exc.reason,
                seconds=took(),
                message="YouTube did not answer the caption check; the track is built from the audio.",
            )
            return None
        except YoutubeVideoError as exc:
            if not exc.can_transcribe:
                events.emit(
                    events.CAPTION_RECHECK,
                    events.FAILED,
                    result="video_unavailable",
                    reason=exc.reason,
                    seconds=took(),
                )
                raise
            events.emit(
                events.CAPTION_RECHECK,
                events.WARN,
                result="video_error",
                reason=exc.reason,
                seconds=took(),
                message="YouTube refused the caption check, but the audio may still work.",
            )
            return None
        events.emit(
            events.CAPTION_RECHECK,
            events.OK,
            result="found",
            source=found.source,
            lang=found.lang,
            timed=bool(found.segments),
            chars=len(found.text),
            seconds=took(),
        )
        return found

    async def _run_transcript(self, job: dict[str, Any]) -> None:
        """ASR, unless YouTube has captions after all: those are used and the audio is skipped.

        The caption check needs the metadata and caption endpoints; when either is cooling or answers
        "delayed" the check is skipped, because the audio comes from another endpoint (`media`). An
        interactive job also skips it while the caption class waits for its background probe
        (`YoutubeGate.interactive_ok`); a background job may be that probe.
        """
        video_id = job["video_id"]
        priority = job["priority"]
        gate = self.pipeline.gate
        check = (
            gate.interactive_ok(*FETCH_CLASSES)
            if priority == INTERACTIVE
            else gate.healthy(*FETCH_CLASSES)
        )
        if check:
            if await self._recheck_captions(video_id, priority):
                return
        else:
            events.emit(
                events.CAPTION_RECHECK,
                events.SKIPPED,
                reason="youtube_limited",
                message="The caption or metadata endpoint of YouTube is limited right now; went straight to the audio.",
            )
        hint = normalize_language((self.transcripts.cached_meta(video_id) or {}).get("language"))
        out = await self.pipeline.transcribe(
            video_id,
            lambda f: self._set_progress(job["id"], f),
            priority=priority,
            language=hint,
        )
        stored = self.transcripts.store_asr(
            video_id,
            out.text,
            out.language or hint,
            engine=out.engine,
            model=out.model,
            segments=out.segment_rows(),
            job_id=job["id"],
        )
        events.emit(
            events.STORED,
            events.OK if stored else events.WARN,
            kind="transcript",
            source=SOURCE_ASR,
            stored=stored,
            lang=out.language or hint,
            engine=out.engine,
            model=out.model,
            chars=len(out.text),
            segments=len(out.segments),
            message=None
            if stored
            else "YouTube captions are already stored for this video and were kept.",
        )
        if self.transcripts.cached(video_id) is None:
            raise PipelineError("the transcript could not be stored")

    async def _recheck_captions(self, video_id: str, priority: int) -> bool:
        """Ask once more whether captions exist; True when they do (and the audio is not needed)."""
        began = time.monotonic()

        def took() -> float:
            return round(time.monotonic() - began, 2)

        try:
            found = await self.transcripts.get(video_id, priority, recheck=True)
        except NoCaptions:
            events.emit(events.CAPTION_RECHECK, events.OK, result="no_captions", seconds=took())
            return False
        except YoutubeDelayed as exc:
            events.emit(
                events.CAPTION_RECHECK,
                events.WARN,
                result="delayed",
                reason=exc.reason,
                seconds=took(),
                message="YouTube did not answer the caption check; went on with the audio.",
            )
            return False
        except YoutubeVideoError as exc:
            if not exc.can_transcribe:
                events.emit(
                    events.CAPTION_RECHECK,
                    events.FAILED,
                    result="video_unavailable",
                    reason=exc.reason,
                    seconds=took(),
                )
                raise
            events.emit(
                events.CAPTION_RECHECK,
                events.WARN,
                result="video_error",
                reason=exc.reason,
                seconds=took(),
                message="YouTube refused the caption check, but the audio may still work.",
            )
            return False
        events.emit(
            events.CAPTION_RECHECK,
            events.OK,
            result="found",
            source=found.source,
            lang=found.lang,
            chars=len(found.text),
            seconds=took(),
            message="A usable transcript exists, so the audio was not downloaded.",
        )
        events.emit(
            events.STORED,
            events.OK,
            kind="transcript",
            source=found.source,
            stored=False,
            lang=found.lang,
            engine=found.engine,
            model=found.model,
            chars=len(found.text),
            message="Used the transcript that was already stored for this video.",
        )
        return True

    def _fail(self, job: dict[str, Any], message: str, exc: BaseException | None = None) -> None:
        now = time.time()
        self.db.execute(
            "UPDATE jobs SET status='failed', error=?, updated_at=?, finished_at=? WHERE id=?",
            [message, now, now, job["id"]],
        )
        trace = events.current()
        detail: dict[str, Any] = {
            "message": message,
            "stage": trace.failed_stage if trace else None,
            "attempts": (job.get("attempts") or 0) + 1,
        }
        if exc is not None:
            detail.update(error_class=events.error_class(exc), technical=events.technical(exc))
        self.events.record(job["id"], events.FAILED_STAGE, events.FAILED, detail)

    def _retry(self, job: dict[str, Any], exc: YoutubeDelayed) -> None:
        """Back into the queue after a transient YouTube problem, at most `job_max_attempts` times."""
        attempts = (job.get("attempts") or 0) + 1
        if attempts >= self.cfg.captions.job_max_attempts:
            log.warning("%s job %s gave up after %d attempts", job["kind"], job["id"], attempts)
            self._fail(job, MSG_JOB_RETRIES, exc)
            return
        log.warning(
            "%s job %s back in the queue (attempt %d, %s)",
            job["kind"],
            job["id"],
            attempts,
            exc.reason,
        )
        self.db.execute(
            "UPDATE jobs SET status='queued', progress=0, attempts=?, not_before=?, updated_at=?"
            " WHERE id=?",
            [attempts, self.pipeline.gate.now() + exc.retry_after_s, time.time(), job["id"]],
        )
        self.events.record(
            job["id"],
            events.RETRY,
            events.WARN,
            {
                "reason": exc.reason,
                "attempt": attempts,
                "max_attempts": self.cfg.captions.job_max_attempts,
                "retry_after_s": round(exc.retry_after_s),
                "message": "YouTube held the job back; it goes back into the queue.",
            },
        )

    async def run_one(self) -> bool:
        job = self._claim()
        if job is None:
            return False
        trace = events.JobTrace(job["id"], self.events)
        token = events.bind(trace)
        began = time.monotonic()
        trace.emit(
            events.STARTED,
            events.OK,
            attempt=(job.get("attempts") or 0) + 1,
            waited_s=round(max(0.0, time.time() - (job.get("updated_at") or time.time())), 1),
            priority=events.priority_name(job["priority"]),
        )
        try:
            if job["kind"] == KIND_TRANSCRIPT:
                await self._run_transcript(job)
            else:
                await self._run_captions(job)
            now = time.time()
            self.db.execute(
                "UPDATE jobs SET status='ready', progress=1, updated_at=?, finished_at=?"
                " WHERE id=?",
                [now, now, job["id"]],
            )
            trace.emit(events.FINISHED, events.OK, seconds=round(time.monotonic() - began, 2))
        except asyncio.CancelledError:
            raise
        except YoutubeVideoError as exc:
            self.transcripts.record_failure(job["video_id"], exc.reason)
            log.warning("%s job %s failed: %s", job["kind"], job["id"], exc.reason)
            self._fail(job, exc.message, exc)
        except MediaArchiveFull as exc:
            log.warning("%s job %s failed: %s", job["kind"], job["id"], exc)
            self._fail(job, exc.message, exc)
        except MediaArchiveError as exc:
            log.warning("%s job %s failed: %s", job["kind"], job["id"], exc)
            self._fail(job, exc.message, exc)
        except YoutubeDelayed as exc:
            self._retry(job, exc)
        except Exception as exc:
            log.warning("%s job %s failed: %s", job["kind"], job["id"], exc, exc_info=True)
            self._fail(job, MSG_TRANSCRIBE if job["kind"] == KIND_TRANSCRIPT else MSG_JOB, exc)
        finally:
            events.unbind(token)
        return True

    async def _worker(self) -> None:
        while not self._stopping:
            if await self.run_one():
                continue
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.cfg.captions.job_poll_s)
            except TimeoutError:
                pass
            self._wake.clear()
