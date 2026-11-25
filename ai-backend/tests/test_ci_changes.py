from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from utubot_ci_changes import (  # noqa: E402
    Classification,
    ci_green,
    classify_files,
    classify_or_everything,
    extension_release_decision,
    parity_fails,
    release_decision,
)

REPO = Path(__file__).resolve().parents[2]


def test_extension_only_is_an_extension_change_and_not_an_app_change():
    assert classify_files(["extension/src/background/main.js"]) == Classification(
        backend=False, app=False, release=False, extension=True, extension_release=False
    )


def test_backend_only_keeps_the_old_answer():
    assert classify_files(["ai-backend/src/utubot/app.py"]) == Classification(
        backend=True, app=False, release=False, extension=False, extension_release=False
    )


def test_app_file_keeps_the_old_answer():
    assert classify_files(
        ["smarttubetv/src/main/java/com/liskovsoft/smartyoutubetv2/tv/MainActivity.java"]
    ) == Classification(
        backend=False, app=True, release=False, extension=False, extension_release=False
    )


def test_pipeline_file_runs_backend_app_and_extension_and_never_releases():
    assert classify_files([".github/workflows/utubot-ci.yml"]) == Classification(
        backend=True, app=True, release=False, extension=True, extension_release=False
    )


def test_docs_only_keeps_the_old_backend_answer():
    assert classify_files(["docs/development.md"]) == Classification(
        backend=True, app=False, release=False, extension=False, extension_release=False
    )


def test_contract_change_runs_backend_and_extension():
    assert classify_files(["ai/CONTRACT.md"]) == Classification(
        backend=True, app=False, release=False, extension=True, extension_release=False
    )


def test_mock_backend_change_runs_backend_and_extension():
    assert classify_files(["scripts/emulator_mock_backend.py"]) == Classification(
        backend=True, app=False, release=False, extension=True, extension_release=False
    )


def test_classifier_command_prints_the_outputs(tmp_path):
    files = tmp_path / "files.txt"
    files.write_text("extension/src/content/main.js\n", encoding="utf-8")
    env = {
        "EVENT_NAME": "pull_request",
        "PR_NUMBER": "1",
        "SHA": "a" * 40,
        "REPO": "evrenesat/u-tubot",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/utubot_ci_changes.py"),
            "classify",
            "--files",
            str(files),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.stdout.splitlines() == [
        "backend=false",
        "app=false",
        "release=false",
        "extension=true",
        "extension_release=false",
    ]


def test_parity_fails_a_contract_change_without_the_box():
    assert parity_fails(["ai/CONTRACT.md"], "a description without the box") is True


def test_parity_passes_with_the_box():
    assert (
        parity_fails(["ai/CONTRACT.md"], "- [x] AI feature parity: this changed both clients")
        is False
    )


def test_parity_passes_with_an_extension_change():
    assert (
        parity_fails(
            ["ai/CONTRACT.md", "extension/src/shared/api.js"], "a description without the box"
        )
        is False
    )


def test_parity_passes_with_the_plan():
    assert parity_fails(["ai/BROWSER_EXTENSION_PLAN.md"], "a description without the box") is False


def test_parity_passes_an_unrelated_change_without_the_box():
    assert parity_fails(["docs/development.md"], "a description without the box") is False


def test_parity_fails_tv_utubot_code_without_the_box():
    assert (
        parity_fails(
            ["common/src/main/java/com/liskovsoft/smartyoutubetv2/common/utubot/UtubotMenu.java"],
            "no box",
        )
        is True
    )


def test_parity_matches_utubot_code_at_the_module_root():
    assert parity_fails(["common/utubot/UtubotMenu.java"], "no box") is True
    assert parity_fails(["smarttubetv/utubot/UtubotMenu.java"], "no box") is True


def test_parity_command_reads_the_body_from_the_environment_without_executing_it(tmp_path):
    files = tmp_path / "files.txt"
    files.write_text("ai/CONTRACT.md\n", encoding="utf-8")
    marker = tmp_path / "should-not-exist"
    env = {
        "EVENT_NAME": "pull_request",
        "REPO": "evrenesat/u-tubot",
        "PR_BODY": f"- [x] AI feature parity: $(touch {marker}) `touch {marker}`",
    }
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/utubot_ci_changes.py"),
            "parity",
            "--files",
            str(files),
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert not marker.exists()


def test_release_only_from_an_app_change_on_a_push():
    assert release_decision(False, ["smarttubetv/src/main/java/Main.java"], True) is False
    assert release_decision(True, ["extension/src/content/main.js"], True) is False
    assert release_decision(True, ["smarttubetv/src/main/java/Main.java"], True) is True
    assert release_decision(True, None, False) is True


def test_extension_release_only_for_an_untagged_version_on_a_push():
    assert extension_release_decision(True, "0.1.0", ["utubot-ext-v0.0.9"]) is True
    assert extension_release_decision(True, "0.1.0", ["utubot-ext-v0.1.0"]) is False
    assert extension_release_decision(True, "0.1.0", ["utubot-v0.3.0"]) is True
    assert extension_release_decision(False, "0.1.0", []) is False
    assert extension_release_decision(True, "not-a-version", []) is False


GREEN_RUN = {"id": 1, "status": "completed", "conclusion": "success"}
OPEN_RUN = {"id": 2, "status": "in_progress", "conclusion": None}


def test_ci_green_accepts_a_completed_successful_run():
    assert ci_green([GREEN_RUN], [], auto=False) is True


def test_ci_green_accepts_the_dispatching_run_with_the_needed_jobs_green():
    jobs = [
        {"name": "changes", "conclusion": "success"},
        {"name": "extension", "conclusion": "success"},
        {"name": "backend", "conclusion": "skipped"},
    ]
    assert ci_green([OPEN_RUN], jobs, auto=True) is True


def test_ci_green_refuses_a_red_or_missing_needed_job():
    red = [
        {"name": "extension", "conclusion": "failure"},
        {"name": "backend", "conclusion": "success"},
    ]
    missing = [{"name": "extension", "conclusion": "success"}]
    assert ci_green([OPEN_RUN], red, auto=True) is False
    assert ci_green([OPEN_RUN], missing, auto=True) is False
    assert ci_green([], [], auto=True) is False


def test_ci_green_refuses_the_in_progress_run_for_a_manual_release():
    jobs = [
        {"name": "extension", "conclusion": "success"},
        {"name": "backend", "conclusion": "success"},
    ]
    assert ci_green([OPEN_RUN], jobs, auto=False) is False


def test_ci_green_command_reads_json_files(tmp_path):
    runs = tmp_path / "runs.json"
    jobs = tmp_path / "jobs.json"
    runs.write_text(json.dumps({"workflow_runs": [GREEN_RUN]}), encoding="utf-8")
    jobs.write_text(json.dumps({"jobs": []}), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/utubot_ci_changes.py"),
            "ci-green",
            "--runs",
            str(runs),
            "--jobs",
            str(jobs),
            "--auto",
            "false",
        ],
        check=True,
    )
    assert result.returncode == 0


