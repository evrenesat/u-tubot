"""The error ledger: record, categorise and count every failure.

One table of failures the owner can analyse instead of digging through logs. Every failure the backend
knows about (a job that gave up, a YouTube breaker opening, an insight/summary/answer that failed) and
every failure a client reports (the TV, the extension) lands here with a category, so the admin page can
show counts per category per day and the newest examples with a link to the job.

Categories are mapped from the known error text (see ``categorize``); a failure whose text matches no
known pattern is ``unknown`` and flagged for triage, so a new failure shape surfaces instead of hiding.
"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

DEFAULT_KEEP_DAYS = 90
SWEEP_INTERVAL_S = 86400

CATEGORY_UNKNOWN = "unknown"
CATEGORY_YOUTUBE_REFUSED = "youtube-refused"
CATEGORY_RATE_LIMITED = "rate-limited"
CATEGORY_TIMEOUT = "timeout"
CATEGORY_NETWORK = "network"
CATEGORY_MODEL_ERROR = "model-error"
CATEGORY_TRANSCRIPT = "transcript"
CATEGORY_CONFIG = "config"
CATEGORY_SYNC = "sync"
CATEGORY_BUG = "bug"

# Every category a client may name when it reports a failure, plus the server's own. Clients map their
# own failure to one of these; anything else is folded to ``unknown`` and flagged.
KNOWN_CATEGORIES = frozenset(
    {
        CATEGORY_UNKNOWN,
        CATEGORY_YOUTUBE_REFUSED,
        CATEGORY_RATE_LIMITED,
        CATEGORY_TIMEOUT,
        CATEGORY_NETWORK,
        CATEGORY_MODEL_ERROR,
        CATEGORY_TRANSCRIPT,
        CATEGORY_CONFIG,
        CATEGORY_SYNC,
        CATEGORY_BUG,
    }
)

CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_YOUTUBE_REFUSED: "YouTube refused",
    CATEGORY_RATE_LIMITED: "Rate limited",
    CATEGORY_TIMEOUT: "Timed out",
    CATEGORY_NETWORK: "Network",
    CATEGORY_MODEL_ERROR: "Model error",
    CATEGORY_TRANSCRIPT: "Transcript",
    CATEGORY_CONFIG: "Config",
    CATEGORY_SYNC: "Sync",
    CATEGORY_BUG: "Unexpected",
    CATEGORY_UNKNOWN: "Unsorted",
}

# (category, patterns) in priority order: the first rule whose text matches wins, the rest is ``unknown``.
_CATEGORY_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        CATEGORY_RATE_LIMITED,
        re.compile(
            r"\b429\b|rate[\s_-]?limit|too many requests|back off|slow down|cooldown|retry[\s_-]?after|quota exhausted",
            re.I,
        ),
    ),
    (
        CATEGORY_YOUTUBE_REFUSED,
        re.compile(
            r"\b403\b|forbidden|bot check|unusual traffic|members?[\s_-]only|age[\s_-]restricted|this video is|video is unavailable|"
            r"is private|is marked as removed|is not available|\b410\b|refused the (?:audio|download|stream|media)|player ?tests?|"
            r"verify (?:that )?you(?:'?s)? not a bot|requires authorization to view",
            re.I,
        ),
    ),
    (
        CATEGORY_TIMEOUT,
        re.compile(
            r"timed? out|timeout|deadline exceeded|operation timed|exceeded the wait|timed out waiting",
            re.I,
        ),
    ),
    (
        CATEGORY_NETWORK,
        re.compile(
            r"connection (?:refused|reset|aborted|closed|rejected)|no address for name|name resolution|resolution failed|"
            r"network unreachable|no route to host|transport error|cannot connect|failed to connect|remote endpoint|"
            r"connect timed|socket|tls|ssl handshake|connection to",
            re.I,
        ),
    ),
    (
        CATEGORY_MODEL_ERROR,
        re.compile(
            r"\b(500|502|503)\b|model is busy|is busy|bad (?:response )?json|invalid json|no json found|empty (?:response|content|"
            r"body|answer|output)|completion (?:ended|streamed)|context length|maximum (?:token|length)|whisper|speech "
            r"(?:recognition|to text)|openai|provider error|api error|api key|authorization|unauthorized|\b401\b",
            re.I,
        ),
    ),
    (
        CATEGORY_TRANSCRIPT,
        re.compile(
            r"transcript|caption|segment|align|proofread|translation|hallucination|sparse|diariz|word ?time|stitch|separation|"
            r"seam|chunk|sync score|word timing",
            re.I,
        ),
    ),
    (
        CATEGORY_CONFIG,
        re.compile(
            r"not configured|no (?:model|provider|asr|engine|speech)|missing (?:model|config|provider)|invalid (?:prompt|language|"
            r"video ?id)|out of range|unknown prompt|too long to transcribe|cuts are not configured",
            re.I,
        ),
    ),
    (
        CATEGORY_SYNC,
        re.compile(r"\bsync\b|app update|release list|github|\btag\b", re.I),
    ),
]


def categorize(message: str | None, *, category: str | None = None) -> tuple[str, bool]:
    """Map one failure to ``(category, flagged)``.

    An explicit ``category`` (the caller already knows it, e.g. the YouTube gate) wins and is never flagged.
    Otherwise the lowercased message is matched against the known patterns in order; the first match wins.
    Nothing that matches returns ``unknown`` and ``flagged=True`` so a new failure shape is triaged.
    """
    if category:
        # An explicit category the caller knows wins; one outside the known set is a caller error, so
        # flag it for triage rather than silently folding it into an existing category.
        return (category, False) if category in KNOWN_CATEGORIES else (CATEGORY_UNKNOWN, True)
    text = (message or "").lower()
    if not text.strip():
        return CATEGORY_UNKNOWN, True
    for known, pattern in _CATEGORY_RULES:
        if pattern.search(text):
            return known, False
    return CATEGORY_UNKNOWN, True


def _day(ts: float) -> str:
    """The UTC calendar day one timestamp falls on, ``YYYY-MM-DD``."""
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d")


_JOB_ID_RE = re.compile(r"(?:job_id=)?([0-9a-fA-F]{8,})$")


def _job_id_of(detail: str | None) -> str | None:
    """The job id a failure detail points at, so the admin example can link to the job report.

    A job failure stores its id as `job_id=<id>`; a bare id is matched too. Anything else (a YouTube
    reason, a client note) has no job and returns None.
    """
    if not detail:
        return None
    match = _JOB_ID_RE.search(detail.strip())
    return match.group(1) if match else None


class LedgerService:
    """Records failures, maps them to a category, and answers the admin page's counts and examples."""

    def __init__(self, db, keep_days: int = DEFAULT_KEEP_DAYS):
        self._db = db
        self._keep_days = keep_days
        self._last_sweep = 0.0

    def record(
        self,
        component: str,
        operation: str,
        *,
        message: str,
        category: str | None = None,
        video_id: str | None = None,
        detail: str | None = None,
        client: str | None = None,
        ts: float | None = None,
    ) -> int | None:
        """Write one failure. Returns its id, or None when the ledger is disabled (no db)."""
        if self._db is None or not message:
            return None
        category, flagged = categorize(message, category=category)
        self._sweep()
        self._db.execute(
            "INSERT INTO failures(ts,component,operation,category,video_id,message,detail,flagged,client)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            [
                ts if ts is not None else time.time(),
                component,
                operation,
                category,
                video_id,
                message[:2000],
                (detail or "")[:4000],
                1 if flagged else 0,
                client,
            ],
        )
        return self._db.one("SELECT last_insert_rowid() AS id")["id"]

    def _sweep(self) -> None:
        now = time.monotonic()
        if self._last_sweep and now - self._last_sweep < SWEEP_INTERVAL_S:
            return
        self._last_sweep = now
        self.sweep(self._keep_days)

    def sweep(self, keep_days: int) -> int:
        """Drop failures older than the retention window; returns the rows removed."""
        if self._db is None:
            return 0
        cutoff = datetime.now(UTC).timestamp() - keep_days * 86400
        return self._db.execute_rc("DELETE FROM failures WHERE ts < ?", [cutoff])

    def reclassify(self, failure_id: int, category: str, by: str) -> bool:
        """The admin sorts one flagged/unknown failure into a real category during triage.

        ``category`` is validated against the known set; an unknown one is refused. Returns whether a row
        changed (a no-op reclassify of an already-correct row reports False).
        """
        if category not in KNOWN_CATEGORIES:
            raise ValueError("unknown category")
        row = self._db.one("SELECT category, flagged FROM failures WHERE id=?", [failure_id])
        if row is None:
            return False
        changed = row["category"] != category or (row["flagged"] and category != CATEGORY_UNKNOWN)
        self._db.execute(
            "UPDATE failures SET category=?, flagged=? WHERE id=?",
            [category, 0 if category != CATEGORY_UNKNOWN else row["flagged"], failure_id],
        )
        return bool(changed)

    def counts(self, period_days: int, now: float | None = None) -> list[dict[str, Any]]:
        """Counts per category per day over the last ``period_days`` (and a per-category total)."""
        if self._db is None:
            return []
        now_dt = datetime.now(UTC) if now is None else datetime.fromtimestamp(now, UTC)
        cutoff = now_dt.timestamp() - period_days * 86400
        rows = self._db.all(
            "SELECT category, flagged, CAST(ts AS INTEGER) - (CAST(ts AS INTEGER) % 86400) AS day, COUNT(*) AS n "
            "FROM failures WHERE ts >= ? GROUP BY category, flagged, day ORDER BY day DESC, category",
            [cutoff],
        )
        by_day: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
        totals: Counter[str] = Counter()
        for r in rows:
            entry = {
                "category": r["category"],
                "flagged": bool(r["flagged"]),
                "day": _day(float(r["day"])),
                "count": int(r["n"]),
            }
            by_day[(r["category"], bool(r["flagged"]))].append(entry)
            totals[(r["category"], bool(r["flagged"]))] += int(r["n"])
        return [
            {**entry, "total": totals[key]} for key, entries in by_day.items() for entry in entries
        ]

    def recent(
        self,
        limit: int = 50,
        *,
        category: str | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """The newest failures, with a link to the job that made them when there is one.

        ``offset`` skips the ``offset`` newest rows, so the admin page can walk the list in pages.
        """
        if self._db is None:
            return []
        if category and category not in KNOWN_CATEGORIES:
            raise ValueError("unknown category")
        rows = self._db.all(
            "SELECT id,ts,component,operation,category,video_id,message,detail,flagged,client FROM failures"
            + (" WHERE category=? " if category else " ")
            + "ORDER BY id DESC LIMIT ? OFFSET ?",
            ([category, limit, offset] if category else [limit, offset]),
        )
        out = []
        for r in rows:
            out.append(
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "day": _day(r["ts"]),
                    "component": r["component"],
                    "operation": r["operation"],
                    "category": r["category"],
                    "flagged": bool(r["flagged"]),
                    "video_id": r["video_id"],
                    "message": r["message"],
                    "detail": r["detail"],
                    "client": r["client"],
                    "job_id": _job_id_of(r["detail"]),
                }
            )
        return out

    def page(self, period_days: int, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Everything the admin page draws: the per-category/day counts and the newest examples."""
        return {
            "period_days": period_days,
            "counts": self.counts(period_days),
            "recent": self.recent(limit, offset=offset),
        }

    def prune(self, ids: Iterable[int]) -> int:
        """Drop the given failures (triage cleanup); returns the rows removed."""
        ids = [int(i) for i in ids]
        if not ids or self._db is None:
            return 0
        marks = ",".join("?" * len(ids))
        return self._db.execute_rc(f"DELETE FROM failures WHERE id IN ({marks})", ids)
