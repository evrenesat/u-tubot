"""T6: per-user secrets are encrypted at rest, write-only for the web and delivered only to the user's own TVs."""

from __future__ import annotations

import logging
import sys

import pytest

from tests.conftest import OTHER_TOKEN
from tests.test_device_settings import setup_tv
from tests.test_voice_api import as_device
from utubot import secretstore as ss

CANARY = "rd-CANARY-0123456789abcdef-4f2a"
ADDON = "https://addon.example.org/CANARYKEY99/manifest.json"
KEY = ss.new_master_key()


@pytest.fixture
def cfg(cfg, monkeypatch):
    cfg.settings_sync.enabled = True
    monkeypatch.setenv(cfg.security.secrets_key_env, KEY)
    return cfg


async def put(env, name, value, client=None):
    return await (client or env.client).put(f"/v1/me/secrets/{name}", json={"value": value})


def raw_db_bytes(env) -> bytes:
    env.svc.db.execute("PRAGMA wal_checkpoint(FULL)") if False else None
    data = b""
    for suffix in ("", "-wal"):
        try:
            data += open(str(env.cfg.db_path) + suffix, "rb").read()
        except FileNotFoundError:
            pass
    return data


async def test_a_secret_is_stored_encrypted_and_the_web_sees_only_set_and_the_last_four(
    env, caplog
):
    caplog.set_level(logging.DEBUG)
    r = await put(env, "films_rd_token", CANARY)
    assert r.status_code == 200 and r.json()["last4"] == "4f2a" and r.json()["set"] is True
    listing = (await env.client.get("/v1/me/secrets")).json()
    assert listing["available"] is True
    rd = next(s for s in listing["secrets"] if s["key"] == "films_rd_token")
    assert rd["set"] and rd["last4"] == "4f2a" and rd["delivered_to"] == []
    for body in (r.text, str(listing)):
        assert CANARY not in body
    assert CANARY.encode() not in raw_db_bytes(env)
    history = (await env.client.get("/v1/me/settings/history")).json()["entries"]
    assert history[0]["key"] == "secrets.films_rd_token" and history[0]["new"] == "set"
    assert CANARY not in str(history) and "4f2a" not in str(history)
    assert CANARY not in caplog.text


async def test_the_addon_address_is_checked_and_shows_its_host_only(env):
    assert (await put(env, "films_addon_url", "ftp://x.example")).status_code == 400
    assert (await put(env, "films_addon_url", "http://addon.example.org/x")).status_code == 400
    ok = await put(env, "films_addon_url", "http://192.168.1.20:7000/CANARYKEY99/manifest.json")
    assert ok.status_code == 200 and ok.json()["last4"] == "192.168.1.20"
    shown = await put(env, "films_addon_url", ADDON)
    assert shown.json()["last4"] == "addon.example.org" and "CANARYKEY99" not in shown.text


async def test_a_bad_value_is_refused_and_nothing_is_stored(env):
    assert (await put(env, "films_rd_token", "short")).status_code == 400
    assert (await put(env, "films_rd_token", "has space in it")).status_code == 400
    assert (await put(env, "nope", CANARY)).status_code == 404
    assert (await env.client.get("/v1/me/secrets")).json()["secrets"][0]["set"] is False


async def test_a_tv_gets_the_secrets_of_its_own_user_only_and_the_page_shows_where(env):
    device_id, tv = await setup_tv(env)
    await put(env, "films_rd_token", CANARY)
    await put(env, "films_addon_url", ADDON)
    r = await tv.get("/v1/device/secrets", params={"have": 0})
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert r.json()["secrets"] == {"films_rd_token": CANARY, "films_addon_url": ADDON}
    rev = r.json()["rev"]
    again = (await tv.get("/v1/device/secrets", params={"have": rev})).json()
    assert again["unchanged"] is True and "secrets" not in again
    listing = (await env.client.get("/v1/me/secrets")).json()["secrets"]
    assert listing[0]["delivered_to"][0]["id"] == device_id
    # a TV of another user gets nothing of it, and the owner's browser-only routes refuse a device token
    from tests.test_voice_api import pair_device

    _, other_token = await pair_device(env, "Partner TV", OTHER_TOKEN)
    other = as_device(env, other_token)
    assert (await other.get("/v1/device/secrets")).json()["secrets"] == {}
    assert (await tv.get("/v1/me/secrets")).status_code == 403
    assert (
        await tv.put("/v1/me/secrets/films_rd_token", json={"value": CANARY})
    ).status_code == 403
    assert (await env.client.get("/v1/device/secrets")).status_code == 400


