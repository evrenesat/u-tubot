"""Crash reports and player logs a TV uploads: stored per user and device, kept for a while, read from the CLI."""

from __future__ import annotations

import gzip
import json
import os

import pytest

from tests.test_voice_api import as_device, pair_device
from utubot.cli import main
from utubot.devicereports import DeviceReports, ReportRefused, unpack

REPORT = {
    "app": {"version": "0.3.72"},
    "failures": [{"kind": "crash", "error": "NPE"}, {"kind": "anr"}, {"kind": "error"}],
    "events": ["12:00:00 open stream"],
}


def packed(doc) -> bytes:
    return gzip.compress(json.dumps(doc).encode())


async def tv(env, name="Den TV"):
    device_id, token = await pair_device(env, name)
    return device_id, as_device(env, token)


async def test_a_tv_uploads_gzip_and_the_server_stores_it_per_device(env):
    device_id, client = await tv(env)
    resp = await client.post(
        "/v1/device/reports", content=packed(REPORT), headers={"Content-Encoding": "gzip"}
    )
    assert resp.status_code == 200
    stored = env.svc.device_reports.get(int(resp.json()["id"]))
    assert stored["device_id"] == device_id and stored["device_name"] == "Den TV"
    assert (stored["crashes"], stored["anrs"], stored["errors"]) == (1, 1, 1)
    assert stored["app_version"] == "0.3.72"
    assert stored["report"]["events"] == REPORT["events"]


async def test_plain_json_works_and_a_config_token_is_not_a_device(env):
    _, client = await tv(env)
    assert (await client.post("/v1/device/reports", json=REPORT)).status_code == 200
    assert (await env.client.post("/v1/device/reports", json=REPORT)).status_code == 400
    assert (await env.client.post("/v1/device/reports", json=REPORT)).status_code != 401


async def test_bad_bodies_are_refused(env):
    _, client = await tv(env)
    gz = {"Content-Encoding": "gzip"}
    assert (await client.post("/v1/device/reports", content=b"nope", headers=gz)).status_code == 400
    assert (await client.post("/v1/device/reports", content=b"[1]")).status_code == 400
    assert (await client.post("/v1/device/reports", content=b"{")).status_code == 400
    env.cfg.reports.max_report_bytes = 2048
    big = {"events": ["x" * 5000]}
    assert (await client.post("/v1/device/reports", json=big)).status_code == 413
    bomb = gzip.compress(json.dumps({"events": ["x" * 50000]}).encode())
    assert len(bomb) < 2048
    assert (await client.post("/v1/device/reports", content=bomb, headers=gz)).status_code == 413


async def test_unauthenticated_uploads_are_refused(env):
    from tests.test_voice_api import anon_client

    assert (await anon_client(env).post("/v1/device/reports", json=REPORT)).status_code == 401


def test_unpack_limits():
    with pytest.raises(ReportRefused):
        unpack(b"x" * 10, False, 5)


def test_retention_by_age_and_size(env):
    store: DeviceReports = env.svc.device_reports
    now = [1_000_000.0]
    store.clock = lambda: now[0]
    store.cfg.keep_days = 30
    old = store.save("owner", "d1", "TV", REPORT)
    now[0] += 31 * 86400
    fresh = store.save("owner", "d1", "TV", REPORT)
    assert store.get(old) is None and store.get(fresh) is not None
    store.cfg.max_bytes_per_user = 1500
    ids = [store.save("owner", "d1", "TV", {"events": [os.urandom(300).hex()]}) for i in range(8)]
    kept = [r["id"] for r in store.list("owner")]
    assert ids[-1] in kept and ids[0] not in kept


def test_counts_cover_a_week_and_one_user(env):
    store: DeviceReports = env.svc.device_reports
    store.save("owner", "d1", "TV", REPORT)
    store.save("someone", "d2", "TV", REPORT)
    assert store.counts()["crashes"] == 2
    assert store.counts("owner") == {"days": 7, "reports": 1, "crashes": 1, "anrs": 1}


async def test_status_has_the_counts(env):
    _, client = await tv(env)
    await client.post("/v1/device/reports", json=REPORT)
    status = (await env.client.get("/v1/status")).json()
    assert status["reports"]["crashes"] == 1


def test_cli_list_and_show(env, tmp_path, capsys):
    env.svc.device_reports.save("owner", "d1", "Den TV", REPORT)
    config = tmp_path / "config.toml"
    config.write_text(f'[server]\ndata_dir = "{env.cfg.server.data_dir}"\n')
    assert main(["--config", str(config), "reports", "list"]) == 0
    assert "Den TV" in capsys.readouterr().out
    first = env.svc.device_reports.list()[0]["id"]
    assert main(["--config", str(config), "reports", "show", str(first)]) == 0
    assert json.loads(capsys.readouterr().out)["report"]["events"] == REPORT["events"]
    assert main(["--config", str(config), "reports", "show", "9999"]) == 1
