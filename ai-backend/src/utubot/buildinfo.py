"""The running backend's real version and what changed since the previous deploy, read from the checkout's git.

Version: `0.<series>.<commit time>+<short sha>`, where the series is the minor of `utubot.version` at the checkout's root and
the commit time is the HEAD commit's date in UTC as `YYYYMMDDHHMM`. It does not use the commit count, which a shallow clone
undercounts (a deploy from one could then report an older version than the previous one).
Outside a git checkout (an installed package) the version is the package version and nothing else is known.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, releasenotes

GIT_TIMEOUT_S = 10
SHORT_SHA_CHARS = 7
STAMP_FORMAT = "%Y%m%d%H%M"
SERIES_FILE = "utubot.version"
FIRST_DEPLOY_COMMITS = 15
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
COMMIT_MARK = "\x01"


@dataclass(frozen=True)
class Build:
    version: str
    commit: str = ""
    root: Path | None = None
    changes: list[dict] = field(default_factory=list, compare=False)


def _git(root: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _checkout_root() -> Path | None:
    top = _git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel")
    return Path(top) if top else None


def series(root: Path) -> str:
    """The minor number of `utubot.version` ("0.3" -> "3"); "0" when the file is missing or odd."""
    try:
        parts = (root / SERIES_FILE).read_text().strip().split(".")
    except OSError:
        return "0"
    return parts[1] if len(parts) > 1 and parts[1].isdigit() else "0"


def commit_stamp(root: Path) -> str | None:
    """The HEAD commit's date as UTC `YYYYMMDDHHMM`; None when git cannot say."""
    seconds = _git(root, "log", "-1", "--format=%ct", "HEAD")
    if not seconds or not seconds.isdigit():
        return None
    return datetime.fromtimestamp(int(seconds), tz=UTC).strftime(STAMP_FORMAT)


def derive_version(root: Path | None, fallback: str = __version__) -> Build:
    """The build of a checkout, or the package version when git cannot say."""
    if root is None:
        return Build(fallback)
    commit = _git(root, "rev-parse", "HEAD")
    stamp = commit_stamp(root)
    if not commit or not COMMIT_RE.match(commit) or not stamp:
        return Build(fallback)
    return Build(f"0.{series(root)}.{stamp}+{commit[:SHORT_SHA_CHARS]}", commit, root)


def detect() -> Build:
    return derive_version(_checkout_root())


def changes_between(root: Path | None, previous: str, current: str) -> list[dict]:
    """Short user-facing notes for the merged changes in `current` that `previous` lacks, newest first; the last few
    commits when `previous` is unknown. [] when git cannot say; "Maintenance only" when nothing there is user-visible."""
    if root is None or not current:
        return []
    known = (
        bool(previous)
        and COMMIT_RE.match(previous)
        and _git(root, "cat-file", "-e", previous) is not None
    )
    args = ["log", "--first-parent", "--name-only", f"--pretty=format:{COMMIT_MARK}%s"]
    args += [f"{previous}..{current}"] if known else ["-n", str(FIRST_DEPLOY_COMMITS), current]
    out = _git(root, *args)
    if out is None:
        return []
    commits = []
    for block in out.split(COMMIT_MARK)[1:]:
        subject, _, files = block.partition("\n")
        commits.append((subject, [name for name in files.splitlines() if name.strip()]))
    return releasenotes.as_changes(
        releasenotes.summarize(commits), empty_means_maintenance=bool(commits)
    )
