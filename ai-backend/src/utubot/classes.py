"""User classes: prime work goes before normal work everywhere, normal work waits for it."""

from __future__ import annotations

import asyncio
import time
from contextvars import ContextVar, Token
from typing import Any

PRIME = "prime"
NORMAL = "normal"
CLASSES = (PRIME, NORMAL)
RANK = {PRIME: 0, NORMAL: 1}
_CURRENT_CLASS: ContextVar[str] = ContextVar("utubot_user_class", default=NORMAL)


def bind_class(value: Any) -> Token:
    """Bind the class of the job running in this task (thread/task children inherit it)."""
    return _CURRENT_CLASS.set(normalize_class(value))


def unbind_class(token: Token) -> None:
    _CURRENT_CLASS.reset(token)


def current_class() -> str:
    return normalize_class(_CURRENT_CLASS.get())


def normalize_class(value: Any, default: str = NORMAL) -> str:
    """A stored class; anything unknown is the safe class, never prime."""
    return value if value in RANK else default


def class_rank(value: Any) -> int:
    return RANK[normalize_class(value)]


def class_of(user: Any) -> str:
    """The class of a `UserConfig`, a user name looked up in `users`, or a stored class value."""
    if isinstance(user, str):
        return normalize_class(user)
    value = getattr(user, "klass", None)
    if value is not None:
        return normalize_class(value)
    return PRIME if bool(getattr(user, "prime", False)) else NORMAL


def highest(*values: Any) -> str:
    """The highest class among requests; prime wins, and a build's class never goes down."""
    return PRIME if any(normalize_class(v) == PRIME for v in values) else NORMAL


class JobYielded(Exception):
    """Control flow: a normal job pauses at a safe point so its worker can run a prime job."""


class ClassGate:
    """Stops normal work at a safe point while a prime job is queued or running."""

    def __init__(self, db: Any, *, poll_s: float = 0.5, sleep=asyncio.sleep, clock=time.time):
        self.db = db
        self.poll_s = max(0.01, poll_s)
        self._sleep = sleep
        self._clock = clock

    def prime_active(self, exclude_job: str | None = None) -> bool:
        """Whether a prime job that needs the shared engines is queued or running.

        A prime quick cut or a cut waiting for its prompt does not pause normal work; a watched
        build does, including before its transcript exists.
        """
        row = self.db.one(
            "SELECT 1 FROM jobs LEFT JOIN cut_requests ON cut_requests.job_id=jobs.id"
            " WHERE jobs.status IN ('queued','running') AND jobs.klass='prime'"
            " AND (jobs.kind IN ('captions','transcript')"
            " OR (jobs.kind='cuts' AND cut_requests.mode='watched'"
            " AND cut_requests.state IN ('building','needs_transcript')))"
            " AND (? IS NULL OR jobs.id!=?) LIMIT 1",
            [exclude_job, exclude_job],
        )
        return row is not None

    async def wait(self, job_id: str | None, klass: Any, on_wait=None) -> bool:
        """Wait while prime work is active; returns whether this call waited.

        `job_id` is the caller's own row: a job marked prime does not wait for itself.
        """
        if normalize_class(klass) == PRIME:
            return False
        waited = False
        while self.prime_active(job_id):
            if not waited and on_wait is not None:
                on_wait()
            waited = True
            await self._sleep(self.poll_s)
        return waited

    async def yield_if_prime(self, job_id: str | None, klass: Any, on_wait=None) -> None:
        """Pause a normal job at a safe point while prime demanding work is queued or running.

        Unlike `wait`, this does not hold the caller's worker while prime runs: it raises
        `JobYielded` so the caller can free the worker to claim the prime job (there is one worker)
        and resume the normal job later. A prime job never yields to itself.
        """
        if normalize_class(klass) == PRIME:
            return
        if self.prime_active(job_id):
            if on_wait is not None:
                on_wait()
            raise JobYielded()