def test_an_unknown_file_list_runs_every_job_and_never_releases():
    assert classify_or_everything(None) == Classification(
        backend=True, app=True, release=False, extension=True, extension_release=False
    )
    assert classify_or_everything(["extension/src/content/main.js"]) == classify_files(
        ["extension/src/content/main.js"]
    )


FAILING_GH = """#!/bin/sh
exit 1
"""


def classify_without_the_api(
    tmp_path,
    event: str,
    *,
    gh_script: str = FAILING_GH,
    sha: str = "a" * 40,
    before: str = "b" * 40,
) -> list[str]:
    """Run `classify` with a gh that cannot list anything, as during an API outage."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(gh_script, encoding="utf-8")
    gh.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "EVENT_NAME": event,
        "PR_NUMBER": "7",
        "BEFORE": before,
        "SHA": sha,
        "REPO": "evrenesat/u-tubot",
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary"),
    }
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/utubot_ci_changes.py"), "classify"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert (tmp_path / "output").read_text(encoding="utf-8").splitlines() == lines
    return lines


def test_a_failed_listing_on_a_pull_request_runs_everything(tmp_path):
    assert classify_without_the_api(tmp_path, "pull_request") == [
        "backend=true",
        "app=true",
        "release=false",
        "extension=true",
        "extension_release=false",
    ]


def test_a_failed_listing_on_a_push_still_decides_the_release(tmp_path):
    # No tag listing either: the push may be a release, and a lost release breaks the update chain.
    assert classify_without_the_api(tmp_path, "push") == [
        "backend=true",
        "app=true",
        "release=true",
        "extension=true",
        "extension_release=true",
    ]


TAGS_ONLY_GH = """#!/bin/sh
case "$*" in
  *matching-refs*) printf 'refs/tags/utubot-v0.9.0\\n'; exit 0 ;;
esac
exit 1
"""


def test_a_failed_listing_after_a_tag_still_releases(tmp_path):
    # The tags answer, the compare does not: the app files since the tag are unknown, so the push releases.
    assert classify_without_the_api(tmp_path, "push", gh_script=TAGS_ONLY_GH) == [
        "backend=true",
        "app=true",
        "release=true",
        "extension=true",
        "extension_release=true",
    ]


def test_a_failed_listing_fails_the_parity_check_closed(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAILING_GH, encoding="utf-8")
    gh.chmod(0o755)
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts/utubot_ci_changes.py"), "parity"],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "EVENT_NAME": "pull_request",
            "PR_NUMBER": "7",
            "REPO": "evrenesat/u-tubot",
            "PR_BODY": "- [x] AI feature parity: nothing to say",
        },
    )
    assert result.returncode == 1
    assert "could not be listed" in result.stderr
