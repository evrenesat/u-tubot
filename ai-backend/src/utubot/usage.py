"""Small per-day counters (LLM calls and tokens) for the status page."""

from __future__ import annotations

from datetime import UTC, datetime

from .db import Database

METRIC_LLM_CALLS = "llm_calls"
METRIC_LLM_ERRORS = "llm_errors"
METRIC_LLM_PROMPT_TOKENS = "llm_prompt_tokens"
METRIC_LLM_COMPLETION_TOKENS = "llm_completion_tokens"
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