async def test_another_user_sees_nothing_of_a_secret(env):
    await put(env, "films_rd_token", CANARY)
    headers = {"Authorization": f"Bearer {OTHER_TOKEN}"}
    other = (await env.client.get("/v1/me/secrets", headers=headers)).json()["secrets"]
    assert all(not s["set"] for s in other)
    assert (
        await env.client.delete("/v1/me/secrets/films_rd_token", headers=headers)
    ).status_code == 404


async def test_removing_it_on_the_web_removes_it_from_the_next_delivery_and_raises_the_revision(
    env,
):
    _, tv = await setup_tv(env)
    await put(env, "films_rd_token", CANARY)
    first = (await tv.get("/v1/device/secrets")).json()["rev"]
    assert (await env.client.delete("/v1/me/secrets/films_rd_token")).status_code == 200
    after = (await tv.get("/v1/device/secrets", params={"have": first})).json()
    assert after["rev"] > first and after["secrets"] == {} and after["set"] == []
    doc = (await tv.get("/v1/device/settings")).json()
    assert doc["secrets_rev"] == after["rev"]


async def test_the_settings_answer_carries_the_secrets_revision(env):
    _, tv = await setup_tv(env)
    assert (await tv.get("/v1/device/settings")).json()["secrets_rev"] == 0
    await put(env, "films_rd_token", CANARY)
    assert (await tv.get("/v1/device/settings")).json()["secrets_rev"] > 0


async def test_a_tv_may_keep_its_token_on_the_server_once(env):
    _, tv = await setup_tv(env)
    r = await tv.put("/v1/device/secrets/films_rd_token", json={"value": CANARY})
    assert r.status_code == 200
    assert (
        await tv.put("/v1/device/secrets/films_rd_token", json={"value": "another-token-123"})
    ).status_code == 409
    assert (await tv.get("/v1/device/secrets")).json()["secrets"]["films_rd_token"] == CANARY
    rows = env.svc.db.all(
        "SELECT via, new_json FROM settings_audit WHERE key='secrets.films_rd_token'"
    )
    assert [(x["via"], x["new_json"]) for x in rows] == [("tv", '"set"')]


async def test_no_master_key_answers_503_and_stores_nothing(env, monkeypatch):
    store = ss.SecretStore(env.svc.db, None)
    env.svc.secrets = store
    env.svc.device_settings.secrets = store
    r = await put(env, "films_rd_token", CANARY)
    assert r.status_code == 503 and "not set up" in r.json()["error"]
    assert (await env.client.get("/v1/me/secrets")).json() == {"available": False, "secrets": []}
    assert env.svc.db.all("SELECT * FROM user_secrets") == []
    assert CANARY.encode() not in raw_db_bytes(env)


def test_a_changed_ciphertext_nonce_or_user_fails_to_decrypt(env):
    store = env.svc.secrets
    store.set("owner", "films_rd_token", CANARY, via="cli")
    assert store.get("owner", "films_rd_token") == CANARY
    row = env.svc.db.one("SELECT * FROM user_secrets WHERE user='owner'")
    flipped = bytes([row["ciphertext"][0] ^ 1]) + row["ciphertext"][1:]
    env.svc.db.execute("UPDATE user_secrets SET ciphertext=? WHERE user='owner'", [flipped])
    with pytest.raises(ss.SecretsUnavailable):
        store.get("owner", "films_rd_token")
    env.svc.db.execute(
        "UPDATE user_secrets SET ciphertext=?, nonce=? WHERE user='owner'",
        [row["ciphertext"], bytes(12)],
    )
    with pytest.raises(ss.SecretsUnavailable):
        store.get("owner", "films_rd_token")
    env.svc.db.execute(
        "UPDATE user_secrets SET ciphertext=?, nonce=?, user='partner' WHERE user='owner'",
        [row["ciphertext"], row["nonce"]],
    )
    with pytest.raises(ss.SecretsUnavailable):
        store.get("partner", "films_rd_token")
    assert store.check()["failed"] == 1


