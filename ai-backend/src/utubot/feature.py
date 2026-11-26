"""Per-feature model alias overrides and their cost/time telemetry.

The admin points each feature (assess, summaries, the quick and watched cut editors, the captions
proofread/translate pass, ...) at a modelgate alias from the web UI. The choice is stored here,
overrides the ``[llm.<task>]`` default in config.toml for everyone, and takes effect on the next call
(no restart). modelgate reports a real cost per alias (EVR-560, modelgate#18/#20); this server has no
gateway, so cost is estimated from tokens and an optional per-alias price. Every model call records
which alias it used, how long it took and its tokens, and this module turns those rows into the
last-7-days calls, tokens, cost, median and p90 the admin page shows.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from .config import FEATURE_KEYS, Config
from .db import Database

ALIAS_MAX_CHARS = 200
DEFAULT_KEEP_DAYS = 30
SWEEP_INTERVAL_S = 86400


def cost_for(cfg: Config, alias: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """The estimated USD cost of one call, or null when the alias has no price (unknown, not guessed)."""
    price = cfg.usage.price_usd_per_million.get(alias)
    if price is None:
        return None
    return (prompt_tokens + completion_tokens) * price / 1_000_000


def median_p90(values: list[float]) -> tuple[float | None, float | None]:
    """Median and 95th percentile of a list of milliseconds; both null when there is no sample."""
    if not values:
        return None, None
    ordered = sorted(values)
    return _percentile(ordered, 50.0), _percentile(ordered, 90.0)


def _percentile(ordered: list[float], pct: float) -> float:
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


class FeatureUsage:
    """Per-call telemetry, one row per successful model call, keyed by feature and alias."""

    def __init__(self, db: Database, keep_days: int = DEFAULT_KEEP_DAYS):
        self._db = db
        self._keep_days = keep_days
        self._last_sweep = 0.0

    def record(
        self,
        feature: str,
        alias: str,
        elapsed_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        cost: float | None,
    ) -> None:
        if feature is None or self._db is None:
            return
        self._sweep_daily()
        self._db.execute(
            "INSERT INTO feature_calls(feature,alias,ts,elapsed_ms,prompt_tokens,"
            "completion_tokens,cost) VALUES(?,?,?,?,?,?,?)",
            [
                feature,
                alias,
                datetime.now(UTC).timestamp(),
                int(elapsed_ms),
                int(prompt_tokens),
                int(completion_tokens),
                cost,
            ],
        )

    def _sweep_daily(self) -> None:
        """Keep the table bounded: drop rows past the retention window at most once a day."""
        now = time.monotonic()
        if self._last_sweep and now - self._last_sweep < SWEEP_INTERVAL_S:
            return
        self._last_sweep = now
        self.sweep(self._keep_days)

    def sweep(self, keep_days: int) -> int:
        """Drop telemetry older than the retention window; returns the rows removed."""
        if self._db is None:
            return 0
        cutoff = datetime.now(UTC).timestamp() - keep_days * 86400
        return self._db.execute_rc("DELETE FROM feature_calls WHERE ts < ?", [cutoff])

    def stats(
        self, feature: str, alias: str, window_days: int, now: float | None = None
    ) -> dict[str, Any]:
        """Last `window_days` of calls, tokens, cost and time for the one feature/alias pair."""
        if self._db is None:
            return _empty_stats()
        now = datetime.now(UTC).timestamp() if now is None else now
        cutoff = now - window_days * 86400
        row = self._db.one(
            "SELECT COUNT(*) AS calls, COALESCE(SUM(prompt_tokens),0) AS prompt_tokens, "
            "COALESCE(SUM(completion_tokens),0) AS completion_tokens, "
            "SUM(cost) AS cost FROM feature_calls WHERE feature=? AND alias=? AND ts>=?",
            [feature, alias, cutoff],
        )
        calls = int(row["calls"])
        prompt_tokens = int(row["prompt_tokens"])
        completion_tokens = int(row["completion_tokens"])
        cost = row["cost"]
        cost = round(cost, 6) if cost is not None else None
        times = [
            float(r["elapsed_ms"])
            for r in self._db.all(
                "SELECT elapsed_ms FROM feature_calls WHERE feature=? AND alias=? AND ts>=?",
                [feature, alias, cutoff],
            )
        ]
        median_ms, p90_ms = median_p90(times)
        return {
            "calls": calls,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "tokens": prompt_tokens + completion_tokens,
            "cost": cost,
            "median_ms": round(median_ms, 1) if median_ms is not None else None,
            "p90_ms": round(p90_ms, 1) if p90_ms is not None else None,
            "samples": len(times),
        }


class FeatureStore:
    """The admin's per-feature alias overrides, the audit log, and the known alias list."""

    def __init__(self, cfg: Config, db: Database):
        self.cfg, self.db = cfg, db
        self.usage = FeatureUsage(db, cfg.usage.keep_days)

    def feature_names(self) -> list[str]:
        """Every feature with a configured model, in a stable order."""
        return [f for f in FEATURE_KEYS if self.cfg.llm.feature_configured(f)]

    def override_for(self, feature: str) -> str | None:
        if self.db is None:
            return None
        row = self.db.one("SELECT alias FROM feature_models WHERE feature=?", [feature])
        return row["alias"] if row else None

    def current_alias(self, feature: str) -> str | None:
        """What the feature runs on now: the admin override, else the config.toml model."""
        return self.override_for(feature) or self.cfg.llm.feature_model(feature)

    def fallback(self, feature: str) -> list[str]:
        return self.cfg.llm.feature_fallback(feature)

    def set_alias(self, feature: str, alias: str, by: str) -> dict[str, Any]:
        """Point a feature at a new alias, record who changed it and when, and log the change."""
        now = datetime.now(UTC).timestamp()
        previous = self.override_for(feature)
        if previous == alias:
            self.db.execute(
                "INSERT INTO feature_models(feature,alias,changed_at,changed_by) VALUES(?,?,?,?)",
                [feature, alias, now, by],
            )
        else:
            self.db.execute(
                "INSERT INTO feature_models(feature,alias,changed_at,changed_by) VALUES(?,?,?,?) "
                "ON CONFLICT(feature) DO UPDATE SET alias=excluded.alias, changed_at=excluded.changed_at, "
                "changed_by=excluded.changed_by",
                [feature, alias, now, by],
            )
        self.db.execute(
            "INSERT INTO feature_audit(feature,from_alias,to_alias,changed_by,at) VALUES(?,?,?,?,?)",
            [feature, previous, alias, by, now],
        )
        return self.doc(feature)

    def reset(self, feature: str, by: str) -> dict[str, Any] | None:
        """Drop the admin override so the feature follows config.toml again."""
        row = self.db.one("SELECT alias FROM feature_models WHERE feature=?", [feature])
        if row is None:
            return None
        self.db.execute("DELETE FROM feature_models WHERE feature=?", [feature])
        self.db.execute(
            "INSERT INTO feature_audit(feature,from_alias,to_alias,changed_by,at) VALUES(?,?,?,?,?)",
            [feature, row["alias"], None, by, datetime.now(UTC).timestamp()],
        )
        return self.doc(feature)

    def recent_changes(self, feature: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT from_alias,to_alias,changed_by,at FROM feature_audit WHERE feature=? "
            "ORDER BY id DESC LIMIT ?",
            [feature, limit],
        )
        return [
            {
                "from": r["from_alias"],
                "to": r["to_alias"],
                "by": r["changed_by"],
                "at": r["at"],
            }
            for r in rows
        ]

    def alias_list(self, catalog_values: list[str] | None = None) -> list[str]:
        """Every alias the admin may choose, validated against this list.

        The live model values the admin page passes in, plus the aliases this server already knows
        from its own config (every feature's model and fallback, and the speech alias), so a choice is
        always offered even before the catalog is fetched.
        """
        known: set[str] = set()
        if catalog_values:
            known.update(catalog_values)
        for feature in FEATURE_KEYS:
            model = self.cfg.llm.feature_model(feature)
            if model:
                known.add(model)
            known.update(self.cfg.llm.feature_fallback(feature))
        speech = self.cfg.speech.alias.strip()
        if speech:
            known.add(speech)
        return sorted(known)

    def doc(self, feature: str) -> dict[str, Any]:
        """One admin page row: the alias in force, its fallback, the audit trail and the usage."""
        alias = self.current_alias(feature)
        stats = (
            self.usage.stats(feature, alias, self.cfg.usage.window_days)
            if alias
            else _empty_stats()
        )
        return {
            "feature": feature,
            "alias": alias,
            "fallback": self.fallback(feature),
            "overridden": self.override_for(feature) is not None,
            "changes": self.recent_changes(feature),
            "usage": stats,
        }

    def page(self, catalog_values: list[str] | None = None) -> dict[str, Any]:
        """Every feature row plus the alias list the select is validated against."""
        return {
            "features": [self.doc(f) for f in self.feature_names()],
            "aliases": self.alias_list(catalog_values),
            "window_days": self.cfg.usage.window_days,
        }


