from __future__ import annotations

import asyncio

import httpx

from tests.conftest import OTHER_TOKEN
from utubot.config import UserPolicy

VID = "abcdefghijk"


def put(env, body, path="/v1/me/settings", client=None):
    return (client or env.client).put(path, json=body)


def partner(env) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )


async def test_document_shape_defaults_and_overrides(env):
    doc = (await env.client.get("/v1/me/settings")).json()
    assert doc["user"] == "owner" and doc["version"] == 0 and doc["overrides"] == {}
    s = doc["settings"]
    assert set(s) == {"models", "prompts", "filtering", "summaries", "transcripts", "tv"}
    assert s["transcripts"] == {"auto_transcribe": "on_open", "auto_transcribe_max_minutes": 30}
    assert s["models"] == {
        "glance": "worker",
        "summary": "worker",
        "answer": "worker",
        "triage": "fast",
        "analysis": "worker",
    }
    assert s["prompts"] == {"default": "builtin/tldr", "panel_default": "builtin/glance"}
    assert s["filtering"]["hide_topics"] == ["reaction videos"]
    assert s["filtering"]["mark_only"] is False and s["tv"]["summary_panel"] is False
    assert s["tv"]["summary_delay_ms"] == 700 and s["tv"]["update_checks"] is True
    assert s["summaries"] == {"language": "en", "auto_long": False}
    assert doc["defaults"]["filtering"]["hide_topics"] == ["reaction videos"]
    assert doc["choices"]["auto_transcribe"] == ["off", "on_dwell", "on_open"]


async def test_put_merges_and_versions(env):
    r = await put(
        env,
        {
            "settings": {
                "filtering": {
                    "hide_topics": ["  asmr ", "asmr", "news"],
                    "mark_clickbait_above": 0.5,
                },
                "transcripts": {"auto_transcribe": "on_dwell", "auto_transcribe_max_minutes": 45},
                "tv": {"summary_delay_ms": 1500},
            }
        },
    )
    doc = r.json()
    assert r.status_code == 200 and doc["version"] == 1
    assert doc["settings"]["filtering"]["hide_topics"] == ["asmr", "news"]
    assert doc["settings"]["filtering"]["mark_clickbait_above"] == 0.5
    assert doc["settings"]["transcripts"]["auto_transcribe"] == "on_dwell"
    assert doc["overrides"]["tv"] == {"summary_delay_ms": 1500}
    assert doc["defaults"]["tv"]["summary_delay_ms"] == 700
    second = (await put(env, {"settings": {"tv": {"update_checks": False}}})).json()
    assert second["version"] == 2
    assert second["settings"]["tv"] == {
        "summary_delay_ms": 1500,
        "summary_panel": False,
        "auto_captions": True,
        "update_checks": False,
    }
    assert second["settings"]["filtering"]["hide_topics"] == ["asmr", "news"]
    me = (await env.client.get("/v1/me")).json()
    assert me["settings_version"] == 2 and me["policy"]["hide_topics"] == ["asmr", "news"]


async def test_null_resets_to_default(env):
    await put(
        env, {"settings": {"filtering": {"hide_topics": ["x"]}, "tv": {"summary_panel": True}}}
    )
    doc = (
        await put(
            env, {"settings": {"filtering": {"hide_topics": None}, "tv": {"summary_panel": None}}}
        )
    ).json()
    assert doc["settings"]["filtering"]["hide_topics"] == ["reaction videos"]
    assert doc["settings"]["tv"]["summary_panel"] is False
    assert doc["overrides"] == {}


async def test_validation_errors(env):
    async def bad(settings, **top):
        r = await put(env, {"settings": settings, **top})
        assert r.status_code == 400, r.text
        return r.json()["error"]

    assert "less than or equal" in await bad({"filtering": {"mark_clickbait_above": 5}})
    assert "greater than or equal" in await bad({"filtering": {"hide_clickbait_above": -1}})
    assert "auto_transcribe" in await bad({"transcripts": {"auto_transcribe": "always"}})
    assert "auto_transcribe_max_minutes" in await bad(
        {"transcripts": {"auto_transcribe_max_minutes": 0}}
    )
    assert "summary_delay_ms" in await bad({"tv": {"summary_delay_ms": 999999}})
    assert "at most" in await bad({"filtering": {"mark_topics": [str(i) for i in range(60)]}})
    assert "unknown settings section" in await bad({"nope": {"a": 1}})
    assert "unknown setting filtering.nope" in await bad({"filtering": {"nope": 1}})
    assert "unknown model task" in await bad({"models": {"captions": "x"}})
    assert "unknown prompt" in await bad({"prompts": {"default": "builtin/missing"}})
    assert (await put(env, {"nothing": 1})).status_code == 400
    assert (await put(env, {"settings": {"models": {"summary": 7}}})).status_code == 400
    assert (await env.client.get("/v1/me/settings")).json()["version"] == 0


