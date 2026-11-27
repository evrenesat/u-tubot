"""T2: the settings store, the device channel, the audit and the old-database rules."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time

import httpx
import pytest

from tests.conftest import OTHER_TOKEN
from tests.test_voice_api import as_device, pair_device
from utubot import db as dbmod


@pytest.fixture
def cfg(cfg):
    cfg.settings_sync.enabled = True
    return cfg


def change(key, value, base_rev=0):
    return {"key": key, "value": value, "base_rev": base_rev}


async def setup_tv(env, name="Den TV"):
    device_id, token = await pair_device(env, name)
    return device_id, as_device(env, token)


def audit_rows(env):
    return env.svc.db.all("SELECT * FROM settings_audit ORDER BY id")


async def version(env):
    return (await env.client.get("/v1/me")).json()["settings_version"]


async def web_put(env, settings, **extra):
    body = {"version": await version(env), "settings": settings, **extra}
    return await env.client.put("/v1/me/settings", json=body)


async def test_routes_answer_404_when_switched_off(env):
    env.cfg.settings_sync.enabled = False
    _, tv = await setup_tv(env)
    for path in ("/v1/settings/schema", "/v1/me/settings/status", "/v1/me/settings/history"):
        assert (await env.client.get(path)).status_code == 404
    assert (await tv.get("/v1/device/settings")).status_code == 404
    me = (await env.client.get("/v1/me")).json()
    assert "settings_sync" not in me["features"]


async def test_off_leaves_me_and_the_document_unchanged(cfg, env):
    env.cfg.settings_sync.enabled = False
    doc = (await env.client.get("/v1/me/settings")).json()
    assert "values" not in doc
    bad = await env.client.put("/v1/me/settings", json={"settings": {"ai.assess": False}})
    assert bad.status_code == 400


async def test_schema_route_has_an_etag(env):
    r = await env.client.get("/v1/settings/schema")
    assert r.status_code == 200 and r.headers["etag"] == '"2"'
    assert r.json()["schema_version"] == 2
    me = (await env.client.get("/v1/me")).json()
    assert me["features"]["settings_sync"] is True


async def test_a_browser_or_config_token_has_no_device(env):
    assert (await env.client.get("/v1/device/settings")).status_code == 400
    assert (await env.client.post("/v1/device/settings", json={})).status_code == 400


async def test_resolution_order_for_each_level(env):
    device_id, tv = await setup_tv(env)
    got = (await tv.get("/v1/device/settings")).json()
    s = got["settings"]
    # schema default / server setting it follows / user value / device override
    assert s["ai.panel_delay_ms"] == {"v": 1800, "rev": 0, "from": "default"}
    assert s["ai.assess"]["v"] is True and s["ai.assess"]["from"] == "default"
    env.cfg.setup.defaults.summary_panel = True
    assert (await tv.get("/v1/device/settings")).json()["settings"]["ai.summary_panel"]["v"] is True
    await web_put(env, {"ai.summary_panel": False, "ai.assess": False})
    s = (await tv.get("/v1/device/settings")).json()["settings"]
    assert s["ai.summary_panel"]["v"] is False and s["ai.summary_panel"]["from"] == "user"
    assert s["ai.assess"] == {"v": False, "rev": s["ai.assess"]["rev"], "from": "user"}
    assert s["ai.assess"]["rev"] > 0
    v = (await tv.get("/v1/device/settings")).json()["version"]
    r = await env.client.put(
        f"/v1/me/devices/{device_id}/settings", json={"version": v, "settings": {"ai.assess": True}}
    )
    assert r.status_code == 200
    s = (await tv.get("/v1/device/settings")).json()["settings"]
    assert s["ai.assess"]["v"] is True and s["ai.assess"]["from"] == "device"


async def test_a_device_override_does_not_leak(env):
    first, tv1 = await setup_tv(env, "One")
    second, tv2 = await setup_tv(env, "Two")
    v = await version(env)
    await env.client.put(
        f"/v1/me/devices/{first}/settings", json={"version": v, "settings": {"ai.auto_cuts": True}}
    )
    assert (await tv1.get("/v1/device/settings")).json()["settings"]["ai.auto_cuts"]["v"] is True
    assert (await tv2.get("/v1/device/settings")).json()["settings"]["ai.auto_cuts"]["v"] is False
    partner = httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    assert (
        await partner.put(f"/v1/me/devices/{first}/settings", json={"version": 0, "settings": {}})
    ).status_code == 404
    assert (await partner.get(f"/v1/me/devices/{first}/settings")).status_code == 404


async def test_the_web_value_wins_over_a_stale_tv_change(env):
    device_id, tv = await setup_tv(env)
    doc = (await tv.get("/v1/device/settings")).json()
    base = doc["settings"]["ai.summary_panel"]["rev"]
    await web_put(env, {"ai.summary_panel": True})
    r = await tv.post(
        "/v1/device/settings",
        json={"schema_version": 1, "changes": [change("ai.summary_panel", False, base)]},
    )
    body = r.json()
    assert body["results"] == [{"key": "ai.summary_panel", "outcome": "superseded"}]
    assert body["settings"]["ai.summary_panel"]["v"] is True
    lost = [r for r in audit_rows(env) if r["outcome"] == "superseded"]
    assert len(lost) == 1 and json.loads(lost[0]["new_json"]) is False


async def test_a_tv_change_with_the_current_rev_lands_as_a_device_override(env):
    device_id, tv = await setup_tv(env)
    rev = (await tv.get("/v1/device/settings")).json()["settings"]["ai.wait_ms"]["rev"]
    r = await tv.post(
        "/v1/device/settings",
        json={"changes": [change("ai.wait_ms", 2000, rev)], "applied_version": 0},
    )
    assert r.json()["results"][0]["outcome"] == "applied"
    assert r.json()["settings"]["ai.wait_ms"]["from"] == "device"
    # the user's own value is untouched (D3)
    doc = (await env.client.get("/v1/me/settings")).json()
    assert doc["values"]["ai.wait_ms"]["v"] == 1200
    row = audit_rows(env)[-1]
    assert (row["via"], row["actor_device_id"], row["device_id"]) == ("tv", device_id, device_id)


async def test_a_tv_change_for_an_unknown_or_invalid_key(env):
    _, tv = await setup_tv(env)
    r = await tv.post(
        "/v1/device/settings",
        json={"changes": [change("nope.key", 1), change("ai.panel_delay_ms", 99999)]},
    )
    assert [x["outcome"] for x in r.json()["results"]] == ["not_remote", "invalid"]
    assert audit_rows(env) == []


async def test_every_applied_change_raises_the_version_by_one_with_one_audit_row(env):
    _, tv = await setup_tv(env)
    v0 = await version(env)
    await web_put(env, {"ai.auto_cuts": True})
    assert await version(env) == v0 + 1
    assert len(audit_rows(env)) == 1
    rev = (await tv.get("/v1/device/settings")).json()["settings"]["ai.wait_ms"]["rev"]
    await tv.post("/v1/device/settings", json={"changes": [change("ai.wait_ms", 900, rev)]})
    assert await version(env) == v0 + 2
    assert len(audit_rows(env)) == 2


async def test_two_web_writers_from_one_version_one_wins(env):
    v = await version(env)
    a = await env.client.put(
        "/v1/me/settings", json={"version": v, "settings": {"ai.assess": False}}
    )
    b = await env.client.put(
        "/v1/me/settings", json={"version": v, "settings": {"ai.assess": True}}
    )
    assert (a.status_code, b.status_code) == (200, 409)


async def test_unchanged_answer_is_small_and_fast(env):
    _, tv = await setup_tv(env)
    doc = (await tv.get("/v1/device/settings")).json()
    start = time.perf_counter()
    for _ in range(100):
        r = await tv.get("/v1/device/settings", params={"have": doc["version"]})
    per_call = (time.perf_counter() - start) / 100
    assert r.json() == {"version": doc["version"], "unchanged": True}
    assert len(r.content) <= 300
    assert per_call < 0.05  # the plan's 10 ms is for the handler; the test client adds its own cost


async def test_have_records_what_the_tv_applied(env):
    device_id, tv = await setup_tv(env)
    await web_put(env, {"ai.auto_cuts": True})
    status = (await env.client.get("/v1/me/settings/status")).json()
    assert status["devices"][0]["syncs"] is False and status["devices"][0]["pending"] == []
    doc = (await tv.get("/v1/device/settings")).json()
    status = (await env.client.get("/v1/me/settings/status")).json()
    assert status["devices"][0]["pending"] == ["ai.auto_cuts"]
    await tv.get("/v1/device/settings", params={"have": doc["version"]})
    status = (await env.client.get("/v1/me/settings/status")).json()
    dev = status["devices"][0]
    assert dev["pending"] == [] and dev["applied_version"] == doc["version"]


async def test_a_key_above_the_clients_schema_is_not_sent(env, monkeypatch):
    _, tv = await setup_tv(env)
    schema = env.svc.device_settings.schema
    monkeypatch.setitem(schema.by_key["ai.auto_cuts"], "since", 2)
    got = (await tv.get("/v1/device/settings", params={"schema": 1})).json()
    assert "ai.auto_cuts" not in got["settings"] and "ai.assess" in got["settings"]


async def test_first_sync_keeps_what_the_tv_has(env):
    """Plan section 7: N of N values after the first sync equal the TV's own, nothing is lost."""
    device_id, tv = await setup_tv(env)
    await web_put(
        env, {"ai.summary_panel": True, "ai.panel_delay_ms": 700}
    )  # web values that never took effect
    tv_values = {
        "ai.assess": False,
        "ai.mark_only": True,
        "ai.answer_in_menu": False,
        "ai.summary_panel": False,
        "ai.panel_delay_ms": 1800,
        "ai.auto_captions": False,
        "ai.auto_cuts": True,
        "ai.wait_ms": 1200,  # the server's own value: nothing is stored for it
    }
    r = await tv.post(
        "/v1/device/settings",
        json={
            "schema_version": 1,
            "initial": True,
            "changes": [{**change(k, v, 0), "user_set": True} for k, v in tv_values.items()],
        },
    )
    got = {k: e["v"] for k, e in r.json()["settings"].items()}
    assert got == tv_values
    assert all(x["outcome"] == "applied" for x in r.json()["results"])
    # the web user's own values stay as they were
    doc = (await env.client.get("/v1/me/settings")).json()
    assert doc["values"]["ai.summary_panel"]["v"] is True
    assert doc["values"]["ai.panel_delay_ms"]["v"] == 700
    state = (await env.client.get("/v1/me/settings/status")).json()["devices"][0]
    assert state["migrated"] is True and "ai.summary_panel" in state["overrides"]
    # keys equal to what the server would have given stay out of the overrides
    assert "ai.wait_ms" not in state["overrides"] and len(state["overrides"]) == 7
    assert {row["via"] for row in audit_rows(env) if row["device_id"]} == {"migration"}


