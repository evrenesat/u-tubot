"""Everything that talks to YouTube goes through one gate: a pacer plus a circuit breaker.

The pacer keeps at most `max_concurrent` requests in flight with a minimum (jittered) gap between
them, interactive work before background work. The breaker opens when YouTube answers 429/403 or
asks for a bot check: interactive callers get `YoutubeCooldown` at once, background callers wait
(paused, not failed) until the cooldown ends. Nothing here logs a URL.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TypeVar

from .config import YoutubeConfig
from .db import Database
from .llm import BACKGROUND, INTERACTIVE

log = logging.getLogger("utubot.youtube")

T = TypeVar("T")

STATE_CLOSED = "closed"
STATE_OPEN = "open"
STATE_HALF_OPEN = "half_open"

REASON_RATE_LIMITED = "rate_limited"
REASON_FORBIDDEN = "forbidden"
REASON_BOT_CHECK = "bot_check"
REASON_COOLDOWN = "cooldown"
REASON_NETWORK = "network"
REASON_EMPTY = "empty_response"
REASON_EMPTY_TRACK = "empty_track"
REASON_INCOMPLETE = "incomplete_response"

REASON_PRIVATE = "private"
REASON_MEMBERS_ONLY = "members_only"
REASON_AGE_RESTRICTED = "age_restricted"
REASON_UNAVAILABLE = "unavailable"
REASON_FORBIDDEN_MEDIA = "forbidden"
REASON_TOO_LONG = "too_long"
REASON_LIVE = "live"

VIDEO_FAILURE_MESSAGES = {
    REASON_PRIVATE: "This video is private.",
    REASON_MEMBERS_ONLY: "This video is for channel members only.",
    REASON_AGE_RESTRICTED: "This video is age-restricted and cannot be read without signing in.",
    REASON_UNAVAILABLE: "This video is unavailable.",
    REASON_FORBIDDEN_MEDIA: "YouTube refused the download for this video.",
    REASON_TOO_LONG: "This video is too long to transcribe.",
    REASON_LIVE: "Live streams cannot be transcribed.",
}
# After these the audio is still reachable, so transcribing may work; after the others it is not.
TRANSCRIBABLE_AFTER = frozenset({REASON_FORBIDDEN_MEDIA})
STATUS_GONE = 410

STATUS_TOO_MANY_REQUESTS = 429
STATUS_FORBIDDEN = 403
STATUS_SERVER_ERROR_FLOOR = 500
ERROR_TEXT_MAX_CHARS = 200

BOT_CHECK_RE = re.compile(r"confirm you.{0,8}re not a bot", re.IGNORECASE)
RATE_LIMIT_RE = re.compile(
    r"HTTP Error 429|Too Many Requests|rate-limited by YouTube", re.IGNORECASE
)
FORBIDDEN_RE = re.compile(r"HTTP Error 403", re.IGNORECASE)
GONE_RE = re.compile(r"HTTP Error 410", re.IGNORECASE)
METADATA_REQUEST_RE = re.compile(
    r"unable to download (?:webpage|api page|json|player)|player response|watch page", re.IGNORECASE
)
VIDEO_FAILURE_PATTERNS = (
    (REASON_MEMBERS_ONLY, re.compile(r"members-only|members only|join this channel", re.I)),
    (
        REASON_AGE_RESTRICTED,
        re.compile(r"confirm your age|age-restricted|inappropriate for some", re.I),
    ),
    (REASON_PRIVATE, re.compile(r"private video|this video is private", re.I)),
    (
        REASON_UNAVAILABLE,
        re.compile(
            r"video unavailable|not available|has been removed|no longer available"
            r"|been terminated|who has blocked it|not made this video available",
            re.I,
        ),
    ),
)
NETWORK_RE = re.compile(
    r"timed out|timeout|connection (?:reset|refused|aborted|error)|name resolution"
    r"|network is unreachable|unable to download|remote end closed|\bSSL\b|HTTP Error 5\d\d",
    re.IGNORECASE,
)
URL_RE = re.compile(r"(https?://[^\s?#'\"<>]+)[^\s'\"<>]*")


class YoutubeError(RuntimeError):
    """A YouTube request failed. The message is safe to log: URLs are stripped of queries."""


class YoutubeDelayed(YoutubeError):
    """Transient: try again after `retry_after_s`. Never cached, never counted as a failure."""

    expected = True

    def __init__(self, reason: str, retry_after_s: float):
        super().__init__(f"youtube delayed: {reason}")
        self.reason = reason
        self.retry_after_s = retry_after_s


class YoutubeBlocked(YoutubeDelayed):
    """YouTube told us to back off (429/403/bot check). The gate sets the cooldown."""

    def __init__(self, reason: str, hint_s: float | None = None):
        super().__init__(reason, hint_s or 0.0)
        self.hint_s = hint_s


class YoutubeVideoError(YoutubeError):
    """This one video cannot be read (private, members-only, age-gated, gone, refused).

    YouTube answered, so it says nothing about the gate: it never opens the breaker.
    """

    expected = True

    def __init__(self, reason: str):
        super().__init__(f"youtube video error: {reason}")
        self.reason = reason

    @property
    def message(self) -> str:
        return VIDEO_FAILURE_MESSAGES.get(self.reason, VIDEO_FAILURE_MESSAGES[REASON_UNAVAILABLE])

    @property
    def can_transcribe(self) -> bool:
        return self.reason in TRANSCRIBABLE_AFTER


class YoutubeCooldown(YoutubeDelayed):
    """The breaker is open; nothing was sent to YouTube."""

    def __init__(self, retry_after_s: float):
        super().__init__(REASON_COOLDOWN, retry_after_s)


def redact_urls(text: str) -> str:
    """Drop query strings and fragments from every URL in `text` (they carry signed tokens)."""
    return URL_RE.sub(r"\1", text)


def classify_failure(
    exc: BaseException,
    network_retry_s: float,
    retry_after_s: float | None = None,
    *,
    media: bool = False,
) -> YoutubeError:
    """Map a yt-dlp or transport failure to a sanitised YouTube error.

    Only gate-level signals open the breaker: a 429, the bot check, or a 403 on the watch, player
    or metadata request. With `media=True` (an audio or caption download) a 403 that does not come
    from such a request, like a 410 or a members-only, age-gated, private or unavailable video, is a
    problem of this one video.
    """
    text = str(exc)
    if BOT_CHECK_RE.search(text):
        return YoutubeBlocked(REASON_BOT_CHECK, retry_after_s)
    if RATE_LIMIT_RE.search(text):
        return YoutubeBlocked(REASON_RATE_LIMITED, retry_after_s)
    for reason, pattern in VIDEO_FAILURE_PATTERNS:
        if pattern.search(text):
            return YoutubeVideoError(reason)
    if GONE_RE.search(text):
        return YoutubeVideoError(REASON_UNAVAILABLE)
    if FORBIDDEN_RE.search(text):
        if media and not METADATA_REQUEST_RE.search(text):
            return YoutubeVideoError(REASON_FORBIDDEN_MEDIA)
        return YoutubeBlocked(REASON_FORBIDDEN, retry_after_s)
    if isinstance(exc, OSError | TimeoutError) or NETWORK_RE.search(text):
        return YoutubeDelayed(REASON_NETWORK, network_retry_s)
    return YoutubeError(redact_urls(text).strip()[:ERROR_TEXT_MAX_CHARS] or "youtube error")


def classify_status(
    status: int, network_retry_s: float, retry_after_s: float | None, *, media: bool = False
) -> YoutubeError | None:
    """Map an HTTP status from a direct YouTube request; None when it is not a problem.

    `media=True` is a caption or media URL: its 403 and 410 belong to the video, not to the gate.
    """
    if status == STATUS_TOO_MANY_REQUESTS:
        return YoutubeBlocked(REASON_RATE_LIMITED, retry_after_s)
    if status == STATUS_GONE:
        return YoutubeVideoError(REASON_UNAVAILABLE)
    if status == STATUS_FORBIDDEN:
        if media:
            return YoutubeVideoError(REASON_FORBIDDEN_MEDIA)
        return YoutubeBlocked(REASON_FORBIDDEN, retry_after_s)
    if status >= STATUS_SERVER_ERROR_FLOOR:
        return YoutubeDelayed(REASON_NETWORK, network_retry_s)
    return None


class RedactUrls(logging.Filter):
    """Strip query strings from URLs in log lines; httpx logs every request URL at INFO."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_urls(record.getMessage())
        record.args = ()
        return True


