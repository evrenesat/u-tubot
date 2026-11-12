"""Where a video's transcript stands, and the ask-first flow for videos without captions.

A summary, insight or answer is only ever built from a real transcript. When there is none the
caller reports why (`transcript_status`) instead: YouTube is slowing us down (`delayed`), the video
has no captions and the user may start a background transcription (`none`), a transcription runs
(`transcribing`) or failed (`failed`).
"""

from __future__ import annotations

import math
import time
from typing import Any

from .captions.jobs import ACTIVE, KIND_TRANSCRIPT, JobQueue
from .config import Config
from .errors import MSG_NO_CAPTIONS, MSG_NO_CAPTIONS_UNAVAILABLE, MSG_TRANSCRIBE, delayed_message
from .transcripts import NoCaptions, TranscriptService
from .youtube import YoutubeDelayed

OK = "ok"
DELAYED = "delayed"
NONE = "none"
TRANSCRIBING = "transcribing"
FAILED = "failed"
UNKNOWN = "unknown"

STATUS_FOR = {
    TRANSCRIBING: "pending",
    NONE: "needs_transcript",
    FAILED: "failed",
    DELAYED: "pending",
}
PROGRESS_DIGITS = 3
MIN_SPEED_FACTOR = 0.01


class TranscribeRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Transcription:
    def __init__(self, cfg: Config, transcripts: TranscriptService, jobs: JobQueue):
        self.cfg, self.transcripts, self.jobs = cfg, transcripts, jobs

    def _meta(self, video_id: str, hint: dict[str, Any] | None) -> dict[str, Any]:
        return {**(hint or {}), **(self.transcripts.cached_meta(video_id) or {})}

    def estimate_s(self, duration_s: float | None) -> int | None:
        """Rough wall-clock seconds to transcribe: fixed overhead plus audio length over ASR speed."""
        if not duration_s:
            return None
        c = self.cfg.captions
        return round(c.asr_overhead_s + duration_s / max(c.asr_speed_factor, MIN_SPEED_FACTOR))

    def can_transcribe(self, meta: dict[str, Any]) -> bool:
        duration = meta.get("duration_s")
        if meta.get("is_live"):
            return False
        return not (duration and duration > self.cfg.captions.max_duration_s)

    def none_fields(self, video_id: str, hint: dict[str, Any] | None = None) -> dict[str, Any]:
        meta = self._meta(video_id, hint)
        can = self.can_transcribe(meta)
        return {
            "transcript_status": NONE,
            "can_transcribe": can,
            "message": MSG_NO_CAPTIONS if can else MSG_NO_CAPTIONS_UNAVAILABLE,
            "estimate_s": self.estimate_s(meta.get("duration_s")) if can else None,
        }

    def state(self, video_id: str, hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Transcript state known without touching YouTube; None when it is not known yet."""
        cached = self.transcripts.cached(video_id)
        if cached:
            return {"transcript_status": OK, "source": cached.source, "lang": cached.lang}
        meta = self._meta(video_id, hint)
        job = self.jobs.transcript_job(video_id)
        if job and job["status"] in ACTIVE:
            return {
                "transcript_status": TRANSCRIBING,
                "progress": round(job["progress"], PROGRESS_DIGITS),
                "estimate_s": self.estimate_s(meta.get("duration_s")),
                "job_id": job["id"],
            }
        recent = (
            job
            and job["status"] == "failed"
            and time.time() - job["updated_at"] <= self.cfg.transcripts.no_captions_ttl_s
        )
        if recent:
            return {
                "transcript_status": FAILED,
                "error": MSG_TRANSCRIBE,
                "can_transcribe": self.can_transcribe(meta),
                "job_id": job["id"],
            }
        if self.transcripts.no_captions(video_id):
            return self.none_fields(video_id, hint)
        return None

    def blocked(self, video_id: str, hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Response fields when the transcript is not usable right now; None when it is."""
        state = self.state(video_id, hint)
        if state is None or state["transcript_status"] == OK:
            return None
        return {"status": STATUS_FOR[state["transcript_status"]], **state}

    def problem(
        self, video_id: str, exc: BaseException, hint: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Response fields for a transcript fetch that ended in an expected outcome."""
        if isinstance(exc, YoutubeDelayed):
            return {
                "status": STATUS_FOR[DELAYED],
                "transcript_status": DELAYED,
                "error": delayed_message(exc),
                "retry_after_s": max(1, math.ceil(exc.retry_after_s)),
            }
        if isinstance(exc, NoCaptions):
            return {"status": STATUS_FOR[NONE], **self.none_fields(video_id, hint)}
        return None

    def request(
        self, user: str, video_id: str, hint: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Queue (or rejoin) the user's background ASR transcript job for a video."""
        base = {"video_id": video_id}
        state = self.state(video_id, hint)
        if state and state["transcript_status"] == OK:
            return {**base, "status": "ready", "progress": 1.0, **state}
        meta = self._meta(video_id, hint)
        if not self.can_transcribe(meta):
            raise TranscribeRefused(400, MSG_NO_CAPTIONS_UNAVAILABLE)
        job = self.jobs.find_active_transcript(user, video_id)
        if job is None:
            limit = self.cfg.captions.transcribe_max_active_per_user
            if self.jobs.active_count(user, KIND_TRANSCRIPT) >= limit:
                raise TranscribeRefused(
                    429, "too many transcriptions queued, wait for one to finish"
                )
            job = self.jobs.enqueue_transcript(user, video_id, meta.get("title"))
        return {
            **base,
            "status": job["status"],
            "job_id": job["id"],
            "transcript_status": TRANSCRIBING,
            "progress": round(job["progress"], PROGRESS_DIGITS),
            "estimate_s": self.estimate_s(meta.get("duration_s")),
        }

    def status(self, video_id: str, hint: dict[str, Any] | None = None) -> dict[str, Any]:
        """`GET /v1/videos/{id}/transcript`: cheap, never touches YouTube."""
        state = self.state(video_id, hint) or {
            "transcript_status": UNKNOWN,
            "source": None,
        }
        return {"video_id": video_id, **state}
