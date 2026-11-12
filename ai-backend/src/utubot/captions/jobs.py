from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from ..config import Config
from ..db import Database
from ..errors import MSG_JOB
from .pipeline import CaptionPipeline

log = logging.getLogger("utubot.jobs")
ACTIVE = ("queued", "running")


class JobQueue:
    def __init__(self, cfg: Config, db: Database, pipeline: CaptionPipeline):
        self.cfg, self.db, self.pipeline = cfg, db, pipeline
        self._wake = asyncio.Event()
        self._workers: list[asyncio.Task] = []
        self._stopping = False

    def start(self) -> None:
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
            "SELECT * FROM jobs WHERE video_id=? AND lang=? AND IFNULL(translate_to,'')=?"
            " AND status IN ('queued','running') ORDER BY created_at DESC LIMIT 1",
            [video_id, lang, translate_to or ""],
        )
        if row:
            return dict(row)
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.execute(
            "INSERT INTO jobs(id,user,video_id,lang,translate_to,status,progress,created_at,"
            "updated_at) VALUES(?,?,?,?,?,'queued',0,?,?)",
            [job_id, user, video_id, lang, translate_to, now, now],
        )
        self._wake.set()
        return dict(self.db.one("SELECT * FROM jobs WHERE id=?", [job_id]))

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
            "SELECT status, progress FROM jobs WHERE video_id=? AND status IN ('queued','running')"
            " ORDER BY created_at DESC LIMIT 1",
            [video_id],
        )
        if active:
            return {"status": active["status"], "progress": active["progress"], "tracks": tracks}
        if tracks:
            return {"status": "ready", "progress": 1.0, "tracks": tracks}
        last = self.db.one(
            "SELECT status, error FROM jobs WHERE video_id=? ORDER BY created_at DESC LIMIT 1",
            [video_id],
        )
        if last and last["status"] == "failed":
            return {"status": "failed", "progress": 0.0, "tracks": [], "error": last["error"]}
        return {"status": "none", "progress": 0.0, "tracks": []}

    def recent(self, user: str, limit: int) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT id,video_id,lang,translate_to,status,progress,error,updated_at FROM jobs"
            " WHERE user=? ORDER BY created_at DESC LIMIT ?",
            [user, limit],
        )
        return [dict(r) for r in rows]

    def _claim(self) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1")
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

    async def run_one(self) -> bool:
        job = self._claim()
        if job is None:
            return False
        try:
            await self.pipeline.run(
                job["video_id"],
                job["lang"],
                job["translate_to"],
                lambda f: self._set_progress(job["id"], f),
            )
            self.db.execute(
                "UPDATE jobs SET status='ready', progress=1, updated_at=? WHERE id=?",
                [time.time(), job["id"]],
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("caption job %s failed: %s", job["id"], exc, exc_info=True)
            self.db.execute(
                "UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?",
                [MSG_JOB, time.time(), job["id"]],
            )
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