async def test_a_second_initial_is_a_normal_sync(env):
    device_id, tv = await setup_tv(env)
    body = {"initial": True, "changes": [{**change("ai.wait_ms", 1500, 0), "user_set": True}]}
    await tv.post("/v1/device/settings", json=body)
    await web_put(env, {"ai.auto_cuts": True})
    r = await tv.post(
        "/v1/device/settings", json={"initial": True, "changes": [change("ai.auto_cuts", False, 0)]}
    )
    assert r.json()["results"][0]["outcome"] == "superseded"
    assert r.json()["settings"]["ai.auto_cuts"]["v"] is True


async def test_use_my_default_removes_the_override_and_the_tv_learns_it(env):
    device_id, tv = await setup_tv(env)
    await tv.post(
        "/v1/device/settings",
        json={"initial": True, "changes": [{**change("ai.wait_ms", 1500, 0), "user_set": True}]},
    )
    doc = (await tv.get("/v1/device/settings")).json()
    await tv.get("/v1/device/settings", params={"have": doc["version"]})
    v = await version(env)
    r = await env.client.put(
        f"/v1/me/devices/{device_id}/settings",
        json={"version": v, "settings": {"ai.wait_ms": None}},
    )
    assert r.json()["settings"]["ai.wait_ms"]["v"] == 1200
    status = (await env.client.get("/v1/me/settings/status")).json()["devices"][0]
    assert status["overrides"] == [] and status["pending"] == ["ai.wait_ms"]


