from __future__ import annotations

from tests.conftest import OTHER_TOKEN


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


def use_clock(env) -> Clock:
    clock = Clock()
    env.svc.catalog._clock = clock
    return clock


def default_models(body):
    return next(p for p in body["providers"] if p["default"])


async def test_models_requires_auth(env):
    import httpx

    anon = httpx.AsyncClient(transport=env.client._transport, base_url="http://utubot")
    assert (await anon.get("/v1/models")).status_code == 401
    assert (await anon.post("/v1/models/refresh")).status_code == 401


async def test_listing_is_cached_for_five_minutes(env):
    clock = use_clock(env)
    first = (await env.client.get("/v1/models")).json()
    prov = default_models(first)
    assert [m["id"] for m in prov["models"]] == ["fast", "llama3.1:8b", "smart", "worker"]
    assert prov["ok"] is True and first["cache_ttl_s"] == 300
    assert len(env.llm.model_requests) == 1
    await env.client.get("/v1/models")
    clock.t += 299
    await env.client.get("/v1/models")
    assert len(env.llm.model_requests) == 1
    clock.t += 2
    await env.client.get("/v1/models")
    assert len(env.llm.model_requests) == 2


async def test_manual_refresh_bypasses_cache_but_is_rate_limited(env):
    clock = use_clock(env)
    env.cfg.models.refresh_min_interval_s = 10
    await env.client.get("/v1/models")
    r = await env.client.post("/v1/models/refresh")
    assert r.json()["refreshed"] is True and len(env.llm.model_requests) == 2
    again = await env.client.post("/v1/models/refresh")
    assert again.json()["refreshed"] is False and len(env.llm.model_requests) == 2
    clock.t += 11
    assert (await env.client.post("/v1/models/refresh")).json()["refreshed"] is True
    assert len(env.llm.model_requests) == 3


async def test_new_models_are_marked_after_a_refresh(env):
    clock = use_clock(env)
    first = default_models((await env.client.get("/v1/models")).json())
    assert not any(m["new"] for m in first["models"]) and first["added"] == []
    env.llm.models.append("shiny-model-2")
    clock.t += 301
    body = (await env.client.get("/v1/models")).json()
    prov = default_models(body)
    flags = {m["id"]: m["new"] for m in prov["models"]}
    assert flags["shiny-model-2"] is True and flags["fast"] is False
    assert prov["added"] == ["shiny-model-2"]
    clock.t += 301
    again = default_models((await env.client.get("/v1/models")).json())
    assert {m["id"]: m["new"] for m in again["models"]}["shiny-model-2"] is True
    assert again["added"] == []
    clock.t += env.cfg.models.new_for_s + 1
    late = default_models((await env.client.post("/v1/models/refresh")).json())
    assert not any(m["new"] for m in late["models"])


async def test_known_models_survive_a_restart_without_new_marks(env):
    await env.client.get("/v1/models")
    from utubot.modelcatalog import ModelCatalog

    fresh = ModelCatalog(env.cfg, env.svc.db, env.svc.llm)
    body = await fresh.refresh(force=False)
    assert not any(m["new"] for m in default_models(body)["models"])


async def test_provider_failure_is_reported_and_stale_list_kept(env):
    clock = use_clock(env)
    await env.client.get("/v1/models")
    env.llm.models_status = 503
    clock.t += 301
    prov = default_models((await env.client.get("/v1/models")).json())
    assert prov["ok"] is False and prov["stale"] is True and prov["error"] == "http 503"
    assert len(prov["models"]) == 4
    count = len(env.llm.model_requests)
    await env.client.get("/v1/models")
    assert len(env.llm.model_requests) == count
    clock.t += env.cfg.models.error_ttl_s + 1
    env.llm.models_status = 200
    prov = default_models((await env.client.get("/v1/models")).json())
    assert prov["ok"] is True and prov["error"] is None


async def test_no_secrets_in_the_response(env, monkeypatch):
    monkeypatch.setenv("UTUBOT_TEST_KEY", "sk-very-secret-value")
    env.cfg.llm.providers["default"].api_key_env = "UTUBOT_TEST_KEY"
    text = (await env.client.get("/v1/models")).text
    assert "sk-very-secret-value" not in text and "UTUBOT_TEST_KEY" not in text
    prov = default_models(__import__("json").loads(text))
    assert prov["key"] == "configured" and prov["ok"] is True
    assert env.llm.model_requests[-1]["auth"] == "Bearer sk-very-secret-value"
    monkeypatch.delenv("UTUBOT_TEST_KEY")
    env.svc.catalog._entries.clear()
    assert default_models((await env.client.get("/v1/models")).json())["key"] == "missing"