async def test_version_conflict(env):
    first = (await put(env, {"settings": {"tv": {"summary_delay_ms": 900}}})).json()
    stale = await put(env, {"version": 0, "settings": {"tv": {"summary_delay_ms": 100}}})
    assert stale.status_code == 409 and stale.json()["version"] == 1
    ok = await put(
        env, {"version": first["version"], "settings": {"tv": {"summary_delay_ms": 100}}}
    )
    assert ok.status_code == 200 and ok.json()["version"] == 2


async def test_models_validated_against_live_list(env):
    ok = await put(env, {"settings": {"models": {"summary": "smart", "triage": "fast"}}})
    assert ok.status_code == 200 and ok.json()["settings"]["models"]["summary"] == "smart"
    assert ok.json()["overrides"]["models"] == {"summary": "smart", "triage": "fast"}
    bad = await put(env, {"settings": {"models": {"answer": "gpt-nope"}}})
    assert bad.status_code == 400 and bad.json()["unlisted"] == "gpt-nope"
    forced = await put(
        env, {"allow_unlisted_models": True, "settings": {"models": {"answer": "gpt-nope"}}}
    )
    assert forced.json()["settings"]["models"]["answer"] == "gpt-nope"
    reset = await put(env, {"settings": {"models": {"summary": None}}})
    assert reset.json()["settings"]["models"]["summary"] == "worker"
    assert "summary" not in reset.json()["overrides"]["models"]
    env.llm.models_status = 500
    env.svc.catalog._entries.clear()
    down = await put(env, {"settings": {"models": {"glance": "fast"}}})
    assert down.status_code == 400 and "unavailable" in down.json()["error"]
    assert (
        await put(env, {"allow_unlisted_models": True, "settings": {"models": {"glance": "fast"}}})
    ).status_code == 200


async def test_provider_prefix_is_checked_against_that_provider(env):
    env.cfg.llm.providers["other"] = env.cfg.llm.providers["default"].model_copy()
    env.svc.llm.limiter("other")
    ok = await put(env, {"settings": {"models": {"summary": "other:smart"}}})
    assert ok.status_code == 200
    bad = await put(env, {"settings": {"models": {"summary": "other:missing"}}})
    assert bad.status_code == 400


async def test_user_model_applies_to_calls_and_prompt_model_wins(env):
    await put(env, {"settings": {"models": {"summary": "smart", "glance": "fast"}}})
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert r.json()["status"] == "ready"
    assert env.llm.calls[-1]["model"] == "smart"
    r = await env.client.get(
        f"/v1/videos/{VID}/summary", params={"prompt": "panel", "wait_ms": 5000}
    )
    assert r.json()["status"] == "ready" and env.llm.calls[-1]["model"] == "fast"
    other = partner(env)
    r = await other.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert r.json()["status"] == "ready" and env.llm.calls[-1]["model"] == "worker"
    n = len(env.llm.calls)
    await other.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert len(env.llm.calls) == n
    pset = {
        "tubeai_prompt_set": 1,
        "id": "mine",
        "name": "Mine",
        "prompts": [{"id": "p", "label": "P", "template": "{transcript}", "model": "pinned-model"}],
    }
    assert (await env.client.put("/v1/prompts/sets/mine", json=pset)).status_code == 200
    r = await env.client.get(
        f"/v1/videos/{VID}/summary", params={"prompt": "mine/p", "wait_ms": 5000}
    )
    assert r.json()["status"] == "ready" and env.llm.calls[-1]["model"] == "pinned-model"
    adhoc = await env.client.post(
        f"/v1/videos/{VID}/summary", json={"prompt_text": "Say hi {transcript}", "wait_ms": 5000}
    )
    assert adhoc.json()["status"] == "ready" and env.llm.calls[-1]["model"] == "smart"
    ask = await env.client.post(f"/v1/videos/{VID}/ask", json={"question": "why?", "wait_ms": 5000})
    assert ask.json()["status"] == "ready" and env.llm.calls[-1]["model"] == "worker"
    await put(
        env, {"allow_unlisted_models": True, "settings": {"models": {"answer": "my-answer-model"}}}
    )
    ask = await env.client.post(
        f"/v1/videos/{VID}/ask", json={"question": "why 2?", "wait_ms": 5000}
    )
    assert env.llm.calls[-1]["model"] == "my-answer-model"
    await put(
        env,
        {
            "allow_unlisted_models": True,
            "settings": {"models": {"analysis": "deep-one", "triage": "tri-one"}},
        },
    )
    ins = await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})
    assert ins.json()["status"] == "ready" and env.llm.calls[-1]["model"] == "deep-one"
    res = await env.client.post(
        "/v1/assess",
        json={"videos": [{"video_id": "zzzzzzzzzzz", "title": "plain title"}], "wait_ms": 3000},
    )
    assert res.status_code == 200
    assert any(c["model"] == "tri-one" for c in env.llm.calls)