async def test_device_put_needs_a_version_and_a_tv_key(env):
    device_id, _ = await setup_tv(env)
    url = f"/v1/me/devices/{device_id}/settings"
    assert (await env.client.put(url, json={"settings": {}})).status_code == 428
    v = await version(env)
    assert (await env.client.put(url, json={"version": v + 5, "settings": {}})).status_code == 409
    bad = await env.client.put(url, json={"version": v, "settings": {"filtering.hide_topics": []}})
    assert bad.status_code == 400
    bad = await env.client.put(url, json={"version": v, "settings": {"ai.wait_ms": 99999}})
    assert bad.status_code == 400


async def test_history_lists_who_where_and_when(env):
    device_id, tv = await setup_tv(env)
    await web_put(env, {"ai.auto_cuts": True})
    await tv.post("/v1/device/settings", json={"changes": [change("ai.wait_ms", 900, 0)]})
    entries = (await env.client.get("/v1/me/settings/history")).json()["entries"]
    assert [e["via"] for e in entries] == ["tv", "web"]
    assert (
        entries[0]["device"] == "Den TV" and entries[0]["old"] == 1200 and entries[0]["new"] == 900
    )
    assert entries[1]["device"] is None and entries[1]["title"] == "Apply ready cuts"
    only = (await env.client.get("/v1/me/settings/history", params={"key": "ai.auto_cuts"})).json()
    assert len(only["entries"]) == 1


