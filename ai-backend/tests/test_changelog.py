from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.test_appsync import PIN, REPO, make_cfg  # noqa: F401
from utubot import appsync, buildinfo, changelog
from utubot.db import Database


def git(root: Path, *args: str) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, env=env
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "utubot.version").write_text("0.3\n")
    commit(root, "feat/cuts: add director's cuts (#10)")
    return root


def commit(root: Path, subject: str) -> str:
    (root / "f.txt").write_text(subject)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", subject)
    return git(root, "rev-parse", "HEAD")


def test_version_is_series_count_and_sha(repo):
    build = buildinfo.derive_version(repo)
    head = git(repo, "rev-parse", "HEAD")
    assert build.version == f"0.3.1+{head[:7]}"
    assert build.commit == head
    commit(repo, "fix/tv: stop the crash (#11)")
    assert buildinfo.derive_version(repo).version.startswith("0.3.2+")


def test_version_falls_back_without_git(tmp_path):
    assert buildinfo.derive_version(None, "9.9.9") == buildinfo.Build("9.9.9")
    assert buildinfo.derive_version(tmp_path / "nothing", "9.9.9").version == "9.9.9"


def test_describe_groups_and_hides():
    assert buildinfo.describe("feat/cuts: add skip (#4)") == {
        "group": "features",
        "text": "Cuts: add skip",
        "pr": 4,
    }
    assert buildinfo.describe("fix/tv: stop crash")["group"] == "fixes"
    assert buildinfo.describe("docs/readme: words") is None
    assert buildinfo.describe("Plain subject")["group"] == "other"


def test_deploy_recorded_once_with_changes_since_previous(repo):
    db = Database(":memory:")
    first = buildinfo.derive_version(repo)
    assert changelog.record_deploy(db, first, now=100.0)
    assert not changelog.record_deploy(db, first, now=200.0)  # restart: no duplicate
    commit(repo, "fix/tv: stop the crash (#11)")
    commit(repo, "docs/readme: words (#12)")
    second = buildinfo.derive_version(repo)
    assert changelog.record_deploy(db, second, now=300.0)
    entries = changelog.history(db, "backend")
    assert [e["version"] for e in entries] == [second.version, first.version]
    assert entries[0]["changes"] == [{"group": "fixes", "text": "Tv: stop the crash", "pr": 11}]
    assert entries[1]["changes"][0]["group"] == "features"
    assert entries[0]["commit"] == second.commit


def test_deploy_without_git_is_recorded_once(tmp_path):
    db = Database(":memory:")
    build = buildinfo.Build("0.2.0")
    assert changelog.record_deploy(db, build)
    assert not changelog.record_deploy(db, build)
    assert changelog.history(db, "backend")[0]["changes"] == []


async def test_changelog_endpoint(env):
    me = (await env.client.get("/v1/me")).json()
    assert me["backend_version"] == env.svc.build.version
    health = (await env.client.get("/v1/health")).json()
    assert health["version"] == env.svc.build.version
    backend = (await env.client.get("/v1/changelog?kind=backend")).json()
    assert backend["current"] == env.svc.build.version
    assert backend["entries"][0]["version"] == env.svc.build.version
    changelog.record_app_release(env.svc.db, "0.3.1", ["Faster"], 1000.0, overwrite=False)
    changelog.record_app_release(env.svc.db, "0.3.2", ["Fixed"], 2000.0, overwrite=False)
    app = (await env.client.get("/v1/changelog?kind=app")).json()
    assert [e["version"] for e in app["entries"]] == ["0.3.2", "0.3.1"]
    assert app["entries"][0]["changes"][0]["text"] == "Fixed"
    assert (await env.client.get("/v1/changelog?kind=nope")).status_code == 400


async def test_changelog_needs_a_token(env):
    from tests.conftest import anon_client

    async with anon_client(env) as anon:
        assert (await anon.get("/v1/changelog")).status_code == 401


def test_release_history_keeps_notes_and_time(tmp_path):
    cfg = make_cfg(tmp_path)
    releases = [
        {
            "tag_name": "utubot-v0.3.5",
            "published_at": "2026-11-25T10:00:00Z",
            "body": "- ignored body\n",
        },
        {
            "tag_name": "utubot-v0.3.4",
            "published_at": "2026-11-20T10:00:00Z",
            "body": "- Older note\n- Another\n",
        },
        {"tag_name": "other-v1.0.0", "published_at": "2026-11-01T10:00:00Z", "body": "- x"},
    ]
    picked = appsync.ReleaseInfo("0.3.5", 3005, ["Manifest note"], [], True)
    appsync.record_history(cfg, releases, False, picked)
    appsync.record_history(cfg, releases, False, picked)
    db = Database(cfg.db_path)
    entries = changelog.history(db, "app")
    assert [e["version"] for e in entries] == ["0.3.5", "0.3.4"]
    assert [c["text"] for c in entries[0]["changes"]] == ["Manifest note"]
    assert [c["text"] for c in entries[1]["changes"]] == ["Older note", "Another"]
    assert entries[0]["at"] == 1795600800.0