async def test_precedence_runtime_over_user_over_default_over_server(env):
    env.cfg.default_policy = UserPolicy(mark_topics=["default-mark"], language="de")
    env.cfg.users[1] = env.cfg.users[1].model_copy(update={"policy": UserPolicy(language="fr")})
    # users are resolved at load time; resolve again the way load_config does
    from utubot.config import resolve_users

    env.cfg.declared_users = [
        env.cfg.users[0],
        env.cfg.users[1].model_copy(update={"policy": UserPolicy(language="fr")}),
    ]
    env.cfg.users = resolve_users(env.cfg, env.cfg.declared_users)
    other = partner(env)
    s = (await other.get("/v1/me/settings")).json()
    assert s["settings"]["summaries"]["language"] == "fr"
    assert s["settings"]["filtering"]["mark_topics"] == ["default-mark"]
    await other.put("/v1/me/settings", json={"settings": {"summaries": {"language": "es"}}})
    s = (await other.get("/v1/me/settings")).json()
    assert (
        s["settings"]["summaries"]["language"] == "es"
        and s["defaults"]["summaries"]["language"] == "fr"
    )
    await other.put("/v1/me/settings", json={"settings": {"summaries": {"language": None}}})
    assert (await other.get("/v1/me/settings")).json()["settings"]["summaries"]["language"] == "fr"
    # server settings: a field left None follows the server
    env.cfg.setup.defaults.mark_only = True
    env.cfg.summary.auto_long = True
    d = (await other.get("/v1/me/settings")).json()["settings"]
    assert d["filtering"]["mark_only"] is True and d["summaries"]["auto_long"] is True
    await other.put("/v1/me/settings", json={"settings": {"filtering": {"mark_only": False}}})
    assert (await other.get("/v1/me/settings")).json()["settings"]["filtering"][
        "mark_only"
    ] is False


async def test_legacy_policy_route_shares_the_store_and_bumps_version(env):
    r = await env.client.put("/v1/me/policy", json={"hide_topics": ["legacy"]})
    assert r.status_code == 200
    doc = (await env.client.get("/v1/me/settings")).json()
    assert doc["settings"]["filtering"]["hide_topics"] == ["legacy"] and doc["version"] == 1
    assert doc["overrides"]["filtering"] == {"hide_topics": ["legacy"]}
    bad = await env.client.put("/v1/me/policy", json={"mark_clickbait_above": 9})
    assert bad.status_code == 400
    await env.client.put("/v1/prompts/panel-default", json={"key": "builtin/tldr"})
    doc = (await env.client.get("/v1/me/settings")).json()
    assert doc["version"] == 2 and doc["settings"]["prompts"]["panel_default"] == "builtin/tldr"
    assert doc["overrides"]["prompts"] == {"panel_default": "builtin/tldr"}


async def test_prompt_defaults_through_settings(env):
    doc = (
        await put(
            env,
            {
                "settings": {
                    "prompts": {"default": "builtin/worth-it", "panel_default": "builtin/tldr"}
                }
            },
        )
    ).json()
    assert doc["settings"]["prompts"] == {
        "default": "builtin/worth-it",
        "panel_default": "builtin/tldr",
    }
    listing = (await env.client.get("/v1/prompts")).json()
    assert listing["default"] == "builtin/worth-it" and listing["panel_default"] == "builtin/tldr"
    doc = (
        await put(env, {"settings": {"prompts": {"default": None, "panel_default": None}}})
    ).json()
    assert doc["settings"]["prompts"] == {
        "default": "builtin/tldr",
        "panel_default": "builtin/glance",
    }
    assert "prompts" not in doc["overrides"]
    env.cfg.summary.panel_prompt = "builtin/answer-title"
    doc = (await env.client.get("/v1/me/settings")).json()
    assert doc["defaults"]["prompts"]["panel_default"] == "builtin/answer-title"


