from __future__ import annotations

import asyncio
import time

from utubot.youtube import Clock

SETTLE_ROUNDS = 25


async def settle(rounds: int = SETTLE_ROUNDS) -> None:
    """Let every runnable task make progress."""
    for _ in range(rounds):
        await asyncio.sleep(0)


class FakeClock(Clock):
    """Deterministic clock: `sleep` only returns when `advance` moves time past its deadline."""

    def __init__(self, start: float | None = None) -> None:
        self.t = time.time() if start is None else start
        self._sleepers: list[tuple[float, asyncio.Future]] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        fut = asyncio.get_running_loop().create_future()
        entry = (self.t + seconds, fut)
        self._sleepers.append(entry)
        try:
            await fut
        finally:
            if entry in self._sleepers:
                self._sleepers.remove(entry)

    async def advance(self, seconds: float) -> None:
        await settle()
        target = self.t + seconds
        while True:
            due = sorted(
                ((d, f) for d, f in self._sleepers if d <= target and not f.done()),
                key=lambda item: item[0],
            )
            if not due:
                break
            deadline, fut = due[0]
            self.t = max(self.t, deadline)
            fut.set_result(None)
            await settle()
        self.t = target
        await settle()
