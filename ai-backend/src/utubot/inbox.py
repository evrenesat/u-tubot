"""The per-user inbox of AI results.

Every requested result that becomes ready is one inbox item: a ready director's cut, a ready
summary or TL;DR, a ready research answer (insight) or done HQ captions. Each result is stored as
one row when it becomes ready (see :meth:`InboxService.add`), and the list view
(:meth:`InboxService.list`) shows them newest first with an unread/read state, so a client can
show a "new results" badge while the viewer is watching. Read and dismiss are per user, so the
phone, the browser extension and the TV share the same inbox.

This is a small append-mostly table: a row is written once when a result is ready, read is a
timestamp and dismiss soft-deletes it. Nothing here reaches YouTube or a model.
"""

from __future__ import annotations

import time
from typing import Any

from .db import Database

# The result kinds the inbox holds. Each maps to one way the client opens the outcome: a cut
# starts playing with that cut, the text answers (summary, research) open and auto-scroll, and
# done captions open the video with the HQ track.
KIND_CUT = "cut"
KIND_SUMMARY = "summary"
KIND_RESEARCH = "research"
KIND_CAPTIONS = "captions"

# The thumbnail an inbox item shows on its tile. The metadata carried with the result usually has
# one; fall back to YouTube's own image for the video, like the processed list (see processed.py).
THUMBNAIL_URL = "https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


def thumbnail_for(meta: dict[str, Any] | None, video_id: str) -> str | None:
    """The tile thumbnail for a result: the metadata's, else YouTube's image for the video."""
    if meta:
        return meta.get("thumbnail") or meta.get("thumbnail_url")
    return THUMBNAIL_URL.format(video_id=video_id)


class InboxService:
    """One item per result that became ready, newest first, with an unread/read state and dismiss."""

    def __init__(self, db: Database):
        self.db = db

    def add(
        self,
        user: str,
        video_id: str,
        kind: str,
        result_id: str,
        *,
        title: str | None = None,
        length_s: int | None = None,
        label: str | None = None,
        prompt_key: str | None = None,
        thumbnail: str | None = None,
    ) -> None:
        """Record one result as ready.

        ``(user, kind, video_id, result_id)`` is the item's identity: a result that is reported
        ready more than once (a re-ready, or a client polling again) does not make a second item,
        and the first ``created_at`` is kept. A dismissed item can be brought back: dismiss is
        only a read-only flag (CONTRACT.md), so a result reported ready again after dismiss is
        inserted once more, deduped by the same identity.
        """
        self.db.execute(
            "INSERT INTO inbox(user,video_id,kind,result_id,prompt_key,title,length_s,label,"
            "thumbnail,created_at) SELECT?,?,?,?,?,?,?,?,?,? WHERE NOT EXISTS ("
            "SELECT 1 FROM inbox WHERE user=? AND video_id=? AND kind=? AND result_id=? "
            "AND dismissed=0)",
            [
                user,
                video_id,
                kind,
                result_id,
                prompt_key,
                title,
                length_s,
                label,
                thumbnail,
                time.time(),
                user,
                video_id,
                kind,
                result_id,
            ],
        )

    def list(self, user: str, limit: int) -> tuple[list[dict[str, Any]], int]:
        """The user's non-dismissed items, newest first, and how many are unread.

        ``read`` is true when the item has been read (``read_at`` set), by any client: the inbox
        and its unread count are shared per user, so reading it on the phone clears the badge on
        the TV.
        """
        rows = self.db.all(
            "SELECT id,video_id,kind,result_id,prompt_key,title,length_s,label,"
            "thumbnail,created_at,read_at FROM inbox WHERE user=? AND dismissed=0 "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            [user, limit],
        )
        items = []
        unread = 0

        for row in rows:
            read = row["read_at"] is not None
            if not read:
                unread += 1
            items.append(self._item(row, read))

        return items, unread

    def mark_read(self, user: str, ids: list[int]) -> None:
        """Mark the user's own items read (``read_at`` now). Unknown or another user's ids are ignored."""
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        self.db.execute(
            f"UPDATE inbox SET read_at=? WHERE user=? AND dismissed=0 AND id IN ({marks})",
            [time.time(), user, *ids],
        )

    def mark_read_all(self, user: str) -> None:
        """Mark every non-dismissed item of the user read."""
        self.db.execute(
            "UPDATE inbox SET read_at=? WHERE user=? AND dismissed=0 AND read_at IS NULL",
            [time.time(), user],
        )

    def dismiss(self, user: str, ids: list[int]) -> None:
        """Remove the user's own items from the inbox (soft delete)."""
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        self.db.execute(
            f"UPDATE inbox SET dismissed=1, dismissed_at=? WHERE user=? AND id IN ({marks})",
            [time.time(), user, *ids],
        )

    @staticmethod
    def _item(row: Any, read: bool) -> dict[str, Any]:
        return {
            "id": row["id"],
            "video_id": row["video_id"],
            "kind": row["kind"],
            "result_id": row["result_id"],
            "prompt_key": row["prompt_key"],
            "title": row["title"],
            "length_s": row["length_s"],
            "label": row["label"],
            "thumbnail": row["thumbnail"],
            "created_at": row["created_at"],
            "read": read,
        }
