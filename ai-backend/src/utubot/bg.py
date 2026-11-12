from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .errors import public_error


def is_failure(exc: BaseException | None) -> bool:
    """Exceptions flagged `expected` (delayed, no captions) are outcomes, not failures."""
    return exc is not None and not getattr(exc, "expected", False)


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
            if not t.cancelled() and is_failure(t.exception()):
                self._failures[key] = (time.time(), public_error(t.exception(), "background task"))

        task.add_done_callback(_done)
        return task

    def recent_failure(self, key: Any) -> str | None:
        item = self._failures.get(key)
        if item and time.time() - item[0] < self._cooldown:
            return item[1]
        self._failures.pop(key, None)
        return None

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