def test_rotation_keeps_every_value_and_check_counts_only(env):
    store = env.svc.secrets
    store.set("owner", "films_rd_token", CANARY, via="cli")
    store.set("partner", "films_addon_url", ADDON, via="cli")
    assert store.check() == {"ok": 2, "failed": 0}
    new_key = ss.new_master_key()
    assert store.rotate(ss.parse_master_key(new_key)) == 2
    rotated = ss.SecretStore(env.svc.db, ss.parse_master_key(new_key))
    assert (
        rotated.get("owner", "films_rd_token") == CANARY
        and rotated.get("partner", "films_addon_url") == ADDON
    )
    assert store.check()["failed"] == 2  # the old key no longer opens them


def test_a_malformed_master_key_is_no_key():
    assert ss.parse_master_key("not base64!!") is None
    assert ss.parse_master_key("c2hvcnQ=") is None
    assert ss.parse_master_key(KEY) is not None


def test_the_cli_reads_the_value_from_stdin_and_never_prints_it(env, tmp_path, monkeypatch):
    import io

    from utubot import cli

    users = tmp_path / "users.toml"
    monkeypatch.setattr(cli, "load_config", lambda _path: env.cfg)
    monkeypatch.setattr(sys, "stdin", io.StringIO(CANARY + "\n"))
    args = cli.argparse.Namespace(config=None, user="owner", name="films_rd_token")
    assert cli.cmd_user_secret_set(args) == 0
    assert env.svc.secrets.get("owner", "films_rd_token") == CANARY
    bad = cli.argparse.Namespace(config=None, user="nobody", name="films_rd_token")
    assert cli.cmd_user_secret_set(bad) == 1
    assert users  # unused path kept for clarity


def test_the_cli_takes_no_value_argument():
    from utubot import cli

    with pytest.raises(SystemExit):
        cli.main(["user", "secret", "set", "owner", "films_rd_token", CANARY])


def test_providers_key_is_moved_into_the_store_and_the_column_blanked(env):
    db = env.svc.db
    db.execute(
        "INSERT INTO user_providers(user,base_url,api_key_hash,api_key,updated_at) VALUES(?,?,?,?,?)",
        [
            "owner",
            "https://api.example/v1",
            ss.hashlib.sha256(CANARY.encode()).hexdigest(),
            CANARY,
            1.0,
        ],
    )
    providers = env.svc.user_providers
    assert providers.migrate_keys() == 1
    assert db.one("SELECT api_key FROM user_providers WHERE user='owner'")["api_key"] == ""
    assert providers.get_live("owner") == ("https://api.example/v1", CANARY)
    assert (
        providers.describe("owner")["key_sha256"]
        == ss.hashlib.sha256(CANARY.encode()).hexdigest()[:16]
    )
    assert CANARY.encode() not in raw_db_bytes(env)
    assert providers.migrate_keys() == 0  # idempotent
    assert providers.restore_clear_keys() == 1
    assert db.one("SELECT api_key FROM user_providers WHERE user='owner'")["api_key"] == CANARY


def test_a_provider_key_set_after_the_migration_is_stored_encrypted(env):
    providers = env.svc.user_providers
    providers.set("partner", "https://api.example/v1", CANARY)
    assert (
        env.svc.db.one("SELECT api_key FROM user_providers WHERE user='partner'")["api_key"] == ""
    )
    assert providers.get_live("partner")[1] == CANARY
    assert CANARY.encode() not in raw_db_bytes(env)
    assert env.svc.secrets.rev("partner") == 0  # no TV is given it: no revision moves
    assert providers.remove("partner") and providers.get_live("partner") is None
    assert env.svc.secrets.names("partner") == []


def test_without_a_master_key_the_provider_key_stays_as_before(env):
    store = ss.SecretStore(env.svc.db, None)
    providers = type(env.svc.user_providers)(env.svc.db, store)
    providers.set("partner", "https://api.example/v1", "legacy-key-123")
    assert providers.get_live("partner")[1] == "legacy-key-123"
    assert providers.migrate_keys() == 0
