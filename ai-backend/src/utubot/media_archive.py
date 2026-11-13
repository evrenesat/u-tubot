"""The media archive: nothing downloaded from YouTube is thrown away, nothing is fetched twice.

Every file a pipeline downloads is stored once, content-addressed by its sha256, under
`[archive] path` (empty: `<data dir>/archive`), and described by one `media_archive` row per
video (format id, codec, bitrate, language, original-track flag, size, sha256, fetch time).
Pipelines ask `lookup` first and only download when it answers None; a fresh download goes
through `store`, which copies it into `files/<sha256[:2]>/<sha256>.<ext>` and records the row.

The quota (`[archive] quota_bytes`, 0: no limit) is a ceiling the archive never frees by itself:
`require_room` refuses a download that would start past it (the job fails with a clear message
and nothing was downloaded), and `store` warns when a file pushes the usage over it. Removing
entries is an explicit admin act (`remove`) — the archive never deletes on its own, its root is
refused when it sits inside the media scratch directory, and the scratch sweep of `media_dir`
never sees these files.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from .config import Config
from .db import Database

log = logging.getLogger("utubot.archive")

KIND_AUDIO = "audio"
KIND_VIDEO = "video"
READ_CHUNK = 1024 * 1024
TMP_DIRNAME = "tmp"
FILES_DIRNAME = "files"
ENTRY_LIMIT = 500
SHA_PREFIX = 12
STATE_OK = "ok"
STATE_WARN = "warn"
STATE_FULL = "full"


class MediaArchiveFull(RuntimeError):
    """The archive is at its quota: a new download is refused, nothing was downloaded."""

    def __init__(self, usage: int, quota: int):
        super().__init__(f"media archive full: {usage} of {quota} bytes used")
        self.usage = usage
        self.quota = quota

    @property
    def message(self) -> str:
        return (
            "The media archive is full; an admin must free space in it "
            "(nothing is deleted automatically)."
        )


class MediaArchiveError(RuntimeError):
    """The archive could not keep a downloaded file; the job stops so it is not thrown away."""

    def __init__(self, message: str, work: Path | None = None):
        super().__init__(message)
        self.message = message
        self.work = work


class MediaArchive:
    def __init__(self, cfg: Config, db: Database):
        self.cfg, self.db = cfg, db
        self.root = cfg.archive_dir
        self._refuse_inside_media_dir()
        self.files = self.root / FILES_DIRNAME
        self.tmp = self.root / TMP_DIRNAME

    def _refuse_inside_media_dir(self) -> None:
        """The scratch sweep of `data_dir/media` must never see archive files (nothing deletes here)."""
        try:
            root = self.root.resolve()
            media = self.cfg.media_dir.resolve()
        except OSError:
            return
        if root == media or media in root.parents:
            raise ValueError(
                f"[archive] path ({self.root}) must not be inside the media scratch directory"
                f" ({self.cfg.media_dir}): its orphan sweep removes old directories"
            )

    # ---- reads ---------------------------------------------------------------------------------

    def lookup(self, video_id: str, kind: str = KIND_AUDIO) -> dict[str, Any] | None:
        """The entry to use for this video: the original track first, then the newest one.

        None when nothing usable is stored (a row whose file vanished is dropped, so the video is
        fetched again and stored properly).
        """
        row = self.db.one(
            "SELECT * FROM media_archive WHERE video_id=? AND kind=?"
            " ORDER BY original DESC, fetched_at DESC LIMIT 1",
            [video_id, kind],
        )
        if row is None:
            return None
        path = self.path_of(row)
        if not path.is_file():
            log.warning(
                "media archive: file of video %s is gone (%s); dropping the entry", video_id, kind
            )
            self.db.execute(
                "DELETE FROM media_archive WHERE video_id=? AND sha256=?", [video_id, row["sha256"]]
            )
            return None
        return dict(row)

    def path_of(self, entry: dict[str, Any]) -> Path:
        return self.root / entry["path"]

    def usage(self) -> int:
        row = self.db.one("SELECT IFNULL(SUM(size),0) AS n FROM media_archive")
        return int(row["n"])

    def count(self) -> int:
        row = self.db.one("SELECT COUNT(*) AS n FROM media_archive")
        return int(row["n"])

    def status(self) -> dict[str, Any]:
        """Usage against the quota for the admin status: ok, warn (near the quota) or full."""
        quota = self.cfg.archive.quota_bytes
        usage = self.usage()
        state = STATE_OK
        if quota > 0:
            if usage >= quota:
                state = STATE_FULL
            elif usage >= quota * self.cfg.archive.warn_frac:
                state = STATE_WARN
        return {
            "files": self.count(),
            "usage_bytes": usage,
            "quota_bytes": quota,
            "state": state,
        }

    def entries(
        self, video_id: str | None = None, limit: int = ENTRY_LIMIT
    ) -> list[dict[str, Any]]:
        """Newest entries first, for the admin page; `video_id` narrows the list to one video."""
        limit = max(1, min(limit, ENTRY_LIMIT))
        if video_id:
            rows = self.db.all(
                "SELECT * FROM media_archive WHERE video_id=? ORDER BY fetched_at DESC LIMIT ?",
                [video_id, limit],
            )
        else:
            rows = self.db.all(
                "SELECT * FROM media_archive ORDER BY fetched_at DESC LIMIT ?", [limit]
            )
        return [dict(r) for r in rows]

    # ---- quota ---------------------------------------------------------------------------------

    def require_room(self) -> None:
        """Refuse a new download while the archive stands at its quota (nothing was downloaded)."""
        quota = self.cfg.archive.quota_bytes
        if quota <= 0:
            return
        usage = self.usage()
        if usage >= quota:
            log.warning("media archive full: %d of %d bytes; refusing new downloads", usage, quota)
            raise MediaArchiveFull(usage, quota)

    def _warn_level(self) -> bool:
        """True when the usage stands at or above `warn_frac` of a set quota."""
        quota = self.cfg.archive.quota_bytes
        return quota > 0 and self.usage() >= quota * self.cfg.archive.warn_frac

    # ---- writes --------------------------------------------------------------------------------

    def store(
        self,
        video_id: str,
        src: Path,
        *,
        kind: str = KIND_AUDIO,
        format_id: str | None = None,
        codec: str | None = None,
        bitrate_kbps: float | None = None,
        language: str | None = None,
        original: int | bool = 1,
        job_id: str | None = None,
        work: Path | None = None,
    ) -> dict[str, Any]:
        """Copy `src` into the archive under its sha256 and record it for this video.

        Identical bytes are stored once; the scratch original is removed afterwards. Raises
        `MediaArchiveError` when the file could not be kept (`work` names the scratch directory
        that must then survive, so the download is not lost).
        """
        digest = hashlib.sha256()
        staged = Path(self.tmp / f"{uuid.uuid4().hex}{src.suffix}")
        try:
            self.tmp.mkdir(parents=True, exist_ok=True)
            with open(src, "rb") as rd, open(staged, "wb") as wr:
                while chunk := rd.read(READ_CHUNK):
                    digest.update(chunk)
                    wr.write(chunk)
                wr.flush()
                os.fsync(wr.fileno())
            sha256 = digest.hexdigest()
            dest = self.files / sha256[:2] / f"{sha256}{src.suffix}"
            if not dest.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, dest)
            staged.unlink(missing_ok=True)
        except OSError as exc:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                pass
            raise MediaArchiveError(
                f"the media archive could not keep the download: {exc}", work
            ) from None
        size = dest.stat().st_size
        rel = dest.relative_to(self.root).as_posix()
        fetched_at = time.time()
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO media_archive(video_id,sha256,kind,format_id,codec,"
                "bitrate_kbps,language,original,size,ext,path,fetched_at,job_id)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    video_id,
                    sha256,
                    kind,
                    format_id,
                    codec,
                    bitrate_kbps,
                    language,
                    int(bool(original)),
                    size,
                    dest.suffix.lstrip("."),
                    rel,
                    fetched_at,
                    job_id,
                ],
            )
        except Exception as exc:
            raise MediaArchiveError(
                f"the media archive could not record the download: {exc}", work
            ) from None
        try:
            src.unlink(missing_ok=True)
        except OSError:
            pass
        if self.cfg.archive.quota_bytes > 0 and self.usage() > self.cfg.archive.quota_bytes:
            log.warning(
                "media archive over its quota: %d of %d bytes (the file was kept anyway)",
                self.usage(),
                self.cfg.archive.quota_bytes,
            )
        elif self._warn_level():
            log.warning(
                "media archive near its quota: %d of %d bytes (admin cleanup frees space)",
                self.usage(),
                self.cfg.archive.quota_bytes,
            )
        return {
            "video_id": video_id,
            "sha256": sha256,
            "kind": kind,
            "format_id": format_id,
            "codec": codec,
            "bitrate_kbps": bitrate_kbps,
            "language": language,
            "original": int(bool(original)),
            "size": size,
            "ext": dest.suffix.lstrip("."),
            "path": rel,
            "fetched_at": fetched_at,
            "job_id": job_id,
        }

    # ---- admin cleanup -------------------------------------------------------------------------

    def remove(self, video_id: str) -> tuple[int, int]:
        """Remove one video's entries and their files (an admin act; nothing does this by itself).

        A file that another entry still uses stays. Returns (entries, bytes) that went away.
        """
        rows = self.db.all("SELECT * FROM media_archive WHERE video_id=?", [video_id])
        for row in rows:
            self.db.execute(
                "DELETE FROM media_archive WHERE video_id=? AND sha256=?",
                [video_id, row["sha256"]],
            )
        removed = 0
        freed = 0
        for row in rows:
            path = self.root / row["path"]
            still = self.db.one(
                "SELECT COUNT(*) AS n FROM media_archive WHERE path=?", [row["path"]]
            )
            if still["n"]:
                log.info("media archive: a file of %s is still in use; kept", video_id)
            elif path.is_file():
                path.unlink(missing_ok=True)
                freed += int(row["size"])
            removed += 1
        return removed, freed

    def sweep_scratch(self) -> None:
        """Left-over staging files (a crash between copy and rename) go; recorded rows never."""
        if not self.tmp.is_dir():
            return
        for child in self.tmp.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
