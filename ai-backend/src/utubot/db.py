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
  fetched_at REAL NOT NULL, engine TEXT, model TEXT, segments TEXT, job_id TEXT);
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
  priority INTEGER NOT NULL DEFAULT 1, klass TEXT NOT NULL DEFAULT 'normal');
CREATE TABLE IF NOT EXISTS job_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, ts REAL NOT NULL,
  stage TEXT NOT NULL, status TEXT NOT NULL, detail TEXT);
CREATE INDEX IF NOT EXISTS job_events_job ON job_events(job_id, id);
CREATE TABLE IF NOT EXISTS media_archive(
  video_id TEXT NOT NULL, sha256 TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'audio',
  format_id TEXT, codec TEXT, bitrate_kbps REAL, language TEXT, original INTEGER NOT NULL DEFAULT 1,
  size INTEGER NOT NULL, ext TEXT NOT NULL, path TEXT NOT NULL, fetched_at REAL NOT NULL,
  job_id TEXT, PRIMARY KEY(video_id, sha256));
CREATE TABLE IF NOT EXISTS captions(
  video_id TEXT NOT NULL, lang TEXT NOT NULL, label TEXT NOT NULL, speakers INTEGER NOT NULL,
  vtt TEXT NOT NULL, created_at REAL NOT NULL, job_id TEXT, PRIMARY KEY(video_id, lang));
CREATE TABLE IF NOT EXISTS stage_cache(
  video_id TEXT NOT NULL, stage TEXT NOT NULL, cache_key TEXT NOT NULL, json TEXT NOT NULL,
  created_at REAL NOT NULL, PRIMARY KEY(video_id, stage, cache_key));
CREATE TABLE IF NOT EXISTS device_tokens(
  id TEXT PRIMARY KEY, user TEXT NOT NULL, token_sha256 TEXT NOT NULL UNIQUE, device TEXT NOT NULL,
  created_at REAL NOT NULL, last_used REAL);
