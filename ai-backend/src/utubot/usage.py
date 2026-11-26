"""Small per-day counters (LLM calls and tokens) for the status page."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .db import Database

METRIC_LLM_CALLS = "llm_calls"
METRIC_LLM_ERRORS = "llm_errors"
METRIC_LLM_PROMPT_TOKENS = "llm_prompt_tokens"
METRIC_LLM_COMPLETION_TOKENS = "llm_completion_tokens"
# A YouTube download refused with HTTP 403 while a cut waited for the TV's own captions.
METRIC_YOUTUBE_FORBIDDEN = "youtube_forbidden"
DAY_FORMAT = "%Y-%m-%d"


def today() -> str:
    return datetime.now(UTC).strftime(DAY_FORMAT)


class Usage:
    def __init__(self, db: Database | None):
        self._db = db

    def add(self, metric: str, n: int = 1) -> None:
        if self._db is None or n <= 0:
            return
        self._db.execute(
            "INSERT INTO usage_daily(day,metric,n) VALUES(?,?,?)"
            " ON CONFLICT(day,metric) DO UPDATE SET n=n+excluded.n",
            [today(), metric, n],
        )

    def today(self) -> dict[str, int]:
        if self._db is None:
            return {}
        rows = self._db.all("SELECT metric, n FROM usage_daily WHERE day=?", [today()])
        return {r["metric"]: int(r["n"]) for r in rows}

    def daily(self, metric: str, days: int) -> list[dict[str, int | str]]:
        """One metric's per-day counts over the last ``days`` days, newest first."""
        if self._db is None:
            return []
        first = (datetime.now(UTC) - timedelta(days=days)).strftime(DAY_FORMAT)
        rows = self._db.all(
            "SELECT day, n FROM usage_daily WHERE metric=? AND day>=? ORDER BY day DESC",
            [metric, first],
        )
        return [{"day": r["day"], "count": int(r["n"])} for r in rows]
