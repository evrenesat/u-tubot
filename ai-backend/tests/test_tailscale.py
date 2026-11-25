from __future__ import annotations

from tests.conftest import PASSWORD, anon_client
from utubot.security import is_loopback

LOGIN = "/v1/auth/login"
SESSION = "/v1/auth/session"
HEADER = "Tailscale-User-Login"


def test_is_loopback():
    assert is_loopback("127.0.0.1")
    assert is_loopback("127.42.0.9")
    assert is_loopback("::1")
    assert is_loopback("::ffff:127.0.0.1")
    assert not is_loopback("203.0.113.9")
    assert not is_loopback("::ffff:203.0.113.9")
    assert not is_loopback("localhost")
    assert not is_loopback(None)
    assert not is_loopback("")


def enable(env, users=None):
    env.cfg.auth.tailscale_identity = True
    env.cfg.auth.tailscale_users = users or {"owner@example.com": "owner"}


async def test_tailscale_identity_signs_in_mapped_user(env):
    enable(env, {"Owner@Example.com": "owner"})
    client = anon_client(env, peer="127.0.0.1")
    response = await client.get(SESSION, headers={HEADER: "owner@example.com"})
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == "owner" and body["admin"] is True
    assert body["via"] == "cookie" and len(body["csrf"]) == 64
    assert "set-cookie" in response.headers
    assert "utubot_session=" in response.headers["set-cookie"]
    assert env.svc.db.one("SELECT COUNT(*) c FROM sessions")["c"] == 1
    me = await client.get("/v1/me")
    assert me.status_code == 200 and me.json()["user"] == "owner"
    csrf = body["csrf"]
    write = await client.put(
        "/v1/prompts/default",
        json={"key": "builtin/tldr"},
        headers={"X-CSRF-Token": csrf},
    )
    assert write.status_code == 200


async def test_tailscale_identity_refuses_unmapped_and_non_loopback(env):
    enable(env)
    unknown = anon_client(env, peer="127.0.0.1")
    response = await unknown.get(SESSION, headers={HEADER: "stranger@example.com"})
    assert response.status_code == 401 and "set-cookie" not in response.headers
    missing = anon_client(env, peer="127.0.0.1")
    assert (await missing.get(SESSION)).status_code == 401
    outside = anon_client(env, peer="203.0.113.9")
    response = await outside.get(SESSION, headers={HEADER: "owner@example.com"})
    assert response.status_code == 401 and "set-cookie" not in response.headers
    forwarded = await outside.get(
        SESSION,
        headers={HEADER: "owner@example.com", "X-Forwarded-For": "127.0.0.1"},
    )
    assert forwarded.status_code == 401
    assert env.svc.db.one("SELECT COUNT(*) c FROM sessions")["c"] == 0


async def test_tailscale_identity_is_off_by_default(env):
    env.cfg.auth.tailscale_users = {"owner@example.com": "owner"}
    client = anon_client(env, peer="127.0.0.1")
    assert (await client.get(SESSION, headers={HEADER: "owner@example.com"})).status_code == 401


async def test_tailscale_identity_leaves_public_sign_in_alone(env):
    enable(env)
    env.svc.webauth.set_password("owner", PASSWORD)
    public = anon_client(env, peer="203.0.113.9")
    response = await public.post(LOGIN, json={"username": "owner", "password": PASSWORD})
    assert response.status_code == 200 and response.json()["user"] == "owner"
    assert (await public.get("/v1/me")).status_code == 200
    assert (await public.get(SESSION)).json()["via"] == "cookie"
