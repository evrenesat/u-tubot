"""Short, plain release notes from PR titles (squash-merge subjects).

Standard library only: `scripts/utubot_release.py` loads this file by path, so the app releases and the backend deploys follow
one set of rules.

A version gets at most MAX_LINES lines, each at most MAX_LINE_CHARS long and starting with "New:", "Fixed:" or "Changed:",
then "+ N smaller fixes". Internal work (docs, tests, CI, refactors, plans, devlog, parity/contract text, dependency bumps) is
skipped; a version with nothing left says "Maintenance only" (backend) or has no lines (app).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_LINES = 6
MAX_LINE_CHARS = 90
ELLIPSIS = "..."
MIN_HEAD_CHARS = 12
MAINTENANCE_ONLY = "Maintenance only"

NEW, FIXED, CHANGED = "New", "Fixed", "Changed"
GROUP_OF_LABEL = {NEW: "features", FIXED: "fixes", CHANGED: "other"}

PR_SUFFIX_RE = re.compile(r"\s*\(#(\d+)\)\s*$")
SUBJECT_RE = re.compile(r"^(?P<type>[A-Za-z]+)(?:/(?P<scope>[^:]+))?:\s*(?P<text>.+)$")
LABELLED_RE = re.compile(r"^(New|Fixed|Changed): \S")
MORE_RE = re.compile(r"^\+ \d+ smaller fixes?$")
BULLET_PREFIX_RE = re.compile(r"^\s*[-*]\s+")

# Allow/deny table. A subject is user-visible unless one of the deny rules matches.
LABEL_OF_TYPE = {
    "feat": NEW,
    "feature": NEW,
    "add": NEW,
    "fix": FIXED,
    "bugfix": FIXED,
    "hotfix": FIXED,
}
DENY_TYPES = frozenset(
    {
        "docs", "doc", "test", "tests", "ci", "chore", "refactor", "style", "build", "perf",
        "deps", "plan", "plans", "devlog", "parity", "contract", "release", "revert", "format", "lint",
    }
)  # fmt: skip
DENY_SCOPES = frozenset(
    {
        "docs", "doc", "test", "tests", "ci", "plan", "plans", "devlog", "parity", "contract",
        "deps", "release", "workflow", "workflows", "lint", "format", "changelog", "dev",
    }
)  # fmt: skip
DENY_TEXT_RE = re.compile(
    r"\b(devlog|changelog|parity|contract|bump(?:s|ed)?|dependenc\w+|dependabot|refactor\w*|"
    r"formatting|reformat\w*|lint\w*|ruff|plans?|workflows?|ci|unit tests?|tests?)\b",
    re.IGNORECASE,
)
# A change whose files are all under these is internal, whatever its title says.
INTERNAL_PATHS = (
    "docs/", "ai/", "plans/", ".github/", "scripts/", "assets/", "ai-backend/tests/", "ai-backend/deploy/",
    "extension/tests/", "DEVLOG", "ai-backend/DEVLOG", "CHANGELOG.md", "AGENTS.md", "README.md",
)  # fmt: skip
FIX_WORDS_RE = re.compile(r"\b(fix|fixes|fixed|no longer|stops?|crash\w*|fail\w*)\b", re.IGNORECASE)
NEW_WORDS_RE = re.compile(r"^(add|adds|new|support|introduce\w*)\b", re.IGNORECASE)
SCOPE_NAMES = {"tv": "TV", "web": "web UI", "ui": "web UI", "webui": "web UI"}


def _clip(text: str, room: int) -> str:
    if len(text) <= room:
        return text
    cut = text[: max(room - len(ELLIPSIS), 1)]
    cut = cut.rsplit(" ", 1)[0] if " " in cut else cut
    return cut.rstrip(" ,;:-") + ELLIPSIS


def _line(label: str, text: str, scope: str = "") -> str:
    text = " ".join(text.split()).rstrip(".")
    suffix = ""
    if scope and scope.lower() not in text.lower():
        suffix = f" ({scope})"
    head = f"{label}: "
    return head + _clip(text, MAX_LINE_CHARS - len(head) - len(suffix)) + suffix


def _paths_internal(paths: Iterable[str] | None) -> bool:
    if paths is None:
        return False
    names = [p for p in paths if p]
    return bool(names) and all(p.startswith(INTERNAL_PATHS) for p in names)


def strip_pr(subject: str) -> tuple[str, int | None]:
    pr = PR_SUFFIX_RE.search(subject)
    return PR_SUFFIX_RE.sub("", subject).strip(), int(pr[1]) if pr else None


def _prose_line(text: str) -> str | None:
    """A line written as prose (an old CHANGELOG bullet): its first sentence, labelled."""
    head, sep, tail = text.partition(": ")
    if sep and len(head) < MIN_HEAD_CHARS and tail:
        text = tail
    first = re.split(r"(?<=[a-z0-9)])\.\s|: | \(", text, maxsplit=1)[0]
    first = first if len(first) >= MIN_HEAD_CHARS else text
    if DENY_TEXT_RE.search(first):
        return None
    label = FIXED if FIX_WORDS_RE.search(first) else NEW if NEW_WORDS_RE.match(first) else CHANGED
    return _line(label, first)


def to_line(subject: str, paths: Iterable[str] | None = None) -> str | None:
    """One PR title (or an older note line) as a short user-facing line; None when a user would not notice it."""
    text, _pr = strip_pr(BULLET_PREFIX_RE.sub("", subject.strip()))
    if not text or MORE_RE.match(text) or text == MAINTENANCE_ONLY:
        return None
    if _paths_internal(paths):
        return None
    if LABELLED_RE.match(text) and len(text) <= MAX_LINE_CHARS:
        return text
    match = SUBJECT_RE.match(text)
    if match and match["type"].lower() in {
        *LABEL_OF_TYPE,
        *DENY_TYPES,
        "change",
        "update",
        "improve",
    }:
        kind = match["type"].lower()
        scope = (match["scope"] or "").strip().lower().replace("/", " ").replace("-", " ")
        if kind in DENY_TYPES or scope.split(" ")[0] in DENY_SCOPES:
            return None
        body = match["text"].strip()
        if DENY_TEXT_RE.search(body):
            return None
        return _line(LABEL_OF_TYPE.get(kind, CHANGED), body, SCOPE_NAMES.get(scope, scope))
    if len(text) > MAX_LINE_CHARS or match:
        return _prose_line(text)
    if DENY_TEXT_RE.search(text):
        return None
    label = FIXED if FIX_WORDS_RE.search(text) else NEW if NEW_WORDS_RE.match(text) else CHANGED
    return _line(label, text)


def cap(lines: Iterable[str]) -> list[str]:
    """Drop duplicates, keep MAX_LINES lines, count the rest."""
    unique = list(dict.fromkeys(lines))
    if len(unique) <= MAX_LINES:
        return unique
    rest = len(unique) - MAX_LINES
    return [*unique[:MAX_LINES], f"+ {rest} smaller {'fix' if rest == 1 else 'fixes'}"]


def summarize(subjects: Iterable[tuple[str, Iterable[str] | None]] | Iterable[str]) -> list[str]:
    """Short lines for a list of PR titles (each optionally paired with its changed paths), newest first."""
    lines: list[str] = []
    for item in subjects:
        subject, paths = (item, None) if isinstance(item, str) else item
        line = to_line(subject, paths)
        if line:
            lines.append(line)
    return cap(lines)


def normalize(lines: Iterable[str]) -> list[str]:
    """Stored note lines in the short form (idempotent: short lines stay as they are)."""
    lines = list(lines)
    kept = [line for line in lines if not MORE_RE.match(line.strip())]
    previous_more = [line.strip() for line in lines if MORE_RE.match(line.strip())]
    result = summarize(kept)
    if previous_more and len(result) <= MAX_LINES:
        result.append(previous_more[0])
    return result


def group_of(line: str) -> str:
    return GROUP_OF_LABEL.get(line.split(":", 1)[0], "other")


def as_changes(lines: Iterable[str], *, empty_means_maintenance: bool = False) -> list[dict]:
    """The stored shape of note lines: {"group", "text", "pr"}."""
    lines = list(lines) or ([MAINTENANCE_ONLY] if empty_means_maintenance else [])
    return [{"group": group_of(line), "text": line, "pr": None} for line in lines]
