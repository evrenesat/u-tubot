"""The two version histories behind GET /v1/changelog: app releases (from the release sync) and backend deploys."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from . import buildinfo, releasenotes
from .db import Database

KINDS = ("app", "backend")
POLISH_TIMEOUT_S = 2.0
POLISH_PROMPT = (
    "Rewrite these release notes in plain words for people who use a TV app. Keep every line, its order and its leading label "
    "(New:, Fixed: or Changed:), at most {chars} characters per line, no new facts, no extra lines. Answer with the lines only."
)
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
    changes = json.dumps(releasenotes.as_changes(releasenotes.normalize(notes)))
    verb = "INSERT OR REPLACE" if overwrite else "INSERT OR IGNORE"
    db.execute(
        f"{verb} INTO changelog(kind, version, at, commit_sha, changes) VALUES('app', ?, ?, '', ?)",
        [version, released_at if released_at else time.time(), changes],
    )


def _is_short_form(changes: list[dict]) -> bool:
    texts = [str(c.get("text", "")) for c in changes]
    return len(texts) <= releasenotes.MAX_LINES + 1 and all(
        t == releasenotes.MAINTENANCE_ONLY
        or releasenotes.MORE_RE.match(t)
        or (releasenotes.LABELLED_RE.match(t) and len(t) <= releasenotes.MAX_LINE_CHARS)
        for t in texts
    )


def rebuild(db: Database, root: Path | None = None) -> int:
    """Bring every stored entry to the short form; the number of rows rewritten. Idempotent.

    App releases: their stored lines are shortened. Backend deploys: re-derived from the git history between the
    deploy and the one before it when the checkout has both commits, else their stored lines are shortened."""
    rows = db.all("SELECT rowid AS id, * FROM changelog ORDER BY kind, at, rowid")
    rewritten = 0
    previous_commit = {"app": "", "backend": ""}
    for row in rows:
        entry = _entry(row)
        kind = row["kind"]
        before = previous_commit[kind]
        previous_commit[kind] = row["commit_sha"] or ""
        if _is_short_form(entry["changes"]):
            continue
        fresh = None
        if kind == "backend" and root is not None and row["commit_sha"]:
            fresh = buildinfo.changes_between(root, before, row["commit_sha"]) or None
        if fresh is None:
            lines = releasenotes.normalize(str(c.get("text", "")) for c in entry["changes"])
            fresh = releasenotes.as_changes(lines, empty_means_maintenance=kind == "backend")
        db.execute("UPDATE changelog SET changes=? WHERE rowid=?", [json.dumps(fresh), row["id"]])
        rewritten += 1
    return rewritten


async def polish(llm, task, lines: list[str], timeout_s: float = POLISH_TIMEOUT_S) -> list[str]:
    """The deterministic lines in plainer words from the configured fast alias; the lines themselves on any problem."""
    if not lines or llm is None or task is None:
        return lines
    prompt = POLISH_PROMPT.format(chars=releasenotes.MAX_LINE_CHARS)
    try:
        text = await asyncio.wait_for(
            llm.chat(
                task,
                [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": "\n".join(lines)},
                ],
                deadline_s=timeout_s,
            ),
            timeout_s,
        )
        rewritten = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
        ok = (
            len(rewritten) == len(lines)
            and all(
                releasenotes.LABELLED_RE.match(ln) and len(ln) <= releasenotes.MAX_LINE_CHARS
                for ln in rewritten
            )
            or lines == [releasenotes.MAINTENANCE_ONLY]
        )
        return rewritten if ok and lines != [releasenotes.MAINTENANCE_ONLY] else lines
    except Exception:
        logging.getLogger(__name__).info("changelog wording kept deterministic", exc_info=True)
        return lines


async def polish_latest_deploy(
    db: Database, llm, task, timeout_s: float = POLISH_TIMEOUT_S
) -> bool:
    """Reword the newest backend entry. True when its text changed."""
    row = db.one(
        "SELECT rowid AS id, * FROM changelog WHERE kind='backend' ORDER BY at DESC, rowid DESC LIMIT 1"
    )
    if row is None:
        return False
    lines = [str(c.get("text", "")) for c in _entry(row)["changes"]]
    reworded = await polish(llm, task, lines, timeout_s)
    if reworded == lines:
        return False
    db.execute(
        "UPDATE changelog SET changes=? WHERE rowid=?",
        [json.dumps(releasenotes.as_changes(reworded)), row["id"]],
    )
    return True
