from __future__ import annotations

import time

import httpx

from tests.conftest import anon_client
from utubot.auth import hash_token


async def device_client(env, device="Living room TV", user="owner"):
    """A client authenticated as a paired device of `user`, so the link is logged under that device."""
    code, _ = env.svc.auth.create_pair_code(user)
    token, _ = env.svc.auth.redeem(code, device, "127.0.0.1")
    return httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_web_login_endpoint_requires_authentication(env):
    assert (await anon_client(env).post("/v1/web-login")).status_code == 401


async def test_an_authenticated_client_gets_a_short_lived_single_use_link(env):
    client = await device_client(env)
    try:
        resp = await client.post("/v1/web-login")
        assert resp.status_code == 200
        body = resp.json()
        assert body["token"].startswith("wtl_")
        assert body["expires_in_s"] == env.cfg.security.web_login_ttl_s
    finally:
        await client.aclose()


async def test_opening_the_link_signs_the_browser_in_and_logs_the_device(env):
    client = await device_client(env, "Living room TV")
    try:
        token = (await client.post("/v1/web-login")).json()["token"]

        browser = anon_client(env)
        open_resp = await browser.get("/web-login/" + token)
        assert open_resp.status_code == 302
        assert open_resp.headers["location"] == "/#/home"
        assert "HttpOnly" in open_resp.headers["set-cookie"]

        # The browser is now signed in on the same cookie jar.
        me = await browser.get("/v1/me")
        assert me.status_code == 200 and me.json()["user"] == "owner"

        # The session the browser got records the device that asked for the link.
        row = env.svc.db.one("SELECT agent FROM sessions ORDER BY created_at DESC LIMIT 1")
        assert row["agent"] == "Living room TV"
    finally:
        await client.aclose()


async def test_link_is_single_use(env):
    client = await device_client(env)
    try:
        token = (await client.post("/v1/web-login")).json()["token"]
        browser = anon_client(env)
        assert (await browser.get("/web-login/" + token)).status_code == 302
        assert (await browser.get("/web-login/" + token)).status_code == 400
    finally:
        await client.aclose()


async def test_expired_link_is_refused(env):
    client = await device_client(env)
    try:
        token = (await client.post("/v1/web-login")).json()["token"]
        env.svc.db.execute(
            "UPDATE web_logins SET expires_at=? WHERE token_sha256=?",
            [time.time() - 1, hash_token(token)],
        )
        assert (await anon_client(env).get("/web-login/" + token)).status_code == 400
    finally:
        await client.aclose()


async def test_unknown_link_is_refused(env):
    assert (await anon_client(env).get("/web-login/wtl_notarealtoken")).status_code == 400


async def test_web_login_is_rate_limited_per_address(env):
    env.cfg.security.web_login_attempts_per_ip_per_min = 3
    client = await device_client(env)
    try:
        for _ in range(3):
            assert (await client.post("/v1/web-login")).status_code == 200
        limited = await client.post("/v1/web-login")
        assert limited.status_code == 429 and limited.headers["retry-after"]
    finally:
        await client.aclose()
