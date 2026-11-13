"""The event log of a job: what was asked, what each stage did, how long it took, who fetched the result.

Every job writes timestamped rows to `job_events` (stage, status, a small JSON detail). The pipeline,
the ASR router and the diarizers do not know the job: they call `emit` / `stage`, which write to the
`JobTrace` the worker bound for the job being run (a `ContextVar`, so threads and tasks started from
the worker inherit it) and do nothing when none is bound. Nothing here ever stores a secret or a URL:
details are filtered by `clean` before they reach the database.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Mapping
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any

from ..config import CaptionsConfig
from ..db import Database

log = logging.getLogger("utubot.jobs")

# Stages, in the order a transcript or captions job passes them.
QUEUED = "queued"
PROMOTED = "promoted"
STARTED = "started"
GATE_WAIT = "gate_wait"
CAPTION_RECHECK = "caption_recheck"
AUDIO = "audio_download"
FFMPEG = "ffmpeg"
CHUNKING = "chunking"
ASR = "asr"
ASR_CHUNK = "asr_chunk"
ASR_FALLBACK = "asr_fallback"
STITCHING = "stitching"
DIARIZATION = "diarization"
CUES = "cues"
TEXT = "text"
TRANSLATE = "translate"
STORED = "stored"
RETRY = "retry"
FINISHED = "finished"
FAILED_STAGE = "failed"
DELIVERED = "delivered"

# Statuses of an event.
RUNNING = "running"
OK = "ok"
WARN = "warn"
SKIPPED = "skipped"
FAILED = "failed"
INFO = "info"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"
TERMINAL_STAGES = frozenset({FINISHED, FAILED_STAGE, RETRY, QUEUED, DELIVERED})

# Where the audio of an `audio_download` event came from: the download, or the media archive.
AUDIO_DOWNLOADED = "downloaded"
AUDIO_FROM_ARCHIVE = "from_archive"
SYNTHETIC_MESSAGE = "finished (no detailed log, created before event logging)"
SYNTHETIC_QUEUED_MESSAGE = "queued (no detailed log, created before event logging)"
PRIORITY_NAMES = {0: "interactive", 1: "background"}
DETAIL_TEXT_CHARS = 240
DETAIL_LIST_ITEMS = 24
DETAIL_DEPTH = 3
TECHNICAL_CHARS = 200
REDACTED = "[redacted]"
URL_PLACEHOLDER = "[url]"

URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+")
WWW_RE = re.compile(r"\bwww\.\S+", re.IGNORECASE)
SECRET_WORD_RE = re.compile(
    r"(?i)\bbearer\s+\S+|\b(?:token|api[_-]?key|key|secret|passw(?:or)?d|authorization|signature|sig|cookie)"
    r"\b\s*[=:]\s*\S+"
)
HEX_RUN_RE = re.compile(r"\b[0-9A-Fa-f]{32,}\b")
KEY_PREFIX_RE = re.compile(r"\b(?:utb|sk|hf|ghp|gho|xox[a-z])[_-][A-Za-z0-9_\-]{8,}")
# Random base64-like runs: long, no separator a model name would have, with upper case, lower case and digits.
MIXED_RUN_RE = re.compile(
    r"\b(?=[A-Za-z0-9_\-+/=]*[A-Z])(?=[A-Za-z0-9_\-+/=]*[a-z])(?=[A-Za-z0-9_\-+/=]*\d)"
    r"[A-Za-z0-9_\-+/=]{32,}\b"
)
SECRET_KEY_RE = re.compile(
    r"(?i)(token|secret|passw|authorization|cookie|signature|api_?key|(^|_)(url|uri|href)($|_)|header)"
)


def clean(value: Any, depth: int = 0) -> Any:
    """`value` made safe to store: URLs, tokens and secret-looking keys never get through.

    Strings are scrubbed and shortened, mappings lose keys that name a secret or a URL, lists are
    cut. Only JSON types come out.
    """
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        text = URL_RE.sub(URL_PLACEHOLDER, value)
        text = WWW_RE.sub(URL_PLACEHOLDER, text)
        text = SECRET_WORD_RE.sub(REDACTED, text)
        for pattern in (KEY_PREFIX_RE, HEX_RUN_RE, MIXED_RUN_RE):
            text = pattern.sub(REDACTED, text)
        return text[:DETAIL_TEXT_CHARS]
    if depth >= DETAIL_DEPTH:
        return None
    if isinstance(value, Mapping):
        return {
            str(k): clean(v, depth + 1)
            for k, v in value.items()
            if not SECRET_KEY_RE.search(str(k))
        }
    if isinstance(value, list | tuple | set | frozenset):
        return [clean(v, depth + 1) for v in list(value)[:DETAIL_LIST_ITEMS]]
    return clean(str(value), depth)


def error_class(exc: BaseException) -> str:
    """A short, stable name for a failure: a gate reason (`rate_limited`), an engine code or the class."""
    for attr in ("reason", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value:
            return value
    return type(exc).__name__


def technical(exc: BaseException) -> str:
    """The exception text, scrubbed and short: for the owner's eyes, never a URL or a token."""
    return str(clean(str(exc)))[:TECHNICAL_CHARS]


