"""Per-video cache of pipeline stage results, so a retried job does not redo finished work.

The media archive keeps the downloaded media; this table keeps what later stages produced from it:
the recognised words of an audio file, the proofread text of a batch of cues. Entries are keyed by
the inputs that define them (a sha256 of the audio, of the texts), so a changed input is never
served from the cache. Rows are removed together with the video's archived media (the one admin
cleanup); nothing in a stage result is secret (a `proofread` entry holds subtitle text).
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..db import Database


class StageCache:
    def __init__(self, db: Database):
        self.db = db

    def get(self, video_id: str, stage: str, cache_key: str) -> Any | None:
        row = self.db.one(
            "SELECT json FROM stage_cache WHERE video_id=? AND stage=? AND cache_key=?",
            [video_id, stage, cache_key],
        )
        if row is None:
            return None
        try:
            return json.loads(row["json"])
        except ValueError:
            return None

    def put(self, video_id: str, stage: str, cache_key: str, value: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO stage_cache(video_id,stage,cache_key,json,created_at)"
            " VALUES(?,?,?,?,?)",
            [video_id, stage, cache_key, json.dumps(value, ensure_ascii=False), time.time()],
        )

    def remove(self, video_id: str) -> int:
        return self.db.execute_rc("DELETE FROM stage_cache WHERE video_id=?", [video_id])