async def test_admin_settings_routes(env):
    other = partner(env)
    assert (await other.get("/v1/users/partner/settings")).status_code == 403
    assert (await other.put("/v1/users/partner/settings", json={"settings": {}})).status_code == 403
    assert (await env.client.get("/v1/users/ghost/settings")).status_code == 404
    got = await env.client.get("/v1/users/partner/settings")
    assert got.status_code == 200 and got.json()["user"] == "partner"
    r = await env.client.put(
        "/v1/users/partner/settings",
        json={"settings": {"filtering": {"hide_topics": ["set by admin"]}}},
    )
    assert r.status_code == 200 and r.json()["version"] == 1
    assert (await other.get("/v1/me/settings")).json()["settings"]["filtering"]["hide_topics"] == [
        "set by admin"
    ]
    assert (await env.client.get("/v1/me/settings")).json()["settings"]["filtering"][
        "hide_topics"
    ] == ["reaction videos"]
    bad = await env.client.put(
        "/v1/users/partner/settings", json={"settings": {"tv": {"update_checks": "x"}}}
    )
    assert bad.status_code == 400


async def test_invalid_stored_override_never_breaks_requests(env):
    env.svc.db.execute(
        "INSERT OR REPLACE INTO policy_overrides(user,json,version,updated_at) VALUES(?,?,?,?)",
        ["owner", '{"mark_clickbait_above": 7, "hide_topics": ["ok"]}', 3, 1.0],
    )
    doc = (await env.client.get("/v1/me/settings")).json()
    assert doc["settings"]["filtering"]["mark_clickbait_above"] == 0.6
    assert doc["settings"]["filtering"]["hide_topics"] == ["ok"]


async def test_defaults_come_from_config_files(tmp_path):
    from utubot.app import create_app
    from utubot.auth import append_user, hash_token
    from utubot.config import load_config

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f"""
[server]
data_dir = "{tmp_path}/d"
[llm.providers.default]
base_url = "http://mock/v1"
[llm.summary]
model = "base-summary"
[llm.glance]
model = "base-glance"
provider = "default"
[summary]
auto_long = true
[setup.defaults]
mark_only = true
summary_panel = true
[default_policy]
auto_transcribe = "off"
auto_transcribe_max_minutes = 12
summary_delay_ms = 1200
update_checks = false
[default_policy.models]
answer = "answer-for-everyone"
[[users]]
name = "owner"
[users.policy]
auto_transcribe = "on_dwell"
"""
    )
    append_user(tmp_path / "d" / "users.toml", "viewer", hash_token("utb_viewer"), admin=True)
    cfg = load_config(cfg_path)
    app = create_app(cfg)
    async with app.router.lifespan_context(app):
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://utubot",
            headers={"Authorization": "Bearer utb_viewer"},
        )
        s = (await client.get("/v1/me/settings")).json()["settings"]
        assert s["transcripts"] == {"auto_transcribe": "off", "auto_transcribe_max_minutes": 12}
        assert s["tv"] == {
            "summary_delay_ms": 1200,
            "summary_panel": True,
            "auto_captions": True,
            "update_checks": False,
        }
        assert s["filtering"]["mark_only"] is True and s["summaries"]["auto_long"] is True
        assert s["models"]["answer"] == "answer-for-everyone"
        assert (
            s["models"]["summary"] == "base-summary"
            and s["models"]["glance"] == "default:base-glance"
        )
        await client.put(
            "/v1/me/settings",
            json={
                "allow_unlisted_models": True,
                "settings": {
                    "transcripts": {"auto_transcribe": "on_open"},
                    "models": {"summary": "mine"},
                },
            },
        )
        merged = (await client.get("/v1/me/settings")).json()
        assert merged["settings"]["models"]["answer"] == "answer-for-everyone"
        assert merged["settings"]["models"]["summary"] == "mine"
        assert merged["overrides"]["models"] == {"summary": "mine"}
        doc = (await client.get("/v1/me/settings")).json()
        assert doc["settings"]["transcripts"]["auto_transcribe"] == "on_open"
        assert doc["defaults"]["transcripts"]["auto_transcribe"] == "off"
        await client.aclose()


def test_policy_table_is_migrated_in_place(tmp_path):
    import sqlite3

    from utubot.db import Database

    path = tmp_path / "old.sqlite"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE policy_overrides(user TEXT PRIMARY KEY, json TEXT NOT NULL)")
    old.execute("INSERT INTO policy_overrides VALUES('owner', '{\"hide_topics\": [\"x\"]}')")
    old.commit()
    old.close()
    db = Database(path)
    row = db.one("SELECT json, version, updated_at FROM policy_overrides WHERE user='owner'")
    assert (
        row["json"] == '{"hide_topics": ["x"]}' and row["version"] == 0 and row["updated_at"] == 0
    )
    Database(path).close()


