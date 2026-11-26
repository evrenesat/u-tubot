#!/usr/bin/env python3
"""CI helpers for the u-tubot repository: classify changed files, check a pull request's parity box and decide
whether a CI run is green for a released commit.

    python3 scripts/utubot_ci_changes.py classify
    python3 scripts/utubot_ci_changes.py parity
    python3 scripts/utubot_ci_changes.py ci-green --runs-file RUNS --jobs-file JOBS --auto true --needed extension,backend

The `classify` and `parity` commands read the GitHub API and the environment; the functions below are pure over
file lists and JSON so their unit tests need no network.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

NON_APP = re.compile(
    r"^(ai-backend/|ai/|docs/|updates/|fastlane/|images/|assets/|scripts/|\.github/|extension/|[^/]+\.md$|LICENSE$|crowdin\.yml$)"
)
BACKEND = re.compile(
    r"^(ai-backend/|ai/|docs/|scripts/utubot_release\.py$|scripts/emulator_mock_backend\.py$|scripts/utubot_ci_changes\.py$|scripts/dev_install\.py$)"
)
PIPELINE = re.compile(
    r"^\.github/(workflows/utubot-ci\.yml$|workflows/utubot-parity\.yml$|workflows/utubot-extension-release\.yml$|actions/)"
)
EXTENSION = re.compile(r"^(extension/|ai/CONTRACT\.md$|scripts/emulator_mock_backend\.py$)")
UTUBOT_CODE = re.compile(r"^(common|smarttubetv)/(?:.*/)?utubot/")
PLAN = "ai/BROWSER_EXTENSION_PLAN.md"
CONTRACT = "ai/CONTRACT.md"
PARITY_BOX = re.compile(r"(?im)^\s*[-*]\s*\[[xX]\]\s*AI feature parity")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
REPO_ROOT = Path(__file__).resolve().parent.parent
EXTENSION_TAG = re.compile(r"^utubot-ext-v(\d+\.\d+\.\d+)$")


@dataclass(frozen=True)
class Classification:
    backend: bool
    app: bool
    release: bool
    extension: bool
    extension_release: bool


def classify_files(files: Iterable[str]) -> Classification:
    """Classify a pull request's or a range's changed files."""
    names = list(files)

    def has(pattern: re.Pattern[str]) -> bool:
        return any(pattern.search(name) for name in names)

    pipeline = has(PIPELINE)
    backend = has(BACKEND) or pipeline
    app = (any(not NON_APP.search(name) for name in names)) or pipeline
    extension = has(EXTENSION) or pipeline
    return Classification(backend=backend, app=app, release=False, extension=extension, extension_release=False)


def release_decision(push: bool, files_since_tag: list[str] | None, has_tag: bool) -> bool:
    """An APK release starts on a push to main that changed an app file since the newest utubot-v* tag."""
    if not push:
        return False
    if not has_tag:
        return True
    if files_since_tag is None:
        return True
    return any(not NON_APP.search(name) for name in files_since_tag)


def extension_release_decision(push: bool, version: str, tags: Iterable[str]) -> bool:
    """The extension releases only for a deliberate version bump that has no utubot-ext-v<version> tag yet."""
    if not push or not VERSION.match(version.strip()):
        return False
    return not any(EXTENSION_TAG.match(tag.strip()) and tag.strip() == f"utubot-ext-v{version.strip()}" for tag in tags)


def parity_fails(files: Iterable[str], body: str) -> bool:
    """The parity box is required when a pull request touches u-tubot AI code or the contract without the extension."""
    names = list(files)
    touches = any(UTUBOT_CODE.search(name) for name in names) or CONTRACT in names
    extension_side = any(name.startswith("extension/") for name in names) or PLAN in names
    return touches and not extension_side and not PARITY_BOX.search(body)


def ci_green(runs: object, jobs: object, *, auto: bool, needed: Iterable[str] = ("extension", "backend")) -> bool:
    """Pure rule of the APK workflow's ci_green, with the extension job in place of the app job.

    `runs` is the workflow-runs JSON (a list or its `.workflow_runs` wrapper); `jobs` is the jobs JSON of the
    dispatching run. A completed successful run is green; only an automatic release accepts the in-progress run
    whose needed jobs are green or skipped.
    """
    run_list = runs.get("workflow_runs", []) if isinstance(runs, dict) else runs
    if not isinstance(run_list, list):
        return False
    if any(run.get("status") == "completed" and run.get("conclusion") == "success" for run in run_list):
        return True
    if not auto:
        return False

    in_progress = next((run for run in run_list if run.get("status") == "in_progress"), None)
    if in_progress is None:
        return False

    job_list = jobs.get("jobs", []) if isinstance(jobs, dict) else jobs
    if not isinstance(job_list, list):
        return False
    wanted = set(needed)
    selected = [job for job in job_list if job.get("name") in wanted]
    if not selected or len({job.get("name") for job in selected}) != len(wanted):
        return False
    return all(job.get("conclusion") in ("success", "skipped") for job in selected)


def gh_json(args: list[str]) -> object:
    answer = subprocess.run(["gh", "api", *args], check=True, text=True, capture_output=True)
    return json.loads(answer.stdout)


def gh_lines(args: list[str]) -> list[str]:
    answer = subprocess.run(["gh", "api", *args], check=True, text=True, capture_output=True)
    return [line for line in answer.stdout.splitlines() if line.strip()]


def gh_lines_or_none(args: list[str]) -> list[str] | None:
    """The lines, or None when the GitHub API cannot answer: a listing failure runs everything, it never skips a job."""
    try:
        return gh_lines(args)
    except (subprocess.CalledProcessError, OSError):
        return None


def changed_files(event: str, sha: str, before: str, pr_number: str) -> list[str] | None:
    repo = os.environ["REPO"]
    zero = "0" * 40
    if event == "pull_request":
        return gh_lines_or_none(["--paginate", f"repos/{repo}/pulls/{pr_number}/files", "--jq", '.[] | .filename, (.previous_filename // empty)'])
    if before != zero:
        return gh_lines_or_none(["--paginate", f"repos/{repo}/compare/{before}...{sha}", "--jq", '.files[] | .filename, (.previous_filename // empty)'])
    return None


def classify_or_everything(files: list[str] | None) -> Classification:
    """An unknown file list runs both test jobs, like the inline script's defaults."""
    if files is None:
        return Classification(backend=True, app=True, release=False, extension=True, extension_release=False)
    return classify_files(files)


