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

from .captions.asr import normalize_language
from .captions.engines import AsrRouter
from .captions.jobs import ACTIVE, KIND_TRANSCRIPT, JobQueue
from .config import Config, UserPolicy
from .errors import (
    MSG_NO_CAPTIONS,
    MSG_NO_CAPTIONS_UNAVAILABLE,
    MSG_TRANSCRIBE,
    captions_limited_message,
    delayed_message,
)
from .llm import BACKGROUND, INTERACTIVE
from .transcripts import HOLD_DELAYED, SOURCE_ASR, NoCaptions, TranscriptService
from .youtube import (
    CLASS_MEDIA,
    FETCH_CLASSES,
    REASON_BOT_CHECK,
    REASON_COOLDOWN,
    REASON_FORBIDDEN,
    REASON_RATE_LIMITED,
    YoutubeDelayed,
    YoutubeVideoError,
)

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
SECONDS_PER_MINUTE = 60
AUTO_OFF = "off"
AUTO_ON_DWELL = "on_dwell"
# YouTube told the server to back off (or the breaker is open); the audio may still be reachable.
BACK_OFF_REASONS = frozenset(
    {REASON_RATE_LIMITED, REASON_FORBIDDEN, REASON_BOT_CHECK, REASON_COOLDOWN}
)


