from __future__ import annotations

import logging
import math

from .llm import LLMBusyError, LLMError
from .youtube import REASON_EMPTY, REASON_NETWORK, YoutubeDelayed

log = logging.getLogger("utubot.errors")

MSG_LLM = "the language model request failed, try again later"
MSG_BUSY = "the language model is busy, try again in a moment"
MSG_GENERIC = "could not process this video, try again later"
MSG_JOB = "caption generation failed"
MSG_TRANSCRIBE = "transcription failed"
MSG_JOB_RETRIES = "YouTube kept refusing the download, try again later"
MSG_NO_CAPTIONS = "No captions. Transcribe the audio in the background?"
MSG_NO_CAPTIONS_UNAVAILABLE = "No captions are available for this video."
SECONDS_PER_MINUTE = 60


def minutes_hint(seconds: float) -> int:
    return max(1, math.ceil(seconds / SECONDS_PER_MINUTE))


def delayed_message(exc: YoutubeDelayed) -> str:
    """User-facing text for a transient YouTube problem; never carries URLs or internals."""
    minutes = minutes_hint(exc.retry_after_s)
    if exc.reason in (REASON_NETWORK, REASON_EMPTY):
        return f"YouTube could not be reached for the transcript; retrying in ~{minutes} min"
    return f"YouTube is limiting transcript downloads; retrying in ~{minutes} min"


def public_error(exc: BaseException, context: str) -> str:
    """Log the real failure server-side and return a message safe to show any user."""
    log.warning("%s failed: %s", context, type(exc).__name__, exc_info=exc)
    if isinstance(exc, LLMBusyError):
        return MSG_BUSY
    return MSG_LLM if isinstance(exc, LLMError) else MSG_GENERIC