CREATE TABLE IF NOT EXISTS pair_codes(
  id TEXT PRIMARY KEY, user TEXT NOT NULL, code_sha256 TEXT NOT NULL, expires_at REAL NOT NULL,
  used INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS pair_failures(ip TEXT NOT NULL, ts REAL NOT NULL);
CREATE TABLE IF NOT EXISTS web_logins(
  id TEXT PRIMARY KEY, user TEXT NOT NULL, token_sha256 TEXT NOT NULL UNIQUE, device TEXT NOT NULL,
  created_at REAL NOT NULL, expires_at REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0, used_at REAL);
CREATE INDEX IF NOT EXISTS web_logins_user ON web_logins(user, created_at);
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
CREATE TABLE IF NOT EXISTS cut_requests(
  id TEXT PRIMARY KEY, user TEXT NOT NULL, video_id TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
  preset_id TEXT, prompt TEXT, state TEXT NOT NULL, error TEXT,
  cut_key TEXT, job_id TEXT, raw_answer TEXT, created_at REAL NOT NULL,
  updated_at REAL NOT NULL, finished_at REAL,
  mode TEXT NOT NULL DEFAULT 'quick', progress REAL,
  source_kind TEXT NOT NULL DEFAULT 'youtube', source_key TEXT, release_key TEXT,
  release_duration_ms INTEGER, force INTEGER NOT NULL DEFAULT 0,
  klass TEXT NOT NULL DEFAULT 'normal',
  mode_rule TEXT NOT NULL DEFAULT 'request', channel_id TEXT);
CREATE TABLE IF NOT EXISTS cut_channel_modes(
  user TEXT NOT NULL, channel_id TEXT NOT NULL, channel_name TEXT, mode TEXT NOT NULL,
  updated_at REAL NOT NULL, PRIMARY KEY(user, channel_id));
CREATE INDEX IF NOT EXISTS cut_requests_user ON cut_requests(user, created_at);
CREATE INDEX IF NOT EXISTS cut_requests_video ON cut_requests(video_id);
CREATE TABLE IF NOT EXISTS cuts(
  cache_key TEXT PRIMARY KEY, video_id TEXT NOT NULL, version TEXT NOT NULL,
  preset_id TEXT, prompt TEXT, model TEXT NOT NULL, transcript_hash TEXT NOT NULL,
  json TEXT NOT NULL, duration_s REAL, kept_s REAL, created_at REAL NOT NULL,
  mode TEXT NOT NULL DEFAULT 'quick',
  source_kind TEXT NOT NULL DEFAULT 'youtube', source_key TEXT, release_key TEXT,
  release_duration_ms INTEGER,
  algo_version INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS cuts_video ON cuts(video_id);
CREATE TABLE IF NOT EXISTS video_scenes(
  cache_key TEXT PRIMARY KEY, video_id TEXT NOT NULL,
  source_kind TEXT NOT NULL DEFAULT 'youtube', source_key TEXT, release_key TEXT,
  release_duration_ms INTEGER, video_sha256 TEXT NOT NULL, settings_key TEXT NOT NULL,
  scene_cuts TEXT NOT NULL, manifest TEXT NOT NULL, coarse INTEGER NOT NULL DEFAULT 0,
  cap_steps INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS video_scenes_video ON video_scenes(video_id);
CREATE TABLE IF NOT EXISTS scene_descriptions(
  cache_key TEXT PRIMARY KEY, video_id TEXT NOT NULL,
  source_kind TEXT NOT NULL DEFAULT 'youtube', source_key TEXT, release_key TEXT,
  release_duration_ms INTEGER, video_sha256 TEXT NOT NULL, settings_key TEXT NOT NULL,
  model TEXT NOT NULL, prompt_hash TEXT NOT NULL, transcript_hash TEXT NOT NULL,
  json TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS scene_descriptions_video ON scene_descriptions(video_id);
CREATE TABLE IF NOT EXISTS scene_labels(
  descriptions_key TEXT NOT NULL, source_key TEXT, release_key TEXT,
  segment_id TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
  category TEXT NOT NULL, intensity INTEGER NOT NULL, confidence REAL NOT NULL,
  vocab_version INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS scene_labels_source ON scene_labels(source_key, release_key, category);
CREATE TABLE IF NOT EXISTS cut_choices(
  user TEXT NOT NULL, video_id TEXT NOT NULL, preset_id TEXT, request_id TEXT,
  off INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL,
  PRIMARY KEY(user, video_id));
CREATE TABLE IF NOT EXISTS changelog(
  kind TEXT NOT NULL, version TEXT NOT NULL, at REAL NOT NULL, commit_sha TEXT NOT NULL DEFAULT '',
  changes TEXT NOT NULL DEFAULT '[]', PRIMARY KEY(kind, version));
CREATE INDEX IF NOT EXISTS changelog_at ON changelog(kind, at);
CREATE TABLE IF NOT EXISTS cut_last_presets(
  user TEXT PRIMARY KEY, preset_id TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS feature_models(
  feature TEXT PRIMARY KEY, alias TEXT NOT NULL, changed_at REAL NOT NULL, changed_by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feature_calls(
  id INTEGER PRIMARY KEY AUTOINCREMENT, feature TEXT NOT NULL, alias TEXT NOT NULL, ts REAL NOT NULL,
  elapsed_ms INTEGER NOT NULL DEFAULT 0, prompt_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0, cost REAL);
CREATE INDEX IF NOT EXISTS feature_calls_feature ON feature_calls(feature, ts);
CREATE TABLE IF NOT EXISTS feature_audit(
  id INTEGER PRIMARY KEY AUTOINCREMENT, feature TEXT NOT NULL, from_alias TEXT, to_alias TEXT,
  changed_by TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS inbox(
   id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL, video_id TEXT NOT NULL,
   kind TEXT NOT NULL, result_id TEXT NOT NULL DEFAULT '', prompt_key TEXT, title TEXT,
   length_s INTEGER, label TEXT, thumbnail TEXT, created_at REAL NOT NULL, read_at REAL, dismissed INTEGER
   NOT NULL DEFAULT 0, dismissed_at REAL);
CREATE INDEX IF NOT EXISTS inbox_user ON inbox(user, dismissed, created_at DESC);
CREATE TABLE IF NOT EXISTS device_voice(
  device_id TEXT PRIMARY KEY, user TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
  listen_mode TEXT NOT NULL DEFAULT 'push', speak INTEGER NOT NULL DEFAULT 0,
  consent_version INTEGER, consented_at REAL, updated_at REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS device_voice_user ON device_voice(user);
CREATE TABLE IF NOT EXISTS user_voice(
  user TEXT PRIMARY KEY, retention_days INTEGER, updated_at REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS voice_commands(
  id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL, device_id TEXT NOT NULL DEFAULT '',
  at REAL NOT NULL, text TEXT NOT NULL DEFAULT '', tool TEXT NOT NULL DEFAULT '',
  args TEXT NOT NULL DEFAULT '{}', outcome TEXT NOT NULL DEFAULT '', marks TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS voice_commands_user ON voice_commands(user, at DESC);
CREATE TABLE IF NOT EXISTS failures(
   id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, component TEXT NOT NULL,
   operation TEXT NOT NULL, category TEXT NOT NULL, video_id TEXT, message TEXT NOT NULL,
   detail TEXT, flagged INTEGER NOT NULL DEFAULT 0, client TEXT);
CREATE INDEX IF NOT EXISTS failures_ts ON failures(ts DESC);
CREATE INDEX IF NOT EXISTS failures_category ON failures(category, ts DESC);
CREATE TABLE IF NOT EXISTS user_providers(
   user TEXT PRIMARY KEY, base_url TEXT NOT NULL, api_key_hash TEXT NOT NULL, api_key TEXT NOT NULL,
   updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS user_usage(
   user TEXT NOT NULL, day TEXT NOT NULL, cost REAL NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0,
   PRIMARY KEY(user, day));
"""

JOB_COLUMNS = {
    "kind": "TEXT NOT NULL DEFAULT 'captions'",
    "title": "TEXT",
    "finished_at": "REAL",
    "attempts": "INTEGER NOT NULL DEFAULT 0",
    "not_before": "REAL",
    "priority": "INTEGER NOT NULL DEFAULT 1",
    "force": "INTEGER NOT NULL DEFAULT 0",
    "klass": "TEXT NOT NULL DEFAULT 'normal'",
}
POLICY_COLUMNS = {"version": "INTEGER NOT NULL DEFAULT 0", "updated_at": "REAL NOT NULL DEFAULT 0"}
TRANSCRIPT_COLUMNS = {
    "engine": "TEXT",
    "model": "TEXT",
    "segments": "TEXT",
    "job_id": "TEXT",
    "words": "TEXT",
    "caption_kind": "TEXT",
    "origin": "TEXT",
}
CAPTION_COLUMNS = {"job_id": "TEXT", "timing_version": "INTEGER", "timing": "TEXT"}
ARCHIVE_COLUMNS = {"last_used_at": "REAL"}
CUT_REQUEST_COLUMNS = {
    "mode": "TEXT NOT NULL DEFAULT 'quick'",
    "progress": "REAL",
    "source_kind": "TEXT NOT NULL DEFAULT 'youtube'",
    "source_key": "TEXT",
    "release_key": "TEXT",
    "release_duration_ms": "INTEGER",
    "force": "INTEGER NOT NULL DEFAULT 0",
}
CUTS_COLUMNS = {
    "mode": "TEXT NOT NULL DEFAULT 'quick'",
    "source_kind": "TEXT NOT NULL DEFAULT 'youtube'",
    "source_key": "TEXT",
    "release_key": "TEXT",
    "release_duration_ms": "INTEGER",
    "algo_version": "INTEGER NOT NULL DEFAULT 0",
}
CUT_REQUEST_CLASS_COLUMNS = {"klass": "TEXT NOT NULL DEFAULT 'normal'"}
CUT_REQUEST_MODE_COLUMNS = {
    "mode_rule": "TEXT NOT NULL DEFAULT 'request'",
    "channel_id": "TEXT",
}
MODE_RULE_REQUEST = "request"
MODE_RULE_CHANNEL = "channel"
MODE_RULE_USER = "user"
MODE_RULE_SERVER = "server"
MAX_CHANNEL_ID_CHARS = 64
MAX_CHANNEL_NAME_CHARS = 120
METADATA_ONLY = "metadata_only"


DB_FILE_MODE = 0o600


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if str(path) != ":memory:":
            # the file holds users' own provider keys: owner-only, like users.toml
            Path(path).chmod(DB_FILE_MODE)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
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
        self._add_missing_columns("captions", CAPTION_COLUMNS)
        self._add_missing_columns("media_archive", ARCHIVE_COLUMNS)
        self._add_missing_columns("cut_requests", CUT_REQUEST_COLUMNS)
        self._add_missing_columns("cuts", CUTS_COLUMNS)
        self._add_missing_columns("cut_requests", CUT_REQUEST_CLASS_COLUMNS)
        self._add_missing_columns("cut_requests", CUT_REQUEST_MODE_COLUMNS)
        # Rows written when a transcript could not be fetched: nothing may be built on a title alone.
        self._migrate_asr_cache_v4()
        self._conn.execute("DELETE FROM transcripts WHERE source=?", [METADATA_ONLY])
        self._conn.execute("DELETE FROM summaries WHERE source=?", [METADATA_ONLY])
        self._conn.execute(
            "DELETE FROM insights WHERE json LIKE ?", [f'%"source": "{METADATA_ONLY}"%']
        )

    def _migrate_asr_cache_v4(self) -> None:
        """Carry the v4 ASR cache rows over to the v5 one-cache layout, so no speech recognition
        already paid for is run again.

        v4 keys were `v4:{audio}:{want_words}:{language}:{separation}[:wm-...]`; v5 keys are
        `v5:{audio}:{separation}:{language}` with the strongest answer (words, real or mixed times)
        per key. Old rows stay in place; an existing v5 row is never replaced. Idempotent."""
        from .captions.asr import normalize_language

        rows = self._conn.execute(
            "SELECT video_id, cache_key, json, created_at FROM stage_cache"
            " WHERE stage='asr' AND cache_key LIKE 'v4:%'"
        ).fetchall()
        best: dict[tuple[str, str], tuple[tuple[int, int, float], str, float]] = {}
        for row in rows:
            parts = row["cache_key"].split(":")
            if len(parts) < 5:
                continue
            _, audio_sha, _, requested, separation = parts[:5]
            try:
                payload = json.loads(row["json"])
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            langclass = normalize_language(payload.get("language")) or (
                None if requested == "auto" else requested
            )
            payload["v"] = 5
            key = f"v5:{audio_sha}:{separation}:{langclass or 'auto'}"
            rank = (
                int(bool(payload.get("words"))),
                int(payload.get("word_timing") in ("real", "mixed")),
                row["created_at"],
            )
            slot = (row["video_id"], key)
            if slot not in best or rank > best[slot][0]:
                best[slot] = (rank, json.dumps(payload, ensure_ascii=False), row["created_at"])
        for (video_id, key), (_, blob, created_at) in best.items():
            self._conn.execute(
                "INSERT OR IGNORE INTO stage_cache(video_id,stage,cache_key,json,created_at)"
                " VALUES(?,?,?,?,?)",
                [video_id, "asr", key, blob, created_at],
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