async def test_unlisted_models_are_for_admins_only(env):
    other = partner(env)
    denied = await other.put(
        "/v1/me/settings",
        json={"allow_unlisted_models": True, "settings": {"models": {"summary": "gpt-nope"}}},
    )
    assert denied.status_code == 403 and "admins" in denied.json()["error"]
    assert (await other.get("/v1/me/settings")).json()["version"] == 0
    listed = await other.put("/v1/me/settings", json={"settings": {"models": {"summary": "smart"}}})
    assert listed.status_code == 200
    unlisted = await other.put(
        "/v1/me/settings", json={"settings": {"models": {"summary": "gpt-nope"}}}
    )
    assert unlisted.status_code == 400 and unlisted.json()["unlisted"] == "gpt-nope"
    # an admin may, for themselves and for another user
    ok = await env.client.put(
        "/v1/users/partner/settings",
        json={"allow_unlisted_models": True, "settings": {"models": {"summary": "gpt-nope"}}},
    )
    assert ok.status_code == 200 and ok.json()["settings"]["models"]["summary"] == "gpt-nope"


async def test_legacy_policy_route_cannot_smuggle_models_for_users(env):
    other = partner(env)
    denied = await other.put("/v1/me/policy", json={"models": {"summary": "gpt-nope"}})
    assert denied.status_code == 403
    assert (await other.put("/v1/me/policy", json={"hide_topics": ["fine"]})).status_code == 200
    assert (await other.get("/v1/me/settings")).json()["settings"]["models"]["summary"] == "worker"
    admin = await env.client.put("/v1/me/policy", json={"models": {"summary": "anything"}})
    assert admin.status_code == 200


async def test_browser_sessions_must_send_the_settings_version(env):
    from tests.conftest import PASSWORD, anon_client

    env.svc.webauth.set_password("owner", PASSWORD)
    client = anon_client(env)
    login = await client.post("/v1/auth/login", json={"username": "owner", "password": PASSWORD})
    headers = {"X-CSRF-Token": login.json()["csrf"]}
    body = {"settings": {"tv": {"summary_delay_ms": 900}}}
    missing = await client.put("/v1/me/settings", json=body, headers=headers)
    assert missing.status_code == 428 and missing.json()["version"] == 0
    assert (await client.get("/v1/me/settings")).json()["version"] == 0
    ok = await client.put("/v1/me/settings", json={"version": 0, **body}, headers=headers)
    assert ok.status_code == 200 and ok.json()["version"] == 1
    admin_missing = await client.put("/v1/users/partner/settings", json=body, headers=headers)
    assert admin_missing.status_code == 428
    admin_ok = await client.put(
        "/v1/users/partner/settings", json={"version": 0, **body}, headers=headers
    )
    assert admin_ok.status_code == 200
    # scripts and the CLI use a bearer token and may leave it out (a partial merge)
    assert (await env.client.put("/v1/me/settings", json=body)).status_code == 200


async def test_two_writers_from_the_same_version_cannot_both_win(env):
    # a model name makes the update await the catalog, which is where the old code let both through
    first = {
        "version": 0,
        "settings": {"models": {"summary": "smart"}, "tv": {"summary_delay_ms": 100}},
    }
    second = {
        "version": 0,
        "settings": {"models": {"answer": "fast"}, "tv": {"summary_delay_ms": 200}},
    }
    results = await asyncio.gather(
        env.client.put("/v1/me/settings", json=first),
        env.client.put("/v1/me/settings", json=second),
    )
    assert sorted(r.status_code for r in results) == [200, 409]
    loser = next(r for r in results if r.status_code == 409)
    assert loser.json()["version"] == 1
    doc = (await env.client.get("/v1/me/settings")).json()
    assert doc["version"] == 1
    winner = next(r for r in results if r.status_code == 200).json()
    assert doc["settings"] == winner["settings"]
    retry = await env.client.put("/v1/me/settings", json={**second, "version": 1})
    assert retry.status_code == 200 and retry.json()["version"] == 2


def test_write_override_is_a_compare_and_set(env):
    from utubot.auth import VersionConflict

    auth = env.svc.auth
    assert auth.write_override("owner", {"hide_topics": ["a"]}, expected=0) == 1
    try:
        auth.write_override("owner", {"hide_topics": ["b"]}, expected=0)
        raise AssertionError("a stale writer was accepted")
    except VersionConflict as exc:
        assert exc.version == 1
    assert auth.policy_override("owner") == {"hide_topics": ["a"]}
    assert auth.write_override("owner", {"hide_topics": ["c"]}, expected=1) == 2
    assert auth.write_override("owner", {"hide_topics": ["d"]}) == 3
