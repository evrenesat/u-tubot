"""Voice control, backend side (ai/VOICE_CONTROL_PLAN.md checkpoint 1): consent, history, retention,
the `me` and setup additions, and proof that nothing changes for a client while voice is off."""

from __future__ import annotations

import sqlite3

import httpx
import pytest

from tests.conftest import OTHER_TOKEN, TOKEN, anon_client
from utubot import db as dbmod
from utubot.db import Database
from utubot.voice import CONSENT_VERSION, VoiceService

OLD_ME_KEYS = {
    "user",
    "policy",
    "admin",
    "backend_version",
    "prime",
    "class",
    "settings_version",
    "features",
}
OLD_FEATURE_KEYS = {
    "assess",
    "insight",
    "captions",
    "transcribe",
    "cuts",
    "cuts_watched",
    "speech",
    "speech_max_s",
}
OLD_SETUP_KEYS = {"utubot_setup", "name", "backend_url", "update_url", "pairing", "defaults"}
OLD_DEVICE_KEYS = {"id", "user", "device", "created_at", "last_used"}
VOICE_ROUTES = [
    ("GET", "/v1/me/voice", None),
    ("PUT", "/v1/me/voice", {"retention_days": 1}),
    ("PUT", "/v1/me/devices/x/voice", {"enabled": False}),
    ("POST", "/v1/voice/commands", {"text": "pause", "tool": "pause"}),
    ("GET", "/v1/voice/commands", None),
    ("DELETE", "/v1/voice/commands", None),
    ("DELETE", "/v1/voice/commands/1", None),
]


async def pair_device(env, name: str = "Den TV", user_token: str = TOKEN) -> tuple[str, str]:
    """Pair a TV for the owner; returns (device id, device token)."""
    headers = {"Authorization": f"Bearer {user_token}"}
    code = (await env.client.post("/v1/me/pair", headers=headers)).json()["code"]
    paired = await anon_client(env).post("/v1/pair", json={"code": code, "device": name})
    token = paired.json()["token"]
    devices = (await env.client.get("/v1/me/devices", headers=headers)).json()["devices"]
    return next(d["id"] for d in devices if d["device"] == name), token


