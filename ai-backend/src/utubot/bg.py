from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .errors import public_error
from .llm import LLMBusyError


def is_failure(exc: BaseException | None) -> bool:
    """Exceptions flagged `expected` (delayed, no captions) are outcomes, not failures."""
    return exc is not None and not getattr(exc, "expected", False)


def is_remembered(exc: BaseException | None) -> bool:
    """A failure worth remembering for a short while. A busy model is never remembered: the next
    request asks again, because the endpoint may be free a second later (the LLM client already
    fails fast and spaces its own retries)."""
    return is_failure(exc) and not isinstance(exc, LLMBusyError)


class TaskRegistry:
    def __init__(self, failure_cooldown_s: float = 30.0):
        self._tasks: dict[Any, asyncio.Task] = {}
        self._failures: dict[Any, tuple[float, str]] = {}
        self._cooldown = failure_cooldown_s

    def start(self, key: Any, factory: Callable[[], Awaitable[Any]]) -> asyncio.Task:
        task = self._tasks.get(key)
        if task is not None and not task.done():
            return task
        task = asyncio.create_task(factory())
        self._tasks[key] = task

        def _done(t: asyncio.Task, key: Any = key) -> None:
            if self._tasks.get(key) is t:
                del self._tasks[key]
            if not t.cancelled() and is_remembered(t.exception()):
                self._failures[key] = (time.time(), public_error(t.exception(), "background task"))

        task.add_done_callback(_done)
        return task

    def recent_failure(self, key: Any) -> str | None:
        item = self._failures.get(key)
        if item and time.time() - item[0] < self._cooldown:
            return item[1]
        self._failures.pop(key, None)
        return None

    def forget_video(self, video_id: str) -> int:
        """Drop every remembered failure of one video (the user pressed Retry). Returns how many.

        Keys are the video id itself or a tuple whose second item is the video id.
        """
        gone = [
            key
            for key in self._failures
            if key == video_id or (isinstance(key, tuple) and len(key) > 1 and key[1] == video_id)
        ]
        for key in gone:
            del self._failures[key]
        return len(gone)

    def running(self, key: Any) -> bool:
        task = self._tasks.get(key)
        return task is not None and not task.done()

    def cancel(self, key: Any) -> bool:
        task = self._tasks.get(key)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def drain(self) -> None:
        pending = [t for t in self._tasks.values() if not t.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def wait_task(task: asyncio.Task, wait_ms: int) -> bool:
    done, _ = await asyncio.wait({task}, timeout=wait_ms / 1000.0)
    return bool(done)
