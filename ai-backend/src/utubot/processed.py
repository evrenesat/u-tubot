"""What a user recently processed: captions jobs and cut requests combined per video.

This is a read-only view over rows that already exist (`jobs` with kind `captions`,
`cut_requests`, and `summaries` for the summary flag). Nothing is stored here. One item is
returned per video id, newest activity first, with title and thumbnail when the cached metadata
has them and the caption/cut entries for that video.
"""

from __future__ import annotations

from typing import Any

from .captions.jobs import JOB_STATES, KIND_CAPTIONS
from .cuts import PRESET_LABELS
from .db import Database
from .prompts import PromptStore
from .transcripts import TranscriptService

THUMBNAIL_URL = "https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


class ProcessedService:
    """The recently processed videos of one user, from captions jobs, cuts and summaries."""

    def __init__(self, db: Database, transcripts: TranscriptService, prompts: PromptStore):
        self.db, self.transcripts, self.prompts = db, transcripts, prompts

    def recent(self, user: str, limit: int) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT video_id, MAX(updated_at) AS changed_at FROM ("
            "SELECT video_id, updated_at FROM jobs WHERE user=? AND kind=?"
            " UNION ALL "
            "SELECT video_id, updated_at FROM cut_requests WHERE user=? AND state!='dismissed'"
            ") GROUP BY video_id ORDER BY changed_at DESC, video_id ASC LIMIT ?",
            [user, KIND_CAPTIONS, user, limit],
        )
        video_ids = [row["video_id"] for row in rows]
        if not video_ids:
            return []
        marks = ",".join("?" * len(video_ids))
        caption_rows = self.db.all(
            "SELECT id,video_id,lang,translate_to,status,progress,error,created_at,updated_at,"
            f"title FROM jobs WHERE user=? AND kind=? AND video_id IN ({marks})"
            " ORDER BY updated_at DESC, created_at DESC",
            [user, KIND_CAPTIONS, *video_ids],
        )
        cut_rows = self.db.all(
            "SELECT id,video_id,preset_id,prompt,state,error,created_at,updated_at FROM"
            f" cut_requests WHERE user=? AND state!='dismissed' AND video_id IN ({marks})"
            " ORDER BY updated_at DESC, created_at DESC",
            [user, *video_ids],
        )
        summaries = {
            row["video_id"]
            for row in self.db.all(
                f"SELECT DISTINCT video_id FROM summaries WHERE video_id IN ({marks})",
                video_ids,
            )
        }
        labels = {p.id: p.label for p in self.prompts.cut_prompts(user)}
        captions_by_video: dict[str, list[dict[str, Any]]] = {}
        for row in caption_rows:
            captions_by_video.setdefault(row["video_id"], []).append(
                {
                    "job_id": row["id"],
                    "lang": row["lang"],
                    "translate_to": row["translate_to"],
                    "state": JOB_STATES.get(row["status"], row["status"]),
                    "progress": row["progress"],
                    "error": row["error"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        cuts_by_video: dict[str, list[dict[str, Any]]] = {}
        for row in cut_rows:
            preset_id = row["preset_id"]
            cuts_by_video.setdefault(row["video_id"], []).append(
                {
                    "request_id": row["id"],
                    "state": row["state"],
                    "preset_id": preset_id,
                    "preset_label": (
                        labels.get(preset_id) or PRESET_LABELS.get(preset_id) or preset_id
                        if preset_id
                        else None
                    ),
                    "prompt": row["prompt"],
                    "error": row["error"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        out = []
        for row in rows:
            video_id = row["video_id"]
            meta = self.transcripts.cached_meta(video_id) or {}
            captions = captions_by_video.get(video_id, [])
            title = meta.get("title") or next(
                (r["title"] for r in caption_rows if r["video_id"] == video_id and r["title"]),
                None,
            )
            thumb = meta.get("thumbnail") or meta.get("thumbnail_url")
            out.append(
                {
                    "video_id": video_id,
                    "title": title,
                    "thumbnail": thumb or THUMBNAIL_URL.format(video_id=video_id),
                    "updated_at": row["changed_at"],
                    "summary": video_id in summaries,
                    "captions": captions,
                    "cuts": cuts_by_video.get(video_id, []),
                }
            )
        return out
