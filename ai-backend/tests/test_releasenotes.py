from __future__ import annotations

import pytest

from utubot import releasenotes as rn

TITLES = [
    ("feat/cuts: add skip to the next scene (#4)", "New: add skip to the next scene (cuts)"),
    (
        "fix/tv: stop the crash when opening settings (#11)",
        "Fixed: stop the crash when opening settings (TV)",
    ),
    (
        "fix/web: summaries no longer vanish on reload (#12)",
        "Fixed: summaries no longer vanish on reload (web UI)",
    ),
    ("feat/captions: speaker labels (#13)", "New: speaker labels (captions)"),
    (
        "feat/summaries: show the summary in the TV panel (#14)",
        "New: show the summary in the TV panel (summaries)",
    ),
    ("Plain subject here (#2)", "Changed: Plain subject here"),
]
INTERNAL = [
    "docs/parity: name parity matrix rows by stable id (#194)",
    "test/cuts: more cases (#1)",
    "ci/release: pin the actions (#2)",
    "refactor/cuts: split the service (#3)",
    "chore/deps: bump httpx (#5)",
    "docs: plan for the next step (#6)",
    "feat/app: devlog entry for checkpoint 3 (#7)",
    "style/format: ruff format (#8)",
    "fix/contract: wording of the contract text (#9)",
]


@pytest.mark.parametrize(("title", "line"), TITLES)
def test_title_becomes_one_short_line(title, line):
    assert rn.to_line(title) == line


@pytest.mark.parametrize("title", INTERNAL)
def test_internal_changes_are_skipped(title):
    assert rn.to_line(title) is None


def test_changes_only_under_internal_paths_are_skipped():
    assert rn.to_line("fix/cuts: tidy", ["docs/a.md", "ai/b.md"]) is None
    assert rn.to_line("fix/cuts: tidy", ["docs/a.md", "ai-backend/src/utubot/cuts.py"])


def test_long_titles_are_clipped():
    line = rn.to_line("feat/captions: " + "very long words " * 20)
    assert len(line) <= rn.MAX_LINE_CHARS and line.endswith("...") or line.endswith(")")
    assert len(line) <= rn.MAX_LINE_CHARS


def test_at_most_six_lines_then_a_count():
    lines = rn.summarize([f"fix/tv: problem number {n}" for n in range(10)])
    assert len(lines) == 7 and lines[-1] == "+ 4 smaller fixes"
    assert rn.summarize([f"fix/tv: problem number {n}" for n in range(7)])[-1] == "+ 1 smaller fix"
    assert all(len(line) <= rn.MAX_LINE_CHARS for line in lines)


def test_duplicates_collapse_and_empty_stays_empty():
    assert rn.summarize(["fix/tv: same (#1)", "fix/tv: same (#2)"]) == ["Fixed: same (TV)"]
    assert rn.summarize(INTERNAL) == []


def test_normalize_is_idempotent_and_shortens_prose():
    wall = (
        "Retry really tries again: besides asking the backend again, it now makes the backend forget a failure. "
        * 3
    )
    once = rn.normalize([f"- {wall}", "feat/cuts: skip (#3)", "docs/x: y"])
    assert once == ["Changed: Retry really tries again", "New: skip (cuts)"]
    assert rn.normalize(once) == once
    capped = rn.summarize([f"fix/tv: problem number {n}" for n in range(10)])
    assert rn.normalize(capped) == capped
