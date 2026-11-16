"""Per-video artifact inventory and the Retry action.

Every artifact the backend makes or downloads for a video is kept (successes are cached
aggressively and versioned by their key: prompt hash, language, model). Failures are the opposite:
short-lived, and a busy model is never remembered (`bg.is_remembered`). Anything that is
remembered about a failure can be cleared on demand: `retry` is what the TV app's Retry action
calls, so the next request really tries again instead of replaying the old answer.

`inventory` lists what is stored for one video (rows, bytes, newest write); `purge` removes
chosen kinds for it (an admin act). The media archive is listed here but only removed through
`MediaArchive.remove` (its own rules).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .assess import Assessor
from .content import ContentService
from .db import Database
from .media_archive import MediaArchive
from .transcripts import TranscriptService

KIND_ARCHIVE = "archive"


@dataclass(frozen=True)
class ArtifactKind:
    name: str
    table: str
    size_sql: str  # bytes of one row
    ts_col: str  # newest-write column


KINDS: tuple[ArtifactKind, ...] = (
    ArtifactKind("metadata", "video_meta", "LENGTH(json)", "fetched_at"),
    ArtifactKind(
        "transcript", "transcripts", "LENGTH(text)+IFNULL(LENGTH(segments),0)", "fetched_at"
    ),
    ArtifactKind("captions", "captions", "LENGTH(vtt)", "created_at"),
    ArtifactKind("triage", "triage", "LENGTH(json)", "created_at"),
    ArtifactKind("analysis", "deep", "LENGTH(json)", "created_at"),
    ArtifactKind("summary", "summaries", "LENGTH(text)", "created_at"),
    ArtifactKind("condensed", "condensed", "LENGTH(text)", "created_at"),
    ArtifactKind("insight", "insights", "LENGTH(json)", "created_at"),
    ArtifactKind("pipeline", "stage_cache", "LENGTH(json)", "created_at"),
    ArtifactKind("verdict", "verdicts", "LENGTH(json)", "updated_at"),
)
BY_NAME = {k.name: k for k in KINDS}
KIND_NAMES = tuple(BY_NAME) + (KIND_ARCHIVE,)


class ArtifactCache:
    def __init__(
        self,
        db: Database,
        transcripts: TranscriptService,
        content: ContentService,
        assessor: Assessor,
        archive: MediaArchive,
    ):
        self.db = db
        self.transcripts, self.content, self.assessor = transcripts, content, assessor
        self.archive = archive

    def retry(self, video_id: str) -> dict[str, int]:
        """Forget every remembered failure of this video; stored successes stay.

        Counts per memory: `fetch` (failure/delay holds and "no captions"), `tasks` (failed
        summary, insight and answer tasks), `analysis` (failed background analysis).
        """
        return {
            "fetch": self.transcripts.clear_failures(video_id),
            "tasks": self.content.registry.forget_video(video_id),
            "analysis": self.assessor.tier2.forget_video(video_id),
        }

    def inventory(self, video_id: str) -> dict[str, Any]:
        """What is stored for one video: per kind the row count, bytes and newest write time."""
        items: list[dict[str, Any]] = []
        for kind in KINDS:
            row = self.db.one(
                f"SELECT COUNT(*) AS n, IFNULL(SUM({kind.size_sql}),0) AS size,"
                f" MAX({kind.ts_col}) AS newest FROM {kind.table} WHERE video_id=?",
                [video_id],
            )
            if row["n"]:
                items.append(
                    {
                        "kind": kind.name,
                        "rows": int(row["n"]),
                        "bytes": int(row["size"]),
                        "newest_at": row["newest"],
                    }
                )
        row = self.db.one(
            "SELECT COUNT(*) AS n, IFNULL(SUM(size),0) AS size, MAX(fetched_at) AS newest"
            " FROM media_archive WHERE video_id=?",
            [video_id],
        )
        if row["n"]:
            items.append(
                {
                    "kind": KIND_ARCHIVE,
                    "rows": int(row["n"]),
                    "bytes": int(row["size"]),
                    "newest_at": row["newest"],
                }
            )
        return {
            "video_id": video_id,
            "artifacts": items,
            "total_bytes": sum(i["bytes"] for i in items),
        }

    def purge(self, video_id: str, kinds: list[str] | None = None) -> dict[str, int]:
        """Remove the chosen kinds (default: all but the media archive) for one video.

        The archive goes only when named: `kinds=["archive"]`. Returns rows removed per kind.
        """
        wanted = list(kinds) if kinds else [k.name for k in KINDS]
        unknown = [name for name in wanted if name not in KIND_NAMES]
        if unknown:
            raise ValueError(f"unknown artifact kind: {', '.join(unknown)}")
        removed: dict[str, int] = {}
        for name in wanted:
            if name == KIND_ARCHIVE:
                entries, _freed = self.archive.remove(video_id)
                removed[name] = entries
            else:
                kind = BY_NAME[name]
                removed[name] = self.db.execute_rc(
                    f"DELETE FROM {kind.table} WHERE video_id=?", [video_id]
                )
        return removed
