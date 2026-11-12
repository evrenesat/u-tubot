from __future__ import annotations

import logging

from .llm import LLMError

log = logging.getLogger("utubot.errors")

MSG_LLM = "the language model request failed, try again later"
MSG_GENERIC = "could not process this video, try again later"
MSG_JOB = "caption generation failed"


def public_error(exc: BaseException, context: str) -> str:
    """Log the real failure server-side and return a message safe to show any user."""
    log.warning("%s failed: %s", context, type(exc).__name__, exc_info=exc)
    return MSG_LLM if isinstance(exc, LLMError) else MSG_GENERIC
