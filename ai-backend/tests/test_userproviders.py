from __future__ import annotations

import hashlib

import httpx

from tests.conftest import OTHER_TOKEN, TOKEN, anon_client
from utubot.db import Database
from utubot.userproviders import (
    KEY_HASH_PREFIX,
    USER_PROVIDER,
    PerUserUsage,
    UserBudgetError,
    UserProvider,
    UserProviders,
    bind_call,
    current_user,
    current_user_provider,
    unbind_call,
)

VID = "abcdefghijk"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --- the store -----------------------------------------------------------------------------


def test_set_describe_and_remove_roundtrip():
    db = Database(":memory:")
    ups = UserProviders(db)
    # nothing stored yet
    assert ups.describe("owner") is None and ups.get_live("owner") is None
    doc = ups.set("owner", "https://models.example.com/v1/", "pk-secret")
    # describe shows the host and a short key fingerprint, never the key
    assert doc == {
        "host": "https://models.example.com",
        "key_sha256": _sha("pk-secret")[:KEY_HASH_PREFIX],
    }
    assert ups.get_live("owner") == ("https://models.example.com", "pk-secret")
    # a second set replaces the first
    ups.set("owner", "https://other.example.com", "pk-two")
    assert ups.get_live("owner") == ("https://other.example.com", "pk-two")
    assert ups.remove("owner") is True and ups.remove("owner") is False
    assert ups.describe("owner") is None


def test_set_rejects_a_base_url_without_a_scheme():
    db = Database(":memory:")
    ups = UserProviders(db)
    for bad in ("", "   ", "no-scheme", "ftp", "just-a-token"):
        try:
            ups.set("owner", bad, "pk-secret")
            assert False, f"expected ValueError for {bad!r}"
        except ValueError:
            pass
    assert ups.describe("owner") is None  # nothing was stored


def test_describe_never_returns_the_key():
    db = Database(":memory:")
    ups = UserProviders(db)
    ups.set("owner", "https://h.example.com", "super-secret-key")
    doc = ups.describe("owner")
    assert "super-secret-key" not in str(doc)
    assert doc["host"] == "https://h.example.com"
    assert doc["key_sha256"] == _sha("super-secret-key")[:KEY_HASH_PREFIX]


def test_list_reports_which_users_have_an_upstream():
    db = Database(":memory:")
    ups = UserProviders(db)
    ups.set("owner", "https://h.example.com", "pk")
    ups.set("partner", "https://h.example.com", "pk")
    assert sorted(ups.list()) == ["owner", "partner"]
    ups.remove("partner")
    assert ups.list() == ["owner"]


# --- per-request context -------------------------------------------------------------------


def test_bind_call_scopes_the_user_and_provider():
    assert current_user() is None and current_user_provider() is None
    token = bind_call("owner", UserProvider("https://h.example.com", "pk"))
    assert current_user() == "owner"
    assert current_user_provider() == UserProvider("https://h.example.com", "pk")
    unbind_call(token)
    assert current_user() is None and current_user_provider() is None


def test_user_provider_is_the_router_identity():
    # the LLM router treats a bound upstream as this synthetic provider, not an [llm.providers] key
    assert USER_PROVIDER == "self"


# --- per-user daily usage ------------------------------------------------------------------


def test_per_user_usage_accumulates_and_reports_today():
    db = Database(":memory:")
    usage = PerUserUsage(db)
    assert usage.for_user("owner") == {"cost": 0, "calls": 0, "day": PerUserUsage.today()}
    usage.add("owner", 0.003)
    usage.add("owner", 0.004)
    assert usage.daily("owner") == (0.007, 2)
    assert usage.for_user("owner")["cost"] == 0.007
    # another user's usage does not bleed in
    usage.add("partner", 1.23)
    assert usage.daily("owner") == (0.007, 2)
    assert usage.daily("partner") == (1.23, 1)


def test_per_user_usage_ignores_anonymous_and_zero_calls():
    db = Database(":memory:")
    usage = PerUserUsage(db)
    usage.add(None, 0.5)  # no caller -> nothing stored
    usage.add("owner", 0.0, calls=0)  # a zero call count is dropped
    assert usage.daily("owner") == (0.0, 0)


def test_per_user_usage_for_admin_groups_by_user_over_a_window():
    db = Database(":memory:")
    usage = PerUserUsage(db)
    usage.add("owner", 0.5)
    usage.add("owner", 0.25)
    usage.add("partner", 2.0)
    rows = {r["user"]: r for r in usage.for_admin(7)}
    assert rows["owner"]["cost"] == 0.75 and rows["owner"]["calls"] == 2
    assert rows["partner"]["cost"] == 2.0


def test_user_budget_error_reports_seconds_to_midnight():
    err = UserBudgetError("over budget")
    assert err.status == 429
    assert 1 <= err.retry_after_s <= 86_400


