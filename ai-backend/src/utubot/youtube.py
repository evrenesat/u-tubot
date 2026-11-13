"""Everything that talks to YouTube goes through one gate: a shared pacer plus per-class breakers.

The pacer keeps at most `max_concurrent` requests in flight with a minimum (jittered) gap between
them, interactive work before background work; it is shared by every class so the overall request
rate stays what the owner configured. The breakers are one per endpoint class (`captions`: the
timedtext API, `metadata`: watch/player/yt-dlp extraction, `media`: audio downloads): a 429 on one
class must not stop the others. A breaker opens when YouTube answers 429/403 or asks for a bot check:
interactive callers get `YoutubeCooldown` at once, background callers wait (paused, not failed)
until the cooldown ends. The caption class (`PROBE_CLASSES`) is probed with care: once its cooldown
is over, exactly one background request goes out and decides whether the class closes or cools
again; interactive callers keep getting `YoutubeCooldown` until then. Nothing here logs a URL.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

from .config import YoutubeConfig
from .db import Database
from .llm import BACKGROUND, INTERACTIVE

log = logging.getLogger("utubot.youtube")

T = TypeVar("T")

CLASS_CAPTIONS = "captions"
CLASS_METADATA = "metadata"
CLASS_MEDIA = "media"
CLASSES = (CLASS_METADATA, CLASS_CAPTIONS, CLASS_MEDIA)
FETCH_CLASSES = (CLASS_METADATA, CLASS_CAPTIONS)
MEDIA_CLASSES = (CLASS_MEDIA,)
YTDLP_CLASSES = (CLASS_METADATA, CLASS_MEDIA)
# After a cooldown these take one background probe at a time; an interactive request never probes.
PROBE_CLASSES = (CLASS_CAPTIONS,)

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
REASON_OFFLINE = "offline"

VIDEO_FAILURE_MESSAGES = {
    REASON_PRIVATE: "This video is private.",
    REASON_MEMBERS_ONLY: "This video is for channel members only.",
    REASON_AGE_RESTRICTED: "This video is age-restricted and cannot be read without signing in.",
    REASON_UNAVAILABLE: "This video is unavailable.",
    REASON_FORBIDDEN_MEDIA: "YouTube refused the download for this video.",
    REASON_TOO_LONG: "This video is too long to transcribe.",
    REASON_LIVE: "Live streams cannot be transcribed.",
    REASON_OFFLINE: (
        "This server has no YouTube access (offline mode); this video is not in its local archive."
    ),
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
    """A YouTube request failed. The message is safe to log: URLs are stripped of queries.

    `klass` names the endpoint class that answered (None: not known, the gate assumes the class(es)
    of the operation it ran).
    """

    klass: str | None = None


class YoutubeDelayed(YoutubeError):
    """Transient: try again after `retry_after_s`. Never cached, never counted as a failure."""

    expected = True

    def __init__(self, reason: str, retry_after_s: float):
        super().__init__(f"youtube delayed: {reason}")
        self.reason = reason
        self.retry_after_s = retry_after_s


class YoutubeBlocked(YoutubeDelayed):
    """YouTube told us to back off (429/403/bot check). The gate sets the cooldown."""

    def __init__(self, reason: str, hint_s: float | None = None, klass: str | None = None):
        super().__init__(reason, hint_s or 0.0)
        self.hint_s = hint_s
        self.klass = klass


class YoutubeVideoError(YoutubeError):
    """This one video cannot be read (private, members-only, age-gated, gone, refused).

    YouTube answered, so it says nothing about the gate: it never opens the breaker.
    """

    expected = True

    def __init__(self, reason: str, klass: str | None = None):
        super().__init__(f"youtube video error: {reason}")
        self.reason = reason
        self.klass = klass

    @property
    def message(self) -> str:
        return VIDEO_FAILURE_MESSAGES.get(self.reason, VIDEO_FAILURE_MESSAGES[REASON_UNAVAILABLE])

    @property
    def can_transcribe(self) -> bool:
        return self.reason in TRANSCRIBABLE_AFTER


class YoutubeCooldown(YoutubeDelayed):
    """A breaker is open; nothing was sent to YouTube."""

    def __init__(self, retry_after_s: float, klass: str | None = None):
        super().__init__(REASON_COOLDOWN, retry_after_s)
        self.klass = klass


class YoutubeOffline(YoutubeVideoError):
    """Offline mode: no request may leave for YouTube and this video has no local answer.

    Raised instead of any network call when `[youtube] offline` is set: the real fetchers refuse,
    the gate refuses media transfers, and the fixture fetcher answers only recorded videos.
    """

    def __init__(self, klass: str | None = None):
        super().__init__(REASON_OFFLINE, klass)


def ytdlp_runtime_options(cfg: YoutubeConfig) -> dict[str, Any]:
    """yt-dlp options for the JavaScript runtime that solves YouTube's "n challenge".

    Without one yt-dlp cannot unscramble some stream URLs and warns about it. The configured runtime
    is always passed on; a service started by systemd often has no `deno` on its PATH, so
    `[youtube] js_runtime_path` names the executable, else yt-dlp looks the runtime up on PATH.
    """
    runtime: dict[str, Any] = {"path": cfg.js_runtime_path} if cfg.js_runtime_path else {}
    opts: dict[str, Any] = {"js_runtimes": {cfg.js_runtime: runtime}}
    if cfg.remote_components:
        opts["remote_components"] = list(cfg.remote_components)
    return opts


def redact_urls(text: str) -> str:
    """Drop query strings and fragments from every URL in `text` (they carry signed tokens)."""
    return URL_RE.sub(r"\1", text)


URL_PLACEHOLDER = "<url>"


def strip_urls(text: str) -> str:
    """Replace every URL in `text` with a placeholder; what cassettes keep carries no URL at all.

    `redact_urls` keeps the scheme and host for log and error text; recorded fixtures get this
    stricter treatment, because even a URL's path can carry signed tokens and the recorder's IP
    (HLS manifest URLs do).
    """
    return URL_RE.sub(lambda _m: URL_PLACEHOLDER, text)


def classify_failure(
    exc: BaseException,
    network_retry_s: float,
    retry_after_s: float | None = None,
    *,
    media: bool = False,
    klass: str = CLASS_METADATA,
) -> YoutubeError:
    """Map a yt-dlp or transport failure to a sanitised YouTube error of endpoint class `klass`.

    Only gate-level signals open the breaker: a 429, the bot check, or a 403 on the watch, player
    or metadata request. With `media=True` (an audio or caption download) a 403 that does not come
    from such a request, like a 410 or a members-only, age-gated, private or unavailable video, is a
    problem of this one video.
    """
    text = str(exc)
    if BOT_CHECK_RE.search(text):
        return YoutubeBlocked(REASON_BOT_CHECK, retry_after_s, klass)
    if RATE_LIMIT_RE.search(text):
        return YoutubeBlocked(REASON_RATE_LIMITED, retry_after_s, klass)
    for reason, pattern in VIDEO_FAILURE_PATTERNS:
        if pattern.search(text):
            return YoutubeVideoError(reason, klass)
    if GONE_RE.search(text):
        return YoutubeVideoError(REASON_UNAVAILABLE, klass)
    if FORBIDDEN_RE.search(text):
        if media and not METADATA_REQUEST_RE.search(text):
            return YoutubeVideoError(REASON_FORBIDDEN_MEDIA, klass)
        return YoutubeBlocked(REASON_FORBIDDEN, retry_after_s, klass)
    if isinstance(exc, OSError | TimeoutError) or NETWORK_RE.search(text):
        return YoutubeDelayed(REASON_NETWORK, network_retry_s)
    return YoutubeError(redact_urls(text).strip()[:ERROR_TEXT_MAX_CHARS] or "youtube error")


def classify_status(
    status: int,
    network_retry_s: float,
    retry_after_s: float | None,
    *,
    media: bool = False,
    klass: str = CLASS_CAPTIONS,
) -> YoutubeError | None:
    """Map an HTTP status from a direct YouTube request of class `klass`; None when it is no problem.

    `media=True` is a caption or media URL: its 403 and 410 belong to the video, not to the gate.
    """
    if status == STATUS_TOO_MANY_REQUESTS:
        return YoutubeBlocked(REASON_RATE_LIMITED, retry_after_s, klass)
    if status == STATUS_GONE:
        return YoutubeVideoError(REASON_UNAVAILABLE, klass)
    if status == STATUS_FORBIDDEN:
        if media:
            return YoutubeVideoError(REASON_FORBIDDEN_MEDIA, klass)
        return YoutubeBlocked(REASON_FORBIDDEN, retry_after_s, klass)
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
    classes: tuple[str, ...]


@dataclass
class _Breaker:
    until: float = 0.0
    strikes: int = 0
    probe_logged: bool = False
    probing: bool = False


def _as_classes(klass: str | Iterable[str] | None, default: Iterable[str]) -> tuple[str, ...]:
    if klass is None:
        return tuple(default)
    return (klass,) if isinstance(klass, str) else tuple(klass)


class YoutubeGate:
    """Process-wide YouTube pacer (shared) with one circuit breaker per endpoint class."""

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
        self._breakers = {name: _Breaker() for name in CLASSES}
        self._load()

    def _load(self) -> None:
        if self._db is None:
            return
        rows = self._db.all("SELECT klass, cooldown_until, strikes FROM youtube_gate_class")
        for row in rows:
            if row["klass"] in self._breakers:
                self._breakers[row["klass"]] = _Breaker(
                    float(row["cooldown_until"]), row["strikes"]
                )
        if not rows:
            self._adopt_legacy_row()
        for name, breaker in self._breakers.items():
            if self._remaining(name) > 0:
                log.warning(
                    "youtube gate restored open: class=%s cooldown_s=%d strikes=%d",
                    name,
                    self._remaining(name),
                    breaker.strikes,
                )

    def _adopt_legacy_row(self) -> None:
        """State saved by the single-breaker version: it applies to every class once."""
        row = self._db.one("SELECT cooldown_until, strikes FROM youtube_gate WHERE id=1")
        if row is None:
            return
        for name in CLASSES:
            self._breakers[name] = _Breaker(float(row["cooldown_until"]), int(row["strikes"]))
            self._save(name)
        self._db.execute("DELETE FROM youtube_gate WHERE id=1")

    def _save(self, klass: str) -> None:
        if self._db is not None:
            breaker = self._breakers[klass]
            self._db.execute(
                "INSERT OR REPLACE INTO youtube_gate_class(klass,cooldown_until,strikes)"
                " VALUES(?,?,?)",
                [klass, breaker.until, breaker.strikes],
            )

    def now(self) -> float:
        return self._clock.now()

    @property
    def offline(self) -> bool:
        """Offline dev-proxy mode: nothing reaches YouTube; answers come from local data."""
        return self.cfg.offline

    def _remaining(self, klass: str) -> float:
        return max(0.0, self._breakers[klass].until - self._clock.now())

    def cooldown_remaining(self, *classes: str) -> float:
        """Seconds until every given class (default: all) may be asked again; the longest wins."""
        return max((self._remaining(name) for name in classes or CLASSES), default=0.0)

    def _class_state(self, klass: str) -> str:
        if self._remaining(klass) > 0:
            return STATE_OPEN
        return STATE_HALF_OPEN if self._breakers[klass].strikes else STATE_CLOSED

    def state(self, *classes: str) -> str:
        """`open` if any given class (default: all) is open, else `half_open` if any is, else closed."""
        states = {self._class_state(name) for name in classes or CLASSES}
        for state in (STATE_OPEN, STATE_HALF_OPEN):
            if state in states:
                return state
        return STATE_CLOSED

    def healthy(self, *classes: str) -> bool:
        """False while any given class (default: all) is open; a half-open one lets probes through."""
        return self.cooldown_remaining(*classes) <= 0

    def _probe_only(self, classes: Iterable[str]) -> tuple[str, ...]:
        """The given classes that are half-open and take one background probe at a time."""
        return tuple(
            name
            for name in classes
            if name in PROBE_CLASSES and self._breakers[name].strikes and self._remaining(name) <= 0
        )

    def interactive_ok(self, *classes: str) -> bool:
        """Would an interactive request for these classes (default: all) be sent to YouTube now?

        False while one is open, and while a probe-only class (captions) waits for its background
        probe: callers should look for another way (the audio) instead of asking.
        """
        names = classes or CLASSES
        return self.cooldown_remaining(*names) <= 0 and not self._probe_only(names)

    def probe_pending(self) -> bool:
        """True while a probe-only class is half-open: one background request should go out."""
        return bool(self._probe_only(PROBE_CLASSES))

    def snapshot(self) -> dict[str, dict[str, Any]]:
        """Per-class breaker state for the status endpoint."""
        return {
            name: {
                "state": self._class_state(name),
                "cooldown_remaining_s": round(self._remaining(name)),
                "strikes": self._breakers[name].strikes,
            }
            for name in CLASSES
        }

    def background_waiting(self) -> int:
        return sum(1 for w in self._waiters if w.priority == BACKGROUND)

    def promote(self, key: str) -> None:
        """Make queued work for `key` interactive (a user started waiting on a background fetch)."""
        changed = False
        for waiter in self._waiters:
            if (
                waiter.key == key
                and waiter.priority != INTERACTIVE
                and not self._probe_bound(waiter)
            ):
                waiter.priority = INTERACTIVE
                changed = True
        if changed:
            self._poke()

    def report_block(
        self,
        reason: str,
        hint_s: float | None = None,
        klass: str | Iterable[str] | None = None,
    ) -> float:
        """Open (or extend) the breaker of `klass` (default: every class); returns its cooldown in s.

        A bot check comes from yt-dlp's player request, which metadata and media share, so it opens
        both. A 429 or 403 only opens the class that received it.
        """
        targets = _as_classes(klass, CLASSES)
        if reason == REASON_BOT_CHECK and any(name in YTDLP_CLASSES for name in targets):
            targets = tuple(dict.fromkeys((*targets, *YTDLP_CLASSES)))
        cfg = self.cfg
        for name in targets:
            breaker = self._breakers[name]
            if self._remaining(name) <= 0:
                breaker.strikes += 1
            if hint_s and hint_s > 0:
                cooldown = hint_s
            else:
                cooldown = cfg.cooldown_base_s * 2 ** (breaker.strikes - 1)
            ceiling = cfg.cooldown_max_s
            if name == CLASS_CAPTIONS:
                ceiling = min(ceiling, cfg.captions_cooldown_max_s)
            cooldown = min(max(cooldown, cfg.min_interval_s), ceiling)
            breaker.until = max(breaker.until, self._clock.now() + cooldown)
            breaker.probe_logged = False
            self._save(name)
            log.warning(
                "youtube gate open: class=%s reason=%s cooldown_s=%d strikes=%d retry_after_hint=%s",
                name,
                reason,
                cooldown,
                breaker.strikes,
                "yes" if hint_s else "no",
            )
        self._poke()
        return self.cooldown_remaining(*targets[:1])

    def report_ok(self, klass: str | Iterable[str] | None = None) -> None:
        for name in _as_classes(klass, CLASSES):
            breaker = self._breakers[name]
            if not breaker.strikes or self._remaining(name) > 0:
                continue
            breaker.strikes, breaker.until = 0, 0.0
            self._save(name)
            log.info("youtube gate closed: class=%s request succeeded", name)
            self._poke()

    def _gap(self) -> float:
        return self.cfg.min_interval_s + self._rand() * self.cfg.jitter_s

    def _cooling(self, waiter: _Waiter) -> tuple[float, str | None]:
        """The longest cooldown among the waiter's classes and the class that has it."""
        worst, which = 0.0, None
        for name in waiter.classes:
            left = self._remaining(name)
            if left > worst:
                worst, which = left, name
        return worst, which

    def _probe_bound(self, waiter: _Waiter) -> bool:
        """Does the waiter need a probe-only class that is cooling or waiting for its probe?"""
        return any(
            name in PROBE_CLASSES and self._breakers[name].strikes for name in waiter.classes
        )

    def _probe_busy(self, waiter: _Waiter) -> bool:
        """A probe for one of the waiter's half-open probe-only classes is already out."""
        return any(self._breakers[name].probing for name in self._probe_only(waiter.classes))

    def _best(self) -> _Waiter | None:
        """The next waiter to run: classes that are cooling or probed never hold up the others."""
        runnable = [
            w for w in self._waiters if self._cooling(w)[0] <= 0 and not self._probe_busy(w)
        ]
        return min(runnable, key=lambda w: (w.priority, w.seq), default=None)

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

    def _as_offline(self, classes: tuple[str, ...]) -> bool:
        """Offline mode refuses every real transfer (media classes); local fixture reads pass."""
        return self.cfg.offline and any(name in MEDIA_CLASSES for name in classes)

    async def _acquire(
        self, priority: int, key: str | None, classes: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Wait for a paced slot; returns the probe-only classes this request is the probe of."""
        if self._as_offline(classes):
            raise YoutubeOffline()
        waiter = _Waiter(priority, next(self._seq), key, classes)
        self._waiters.append(waiter)
        try:
            while True:
                cooling, which = self._cooling(waiter)
                if cooling > 0:
                    if waiter.priority == INTERACTIVE:
                        raise YoutubeCooldown(cooling, which)
                    await self._wait_change(cooling)
                    continue
                probed = self._probe_only(classes)
                if probed and waiter.priority == INTERACTIVE:
                    raise YoutubeCooldown(self.cfg.captions_probe_retry_s, probed[0])
                if probed and self._probe_busy(waiter):
                    await self._wait_change(None)
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
        for name in classes:
            breaker = self._breakers[name]
            if breaker.strikes and not breaker.probe_logged:
                breaker.probe_logged = True
                log.info("youtube gate half-open: class=%s probing", name)
        for name in probed:
            self._breakers[name].probing = True
        return probed

    def _release(self, probed: tuple[str, ...] = ()) -> None:
        for name in probed:
            self._breakers[name].probing = False
        self._in_use -= 1
        self._ready_at = max(self._ready_at, self._clock.now() + self._gap())
        self._poke()

    @asynccontextmanager
    async def slot(
        self,
        priority: int = INTERACTIVE,
        key: str | None = None,
        classes: Sequence[str] = FETCH_CLASSES,
    ):
        probed = await self._acquire(priority, key, tuple(classes))
        try:
            yield
        finally:
            self._release(probed)

    async def run(
        self,
        fn: Callable[[], Awaitable[T]],
        priority: int = INTERACTIVE,
        key: str | None = None,
        classes: Sequence[str] = FETCH_CLASSES,
    ) -> T:
        """Run one YouTube operation in a paced slot and feed its outcome to the breakers.

        `classes` are the endpoint classes the operation needs: it starts only when none of them is
        cooling. A block opens the class named by the error (`exc.klass`, else all of `classes`);
        success closes every class the result says it `answered` (else all of `classes`).
        """
        classes = tuple(classes)
        async with self.slot(priority, key, classes):
            try:
                result = await fn()
            except YoutubeBlocked as exc:
                exc.retry_after_s = self.report_block(exc.reason, exc.hint_s, exc.klass or classes)
                raise
            except YoutubeVideoError as exc:
                self.report_ok(exc.klass or classes)
                raise
            self.report_ok(getattr(result, "answered", None) or classes)
            return result

    async def run_started(
        self,
        fn: Callable[[Callable[[], None]], Awaitable[T]],
        priority: int = BACKGROUND,
        key: str | None = None,
        classes: Sequence[str] = MEDIA_CLASSES,
    ) -> T:
        """Gate only the start of a long transfer.

        `fn(started)` runs in a paced slot; the slot is released as soon as `fn` calls `started()`
        (thread-safe) or finishes, and the transfer then runs on without holding it, so metadata and
        caption fetches never wait behind a whole download. A 429 after the start still opens the
        breaker.
        """
        classes = tuple(classes)
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

        await self.run(start_phase, priority, key, classes)
        task = tasks[0]
        try:
            return await task
        except YoutubeBlocked as exc:
            exc.retry_after_s = self.report_block(exc.reason, exc.hint_s, exc.klass or classes)
            raise
        except asyncio.CancelledError:
            task.cancel()
            raise
