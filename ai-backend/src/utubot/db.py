from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS video_meta(
  video_id TEXT PRIMARY KEY, json TEXT NOT NULL, fetched_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS transcripts(
  video_id TEXT PRIMARY KEY, lang TEXT, source TEXT NOT NULL, text TEXT NOT NULL,
  fetched_at REAL NOT NULL, engine TEXT, model TEXT, segments TEXT);
CREATE INDEX IF NOT EXISTS transcripts_fetched ON transcripts(fetched_at);
CREATE TABLE IF NOT EXISTS no_captions(
  video_id TEXT PRIMARY KEY, checked_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS video_holds(
  video_id TEXT PRIMARY KEY, kind TEXT NOT NULL, reason TEXT NOT NULL, until REAL NOT NULL);
CREATE TABLE IF NOT EXISTS youtube_gate(
  id INTEGER PRIMARY KEY CHECK(id=1), cooldown_until REAL NOT NULL, strikes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS youtube_gate_class(
  klass TEXT PRIMARY KEY, cooldown_until REAL NOT NULL, strikes INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS triage(
  video_id TEXT NOT NULL, topics_hash TEXT NOT NULL, json TEXT NOT NULL, created_at REAL NOT NULL,
  PRIMARY KEY(video_id, topics_hash));
CREATE TABLE IF NOT EXISTS deep(
  video_id TEXT PRIMARY KEY, json TEXT NOT NULL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS tier2_usage(
  user TEXT NOT NULL, day TEXT NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(user, day));
CREATE TABLE IF NOT EXISTS prompt_sets(
  user TEXT NOT NULL, set_id TEXT NOT NULL, json TEXT NOT NULL, source_url TEXT,
  updated_at REAL NOT NULL, PRIMARY KEY(user, set_id));
CREATE TABLE IF NOT EXISTS user_default(user TEXT PRIMARY KEY, prompt_key TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user_panel_default(user TEXT PRIMARY KEY, prompt_key TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS summaries(
  video_id TEXT NOT NULL, prompt_key TEXT NOT NULL, content_hash TEXT NOT NULL,
  language TEXT NOT NULL, text TEXT NOT NULL, source TEXT NOT NULL, created_at REAL NOT NULL,
  PRIMARY KEY(video_id, prompt_key, content_hash, language));
CREATE TABLE IF NOT EXISTS condensed(
  video_id TEXT NOT NULL, budget INTEGER NOT NULL, text TEXT NOT NULL, created_at REAL NOT NULL,
  PRIMARY KEY(video_id, budget));
CREATE TABLE IF NOT EXISTS insights(
  video_id TEXT NOT NULL, language TEXT NOT NULL, json TEXT NOT NULL, created_at REAL NOT NULL,
  PRIMARY KEY(video_id, language));
CREATE TABLE IF NOT EXISTS verdicts(
  user TEXT NOT NULL, video_id TEXT NOT NULL, policy_hash TEXT NOT NULL, json TEXT NOT NULL,
  updated_at REAL NOT NULL, PRIMARY KEY(user, video_id));
CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, user TEXT NOT NULL, video_id TEXT NOT NULL, lang TEXT NOT NULL,
  translate_to TEXT, status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, error TEXT,
  created_at REAL NOT NULL, updated_at REAL NOT NULL, kind TEXT NOT NULL DEFAULT 'captions',
  title TEXT, finished_at REAL, attempts INTEGER NOT NULL DEFAULT 0, not_before REAL,
  priority INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS captions(
  video_id TEXT NOT NULL, lang TEXT NOT NULL, label TEXT NOT NULL, speakers INTEGER NOT NULL,
  vtt TEXT NOT NULL, created_at REAL NOT NULL, PRIMARY KEY(video_id, lang));
CREATE TABLE IF NOT EXISTS device_tokens(
  id TEXT PRIMARY KEY, user TEXT NOT NULL, token_sha256 TEXT NOT NULL UNIQUE, device TEXT NOT NULL,
  created_at REAL NOT NULL, last_used REAL);
CREATE TABLE IF NOT EXISTS pair_codes(
  id TEXT PRIMARY KEY, user TEXT NOT NULL, code_sha256 TEXT NOT NULL, expires_at REAL NOT NULL,
  used INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pair_failures(ip TEXT NOT NULL, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS pair_failures_ip ON pair_failures(ip, ts);
CREATE TABLE IF NOT EXISTS policy_overrides(
  user TEXT PRIMARY KEY, json TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS user_passwords(
  user TEXT PRIMARY KEY, hash TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(
  id_sha256 TEXT PRIMARY KEY, user TEXT NOT NULL, created_at REAL NOT NULL, last_seen REAL NOT NULL,
  expires_at REAL NOT NULL, ip TEXT, agent TEXT, via TEXT NOT NULL DEFAULT 'password');
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user);
CREATE TABLE IF NOT EXISTS login_failures(scope TEXT NOT NULL, ts REAL NOT NULL);
CREATE INDEX IF NOT EXISTS login_failures_scope ON login_failures(scope, ts);
CREATE TABLE IF NOT EXISTS model_seen(
  provider TEXT NOT NULL, model TEXT NOT NULL, first_seen REAL NOT NULL,
  PRIMARY KEY(provider, model));
CREATE TABLE IF NOT EXISTS usage_daily(
  day TEXT NOT NULL, metric TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY(day, metric));
CREATE TABLE IF NOT EXISTS feedback(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL, video_id TEXT NOT NULL,
  kind TEXT NOT NULL, correct INTEGER NOT NULL, note TEXT, created_at REAL NOT NULL);
"""

JOB_COLUMNS = {
    "kind": "TEXT NOT NULL DEFAULT 'captions'",
    "title": "TEXT",
    "finished_at": "REAL",
    "attempts": "INTEGER NOT NULL DEFAULT 0",
    "not_before": "REAL",
    "priority": "INTEGER NOT NULL DEFAULT 1",
}
POLICY_COLUMNS = {"version": "INTEGER NOT NULL DEFAULT 0", "updated_at": "REAL NOT NULL DEFAULT 0"}
TRANSCRIPT_COLUMNS = {"engine": "TEXT", "model": "TEXT", "segments": "TEXT"}
METADATA_ONLY = "metadata_only"


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _add_missing_columns(self, table: str, columns: dict[str, str]) -> None:
        have = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})")}
        for column, ddl in columns.items():
            if column not in have:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _migrate(self) -> None:
        self._add_missing_columns("jobs", JOB_COLUMNS)
        self._add_missing_columns("policy_overrides", POLICY_COLUMNS)
        self._add_missing_columns("transcripts", TRANSCRIPT_COLUMNS)
        # Rows written when a transcript could not be fetched: nothing may be built on a title alone.
        self._conn.execute("DELETE FROM transcripts WHERE source=?", [METADATA_ONLY])
        self._conn.execute("DELETE FROM summaries WHERE source=?", [METADATA_ONLY])
        self._conn.execute(
            "DELETE FROM insights WHERE json LIKE ?", [f'%"source": "{METADATA_ONLY}"%']
        )

    def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self._lock:
            self._conn.execute(sql, tuple(params))
            self._conn.commit()

    def execute_rc(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur.rowcount

    def one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchone()

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, tuple(params)).fetchall()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def get_json(self, table: str, where: str, params: Iterable[Any], ttl_s: float | None = None):
        row = self.one(
            f"SELECT json, {self._ts_col(table)} AS ts FROM {table} WHERE {where}", params
        )
        if row is None:
            return None
        if ttl_s is not None and time.time() - row["ts"] > ttl_s:
            return None
        return json.loads(row["json"])

    @staticmethod
    def _ts_col(table: str) -> str:
        return {"video_meta": "fetched_at", "verdicts": "updated_at"}.get(table, "created_at")