# --- additive schema -----------------------------------------------------------------------


def test_a_database_from_before_the_user_tables_opens(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE transcripts(video_id TEXT PRIMARY KEY, lang TEXT)")
    conn.execute("INSERT INTO transcripts VALUES('vid','en')")
    conn.commit()
    conn.close()
    db = Database(path)
    assert db.one("SELECT lang FROM transcripts WHERE video_id='vid'")["lang"] == "en"
    UserProviders(db).set("owner", "https://h.example.com", "pk")
    PerUserUsage(db).add("owner", 0.5)
    assert db.one("SELECT cost FROM user_usage WHERE user='owner'")["cost"] == 0.5


# --- routes --------------------------------------------------------------------------------


async def test_a_user_can_store_their_own_upstream(env):
    r = await env.client.put(
        "/v1/me/provider",
        json={"base_url": "https://models.example.com/v1/", "api_key": "pk-owner"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["host"] == "https://models.example.com"
    assert body["key_sha256"] == _sha("pk-owner")[:KEY_HASH_PREFIX]
    assert body["configured"] is True
    # the key itself never travels back to the client
    assert "pk-owner" not in body


async def test_their_upstream_routes_the_next_call(env):
    await env.client.put(
        "/v1/me/provider",
        json={"base_url": "https://user-models.example.com", "api_key": "pk-owner"},
    )
    await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})
    # the analysis call authenticated with the user's own key, not the server default
    assert env.llm.requests, "an LLM call should have been made"
    assert all(req["auth"] == "Bearer pk-owner" for req in env.llm.requests)


async def test_get_provider_reports_configured_without_a_key(env):
    assert (await env.client.get("/v1/me/provider")).json() == {"configured": False}
    await env.client.put(
        "/v1/me/provider", json={"base_url": "https://h.example.com", "api_key": "pk"}
    )
    got = (await env.client.get("/v1/me/provider")).json()
    assert got == {"host": "https://h.example.com", "key_sha256": _sha("pk")[:KEY_HASH_PREFIX]}
    assert "pk" not in str(got)


async def test_clearing_the_provider_returns_to_the_server_default(env):
    await env.client.put(
        "/v1/me/provider", json={"base_url": "https://h.example.com", "api_key": "pk-owner"}
    )
    r = await env.client.delete("/v1/me/provider")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert (await env.client.get("/v1/me/provider")).json() == {"configured": False}
    await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})
    # back on the server default: the owner key was no longer sent
    assert all(req["auth"] != "Bearer pk-owner" for req in env.llm.requests)


async def test_a_bad_base_url_is_refused(env):
    r = await env.client.put("/v1/me/provider", json={"base_url": "not-a-url", "api_key": "pk"})
    assert r.status_code == 400
    assert (await env.client.get("/v1/me/provider")).json() == {"configured": False}


async def test_anonymous_cannot_touch_the_provider_route(env):
    r = await anon_client(env).get("/v1/me/provider")
    assert r.status_code == 401


async def test_the_budget_is_enforced_before_a_send(env):
    env.cfg.usage.user_budget_usd = 0.001
    # owner already spent past their ceiling, so the next call is refused before it is sent
    env.svc.db.execute(
        "INSERT INTO user_usage(user,day,cost,calls) VALUES('owner',?,1.0,1)",
        [PerUserUsage.today()],
    )
    r = await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})
    assert r.status_code == 429
    assert r.headers["retry-after"].isdigit() and int(r.headers["retry-after"]) > 0


async def test_a_user_over_budget_leaves_another_user_spending(env):
    env.cfg.usage.user_budget_usd = 0.001
    env.svc.db.execute(
        "INSERT INTO user_usage(user,day,cost,calls) VALUES('owner',?,1.0,1)",
        [PerUserUsage.today()],
    )
    # the owner is blocked...
    assert (
        await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})
    ).status_code == 429
    # ...but a second user, on their own fresh budget, still runs to completion.
    other = httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    try:
        r = await other.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})
        assert r.status_code == 200
    finally:
        await other.aclose()


async def test_admin_users_report_per_user_usage_and_provider(env):
    env.svc.db.execute(
        "INSERT INTO user_usage(user,day,cost,calls) VALUES('owner',?,0.5,2)",
        [PerUserUsage.today()],
    )
    await env.client.put(
        "/v1/me/provider", json={"base_url": "https://h.example.com", "api_key": "pk-owner"}
    )
    users = {u["name"]: u for u in (await env.client.get("/v1/admin/users")).json()["users"]}
    owner = users["owner"]
    assert owner["usage"] == {"cost": 0.5, "calls": 2, "day": PerUserUsage.today()}
    assert owner["provider"] == {
        "host": "https://h.example.com",
        "key_sha256": _sha("pk-owner")[:KEY_HASH_PREFIX],
    }
    # the key itself is never in the admin listing
    assert "pk-owner" not in str(users)