async def test_audit_pruning(env):
    env.cfg.settings_sync.audit_max_rows_per_user = 5
    for i in range(8):
        await web_put(env, {"ai.wait_ms": 100 * (i + 1)})
    assert len(audit_rows(env)) == 5
    env.cfg.settings_sync.audit_days = 1
    env.svc.db.execute("UPDATE settings_audit SET at=at-?", [3 * 86400])
    await web_put(env, {"ai.wait_ms": 5})
    assert len(audit_rows(env)) == 1


async def test_the_document_accepts_old_sections_and_dotted_keys_and_records_both(env):
    r = await web_put(env, {"tv": {"summary_delay_ms": 900}, "ai.auto_cuts": True})
    doc = r.json()
    assert doc["settings"]["tv"]["summary_delay_ms"] == 900
    assert (
        doc["values"]["ai.panel_delay_ms"]["v"] == 900
        and doc["values"]["ai.auto_cuts"]["v"] is True
    )
    assert {row["key"] for row in audit_rows(env)} == {"ai.panel_delay_ms", "ai.auto_cuts"}
    assert (await web_put(env, {"nope.key": 1})).status_code == 400
    assert (await web_put(env, {"ai.wait_ms": 99999})).status_code == 400


async def test_a_reset_with_null_returns_the_default(env):
    await web_put(env, {"ai.auto_cuts": True})
    doc = (await web_put(env, {"ai.auto_cuts": None})).json()
    assert doc["values"]["ai.auto_cuts"] == {"v": False, "rev": doc["version"], "from": "default"}


async def test_admin_edits_are_named_in_the_history(env):
    v = (await env.client.get("/v1/users/partner/settings")).json()["version"]
    r = await env.client.put(
        "/v1/users/partner/settings", json={"version": v, "settings": {"ai.auto_cuts": True}}
    )
    assert r.status_code == 200
    row = env.svc.db.one("SELECT * FROM settings_audit WHERE user='partner'")
    assert (row["via"], row["by_user"]) == ("admin", "owner")


async def test_revoking_a_device_removes_its_settings(env):
    device_id, tv = await setup_tv(env)
    await tv.post(
        "/v1/device/settings",
        json={"initial": True, "changes": [{**change("ai.wait_ms", 1500, 0), "user_set": True}]},
    )
    assert (await env.client.delete(f"/v1/me/devices/{device_id}")).status_code == 200
    db = env.svc.db
    for table in ("settings_values", "settings_rev", "device_settings_state"):
        assert db.one(f"SELECT COUNT(*) n FROM {table} WHERE device_id=?", [device_id])["n"] == 0