def extension_tags() -> list[str] | None:
    repo = os.environ["REPO"]
    refs = gh_lines_or_none(["--paginate", f"repos/{repo}/git/matching-refs/tags/utubot-ext-v", "--jq", ".[].ref"])
    return None if refs is None else [ref.removeprefix("refs/tags/") for ref in refs]


def apk_tags() -> list[str] | None:
    repo = os.environ["REPO"]
    refs = gh_lines_or_none(["--paginate", f"repos/{repo}/git/matching-refs/tags/utubot-v", "--jq", ".[].ref"])
    if refs is None:
        return None
    tags = [ref.removeprefix("refs/tags/utubot-v") for ref in refs]
    return [tag for tag in tags if VERSION.match(tag)]


def classify_command(args: argparse.Namespace) -> int:
    event = os.environ.get("EVENT_NAME", "")
    sha = os.environ.get("SHA", "")
    before = os.environ.get("BEFORE", "")
    pr_number = os.environ.get("PR_NUMBER", "")
    files = args.files.read().splitlines() if args.files else changed_files(event, sha, before, pr_number)
    result = classify_or_everything(files)

    push = event == "push"
    release = False
    if push:
        tags = apk_tags()
        newest = max(tags, key=lambda value: tuple(int(part) for part in value.split("."))) if tags else None
        since = None
        if newest:
            since = gh_lines_or_none(["--paginate", f"repos/{os.environ['REPO']}/compare/utubot-v{newest}...{sha}", "--jq", '.files[] | .filename, (.previous_filename // empty)'])
        release = release_decision(push, since, bool(newest))
        if release:
            result = Classification(backend=result.backend, app=True, release=True, extension=result.extension, extension_release=False)

    extension_release = False
    if push:
        # The workflow runs this from the repository root; tests run it from ai-backend, so anchor the default here.
        version_file = Path(args.version_file) if args.version_file else REPO_ROOT / "extension" / "version"
        version = version_file.read_text().strip() if version_file.is_file() else ""
        # A failed tag listing must not lose a version bump either: treat it as "no tag yet".
        tags = extension_tags()
        extension_release = extension_release_decision(push, version, tags if tags is not None else [])

    result = Classification(result.backend, result.app, release, result.extension, extension_release)
    lines = [f"{key}={str(value).lower()}" for key, value in result.__dict__.items()]
    print("\n".join(lines))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("\n".join(lines) + "\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write("\n".join(lines) + "\n")
    return 0


def parity_command(args: argparse.Namespace) -> int:
    event = os.environ.get("EVENT_NAME", "pull_request")
    files = args.files.read().splitlines() if args.files else changed_files(
        event, os.environ.get("SHA", ""), os.environ.get("BEFORE", ""), os.environ.get("PR_NUMBER", "")
    )
    if files is None:
        print("AI feature parity: the changed files could not be listed; the parity check needs the list, so it fails closed", file=sys.stderr)
        return 1
    body = os.environ.get("PR_BODY", "")
    if parity_fails(files, body):
        print("AI feature parity: the pull request touches u-tubot AI code or the contract, changes nothing under extension/ and not the plan, and its parity box is not ticked", file=sys.stderr)
        return 1
    print("AI feature parity: ok")
    return 0


def ci_green_command(args: argparse.Namespace) -> int:
    runs = json.loads(args.runs.read() if args.runs else "[]")
    jobs = json.loads(args.jobs.read() if args.jobs else "[]")
    needed = [name.strip() for name in args.needed.split(",") if name.strip()]
    return 0 if ci_green(runs, jobs, auto=args.auto, needed=needed) else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    classify = commands.add_parser("classify", help="classify the changed files of a pull request or a push")
    classify.add_argument("--files", type=argparse.FileType("r"), help="a file list instead of the GitHub API")
    classify.add_argument("--version-file", help="the extension version file (default extension/version)")
    classify.set_defaults(run=classify_command)

    parity = commands.add_parser("parity", help="check the AI feature parity box")
    parity.add_argument("--files", type=argparse.FileType("r"), help="a file list instead of the GitHub API")
    parity.set_defaults(run=parity_command)

    green = commands.add_parser("ci-green", help="decide whether a commit's CI run is green")
    green.add_argument("--runs", type=argparse.FileType("r"), required=True, help="workflow-runs JSON")
    green.add_argument("--jobs", type=argparse.FileType("r"), required=True, help="jobs JSON of the dispatching run")
    green.add_argument("--auto", type=lambda value: value.lower() == "true", default=False)
    green.add_argument("--needed", default="extension,backend")
    green.set_defaults(run=ci_green_command)

    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