async def test_base_url_only_for_admins_and_without_credentials(env):
    env.cfg.llm.providers["default"].base_url = "http://user:pw-in-url@mock/v1?key=qs-secret"
    admin = env.svc.catalog.listing(admin=True)
    assert admin["providers"][0]["base_url"] == "http://mock/v1"
    assert "pw-in-url" not in str(admin) and "qs-secret" not in str(admin)
    assert "base_url" not in env.svc.catalog.listing(admin=False)["providers"][0]
    env.cfg.llm.providers["default"].base_url = "http://mock/v1"
    other = (
        await env.client.get("/v1/models", headers={"Authorization": f"Bearer {OTHER_TOKEN}"})
    ).json()
    assert "base_url" not in other["providers"][0]


async def test_providers_are_listed_default_first(env):
    env.cfg.llm.providers["alpha"] = env.cfg.llm.providers["default"].model_copy()
    env.cfg.llm.providers["zulu"] = env.cfg.llm.providers["default"].model_copy()
    body = (await env.client.get("/v1/models")).json()
    assert [p["name"] for p in body["providers"]] == ["default", "alpha", "zulu"]
    alpha = body["providers"][1]
    assert alpha["models"][0]["value"] == "alpha:fast"
    assert body["providers"][0]["models"][0]["value"] == "fast"


VID = "abcdefghijk"
ORNITH = "ornith-1.0-35b-oq4e"
TLDR_MARK = "TL;DR as 5 short bullet points"
GLANCE_MARK = "280 characters"


def calls_with(env, mark: str) -> list[dict]:
    return [
        c
        for c in env.llm.calls
        if mark in c["messages"][0]["content"] + c["messages"][1]["content"]
    ]


async def settings_doc(env):
    return (await env.client.get("/v1/me/settings")).json()


async def test_summary_default_falls_back_without_a_match(env):
    """R7: no discovered model matches the glob, so the configured default stands."""
    doc = await settings_doc(env)
    assert doc["settings"]["models"]["summary"] == "worker"
    assert doc["defaults"]["models"]["summary"] == "worker"


async def test_summary_default_is_the_discovered_local_model(env):
    """R7: a discovered `ornith-*` model on the default provider becomes the summary default."""
    env.llm.models.append(ORNITH)
    await env.client.get("/v1/models")
    doc = await settings_doc(env)
    assert doc["settings"]["models"]["summary"] == ORNITH
    assert doc["defaults"]["models"]["summary"] == ORNITH
    assert not doc["overrides"].get("models")


async def test_summary_default_matches_by_name_not_version(env):
    env.llm.models.append("Ornith-2.0-40B-oq5")
    await env.client.get("/v1/models")
    assert (await settings_doc(env))["settings"]["models"]["summary"] == "Ornith-2.0-40B-oq5"


async def test_summary_default_falls_back_when_the_provider_is_unreachable(env):
    env.llm.models.append(ORNITH)
    env.llm.models_status = 503
    await env.client.get("/v1/models")
    doc = await settings_doc(env)
    assert doc["settings"]["models"]["summary"] == "worker"


async def test_summary_default_keeps_the_stale_match_while_the_provider_fails(env):
    clock = use_clock(env)
    env.llm.models.append(ORNITH)
    await env.client.get("/v1/models")
    env.llm.models_status = 503
    clock.t += 301
    prov = default_models((await env.client.get("/v1/models")).json())
    assert prov["ok"] is False and prov["stale"] is True
    doc = await settings_doc(env)
    assert doc["settings"]["models"]["summary"] == ORNITH


async def test_summaries_run_on_the_discovered_default(env):
    env.llm.models.append(ORNITH)
    await env.client.get("/v1/models")
    body = (await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 8000})).json()
    assert body["status"] == "ready"
    call = calls_with(env, TLDR_MARK)[-1]
    assert call["model"] == ORNITH


async def test_user_choice_beats_the_discovered_default(env):
    env.llm.models.append(ORNITH)
    await env.client.get("/v1/models")
    r = await env.client.put("/v1/me/settings", json={"settings": {"models": {"summary": "smart"}}})
    assert r.status_code == 200
    body = (await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 8000})).json()
    assert body["status"] == "ready"
    call = calls_with(env, TLDR_MARK)[-1]
    assert call["model"] == "smart"
    doc = await settings_doc(env)
    assert doc["settings"]["models"]["summary"] == "smart"
    assert doc["overrides"]["models"] == {"summary": "smart"}


async def test_the_panel_keeps_its_configured_model(env):
    """R7 is about the summary task; the glance panel keeps its fast configured model."""
    env.llm.models.append(ORNITH)
    await env.client.get("/v1/models")
    body = (
        await env.client.get(
            f"/v1/videos/{VID}/summary", params={"prompt": "panel", "wait_ms": 8000}
        )
    ).json()
    assert body["status"] == "ready"
    call = calls_with(env, GLANCE_MARK)[-1]
    assert call["model"] == "worker"


async def test_disabling_the_glob_restores_the_configured_default(env):
    env.cfg.models.summary_default_glob = ""
    env.llm.models.append(ORNITH)
    await env.client.get("/v1/models")
    assert (await settings_doc(env))["settings"]["models"]["summary"] == "worker"