def test_a_database_from_before_opens_with_its_data(tmp_path):
    """The live database predates these tables: it opens, keeps every row and gains the new tables."""
    path = tmp_path / "old.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE policy_overrides(user TEXT PRIMARY KEY, json TEXT NOT NULL,
          version INTEGER NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0);
        INSERT INTO policy_overrides VALUES('owner','{"summary_panel": true}',7,1.0);
        CREATE TABLE device_tokens(id TEXT PRIMARY KEY, user TEXT NOT NULL,
          token_sha256 TEXT NOT NULL UNIQUE, device TEXT NOT NULL, created_at REAL NOT NULL, last_used REAL);
        INSERT INTO device_tokens VALUES('d1','owner','h','Den TV',1,NULL);
        """
    )
    conn.commit()
    conn.close()
    database = dbmod.Database(path)
    assert database.one("SELECT version, json FROM policy_overrides")["version"] == 7
    assert database.one("SELECT device FROM device_tokens")["device"] == "Den TV"
    tables = {r["name"] for r in database.all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"settings_values", "settings_rev", "device_settings_state", "settings_audit"} <= tables
    database.close()
    again = dbmod.Database(path)  # a second open changes nothing
    assert again.one("SELECT COUNT(*) n FROM policy_overrides")["n"] == 1
    again.close()


async def test_a_web_change_does_not_touch_a_tv_that_holds_its_own_value(env):
    device_id, tv = await setup_tv(env)
    await tv.post(
        "/v1/device/settings",
        json={"initial": True, "changes": [{**change("ai.wait_ms", 1500, 0), "user_set": True}]},
    )
    doc = (await tv.get("/v1/device/settings")).json()
    await tv.get("/v1/device/settings", params={"have": doc["version"]})
    await web_put(env, {"ai.wait_ms": 900})  # the user's value; this TV keeps 1500
    status = (await env.client.get("/v1/me/settings/status")).json()["devices"][0]
    assert "ai.wait_ms" not in status["pending"]
    r = await tv.post(
        "/v1/device/settings",
        json={"changes": [change("ai.wait_ms", 1700, doc["settings"]["ai.wait_ms"]["rev"])]},
    )
    assert r.json()["results"][0]["outcome"] == "applied"


async def test_a_tv_cannot_read_or_change_settings_through_the_browser_routes(env):
    first, tv1 = await setup_tv(env, "One")
    second, _ = await setup_tv(env, "Two")
    v = await version(env)
    for method, path, kw in [
        ("get", "/v1/me/settings/status", {}),
        ("get", "/v1/me/settings/history", {}),
        ("get", f"/v1/me/devices/{second}/settings", {}),
        (
            "put",
            f"/v1/me/devices/{second}/settings",
            {"json": {"version": v, "settings": {"ai.assess": False}}},
        ),
    ]:
        assert (await getattr(tv1, method)(path, **kw)).status_code == 403, path
    assert audit_rows(env) == []


async def test_an_untouched_default_never_replaces_a_newer_web_value_on_first_sync(env):
    _, tv = await setup_tv(env)
    await web_put(env, {"ai.auto_cuts": True})
    r = await tv.post(
        "/v1/device/settings",
        json={
            "initial": True,
            "changes": [change("ai.auto_cuts", False, 0)],
        },  # not flagged: a default
    )
    assert r.json()["results"][0]["outcome"] == "superseded"
    assert r.json()["settings"]["ai.auto_cuts"]["v"] is True
    assert r.json()["settings"]["ai.auto_cuts"]["from"] == "user"


async def test_an_untouched_default_the_web_never_changed_is_kept_and_a_user_set_value_wins(env):
    _, tv = await setup_tv(env)
    await web_put(env, {"ai.auto_cuts": True})
    r = await tv.post(
        "/v1/device/settings",
        json={
            "initial": True,
            "changes": [
                {**change("ai.auto_cuts", False, 0), "user_set": True},  # the TV's real choice
                change(
                    "ai.panel_delay_ms", 1000, 0
                ),  # default of another build, web never touched it
            ],
        },
    )
    got = {k: e["v"] for k, e in r.json()["settings"].items()}
    assert got["ai.auto_cuts"] is False and got["ai.panel_delay_ms"] == 1000


async def test_a_large_report_is_summarised_and_status_still_answers(env):
    device_id, tv = await setup_tv(env)
    report = {"caption_store_bytes": 123, "blob": "x" * 5000, "nested": {"a": 1}, "ok": "fine"}
    r = await tv.post("/v1/device/settings", json={"changes": [], "report": report})
    assert r.status_code == 200
    status = await env.client.get("/v1/me/settings/status")
    assert status.status_code == 200
    assert status.json()["devices"][0]["report"] == {"caption_store_bytes": 123, "ok": "fine"}
    big = {"changes": [], "report": {f"k{i}": i for i in range(50000)}}
    assert (await tv.post("/v1/device/settings", json=big)).status_code == 413
    assert (await env.client.get("/v1/me/settings/status")).status_code == 200


async def test_a_key_without_device_override_is_not_a_tv_change(env, monkeypatch):
    _, tv = await setup_tv(env)
    schema = env.svc.device_settings.schema
    monkeypatch.setitem(schema.by_key["ai.wait_ms"], "device_override", False)
    r = await tv.post("/v1/device/settings", json={"changes": [change("ai.wait_ms", 900, 0)]})
    assert r.json()["results"][0]["outcome"] == "not_remote"


# ---- checkpoint 5: per-TV keys, schema upgrade, long poll -------------------------------------------


async def test_a_per_tv_key_is_set_from_the_web_and_reaches_that_tv_only(env):
    device_id, tv = await setup_tv(env)
    _, other = await setup_tv(env, "Bedroom TV")
    await tv.get("/v1/device/settings", params={"schema": 2})
    r = await env.client.put(
        f"/v1/me/devices/{device_id}/settings",
        json={"version": await version(env), "settings": {"updates.interval_minutes": 60}},
    )
    assert r.status_code == 200
    mine = (await tv.get("/v1/device/settings", params={"schema": 2})).json()["settings"]
    theirs = (await other.get("/v1/device/settings", params={"schema": 2})).json()["settings"]
    assert (
        mine["updates.interval_minutes"]["v"] == 60
        and mine["updates.interval_minutes"]["from"] == "device"
    )
    assert theirs["updates.interval_minutes"]["v"] == 5


async def test_a_per_tv_key_has_no_user_level_value(env):
    doc = (await env.client.get("/v1/me/settings")).json()
    assert "ai.cut_jump" not in doc["values"] and "ai.assess" in doc["values"]
    bad = await web_put(env, {"ai.cut_jump": "off"})
    assert bad.status_code == 400


async def test_the_update_check_switch_is_a_user_value_a_tv_may_override(env):
    device_id, tv = await setup_tv(env)
    assert (await web_put(env, {"updates.checks": False})).status_code == 200
    got = (await tv.get("/v1/device/settings", params={"schema": 2})).json()["settings"]
    assert got["updates.checks"]["v"] is False and got["updates.checks"]["from"] == "user"
    assert (await env.client.get("/v1/me/settings")).json()["settings"]["tv"][
        "update_checks"
    ] is False


async def test_a_value_outside_the_choices_is_invalid(env):
    device_id, tv = await setup_tv(env)
    r = await tv.post(
        "/v1/device/settings",
        json={"schema_version": 2, "changes": [change("updates.interval_minutes", 7)]},
    )
    assert r.json()["results"][0]["outcome"] == "invalid"


async def test_a_schema_one_tv_does_not_see_or_get_the_new_keys(env):
    device_id, tv = await setup_tv(env)
    doc = (await tv.get("/v1/device/settings", params={"schema": 1})).json()
    assert "ai.cut_jump" not in doc["settings"] and "updates.checks" not in doc["settings"]
    r = await env.client.put(
        f"/v1/me/devices/{device_id}/settings",
        json={"version": await version(env), "settings": {"ai.cut_jump": "off"}},
    )
    assert r.status_code == 400
    view = (await env.client.get(f"/v1/me/devices/{device_id}/settings")).json()
    assert "ai.cut_jump" not in view["settings"]


async def test_a_synced_tv_updated_to_schema_two_keeps_its_own_new_values(env):
    """The app update brings six keys; the values the TV already had win, the old ten stay base-checked."""
    device_id, tv = await setup_tv(env)
    first = {"schema_version": 1, "initial": True, "changes": [change("ai.assess", True, 0)]}
    assert (await tv.post("/v1/device/settings", json=first)).status_code == 200
    await web_put(env, {"ai.summary_panel": True})
    assert (await tv.get("/v1/device/settings", params={"schema": 1, "have": 0})).status_code == 200
    upgrade = {
        "schema_version": 2,
        "from_schema": 1,
        "initial": True,
        "changes": [
            {**change("updates.interval_minutes", 360, 0), "user_set": True},
            {**change("ai.cut_jump", "up_down", 0), "user_set": True},
            {**change("ai.summary_panel", False, 0), "user_set": True},  # an old key: not trusted
        ],
    }
    r = await tv.post("/v1/device/settings", json=upgrade)
    got = {x["key"]: x["outcome"] for x in r.json()["results"]}
    assert got == {
        "updates.interval_minutes": "applied",
        "ai.cut_jump": "applied",
        "ai.summary_panel": "superseded",
    }
    settings = r.json()["settings"]
    assert (
        settings["updates.interval_minutes"]["v"] == 360
        and settings["ai.cut_jump"]["v"] == "up_down"
    )
    assert settings["ai.summary_panel"]["v"] is True
    rows = [row for row in audit_rows(env) if row["device_id"] and row["outcome"] == "applied"]
    assert {row["via"] for row in rows} == {"migration"}


async def test_a_plain_second_initial_without_from_schema_stays_a_normal_sync(env):
    device_id, tv = await setup_tv(env)
    await tv.post("/v1/device/settings", json={"schema_version": 2, "initial": True, "changes": []})
    await web_put(env, {"ai.summary_panel": True})
    r = await tv.post(
        "/v1/device/settings",
        json={
            "schema_version": 2,
            "initial": True,
            "changes": [{**change("ai.summary_panel", False, 0), "user_set": True}],
        },
    )
    assert r.json()["results"][0]["outcome"] == "superseded"


async def test_the_status_of_an_old_tv_does_not_wait_for_keys_it_cannot_take(env):
    device_id, tv = await setup_tv(env)
    await tv.get("/v1/device/settings", params={"schema": 1})
    await web_put(env, {"updates.checks": False})
    dev = (await env.client.get("/v1/me/settings/status")).json()["devices"][0]
    assert "updates.checks" not in dev["pending"] and dev["schema_version"] == 1


async def test_long_poll_answers_at_once_when_the_version_moves(env):
    _, tv = await setup_tv(env)
    have = (await tv.get("/v1/device/settings", params={"schema": 2})).json()["version"]

    async def change_soon():
        await asyncio.sleep(0.3)
        await web_put(env, {"ai.summary_panel": True})

    started = time.monotonic()
    task = asyncio.create_task(change_soon())
    r = await tv.get("/v1/device/settings", params={"have": have, "schema": 2, "wait_ms": 10000})
    await task
    took = time.monotonic() - started
    body = r.json()
    assert "unchanged" not in body and body["settings"]["ai.summary_panel"]["v"] is True
    assert 0.25 < took < 1.5


async def test_long_poll_ends_unchanged_at_wait_ms(env):
    _, tv = await setup_tv(env)
    have = (await tv.get("/v1/device/settings", params={"schema": 2})).json()["version"]
    started = time.monotonic()
    r = await tv.get("/v1/device/settings", params={"have": have, "wait_ms": 600})
    took = time.monotonic() - started
    assert r.json() == {"version": have, "unchanged": True} and 0.55 < took < 1.5


async def test_long_poll_wait_is_capped_and_needs_have(env):
    env.cfg.settings_sync.long_poll_max_ms = 300
    _, tv = await setup_tv(env)
    have = (await tv.get("/v1/device/settings")).json()["version"]
    started = time.monotonic()
    await tv.get("/v1/device/settings", params={"have": have, "wait_ms": 60000})
    assert time.monotonic() - started < 1.2
    started = time.monotonic()
    r = await tv.get("/v1/device/settings", params={"wait_ms": 5000})
    assert time.monotonic() - started < 1.0 and "settings" in r.json()


async def test_long_poll_is_for_a_paired_tv_only(env):
    r = await env.client.get("/v1/device/settings", params={"have": 1, "wait_ms": 1000})
    assert r.status_code == 400


async def test_an_unchanged_answer_stays_small(env):
    _, tv = await setup_tv(env)
    have = (await tv.get("/v1/device/settings")).json()["version"]
    r = await tv.get("/v1/device/settings", params={"have": have, "schema": 2})
    assert len(r.content) <= 300