def as_device(env, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.fixture
def voice_env(env):
    env.cfg.voice.enabled = True
    return env


async def test_old_clients_see_nothing_new_while_voice_is_off(env):
    """The shapes a TV or the extension reads today, replayed against the default configuration."""
    device_id, token = await pair_device(env)
    tv = as_device(env, token)
    me = (await tv.get("/v1/me")).json()
    assert set(me) == OLD_ME_KEYS
    assert set(me["features"]) == OLD_FEATURE_KEYS | {"voice"}
    assert me["features"]["voice"] is False
    assert set(me["features"]) - {"voice"} == OLD_FEATURE_KEYS
    setup = (await anon_client(env).get("/setup.json")).json()
    assert set(setup) == OLD_SETUP_KEYS
    devices = (await env.client.get("/v1/me/devices")).json()["devices"]
    assert all(set(d) == OLD_DEVICE_KEYS for d in devices)
    for method, path, body in VOICE_ROUTES:
        res = await env.client.request(method, path, json=body)
        assert res.status_code == 404, (method, path)
    assert env.svc.db.one("SELECT COUNT(*) n FROM device_voice")["n"] == 0
    assert device_id


async def test_me_and_setup_carry_voice_when_enabled(voice_env):
    env = voice_env
    device_id, token = await pair_device(env, "Den TV")
    tv = as_device(env, token)
    me = (await tv.get("/v1/me")).json()
    assert me["features"]["voice"] is True
    assert me["device"] == {"id": device_id, "name": "Den TV"}
    assert me["voice"] == {
        "enabled": False,
        "listen_mode": "push",
        "speak": False,
        "retention_days": 30,
    }
    owner = (await env.client.get("/v1/me")).json()
    assert owner["device"] is None and owner["voice"]["enabled"] is False
    setup = (await anon_client(env).get("/setup.json")).json()
    assert setup["realtime_url"] == env.cfg.server.public_base_url.rstrip("/") + "/rt"
    assert set(setup) - {"realtime_url"} == OLD_SETUP_KEYS


async def test_consent_lifecycle(voice_env):
    env = voice_env
    device_id, token = await pair_device(env)
    tv = as_device(env, token)
    path = f"/v1/me/devices/{device_id}/voice"

    overview = (await env.client.get("/v1/me/voice")).json()
    assert overview["consent"]["version"] == CONSENT_VERSION and overview["consent"]["text"]
    assert overview["devices"][0]["enabled"] is False

    refused = await env.client.put(path, json={"enabled": True})
    assert refused.status_code == 400 and "consent" in refused.json()["error"]
    wrong = await env.client.put(path, json={"enabled": True, "consent_version": 99})
    assert wrong.status_code == 400
    assert (await tv.get("/v1/me")).json()["voice"]["enabled"] is False

    on = await env.client.put(
        path, json={"enabled": True, "consent_version": CONSENT_VERSION, "speak": True}
    )
    assert on.status_code == 200
    assert on.json()["enabled"] is True and on.json()["speak"] is True
    assert on.json()["consented_at"] is not None
    assert (await tv.get("/v1/me")).json()["voice"] == {
        "enabled": True,
        "listen_mode": "push",
        "speak": True,
        "retention_days": 30,
    }

    mode = await env.client.put(path, json={"listen_mode": "wake"})
    assert mode.json()["listen_mode"] == "wake" and mode.json()["enabled"] is True
    assert (await env.client.put(path, json={"listen_mode": "always"})).status_code == 400

    off = await env.client.put(path, json={"enabled": False})
    assert off.json()["enabled"] is False
    again = await env.client.put(path, json={"enabled": True})
    assert again.status_code == 400  # switching on again shows the text again

    # another user's device, and an unknown one, are not reachable
    other = as_device(env, OTHER_TOKEN)
    assert (await other.put(path, json={"enabled": False})).status_code == 404
    assert (await env.client.put("/v1/me/devices/nope/voice", json={})).status_code == 404


async def test_all_off_switches_every_device_and_asks_for_consent_again(voice_env):
    env = voice_env
    first, _ = await pair_device(env, "Den TV")
    second, _ = await pair_device(env, "Phone")
    for dev in (first, second):
        res = await env.client.put(
            f"/v1/me/devices/{dev}/voice",
            json={"enabled": True, "consent_version": CONSENT_VERSION},
        )
        assert res.json()["enabled"] is True
    off = (await env.client.put("/v1/me/voice", json={"all_off": True})).json()
    assert [d["enabled"] for d in off["devices"]] == [False, False]
    retry = await env.client.put(f"/v1/me/devices/{first}/voice", json={"enabled": True})
    assert retry.status_code == 400


async def test_revoking_a_device_removes_its_consent(voice_env):
    env = voice_env
    device_id, _ = await pair_device(env)
    await env.client.put(
        f"/v1/me/devices/{device_id}/voice",
        json={"enabled": True, "consent_version": CONSENT_VERSION},
    )
    assert env.svc.db.one("SELECT COUNT(*) n FROM device_voice")["n"] == 1
    assert (await env.client.delete(f"/v1/me/devices/{device_id}")).status_code == 200
    assert env.svc.db.one("SELECT COUNT(*) n FROM device_voice")["n"] == 0


async def test_history_lifecycle(voice_env):
    env = voice_env
    device_id, token = await pair_device(env)
    tv = as_device(env, token)
    record = {
        "text": "  make a cut   that keeps the benchmarks ",
        "tool": "cut_custom",
        "args": {"prompt": "benchmarks"},
        "outcome": "ok",
        "marks": {"stt_ms": 410.5, "intent_ms": 220},
    }
    # a device that has not switched voice on cannot file records
    assert (await tv.post("/v1/voice/commands", json=record)).status_code == 403
    await env.client.put(
        f"/v1/me/devices/{device_id}/voice",
        json={"enabled": True, "consent_version": CONSENT_VERSION},
    )
    filed = await tv.post("/v1/voice/commands", json=record)
    assert filed.status_code == 200 and filed.json()["stored"] is True
    second = (await tv.post("/v1/voice/commands", json={"text": "pause", "tool": "pause"})).json()

    listing = (await env.client.get("/v1/voice/commands?limit=10")).json()
    assert listing["retention_days"] == 30
    assert [c["tool"] for c in listing["commands"]] == ["pause", "cut_custom"]
    kept = listing["commands"][1]
    assert kept["text"] == "make a cut that keeps the benchmarks"
    assert kept["args"] == {"prompt": "benchmarks"} and kept["device"] == "Den TV"
    assert kept["marks"] == {"stt_ms": 410.5, "intent_ms": 220}
    assert "audio" not in kept

    # another user sees and deletes nothing of it
    other = as_device(env, OTHER_TOKEN)
    assert (await other.get("/v1/voice/commands")).json()["commands"] == []
    assert (await other.delete(f"/v1/voice/commands/{second['id']}")).status_code == 404
    assert (await other.delete("/v1/voice/commands")).json() == {"deleted": 0}

    assert (await env.client.delete(f"/v1/voice/commands/{second['id']}")).status_code == 200
    assert (await env.client.delete(f"/v1/voice/commands/{second['id']}")).status_code == 404
    assert (await env.client.delete("/v1/voice/commands")).json() == {"deleted": 1}
    assert (await env.client.get("/v1/voice/commands")).json()["commands"] == []


async def test_history_input_is_validated(voice_env):
    env = voice_env
    cases = [
        {"text": "x" * (env.cfg.voice.max_text_chars + 1), "tool": "pause"},
        {"tool": "pause", "outcome": "exploded"},
        {"tool": "pause", "args": {"k": "v" * env.cfg.voice.max_args_bytes}},
        {"tool": "pause", "marks": {"a": -1}},
        {"tool": "pause", "marks": {f"m{i}": 1 for i in range(40)}},
    ]
    for body in cases:
        res = await env.client.post("/v1/voice/commands", json=body)
        assert res.status_code in (400, 413), body
    assert (await env.client.get("/v1/voice/commands?limit=0")).status_code == 400
    assert (await env.client.get("/v1/voice/commands?limit=9999")).status_code == 400
    assert (await env.client.get("/v1/voice/commands")).json()["commands"] == []


async def test_retention_expires_and_zero_keeps_nothing(voice_env):
    env = voice_env
    svc: VoiceService = env.svc.voice
    day = 86400
    now = 1_000_000.0
    for age, text in ((40, "old"), (1, "new")):
        env.svc.db.execute(
            "INSERT INTO voice_commands(user,at,text,tool,outcome) VALUES('owner',?,?,'pause','ok')",
            [now - age * day, text],
        )
    assert [c["text"] for c in svc.commands("owner", 10, now=now)] == ["new"]  # 30 days default
    svc.set_retention("owner", 0, now=now)
    assert svc.commands("owner", 10, now=now) == []
    res = await env.client.post("/v1/voice/commands", json={"text": "pause", "tool": "pause"})
    assert res.json() == {"stored": False, "id": None}
    assert env.svc.db.one("SELECT COUNT(*) n FROM voice_commands")["n"] == 0

    put = await env.client.put("/v1/me/voice", json={"retention_days": 7})
    assert put.json()["retention_days"] == 7
    assert (await env.client.put("/v1/me/voice", json={"retention_days": -1})).status_code == 400
    assert (await env.client.put("/v1/me/voice", json={"retention_days": 9999})).status_code == 400
    kept = await env.client.post("/v1/voice/commands", json={"text": "pause", "tool": "pause"})
    assert kept.json()["stored"] is True
    # lowering the retention drops what is already older
    svc.db.execute("UPDATE voice_commands SET at=at-? WHERE user='owner'", [10 * day])
    assert (await env.client.put("/v1/me/voice", json={"retention_days": 5})).status_code == 200
    assert svc.db.one("SELECT COUNT(*) n FROM voice_commands")["n"] == 0


async def test_filing_is_rate_limited(voice_env):
    env = voice_env
    env.cfg.voice.commands_per_min = 3
    codes = [
        (await env.client.post("/v1/voice/commands", json={"tool": "pause"})).status_code
        for _ in range(4)
    ]
    assert codes == [200, 200, 200, 429]


def test_a_database_from_before_voice_opens_with_its_data_and_gains_the_tables(tmp_path):
    """The live server's database predates the voice tables: opening it adds them, loses nothing."""
    path = tmp_path / "old.db"
    old_schema = dbmod.SCHEMA.split("CREATE TABLE IF NOT EXISTS device_voice")[0]
    conn = sqlite3.connect(path)
    conn.executescript(old_schema)
    conn.execute(
        "INSERT INTO device_tokens(id,user,token_sha256,device,created_at) VALUES('d1','owner','h','Den TV',1)"
    )
    conn.execute(
        "INSERT INTO inbox(user,video_id,kind,created_at) VALUES('owner','abcdefghijk','cut',1)"
    )
    conn.execute(
        "INSERT INTO transcripts(video_id,lang,source,text,fetched_at) VALUES('v','en','asr','kept',1)"
    )
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not {"device_voice", "user_voice", "voice_commands"} & tables
    conn.commit()
    conn.close()

    db = Database(path)
    tables = {r["name"] for r in db.all("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"device_voice", "user_voice", "voice_commands"} <= tables
    assert db.one("SELECT device FROM device_tokens WHERE id='d1'")["device"] == "Den TV"
    assert db.one("SELECT kind FROM inbox")["kind"] == "cut"
    assert db.one("SELECT text FROM transcripts WHERE video_id='v'")["text"] == "kept"
    db.close()
    # a second open is a no-op and the previous revision's INSERTs still work on the result
    again = Database(path)
    again.execute(
        "INSERT INTO device_tokens(id,user,token_sha256,device,created_at) VALUES('d2','owner','h2','Phone',2)"
    )
    assert again.one("SELECT COUNT(*) n FROM device_tokens")["n"] == 2
    again.close()
