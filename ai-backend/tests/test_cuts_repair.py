"""Repair of the long-video cuts that kept almost the whole video (#125)."""

from __future__ import annotations

import time

import pytest

from tests.test_cuts_api import VID, set_transcript, wait_ready
from utubot.cli import main
from utubot.config import LLMTask, load_config
from utubot.cuts import CUT_BUILD_VERSION
from utubot.db import Database


@pytest.fixture
async def repair_env(env):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.cuts.poll_s = 0.02
    env.cfg.cuts.transcript_wait_s = 60.0
    env.cfg.cuts.default_wait_ms = 0
    env.cfg.captions.job_poll_s = 0.02
    env.cfg.cuts.repair_on_start = False
    return env


def add_old_cut(env, **kwargs) -> str:
    return insert_old_cut(env.svc.db, **kwargs)


def insert_old_cut(
    db: Database,
    *,
    key: str,
    preset: str | None = "cut-demo",
    prompt: str | None = None,
    duration_s: float = 6000.0,
    kept_s: float = 5940.0,
    algo_version: int = 0,
    user: str = "owner",
    state: str = "ready",
) -> str:
    now = time.time()
    doc = {
        "version": 1,
        "video_id": VID,
        "transcript_hash": "old",
        "duration_ms": int(duration_s * 1000),
        "label": "Old cut",
        "summary": "Kept almost all of it.",
        "parts": [{"label": "All", "start_ms": 0, "end_ms": int(kept_s * 1000)}],
        "skip_ranges_ms": [[int(kept_s * 1000), int(duration_s * 1000)]]
        if kept_s < duration_s
        else [],
        "kept_ms": int(kept_s * 1000),
        "kept_s": kept_s,
        "target_s": None,
        "source": "preset" if preset else "prompt",
        "preset_id": preset,
        "model": "cutmodel",
        "built_at": now,
    }
    import json

    db.execute(
        "INSERT OR REPLACE INTO cuts(cache_key,video_id,version,preset_id,prompt,model,"
        "transcript_hash,json,duration_s,kept_s,created_at,algo_version)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            key,
            VID,
            f"cut:old-{key}",
            preset,
            prompt,
            "cutmodel",
            "old",
            json.dumps(doc),
            duration_s,
            kept_s,
            now,
            algo_version,
        ],
    )
    request_id = f"old-{key}"[:12]
    db.execute(
        "INSERT OR REPLACE INTO cut_requests(id,user,video_id,source,preset_id,prompt,state,"
        "cut_key,created_at,updated_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [request_id, user, VID, "API token", preset, prompt, state, key, now, now, now],
    )
    return request_id


class TestCutRepair:
    def test_dry_run_reports_a_near_full_no_target_cut(self, repair_env):
        request_id = add_old_cut(repair_env, key="bad")
        items = repair_env.svc.cuts.repair_near_full(dry_run=True)
        assert len(items) == 1
        item = items[0]
        assert item["cache_key"] == "bad" and item["old_share"] == pytest.approx(0.99)
        assert [r["user"] for r in item["requests"]] == ["owner"]
        assert request_id in [r["id"] for r in repair_env.svc.cuts.queue("owner")]
        # Nothing was changed.
        assert repair_env.svc.db.one("SELECT * FROM cuts WHERE cache_key='bad'")

    def test_a_targeted_cut_a_small_keep_and_a_current_build_are_left_alone(self, repair_env):
        add_old_cut(repair_env, key="highlight", preset="cut-highlights-5", kept_s=5940.0)
        add_old_cut(repair_env, key="small", preset="cut-demo", kept_s=3000.0)
        add_old_cut(repair_env, key="current", preset="cut-demo", algo_version=CUT_BUILD_VERSION)
        add_old_cut(
            repair_env,
            key="typed",
            preset=None,
            prompt="make it half as long",
            kept_s=5940.0,
        )
        assert repair_env.svc.cuts.repair_near_full(dry_run=True) == []

    async def test_repair_supersedes_the_old_cut_and_rebuilds_it_once(self, repair_env):
        set_transcript(repair_env.fetcher, n=600, seconds_each=10.0)  # 100 min
        old_request = add_old_cut(repair_env, key="bad")
        repair_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 590, "label": "Almost all"}],
            "summary": "s",
            "kept_s": 5900,
        }
        items = repair_env.svc.cuts.repair_near_full()
        assert len(items) == 1
        item = items[0]
        assert item["old_share"] == pytest.approx(0.99)
        assert len(item["new"]) == 1
        new_request = item["new"][0]["request_id"]
        assert new_request != old_request
        # The old row is gone, its request leaves the queue, and the new one waits for its build.
        assert repair_env.svc.db.one("SELECT * FROM cuts WHERE cache_key='bad'") is None
        old = repair_env.svc.db.one("SELECT state FROM cut_requests WHERE id=?", [old_request])
        assert old["state"] == "dismissed"
        queued = [r["id"] for r in repair_env.svc.cuts.queue("owner")]
        assert old_request not in queued and new_request in queued

        repair_env.svc.cuts.start()  # what the server does after a deploy
        doc = await wait_ready(repair_env, new_request, wait_ms=30000)
        assert doc["state"] == "ready", doc
        # The rebuilt cut is marked with the new algorithm version even though it keeps ~98 %:
        # a one-pass named preset is allowed to, and the repair must not queue it again.
        row = repair_env.svc.db.one(
            "SELECT algo_version, kept_s, duration_s FROM cuts WHERE video_id=?", [VID]
        )
        assert row["algo_version"] == CUT_BUILD_VERSION
        assert row["kept_s"] / row["duration_s"] > 0.9
        assert repair_env.svc.cuts.repair_near_full(dry_run=True) == []

    def test_an_orphan_cut_is_removed_and_nothing_is_queued(self, repair_env):
        add_old_cut(repair_env, key="orphan")
        repair_env.svc.db.execute("DELETE FROM cut_requests WHERE cut_key='orphan'")
        items = repair_env.svc.cuts.repair_near_full()
        assert len(items) == 1 and items[0]["new"] == []
        assert repair_env.svc.db.one("SELECT * FROM cuts WHERE cache_key='orphan'") is None


def test_cli_repair_dry_run_reports_and_changes_nothing(tmp_path, capsys):
    path = tmp_path / "config.toml"
    path.write_text(
        f'[server]\ndata_dir = "{tmp_path}/d"\n'
        '[llm]\ndefault_provider = "default"\n'
        '[llm.providers.default]\nbase_url = "http://mock/v1"\n'
        '[llm.cuts]\nmodel = "cutmodel"\n'
        "[cuts]\nrepair_on_start = false\n"
    )
    cfg = load_config(path)
    db = Database(cfg.db_path)
    insert_old_cut(db, key="bad")
    db.close()
    assert main(["--config", str(path), "cuts", "repair", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert VID in out and "99%" in out and "would queue" in out and "1 cut(s)" in out
    reopened = Database(cfg.db_path)
    assert reopened.one("SELECT * FROM cuts WHERE cache_key='bad'") is not None
    reopened.close()
