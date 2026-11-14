"""The detail report of one job: what was asked, what was done, what happened, who fetched it."""

from __future__ import annotations

import json
from typing import Any

from ..config import Config
from ..db import METADATA_ONLY, Database
from ..transcripts import TranscriptService, parse_vtt
from . import events
from .jobs import (
    DETAIL_API,
    DETAIL_PAGE,
    JOB_STATES,
    KIND_CAPTIONS,
    KIND_TRANSCRIPT,
    JobQueue,
)

PREVIEW_ITEMS = 10
PREVIEW_CHARS = 400
TRANSCRIPT_URL = "/v1/jobs/{}/transcript.txt"
VTT_URL = "/v1/videos/{}/captions/{}.vtt"
TRACK_TEXT_URL = TRANSCRIPT_URL + "?lang={}"


class JobReports:
    def __init__(self, cfg: Config, db: Database, jobs: JobQueue, transcripts: TranscriptService):
        self.cfg, self.db, self.jobs, self.transcripts = cfg, db, jobs, transcripts

    def visible(self, job: dict[str, Any] | None, user: str, is_admin: bool) -> bool:
        """A job is shown to its owner and to admins; anybody else is told it does not exist."""
        return job is not None and (is_admin or job["user"] == user)

    def report(self, job: dict[str, Any], viewer: str) -> dict[str, Any]:
        """The document behind `GET /v1/jobs/{id}`; `viewer` decides which actions are offered."""
        job_id = job["id"]
        log = self.jobs.events.list(job_id)
        if not log:
            stage, status, detail, ts = events.synthetic_event(job)
            log = [{"id": 0, "ts": ts, "stage": stage, "status": status, "detail": detail}]
        queued = next((e["detail"] for e in log if e["stage"] == events.QUEUED), {})
        meta = self.transcripts.cached_meta(job["video_id"]) or {}
        state = JOB_STATES.get(job["status"], job["status"])
        owner = job["user"] == viewer
        return {
            "id": job_id,
            "kind": job["kind"],
            "user": job["user"],
            "state": state,
            "progress": job["progress"],
            "error": job["error"],
            "priority": events.priority_name(job["priority"]),
            "attempts": job["attempts"] or 0,
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "finished_at": job["finished_at"],
            "retry_after_s": self.jobs.retry_after(job, state),
            "detail_url": DETAIL_PAGE.format(job_id),
            "api_url": DETAIL_API.format(job_id),
            "can_cancel": owner and job["status"] == "queued",
            "can_retry": owner and job["status"] in ("failed", "cancelled"),
            "inputs": self._inputs(job, meta, queued),
            "outputs": self._outputs(job),
            "delivery": self._delivery(log),
            "events": log,
        }

    def _inputs(
        self, job: dict[str, Any], meta: dict[str, Any], queued: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "video_id": job["video_id"],
            "title": job["title"] or meta.get("title"),
            "channel": meta.get("channel"),
            "duration_s": meta.get("duration_s"),
            "language": meta.get("language"),
            "lang": job["lang"],
            "translate_to": job["translate_to"],
            "requested": {
                "user": queued.get("user", job["user"]),
                "client": queued.get("client"),
                "endpoint": queued.get("endpoint"),
                "trigger": queued.get("trigger"),
                "priority": queued.get("priority") or events.priority_name(job["priority"]),
                "at": job["created_at"],
            },
        }

    def _outputs(self, job: dict[str, Any]) -> dict[str, Any]:
        if job["kind"] == KIND_TRANSCRIPT:
            return {"transcript": self._transcript(job), "captions": []}
        return {"transcript": None, "captions": self._tracks(job)}

    def _transcript(self, job: dict[str, Any]) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM transcripts WHERE video_id=?", [job["video_id"]])
        if row is None or not row["text"] or row["source"] == METADATA_ONLY:
            return None
        text = row["text"]
        lines = [line for line in text.splitlines() if line.strip()]
        segments = json.loads(row["segments"]) if row["segments"] else []
        return {
            "source": row["source"],
            "lang": row["lang"],
            "engine": row["engine"],
            "model": row["model"],
            "chars": len(text),
            "lines": len(lines),
            "segments": len(segments),
            "stored_at": row["fetched_at"],
            "from_this_job": row["job_id"] == job["id"] if row["job_id"] else None,
            "first_lines": [line[:PREVIEW_CHARS] for line in lines[:PREVIEW_ITEMS]],
            "text_url": TRANSCRIPT_URL.format(job["id"]),
        }

    def _track_rows(self, job: dict[str, Any]) -> list[Any]:
        return self.db.all(
            "SELECT lang,label,speakers,vtt,created_at,job_id FROM captions"
            " WHERE video_id=? AND (job_id=? OR job_id IS NULL) ORDER BY lang",
            [job["video_id"], job["id"]],
        )

    def _tracks(self, job: dict[str, Any]) -> list[dict[str, Any]]:
        tracks = []
        for row in self._track_rows(job):
            cues = parse_vtt(row["vtt"])
            tracks.append(
                {
                    "lang": row["lang"],
                    "label": row["label"],
                    "speakers": row["speakers"],
                    "cues": row["vtt"].count("-->"),
                    "bytes": len(row["vtt"].encode()),
                    "created_at": row["created_at"],
                    "from_this_job": row["job_id"] == job["id"] if row["job_id"] else None,
                    "preview": [
                        {"start": round(start, 2), "text": text[:PREVIEW_CHARS]}
                        for start, _end, text in cues[:PREVIEW_ITEMS]
                    ],
                    "vtt_url": VTT_URL.format(job["video_id"], row["lang"]),
                    "text_url": TRACK_TEXT_URL.format(job["id"], row["lang"]),
                }
            )
        return tracks

    def transcript_text(self, job: dict[str, Any], lang: str | None = None) -> str | None:
        """The plain text of the job's result: the stored transcript, or the cue text of a captions track."""
        if job["kind"] == KIND_CAPTIONS:
            rows = [r for r in self._track_rows(job) if lang in (None, r["lang"])]
            if not rows:
                return None
            return "\n".join(text for _start, _end, text in parse_vtt(rows[0]["vtt"]))
        row = self.db.one(
            "SELECT text, source FROM transcripts WHERE video_id=?", [job["video_id"]]
        )
        if row is None or not row["text"] or row["source"] == METADATA_ONLY:
            return None
        return row["text"]

    @staticmethod
    def _delivery(log: list[dict[str, Any]]) -> dict[str, Any]:
        """Who fetched the result: one entry per client with the ways it did so and how often."""
        clients: dict[str, dict[str, Any]] = {}
        for event in log:
            if event["stage"] != events.DELIVERED:
                continue
            detail = event["detail"]
            name = detail.get("client") or "unknown"
            entry = clients.setdefault(
                name,
                {"client": name, "user": detail.get("user"), "count": 0, "last_ts": 0.0, "via": []},
            )
            entry["count"] += int(detail.get("count", 1))
            entry["last_ts"] = max(entry["last_ts"], event["ts"])
            via = detail.get("via")
            if via and via not in entry["via"]:
                entry["via"].append(via)
        ordered = sorted(clients.values(), key=lambda c: -c["last_ts"])
        return {
            "delivered": bool(ordered),
            "count": sum(c["count"] for c in ordered),
            "last_ts": ordered[0]["last_ts"] if ordered else None,
            "clients": ordered,
        }
