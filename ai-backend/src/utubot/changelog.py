"""The two version histories behind GET /v1/changelog: app releases (from the release sync) and backend deploys."""

from __future__ import annotations

import json
import time

from . import buildinfo
from .db import Database

KINDS = ("app", "backend")
DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _entry(row) -> dict:
    try:
        changes = json.loads(row["changes"])
    except json.JSONDecodeError:
        changes = []
    return {
        "kind": row["kind"],
        "version": row["version"],
        "at": row["at"],
        "commit": row["commit_sha"],
        "changes": changes,
    }


def history(db: Database, kind: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Newest first."""
    limit = max(1, min(limit, MAX_LIMIT))
    rows = db.all(
        "SELECT * FROM changelog WHERE kind=? ORDER BY at DESC, rowid DESC LIMIT ?", [kind, limit]
    )
    return [_entry(row) for row in rows]


def record_deploy(db: Database, build: buildinfo.Build, now: float | None = None) -> bool:
    """Record the running build unless the last recorded deploy already is this commit. True when a row was added."""
    last = db.one(
        "SELECT commit_sha, version FROM changelog WHERE kind='backend' ORDER BY at DESC, rowid DESC LIMIT 1"
    )
    if last is not None and (
        last["commit_sha"] == build.commit and last["version"] == build.version
    ):
        return False
    previous = last["commit_sha"] if last else ""
    changes = buildinfo.changes_between(build.root, previous, build.commit)
    added = db.execute_rc(
        "INSERT OR IGNORE INTO changelog(kind, version, at, commit_sha, changes) VALUES('backend', ?, ?, ?, ?)",
        [build.version, now if now is not None else time.time(), build.commit, json.dumps(changes)],
    )
    return added > 0


def record_app_release(
    db: Database, version: str, notes: list[str], released_at: float | None, *, overwrite: bool
) -> None:
    """Keep an app release's notes and release time. A release already stored keeps its row unless `overwrite`."""
    changes = json.dumps([{"group": "other", "text": line, "pr": None} for line in notes])
    verb = "INSERT OR REPLACE" if overwrite else "INSERT OR IGNORE"
    db.execute(
        f"{verb} INTO changelog(kind, version, at, commit_sha, changes) VALUES('app', ?, ?, '', ?)",
        [version, released_at if released_at else time.time(), changes],
    )
