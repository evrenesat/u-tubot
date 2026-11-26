from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from tests.test_appsync import PIN, REPO, make_cfg  # noqa: F401
from utubot import appsync, buildinfo, changelog, releasenotes
from utubot.db import Database


def git(root: Path, *args: str, date: str | None = None) -> str:
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.com",
        "PATH": "/usr/bin:/bin:/usr/local/bin",
    }
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    done = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, env=env
    )
    return done.stdout.strip()


FIRST_DATE = "2026-11-26T14:30:00Z"
LATER_DATE = "2026-11-27T09:05:00Z"


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "utubot.version").write_text("0.3\n")
    commit(root, "feat/cuts: add director's cuts (#10)", date=FIRST_DATE)
    return root


def commit(root: Path, subject: str, date: str | None = None) -> str:
    (root / "f.txt").write_text(subject)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", subject, date=date)
    return git(root, "rev-parse", "HEAD")


def test_version_is_series_commit_time_and_sha(repo):
    build = buildinfo.derive_version(repo)
    head = git(repo, "rev-parse", "HEAD")
    assert build.version == f"0.3.202611261430+{head[:7]}"
    assert build.commit == head
    commit(repo, "fix/tv: stop the crash (#11)", date=LATER_DATE)
    later = buildinfo.derive_version(repo).version
    assert later.startswith("0.3.202611270905+")
    assert later > build.version


def test_version_uses_utc_for_the_commit_time(repo):
    commit(repo, "fix/tv: offset (#12)", date="2026-11-27T00:30:00+02:00")
    assert buildinfo.derive_version(repo).version.startswith("0.3.202611262230+")


def test_shallow_clone_reports_the_same_version_as_the_full_clone(repo, tmp_path):
    for day in range(2, 6):
        commit(repo, f"fix/tv: step {day} (#{day})", date=f"2026-11-{day:02d}T12:00:00Z")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(shallow)],
        check=True,
        capture_output=True,
    )
    assert git(shallow, "rev-list", "--count", "HEAD") == "1"
    head = git(repo, "rev-parse", "HEAD")
    cut = buildinfo.derive_version(shallow)
    assert cut.version == f"0.3.202611051200+{head[:7]}"
    assert cut.version == buildinfo.derive_version(repo).version


def test_version_falls_back_without_git(tmp_path):
    assert buildinfo.derive_version(None, "9.9.9") == buildinfo.Build("9.9.9")
    assert buildinfo.derive_version(tmp_path / "nothing", "9.9.9").version == "9.9.9"


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
    assert entries[0]["changes"] == [
        {"group": "fixes", "text": "Fixed: stop the crash (TV)", "pr": None}
    ]
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
    changelog.record_app_release(env.svc.db, "0.3.1", ["New: faster"], 1000.0, overwrite=False)
    changelog.record_app_release(env.svc.db, "0.3.2", ["Fixed: it"], 2000.0, overwrite=False)
    app = (await env.client.get("/v1/changelog?kind=app")).json()
    assert [e["version"] for e in app["entries"]] == ["0.3.2", "0.3.1"]
    assert app["entries"][0]["changes"][0]["text"] == "Fixed: it"
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
    assert [c["text"] for c in entries[0]["changes"]] == ["Changed: Manifest note"]
    assert [c["text"] for c in entries[1]["changes"]] == ["Changed: Older note", "Changed: Another"]
    assert entries[0]["at"] == 1795600800.0


def test_deploy_with_only_internal_commits_says_maintenance_only(repo):
    db = Database(":memory:")
    changelog.record_deploy(db, buildinfo.derive_version(repo), now=1.0)
    commit(repo, "docs/readme: words (#12)")
    commit(repo, "ci/release: pin (#13)")
    changelog.record_deploy(db, buildinfo.derive_version(repo), now=2.0)
    assert [c["text"] for c in changelog.history(db, "backend")[0]["changes"]] == [
        "Maintenance only"
    ]


def _store(db, kind, version, at, sha, texts):
    changes = [{"group": "other", "text": t, "pr": None} for t in texts]
    db.execute(
        "INSERT INTO changelog(kind, version, at, commit_sha, changes) VALUES(?, ?, ?, ?, ?)",
        [kind, version, at, sha, json.dumps(changes)],
    )


def test_rebuild_shortens_stored_entries_and_is_idempotent(repo):
    db = Database(":memory:")
    wall = (
        "AI verdicts and summaries that are ready survive a restart of the app: "
        + "the TV keeps them " * 20
    )
    _store(db, "app", "0.3.1", 1.0, "", [wall, "feat/cuts: skip reads (#3)", "docs/x: words (#4)"])
    _store(db, "app", "0.3.2", 2.0, "", [f"fix/tv: thing {n}" for n in range(9)])
    first = buildinfo.derive_version(repo)
    commit(repo, "feat/captions: speaker labels (#21)")
    commit(repo, "test/captions: more cases (#22)")
    second = buildinfo.derive_version(repo)
    _store(db, "backend", first.version, 3.0, first.commit, ["Old long wall text " * 10])
    _store(
        db,
        "backend",
        second.version,
        4.0,
        second.commit,
        ["Captions: speaker labels", "Captions: more cases"],
    )
    assert changelog.rebuild(db, repo) == 4
    snapshot = [changelog.history(db, k) for k in changelog.KINDS]
    assert changelog.rebuild(db, repo) == 0
    assert [changelog.history(db, k) for k in changelog.KINDS] == snapshot
    app = {e["version"]: [c["text"] for c in e["changes"]] for e in changelog.history(db, "app")}
    assert app["0.3.1"] == [
        "Changed: AI verdicts and summaries that are ready survive a restart of the app",
        "New: skip reads (cuts)",
    ]
    assert len(app["0.3.2"]) == 7 and app["0.3.2"][-1] == "+ 3 smaller fixes"
    backend = changelog.history(db, "backend")
    assert [c["text"] for c in backend[0]["changes"]] == ["New: speaker labels (captions)"]
    assert all(
        len(c["text"]) <= releasenotes.MAX_LINE_CHARS
        for e in snapshot[0] + snapshot[1]
        for c in e["changes"]
    )


async def test_polish_falls_back_on_error_and_accepts_good_rewrites():
    from utubot.config import LLMTask

    class Boom:
        async def chat(self, *a, **k):
            raise RuntimeError("down")

    class Slow:
        async def chat(self, *a, **k):
            await asyncio.sleep(5)

    class Plain:
        def __init__(self, text):
            self.text = text

        async def chat(self, *a, **k):
            return self.text

    task = LLMTask(model="fast")
    lines = ["Fixed: stop the crash (TV)", "New: skip reads (cuts)"]
    assert await changelog.polish(Boom(), task, lines) == lines
    assert await changelog.polish(Slow(), task, lines, timeout_s=0.05) == lines
    assert (
        await changelog.polish(Plain("Fixed: the TV no longer crashes"), task, lines) == lines
    )  # wrong count
    good = "Fixed: the TV no longer crashes on resume\nNew: skip sponsor reads"
    assert await changelog.polish(Plain(good), task, lines) == good.splitlines()
    assert await changelog.polish(Plain("blah\nblah"), task, lines) == lines