def install_log_redaction() -> None:
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactUrls) for f in logger.filters):
            logger.addFilter(RedactUrls())


install_log_redaction()


class Clock:
    def now(self) -> float:
        return time.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


@dataclass(eq=False)
class _Waiter:
    priority: int
    seq: int
    key: str | None


class YoutubeGate:
    """Process-wide YouTube pacer and circuit breaker."""

    def __init__(
        self,
        cfg: YoutubeConfig,
        db: Database | None = None,
        clock: Clock | None = None,
        rand: Callable[[], float] = random.random,
    ):
        self.cfg = cfg
        self._db = db
        self._clock = clock or Clock()
        self._rand = rand
        self._limit = max(1, cfg.max_concurrent)
        self._in_use = 0
        self._ready_at = 0.0
        self._waiters: list[_Waiter] = []
        self._seq = itertools.count()
        self._changed: asyncio.Future | None = None
        self._until = 0.0
        self._strikes = 0
        self._probe_logged = False
        self._load()

    def _load(self) -> None:
        if self._db is None:
            return
        row = self._db.one("SELECT cooldown_until, strikes FROM youtube_gate WHERE id=1")
        if row is None:
            return
        self._until, self._strikes = float(row["cooldown_until"]), int(row["strikes"])
        if self.cooldown_remaining() > 0:
            log.warning(
                "youtube gate restored open: cooldown_s=%d strikes=%d",
                self.cooldown_remaining(),
                self._strikes,
            )

    def _save(self) -> None:
        if self._db is not None:
            self._db.execute(
                "INSERT OR REPLACE INTO youtube_gate(id,cooldown_until,strikes) VALUES(1,?,?)",
                [self._until, self._strikes],
            )

    def now(self) -> float:
        return self._clock.now()

    def cooldown_remaining(self) -> float:
        return max(0.0, self._until - self._clock.now())

    def state(self) -> str:
        if self.cooldown_remaining() > 0:
            return STATE_OPEN
        return STATE_HALF_OPEN if self._strikes else STATE_CLOSED

    def healthy(self) -> bool:
        """False while the breaker is open; a half-open gate lets requests through as probes."""
        return self.cooldown_remaining() <= 0

    def background_waiting(self) -> int:
        return sum(1 for w in self._waiters if w.priority == BACKGROUND)

    def promote(self, key: str) -> None:
        """Make queued work for `key` interactive (a user started waiting on a background fetch)."""
        changed = False
        for waiter in self._waiters:
            if waiter.key == key and waiter.priority != INTERACTIVE:
                waiter.priority = INTERACTIVE
                changed = True
        if changed:
            self._poke()

    def report_block(self, reason: str, hint_s: float | None = None) -> float:
        """Open (or extend) the breaker; returns the cooldown applied in seconds."""
        cfg = self.cfg
        if self.cooldown_remaining() <= 0:
            self._strikes += 1
        if hint_s and hint_s > 0:
            cooldown = hint_s
        else:
            cooldown = cfg.cooldown_base_s * 2 ** (self._strikes - 1)
        cooldown = min(max(cooldown, cfg.min_interval_s), cfg.cooldown_max_s)
        self._until = max(self._until, self._clock.now() + cooldown)
        self._probe_logged = False
        self._save()
        log.warning(
            "youtube gate open: reason=%s cooldown_s=%d strikes=%d retry_after_hint=%s",
            reason,
            cooldown,
            self._strikes,
            "yes" if hint_s else "no",
        )
        self._poke()
        return self.cooldown_remaining()

    def report_ok(self) -> None:
        if not self._strikes or self.cooldown_remaining() > 0:
            return
        self._strikes = 0
        self._until = 0.0
        self._save()
        log.info("youtube gate closed: request succeeded")
        self._poke()

    def _gap(self) -> float:
        return self.cfg.min_interval_s + self._rand() * self.cfg.jitter_s

    def _best(self) -> _Waiter | None:
        return min(self._waiters, key=lambda w: (w.priority, w.seq), default=None)

    def _poke(self) -> None:
        fut, self._changed = self._changed, None
        if fut is not None and not fut.done():
            fut.set_result(None)

    def _changed_future(self) -> asyncio.Future:
        if self._changed is None:
            self._changed = asyncio.get_running_loop().create_future()
        return self._changed

    async def _wait_change(self, timeout_s: float | None) -> None:
        """Sleep up to `timeout_s` or until gate state changes; cancel-safe for shared waiters."""
        pending: set[asyncio.Future] = {self._changed_future()}
        sleeper = None
        if timeout_s is not None:
            sleeper = asyncio.ensure_future(self._clock.sleep(timeout_s))
            pending.add(sleeper)
        try:
            await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if sleeper is not None:
                sleeper.cancel()

    async def _acquire(self, priority: int, key: str | None) -> None:
        waiter = _Waiter(priority, next(self._seq), key)
        self._waiters.append(waiter)
        try:
            while True:
                cooling = self.cooldown_remaining()
                if cooling > 0:
                    if waiter.priority == INTERACTIVE:
                        raise YoutubeCooldown(cooling)
                    await self._wait_change(cooling)
                    continue
                if self._in_use < self._limit and self._best() is waiter:
                    wait = self._ready_at - self._clock.now()
                    if wait <= 0:
                        break
                    await self._wait_change(wait)
                else:
                    await self._wait_change(None)
        finally:
            self._waiters.remove(waiter)
            self._poke()
        self._in_use += 1
        self._ready_at = self._clock.now() + self._gap()
        if self._strikes and not self._probe_logged:
            self._probe_logged = True
            log.info("youtube gate half-open: probing")

    def _release(self) -> None:
        self._in_use -= 1
        self._ready_at = max(self._ready_at, self._clock.now() + self._gap())
        self._poke()

    @asynccontextmanager
    async def slot(self, priority: int = INTERACTIVE, key: str | None = None):
        await self._acquire(priority, key)
        try:
            yield
        finally:
            self._release()

    async def run(
        self,
        fn: Callable[[], Awaitable[T]],
        priority: int = INTERACTIVE,
        key: str | None = None,
    ) -> T:
        """Run one YouTube operation in a paced slot and feed its outcome to the breaker."""
        async with self.slot(priority, key):
            try:
                result = await fn()
            except YoutubeBlocked as exc:
                exc.retry_after_s = self.report_block(exc.reason, exc.hint_s)
                raise
            except YoutubeVideoError:
                self.report_ok()
                raise
            self.report_ok()
            return result

    async def run_started(
        self,
        fn: Callable[[Callable[[], None]], Awaitable[T]],
        priority: int = BACKGROUND,
        key: str | None = None,
    ) -> T:
        """Gate only the start of a long transfer.

        `fn(started)` runs in a paced slot; the slot is released as soon as `fn` calls `started()`
        (thread-safe) or finishes, and the transfer then runs on without holding it, so metadata and
        caption fetches never wait behind a whole download. A 429 after the start still opens the
        breaker.
        """
        loop = asyncio.get_running_loop()
        started: asyncio.Future[None] = loop.create_future()
        tasks: list[asyncio.Task[T]] = []

        def signal() -> None:
            loop.call_soon_threadsafe(lambda: started.done() or started.set_result(None))

        async def start_phase() -> None:
            task = loop.create_task(fn(signal))
            tasks.append(task)
            try:
                await asyncio.wait({task, started}, return_when=asyncio.FIRST_COMPLETED)
            except asyncio.CancelledError:
                task.cancel()
                raise
            if task.done():
                task.result()

        await self.run(start_phase, priority, key)
        task = tasks[0]
        try:
            return await task
        except YoutubeBlocked as exc:
            exc.retry_after_s = self.report_block(exc.reason, exc.hint_s)
            raise
        except asyncio.CancelledError:
            task.cancel()
            raise