class TranscribeRefused(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class Transcription:
    def __init__(self, cfg: Config, transcripts: TranscriptService, jobs: JobQueue):
        self.cfg, self.transcripts, self.jobs = cfg, transcripts, jobs
        asr = jobs.pipeline.asr
        self.engines = asr if isinstance(asr, AsrRouter) else AsrRouter(cfg.captions)

    def _meta(self, video_id: str, hint: dict[str, Any] | None) -> dict[str, Any]:
        return {**(hint or {}), **(self.transcripts.cached_meta(video_id) or {})}

    def estimate_s(
        self,
        duration_s: float | None,
        language: str | None = None,
        priority: int = INTERACTIVE,
    ) -> int | None:
        """Rough wall-clock seconds: the audio download plus the chosen engine's chunked ASR."""
        if not duration_s:
            return None
        c = self.cfg.captions
        asr = self.engines.estimate_s(duration_s, normalize_language(language), priority)
        if asr is None:
            return None
        download = c.download_overhead_s + duration_s / max(
            c.download_speed_factor, MIN_SPEED_FACTOR
        )
        return round(download + asr)

    def can_transcribe(self, meta: dict[str, Any]) -> bool:
        duration = meta.get("duration_s")
        if meta.get("is_live"):
            return False
        if duration and duration > self.cfg.captions.max_duration_s:
            return False
        return self.engines.available(normalize_language(meta.get("language")))

    def none_fields(self, video_id: str, hint: dict[str, Any] | None = None) -> dict[str, Any]:
        meta = self._meta(video_id, hint)
        can = self.can_transcribe(meta)
        return {
            "transcript_status": NONE,
            "can_transcribe": can,
            "message": MSG_NO_CAPTIONS if can else MSG_NO_CAPTIONS_UNAVAILABLE,
            "estimate_s": self.estimate_s(meta.get("duration_s"), meta.get("language"))
            if can
            else None,
        }

    def captions_limited(self, video_id: str) -> bool:
        """True while interactive caption fetches are held back: a cooldown, or the probe is out.

        Also asks for the background probe once a cooldown is over (a no-op otherwise), because
        nothing interactive may do it.
        """
        if self.transcripts.gate.interactive_ok(*FETCH_CLASSES):
            return False
        self.transcripts.probe_captions(video_id)
        return True

    def audio_fallback(
        self, video_id: str, hint: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """`needs_transcript` fields for a video whose captions YouTube will not give us just now.

        The audio is reachable (the `media` class is healthy) and a speech engine can take it, so the
        transcription stands in for the captions, subject to the user's policy like "no captions".
        None when it cannot: the answer is then "delayed". Nothing of this is remembered.
        """
        if not self.transcripts.gate.healthy(CLASS_MEDIA):
            return None
        meta = self._meta(video_id, hint)
        if not self.can_transcribe(meta):
            return None
        estimate = self.estimate_s(meta.get("duration_s"), meta.get("language"))
        return {
            "transcript_status": NONE,
            "can_transcribe": True,
            "message": captions_limited_message(estimate),
            "estimate_s": estimate,
        }

    def auto_allowed(self, policy: UserPolicy, meta: dict[str, Any], *, passive: bool) -> bool:
        """May a video without captions be transcribed without asking this user?

        `on_open` transcribes when the user asks for a summary, insight or answer; `on_dwell` also
        when they merely linger on the video (`passive`: the side panel). Only videos up to
        `auto_transcribe_max_minutes` (length must be known) qualify.
        """
        mode = policy.auto_transcribe
        if mode == AUTO_OFF or (passive and mode != AUTO_ON_DWELL):
            return False
        duration = meta.get("duration_s")
        if not duration or duration > policy.auto_transcribe_max_minutes * SECONDS_PER_MINUTE:
            return False
        return self.can_transcribe(meta)

    def auto(
        self,
        fields: dict[str, Any],
        *,
        user: str | None,
        policy: UserPolicy,
        video_id: str,
        hint: dict[str, Any] | None,
        passive: bool = False,
    ) -> dict[str, Any]:
        """Turn a `needs_transcript` answer into a started transcription when the policy allows.

        Anything else (and a refused or disallowed start) comes back unchanged. The answer then
        is `pending` + `transcribing` with `progress` and `estimate_s`, like any running job.
        """
        if user is None or fields.get("transcript_status") != NONE:
            return fields
        if not self.auto_allowed(policy, self._meta(video_id, hint), passive=passive):
            return fields
        try:
            queued = self.request(
                user, video_id, hint, priority=BACKGROUND if passive else INTERACTIVE
            )
        except TranscribeRefused:
            return fields
        return {
            "status": STATUS_FOR[TRANSCRIBING],
            "transcript_status": TRANSCRIBING,
            "progress": queued["progress"],
            "estimate_s": queued["estimate_s"],
        }

    def _held(self, video_id: str, meta: dict[str, Any]) -> dict[str, Any] | None:
        held = self.transcripts.hold(video_id)
        if held is None:
            return None
        if held["kind"] == HOLD_DELAYED:
            wait = YoutubeDelayed(held["reason"], max(0.0, held["until"] - time.time()))
            return {
                "transcript_status": DELAYED,
                "error": delayed_message(wait),
                "retry_after_s": max(1, math.ceil(wait.retry_after_s)),
            }
        failure = YoutubeVideoError(held["reason"])
        return {
            "transcript_status": FAILED,
            "error": failure.message,
            "reason": failure.reason,
            "can_transcribe": failure.can_transcribe and self.can_transcribe(meta),
        }

    def state(self, video_id: str, hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Transcript state known without touching YouTube; None when it is not known yet.

        Never carries a job id: jobs belong to the user who queued them (see `status`).
        """
        cached = self.transcripts.cached(video_id)
        if cached:
            ok = {"transcript_status": OK, "source": cached.source, "lang": cached.lang}
            if cached.source == SOURCE_ASR:
                ok.update(engine=cached.engine, model=cached.model)
            return ok
        meta = self._meta(video_id, hint)
        job = self.jobs.transcript_job(video_id)
        if job and job["status"] in ACTIVE:
            return {
                "transcript_status": TRANSCRIBING,
                "progress": round(job["progress"], PROGRESS_DIGITS),
                "estimate_s": self.estimate_s(
                    meta.get("duration_s"), meta.get("language"), job["priority"]
                ),
            }
        held = self._held(video_id, meta)
        if held:
            return held
        recent = (
            job
            and job["status"] == "failed"
            and time.time() - job["updated_at"] <= self.cfg.transcripts.no_captions_ttl_s
        )
        if recent:
            return {
                "transcript_status": FAILED,
                "error": job["error"] or MSG_TRANSCRIBE,
                "can_transcribe": self.can_transcribe(meta),
            }
        if self.transcripts.no_captions(video_id):
            return self.none_fields(video_id, hint)
        if self.captions_limited(video_id):
            return self.audio_fallback(video_id, hint)
        return None

    def blocked(
        self, video_id: str, hint: dict[str, Any] | None = None, *, promote: bool = False
    ) -> dict[str, Any] | None:
        """Response fields when the transcript is not usable right now; None when it is.

        `promote`: the caller is waiting on a running or queued transcription, so it goes first.
        """
        state = self.state(video_id, hint)
        if state is None or state["transcript_status"] == OK:
            return None
        if promote and state["transcript_status"] == TRANSCRIBING:
            self.jobs.promote_transcript(video_id)
        return {"status": STATUS_FOR[state["transcript_status"]], **state}

    def problem(
        self, video_id: str, exc: BaseException, hint: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Response fields for a transcript fetch that ended in an expected outcome."""
        if isinstance(exc, YoutubeDelayed):
            self.transcripts.probe_captions(video_id)
            fallback = (
                self.audio_fallback(video_id, hint) if exc.reason in BACK_OFF_REASONS else None
            )
            if fallback:
                return {"status": STATUS_FOR[NONE], **fallback}
            return {
                "status": STATUS_FOR[DELAYED],
                "transcript_status": DELAYED,
                "error": delayed_message(exc),
                "retry_after_s": max(1, math.ceil(exc.retry_after_s)),
            }
        if isinstance(exc, YoutubeVideoError):
            return {
                "status": STATUS_FOR[FAILED],
                "transcript_status": FAILED,
                "error": exc.message,
                "reason": exc.reason,
                "can_transcribe": exc.can_transcribe
                and self.can_transcribe(self._meta(video_id, hint)),
            }
        if isinstance(exc, NoCaptions):
            return {"status": STATUS_FOR[NONE], **self.none_fields(video_id, hint)}
        return None

    def request(
        self,
        user: str,
        video_id: str,
        hint: dict[str, Any] | None = None,
        priority: int = INTERACTIVE,
    ) -> dict[str, Any]:
        """Queue (or rejoin) the user's ASR transcript job for a video.

        The user asked for it, so it is interactive unless the caller says otherwise (`BACKGROUND`:
        started on the user's behalf by a passive trigger).
        """
        base = {"video_id": video_id}
        state = self.state(video_id, hint)
        if state and state["transcript_status"] == OK:
            return {**base, "status": "ready", "progress": 1.0, **state}
        meta = self._meta(video_id, hint)
        if not self.can_transcribe(meta):
            raise TranscribeRefused(400, MSG_NO_CAPTIONS_UNAVAILABLE)
        if state and state["transcript_status"] == FAILED and not state.get("can_transcribe", True):
            raise TranscribeRefused(400, state["error"])
        job = self.jobs.find_active_transcript(user, video_id)
        if job is None:
            limit = self.cfg.captions.transcribe_max_active_per_user
            if self.jobs.active_count(user, KIND_TRANSCRIPT) >= limit:
                raise TranscribeRefused(
                    429, "too many transcriptions queued, wait for one to finish"
                )
            job = self.jobs.enqueue_transcript(user, video_id, meta.get("title"), priority)
        elif priority == INTERACTIVE:
            self.jobs.promote_transcript(video_id)
        return {
            **base,
            "status": job["status"],
            "job_id": job["id"],
            "transcript_status": TRANSCRIBING,
            "progress": round(job["progress"], PROGRESS_DIGITS),
            "estimate_s": self.estimate_s(meta.get("duration_s"), meta.get("language"), priority),
        }

    def status(
        self, video_id: str, user: str, hint: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """`GET /v1/videos/{id}/transcript`: cheap, never touches YouTube.

        Progress and outcome are about the video and shared; `job_id` is only the caller's own job.
        """
        state = self.state(video_id, hint) or {"transcript_status": UNKNOWN, "source": None}
        out = {"video_id": video_id, **state}
        job = self.jobs.own_transcript_job(user, video_id)
        if job and state["transcript_status"] in (TRANSCRIBING, FAILED):
            out["job_id"] = job["id"]
        return out
