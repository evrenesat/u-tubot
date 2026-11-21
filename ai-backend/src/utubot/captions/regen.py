"""Queue fresh captions jobs for tracks made before the current timing scheme (`utubot captions-regen`)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, TextIO

from ..config import Config
from ..db import Database
from .asr import normalize_language
from .jobs import LANG_AUTO, JobQueue
from .pipeline import TIMING_VERSION

TRIGGER_REGEN = {"via": "regen"}
FALLBACK_USER = "system"


@dataclass
class RegenItem:
    video_id: str
    lang: str
    timing_version: int | None
    user: str
    job_lang: str
    translate_to: str | None
    queued: str | None = None  # the job id once queued


def stale_tracks(
    db: Database, videos: list[str] | None = None, legacy_only: bool = False
) -> list[dict[str, Any]]:
    """Stored tracks whose `timing_version` is missing, or older than `TIMING_VERSION` (unless `legacy_only`)."""
    condition = "c.timing_version IS NULL"
    params: list[Any] = []
    if not legacy_only:
        condition = f"({condition} OR c.timing_version < ?)"
        params.append(TIMING_VERSION)
    # a newer track of the video that is already current means this one was replaced in effect
    # (e.g. the regenerated job stored another language than this row's)
    condition += (
        " AND NOT EXISTS (SELECT 1 FROM captions n WHERE n.video_id=c.video_id"
        " AND n.timing_version>=? AND n.created_at>c.created_at)"
    )
    params.append(TIMING_VERSION)
    if videos:
        condition += f" AND c.video_id IN ({','.join('?' for _ in videos)})"
        params += videos
    rows = db.all(
        "SELECT c.video_id, c.lang, c.timing_version, c.job_id FROM captions c"
        f" WHERE {condition} ORDER BY c.created_at",
        params,
    )
    return [dict(row) for row in rows]


def plan(cfg: Config, db: Database, rows: list[dict[str, Any]]) -> list[RegenItem]:
    """What to queue for each track: the original job's language, target and user when it is known."""
    fallback_user = next(
        (u.name for u in cfg.users if u.admin), cfg.users[0].name if cfg.users else FALLBACK_USER
    )
    items: list[RegenItem] = []
    for row in rows:
        job = db.one("SELECT user,lang,translate_to FROM jobs WHERE id=?", [row["job_id"] or ""])
        if job is not None:
            user, job_lang, target = job["user"], job["lang"], job["translate_to"]
        else:
            transcript = db.one("SELECT lang FROM transcripts WHERE video_id=?", [row["video_id"]])
            spoken = normalize_language(transcript["lang"]) if transcript else None
            user, job_lang = fallback_user, LANG_AUTO
            target = row["lang"] if spoken and row["lang"] != spoken else None
        items.append(
            RegenItem(row["video_id"], row["lang"], row["timing_version"], user, job_lang, target)
        )
    return items


def regen(
    cfg: Config,
    db: Database,
    *,
    videos: list[str] | None = None,
    legacy_only: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
) -> list[RegenItem]:
    """List the stale tracks (at most `limit`, default `[captions] regen_limit_default`) and, unless
    `dry_run`, queue a background captions job for each."""
    rows = stale_tracks(db, videos, legacy_only)
    cap = limit or cfg.captions.regen_limit_default
    items = plan(cfg, db, rows[:cap])
    if dry_run:
        return items
    # only `enqueue` is used: the queue is the one table the running server's workers read
    queue = JobQueue(cfg, db, None, None)  # type: ignore[arg-type]
    for item in items:
        job = queue.enqueue(
            item.user, item.video_id, item.job_lang, item.translate_to, trigger=TRIGGER_REGEN
        )
        item.queued = job["id"]
    return items


def print_items(items: list[RegenItem], dry_run: bool, out: TextIO | None = None) -> None:
    out = out or sys.stdout
    for item in items:
        state = "would queue" if dry_run else f"queued {item.queued}"
        version = "legacy" if item.timing_version is None else f"timing v{item.timing_version}"
        print(f"{item.video_id}  {item.lang}  {version}  {state}", file=out)
    print(f"{len(items)} track(s)", file=out)