def _empty_stats() -> dict[str, Any]:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "tokens": 0,
        "cost": None,
        "median_ms": None,
        "p90_ms": None,
        "samples": 0,
    }


# A feature run (one summary, cut, insight, ...): the cost of its model calls, plus the wall clock
# the endpoint measured, shown to the caller as "this run cost $0.004, 41 s". Set at the top of a
# request, read at the end.
_RUN: ContextVar[dict[str, float] | None] = ContextVar("utubot_feature_run", default=None)


def run_start() -> Any:
    return _RUN.set({"cost": 0.0})


def run_reset(token: Any) -> None:
    _RUN.reset(token)


def run_current() -> dict[str, float] | None:
    return _RUN.get()


def run_accumulate(cost: float | None) -> None:
    """Add one model call's cost to the active run, if any (nothing when the run is off)."""
    run = _RUN.get()
    if run is not None and cost:
        run["cost"] += cost


def run_finish(run: dict[str, float], elapsed_s: float) -> None:
    """Close a run with the wall clock the endpoint measured around the feature call."""
    run["elapsed_s"] = round(elapsed_s, 3)


@contextmanager
def feature_run():
    """Time one feature call and expose its model cost as ``cost_usd`` and ``elapsed_s``.

    The model calls inside add their cost to the run (see `run_accumulate`); this measures how long
    the whole call took and yields the run so the caller can attach the numbers to its response.
    """
    token = run_start()
    start = time.perf_counter()
    try:
        yield run_current()
    finally:
        run = _RUN.get()
        if run is not None:
            run_finish(run, time.perf_counter() - start)
        run_reset(token)
