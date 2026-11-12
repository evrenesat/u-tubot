from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from ..config import Config
from ..db import Database
from ..errors import MSG_JOB, MSG_JOB_RETRIES, MSG_TRANSCRIBE
from ..llm import BACKGROUND
from ..transcripts import NoCaptions, TranscriptService
from ..youtube import YoutubeDelayed, YoutubeVideoError
from .pipeline import CaptionPipeline, sweep_media

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
        self._wake = asyncio.Event()
        self._workers: list[asyncio.Task] = []
        self._stopping = False

    def start(self) -> None:
        if not self.cfg.captions.keep_media:
            removed = sweep_media(self.cfg.media_dir, self.cfg.captions.media_orphan_age_s)
            if removed:
                log.info("removed %d orphaned media directories", removed)
        self.db.execute(
            "UPDATE jobs SET status='queued', progress=0, updated_at=? WHERE status='running'",
            [time.time()],
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
        self, user: str, video_id: str, lang: str, translate_to: str | None
    ) -> dict[str, Any]:
        row = self.db.one(
            "SELECT * FROM jobs WHERE kind=? AND video_id=? AND lang=?"
            " AND IFNULL(translate_to,'')=? AND status IN ('queued','running')"
            " ORDER BY created_at DESC LIMIT 1",
            [KIND_CAPTIONS, video_id, lang, translate_to or ""],
        )
        if row:
            return dict(row)
        return self._insert(user, video_id, KIND_CAPTIONS, lang, translate_to, None)

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

    def enqueue_transcript(self, user: str, video_id: str, title: str | None) -> dict[str, Any]:
        """Queue an ASR transcript; the same user asking again gets the job already queued."""
        return self.find_active_transcript(user, video_id) or self._insert(
            user, video_id, KIND_TRANSCRIPT, LANG_AUTO, None, title
        )

    def _insert(
        self,
        user: str,
        video_id: str,
        kind: str,
        lang: str,
        translate_to: str | None,
        title: str | None,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.execute(
            "INSERT INTO jobs(id,user,video_id,lang,translate_to,status,progress,created_at,"
            "updated_at,kind,title) VALUES(?,?,?,?,?,'queued',0,?,?,?,?)",
            [job_id, user, video_id, lang, translate_to, now, now, kind, title],
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
            "SELECT id, status, progress, error, updated_at FROM jobs WHERE kind=? AND video_id=?"
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
        now = self.pipeline.gate.now()
        out = []
        for r in rows:
            retry = max(self.pipeline.gate.cooldown_remaining(), (r["not_before"] or 0) - now)
            title = r["title"] or (self.transcripts.cached_meta(r["video_id"]) or {}).get("title")
            state = JOB_STATES.get(r["status"], r["status"])
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
                    "retry_after_s": round(retry) if retry > 0 and state == "waiting" else None,
                }
            )
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
        self._wake.set()
        return self.get(job_id) or job

    def _claim(self) -> dict[str, Any] | None:
        """Next queued job; none while the YouTube breaker is open (queued work waits, not fails)."""
        if not self.pipeline.gate.healthy():
            return None
        row = self.db.one(
            "SELECT * FROM jobs WHERE status='queued' AND (not_before IS NULL OR not_before<=?)"
            " AND NOT EXISTS"
            " (SELECT 1 FROM jobs r WHERE r.video_id=jobs.video_id AND r.status='running')"
            " ORDER BY created_at LIMIT 1",
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

    async def _run_transcript(self, job: dict[str, Any]) -> None:
        """ASR, unless YouTube has captions after all: those are used and the audio is skipped."""
        video_id = job["video_id"]
        try:
            await self.transcripts.get(video_id, BACKGROUND, recheck=True)
            return
        except NoCaptions:
            pass
        except YoutubeVideoError as exc:
            if not exc.can_transcribe:
                raise
        text, lang = await self.pipeline.transcribe(
            video_id, lambda f: self._set_progress(job["id"], f)
        )
        self.transcripts.store_asr(video_id, text, lang)

    def _fail(self, job: dict[str, Any], message: str) -> None:
        now = time.time()
        self.db.execute(
            "UPDATE jobs SET status='failed', error=?, updated_at=?, finished_at=? WHERE id=?",
            [message, now, now, job["id"]],
        )

    def _retry(self, job: dict[str, Any], exc: YoutubeDelayed) -> None:
        """Back into the queue after a transient YouTube problem, at most `job_max_attempts` times."""
        attempts = (job.get("attempts") or 0) + 1
        if attempts >= self.cfg.captions.job_max_attempts:
            log.warning("%s job %s gave up after %d attempts", job["kind"], job["id"], attempts)
            self._fail(job, MSG_JOB_RETRIES)
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

    async def run_one(self) -> bool:
        job = self._claim()
        if job is None:
            return False
        try:
            if job["kind"] == KIND_TRANSCRIPT:
                await self._run_transcript(job)
            else:
                await self.pipeline.run(
                    job["video_id"],
                    job["lang"],
                    job["translate_to"],
                    lambda f: self._set_progress(job["id"], f),
                )
            now = time.time()
            self.db.execute(
                "UPDATE jobs SET status='ready', progress=1, updated_at=?, finished_at=?"
                " WHERE id=?",
                [now, now, job["id"]],
            )
        except asyncio.CancelledError:
            raise
        except YoutubeVideoError as exc:
            self.transcripts.record_failure(job["video_id"], exc.reason)
            log.warning("%s job %s failed: %s", job["kind"], job["id"], exc.reason)
            self._fail(job, exc.message)
        except YoutubeDelayed as exc:
            self._retry(job, exc)
        except Exception as exc:
            log.warning("%s job %s failed: %s", job["kind"], job["id"], exc, exc_info=True)
            self._fail(job, MSG_TRANSCRIBE if job["kind"] == KIND_TRANSCRIPT else MSG_JOB)
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