def priority_name(priority: int | None) -> str:
    return PRIORITY_NAMES.get(priority if priority is not None else 1, "background")


@dataclass
class Origin:
    """Who is behind the request being served: set by the HTTP routes, read when a job is queued."""

    client: str
    user: str
    endpoint: str


_ORIGIN: ContextVar[Origin | None] = ContextVar("utubot_job_origin", default=None)
_TRACE: ContextVar[JobTrace | None] = ContextVar("utubot_job_trace", default=None)


def set_origin(origin: Origin | None) -> None:
    _ORIGIN.set(origin)


def current_origin() -> Origin | None:
    return _ORIGIN.get()


class JobEvents:
    """Reads and writes the `job_events` table."""

    def __init__(self, db: Database, cfg: CaptionsConfig):
        self.db, self.cfg = db, cfg

    def record(
        self,
        job_id: str,
        stage: str,
        status: str,
        detail: Mapping[str, Any] | None = None,
        *,
        ts: float | None = None,
    ) -> None:
        """Append an event. Past `job_events_max` a job only keeps its milestones (queued, finished ...)."""
        if stage not in TERMINAL_STAGES:
            row = self.db.one("SELECT COUNT(*) AS n FROM job_events WHERE job_id=?", [job_id])
            if row and row["n"] >= self.cfg.job_events_max:
                return
        payload = json.dumps(clean(dict(detail or {})), ensure_ascii=False)
        self.db.execute(
            "INSERT INTO job_events(job_id,ts,stage,status,detail) VALUES(?,?,?,?,?)",
            [job_id, time.time() if ts is None else ts, stage, status, payload],
        )

    def list(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT id,ts,stage,status,detail FROM job_events WHERE job_id=? ORDER BY id", [job_id]
        )
        return [
            {
                "id": r["id"],
                "ts": r["ts"],
                "stage": r["stage"],
                "status": r["status"],
                "detail": json.loads(r["detail"]) if r["detail"] else {},
            }
            for r in rows
        ]

    def deliver(self, job_id: str, via: str, client: str, user: str, **detail: Any) -> None:
        """Note that a client fetched the result of the job.

        The same client fetching the same way again within `delivery_coalesce_s` only raises the count
        and moves the time of the one row, so a TV that polls does not flood the log.
        """
        now = time.time()
        client, user = str(clean(client)), str(clean(user))
        recent = self.db.all(
            "SELECT id,detail FROM job_events WHERE job_id=? AND stage=? AND ts>=? ORDER BY id DESC",
            [job_id, DELIVERED, now - self.cfg.delivery_coalesce_s],
        )
        for row in recent:
            body = json.loads(row["detail"])
            if body.get("via") == via and body.get("client") == client:
                body.update(clean(detail))
                body["count"] = int(body.get("count", 1)) + 1
                self.db.execute(
                    "UPDATE job_events SET ts=?, detail=? WHERE id=?",
                    [now, json.dumps(body, ensure_ascii=False), row["id"]],
                )
                return
        self.record(
            job_id,
            DELIVERED,
            OK,
            {"via": via, "client": client, "user": user, "count": 1, "first_ts": now, **detail},
            ts=now,
        )

    def backfill(self) -> int:
        """One synthetic event for every job that has none (jobs from before event logging)."""
        rows = self.db.all(
            "SELECT id,status,created_at,updated_at,finished_at,error FROM jobs"
            " WHERE NOT EXISTS (SELECT 1 FROM job_events e WHERE e.job_id=jobs.id)"
        )
        for row in rows:
            stage_name, status, detail, ts = synthetic_event(dict(row))
            self.record(row["id"], stage_name, status, detail, ts=ts)
        return len(rows)


