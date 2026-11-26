"""The running backend's real version and what changed since the previous deploy, read from the checkout's git.

Version: `0.<series>.<commit count>+<short sha>`, where the series is the minor of `utubot.version` at the checkout's root.
Outside a git checkout (an installed package) the version is the package version and nothing else is known.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__

GIT_TIMEOUT_S = 10
SHORT_SHA_CHARS = 7
SERIES_FILE = "utubot.version"
FIRST_DEPLOY_COMMITS = 15
MAX_CHANGES = 60
MAX_TEXT_CHARS = 200
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PR_SUFFIX_RE = re.compile(r"\s*\(#(\d+)\)\s*$")
SUBJECT_RE = re.compile(r"^(?P<type>[a-z]+)(?:/(?P<scope>[^:]+))?:\s*(?P<text>.+)$")
GROUPS = {"feat": "features", "fix": "fixes"}
# Commits that are not something a user notices.
HIDDEN_TYPES = frozenset(
    {"docs", "test", "tests", "chore", "ci", "refactor", "style", "build", "perf"}
)


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


def derive_version(root: Path | None, fallback: str = __version__) -> Build:
    """The build of a checkout, or the package version when git cannot say."""
    if root is None:
        return Build(fallback)
    commit = _git(root, "rev-parse", "HEAD")
    count = _git(root, "rev-list", "--count", "HEAD")
    if not commit or not COMMIT_RE.match(commit) or not count or not count.isdigit():
        return Build(fallback)
    return Build(f"0.{series(root)}.{count}+{commit[:SHORT_SHA_CHARS]}", commit, root)


def detect() -> Build:
    return derive_version(_checkout_root())


def describe(subject: str) -> dict | None:
    """One commit subject as a user-facing change: {"group", "text", "pr"}; None for what a user would not notice."""
    subject = subject.strip()
    pr = PR_SUFFIX_RE.search(subject)
    subject = PR_SUFFIX_RE.sub("", subject)
    match = SUBJECT_RE.match(subject)
    if match:
        kind = match["type"]
        if kind in HIDDEN_TYPES:
            return None
        group = GROUPS.get(kind, "other")
        scope = (match["scope"] or "").replace("-", " ").replace("/", " ").strip()
        text = match["text"].strip()
        text = f"{scope}: {text}" if scope and scope.lower() not in text.lower() else text
    else:
        group, text = "other", subject
    if not text:
        return None
    text = text[:1].upper() + text[1:]
    return {"group": group, "text": text[:MAX_TEXT_CHARS], "pr": int(pr[1]) if pr else None}


def changes_between(root: Path | None, previous: str, current: str) -> list[dict]:
    """The merged changes in `current` that `previous` lacks, newest first; the last few when `previous` is unknown."""
    if root is None or not current:
        return []
    known = (
        bool(previous)
        and COMMIT_RE.match(previous)
        and _git(root, "cat-file", "-e", previous) is not None
    )
    args = ["log", "--first-parent", "--pretty=%s"]
    args += [f"{previous}..{current}"] if known else ["-n", str(FIRST_DEPLOY_COMMITS), current]
    out = _git(root, *args)
    changes = [c for line in (out or "").splitlines() if (c := describe(line))]
    return changes[:MAX_CHANGES]