def synthetic_event(job: Mapping[str, Any]) -> tuple[str, str, dict[str, Any], float]:
    """(stage, status, detail, ts) standing in for the log of a job that predates event logging."""
    status = job.get("status")
    if status in ("queued", "running"):
        return (
            QUEUED,
            OK,
            {"synthetic": True, "message": SYNTHETIC_QUEUED_MESSAGE},
            job.get("created_at") or 0.0,
        )
    outcome = {"ready": OK, "failed": FAILED}.get(str(status), CANCELLED)
    detail: dict[str, Any] = {"synthetic": True, "message": SYNTHETIC_MESSAGE}
    if job.get("error"):
        detail["error"] = job["error"]
    ts = job.get("finished_at") or job.get("updated_at") or job.get("created_at") or 0.0
    return FINISHED, outcome, detail, ts


class _Stage:
    """`with stage(...)`: a running event now, an ok or failed one with `seconds` when the block ends."""

    def __init__(self, trace: JobTrace | None, name: str, detail: dict[str, Any], announce: bool):
        self.trace, self.name, self.detail, self.announce = trace, name, detail, announce
        self.extra: dict[str, Any] = {}
        self.status = OK
        self._t0 = 0.0

    def set(self, **detail: Any) -> None:
        self.extra.update(detail)

    def skip(self, **detail: Any) -> None:
        self.status = SKIPPED
        self.extra.update(detail)

    def __enter__(self) -> _Stage:
        self._t0 = time.monotonic()
        if self.trace is not None and self.announce:
            self.trace.emit(self.name, RUNNING, **self.detail)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self.trace is None:
            return False
        seconds = round(time.monotonic() - self._t0, 2)
        if exc is None:
            self.trace.emit(self.name, self.status, **self.detail, **self.extra, seconds=seconds)
        elif isinstance(exc, asyncio.CancelledError):
            self.trace.emit(self.name, INTERRUPTED, **self.detail, seconds=seconds)
        else:
            self.trace.emit(
                self.name,
                FAILED,
                **self.detail,
                **self.extra,
                seconds=seconds,
                error_class=error_class(exc),
                technical=technical(exc),
            )
            self.trace.failed_stage = self.name
        return False


@dataclass
class JobTrace:
    """The log of the job a worker is running; `emit` writes to the database as things happen."""

    job_id: str
    events: JobEvents
    notes: dict[str, Any] = field(default_factory=dict)
    emitted: set[str] = field(default_factory=set)
    failed_stage: str | None = None

    def emit(self, stage: str, status: str, **detail: Any) -> None:
        self.emitted.add(stage)
        try:
            self.events.record(self.job_id, stage, status, detail)
        except Exception:
            log.warning("job %s: could not record a %s event", self.job_id, stage, exc_info=True)


def bind(trace: JobTrace | None) -> Token:
    return _TRACE.set(trace)


def unbind(token: Token) -> None:
    _TRACE.reset(token)


def current() -> JobTrace | None:
    return _TRACE.get()


def emit(stage: str, status: str = OK, **detail: Any) -> None:
    trace = _TRACE.get()
    if trace is not None:
        trace.emit(stage, status, **detail)


def emitted(stage: str) -> bool:
    trace = _TRACE.get()
    return trace is not None and stage in trace.emitted


def stage(name: str, *, announce: bool = True, **detail: Any) -> _Stage:
    """A timed stage of the current job (no-op without one); `announce=False` writes only the outcome."""
    return _Stage(_TRACE.get(), name, detail, announce)


def note(**values: Any) -> None:
    """Facts learnt deep inside a stage (the chosen audio format) for the stage's own event."""
    trace = _TRACE.get()
    if trace is not None:
        trace.notes.update(values)


def take_notes() -> dict[str, Any]:
    trace = _TRACE.get()
    if trace is None:
        return {}
    taken, trace.notes = trace.notes, {}
    return taken


def job_id() -> str | None:
    trace = _TRACE.get()
    return trace.job_id if trace is not None else None
