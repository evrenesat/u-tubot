from __future__ import annotations

import time

from tests.conftest import OTHER_TOKEN, PASSWORD, TOKEN, anon_client
from utubot.passwords import hash_password, verify_password
from utubot.webauth import csrf_token

LOGIN = "/v1/auth/login"


async def sign_in(env, client=None, user="owner", password=PASSWORD):
    if not env.svc.webauth.has_password(user):
        env.svc.webauth.set_password(user, PASSWORD)
    client = client or anon_client(env)
    resp = await client.post(LOGIN, json={"username": user, "password": password})
    return client, resp


def test_scrypt_hash_roundtrip_and_params(cfg):
    stored = hash_password("s3cret-pass-word", cfg.security)
    assert stored.startswith("scrypt$1024$8$1$")
    assert verify_password("s3cret-pass-word", stored)
    assert not verify_password("s3cret-pass-wor", stored)
    assert not verify_password("x", "scrypt$garbage")
    assert not verify_password("x", "md5$1$1$1$AAAA$AAAA")
    assert hash_password("s3cret-pass-word", cfg.security) != stored


async def test_password_login_sets_hardened_cookie(env):
    client, resp = await sign_in(env)
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"] == "owner" and body["admin"] is True and len(body["csrf"]) == 64
    cookie = resp.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
    assert f"Max-Age={30 * 86400}" in cookie
    assert "Secure" not in cookie
    stored = env.svc.db.one("SELECT id_sha256 FROM sessions")["id_sha256"]
    assert stored not in cookie and cookie.split("=")[1].split(";")[0] not in stored
    me = await client.get("/v1/me")
    assert me.status_code == 200 and me.json()["user"] == "owner"


async def test_cookie_secure_behind_trusted_https_proxy(env):
    env.cfg.security.trusted_proxies = ["127.0.0.1"]
    env.svc.webauth.set_password("owner", PASSWORD)
    body = {"username": "owner", "password": PASSWORD}
    proxy = anon_client(env, peer="127.0.0.1")
    resp = await proxy.post(LOGIN, json=body, headers={"X-Forwarded-Proto": "https"})
    assert "Secure" in resp.headers["set-cookie"]
    resp = await proxy.post(LOGIN, json=body, headers={"X-Forwarded-Proto": "http"})
    assert "Secure" not in resp.headers["set-cookie"]
    stranger = anon_client(env, peer="203.0.113.9")
    resp = await stranger.post(LOGIN, json=body, headers={"X-Forwarded-Proto": "https"})
    assert "Secure" not in resp.headers["set-cookie"]
    direct = anon_client(env, base_url="https://utubot")
    resp = await direct.post(LOGIN, json=body)
    assert "Secure" in resp.headers["set-cookie"]


async def test_wrong_password_and_unknown_user_look_alike(env):
    env.svc.webauth.set_password("owner", PASSWORD)
    client = anon_client(env)
    a = await client.post(LOGIN, json={"username": "owner", "password": "wrong-password-1"})
    b = await client.post(LOGIN, json={"username": "nobody", "password": "wrong-password-1"})
    c = await client.post(LOGIN, json={"username": "partner", "password": "wrong-password-1"})
    assert a.status_code == b.status_code == c.status_code == 401
    assert a.json() == b.json() == c.json() == {"error": "invalid username or password"}
    assert "set-cookie" not in a.headers
    assert (await client.post(LOGIN, json={})).status_code == 400


async def test_token_login_exchanges_token_for_session(env):
    client = anon_client(env)
    bad = await client.post(LOGIN, json={"token": "utb_nope"})
    assert bad.status_code == 401
    ok = await client.post(LOGIN, json={"token": OTHER_TOKEN})
    assert ok.status_code == 200 and ok.json()["user"] == "partner" and ok.json()["admin"] is False
    me = await client.get("/v1/me")
    assert me.json()["user"] == "partner"
    session = await client.get("/v1/auth/session")
    assert session.json()["via"] == "cookie" and session.json()["csrf"]


async def test_csrf_required_for_cookie_mutations_not_for_bearer(env):
    client, resp = await sign_in(env)
    csrf = resp.json()["csrf"]
    body = {"key": "builtin/tldr"}
    assert (await client.get("/v1/prompts")).status_code == 200
    no_header = await client.put("/v1/prompts/default", json=body)
    assert no_header.status_code == 403 and "csrf" in no_header.json()["error"]
    wrong = await client.put("/v1/prompts/default", json=body, headers={"X-CSRF-Token": "0" * 64})
    assert wrong.status_code == 403
    ok = await client.put("/v1/prompts/default", json=body, headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200
    bearer = await anon_client(env).put(
        "/v1/prompts/default", json=body, headers={"Authorization": f"Bearer {TOKEN}"}
    )
    assert bearer.status_code == 200
    other_session = await anon_client(env).post(LOGIN, json={"token": OTHER_TOKEN})
    foreign = await client.put(
        "/v1/prompts/default", json=body, headers={"X-CSRF-Token": other_session.json()["csrf"]}
    )
    assert foreign.status_code == 403


async def test_csrf_origin_check(env):
    client, resp = await sign_in(env)
    headers = {"X-CSRF-Token": resp.json()["csrf"]}
    body = {"key": "builtin/tldr"}
    evil = await client.put(
        "/v1/prompts/default", json=body, headers={**headers, "Origin": "https://evil.example"}
    )
    assert evil.status_code == 403 and evil.json()["error"] == "cross-origin request refused"
    same = await client.put(
        "/v1/prompts/default", json=body, headers={**headers, "Origin": "http://utubot"}
    )
    assert same.status_code == 200
    login_evil = await anon_client(env).post(
        LOGIN, json={"token": TOKEN}, headers={"Origin": "https://evil.example"}
    )
    assert login_evil.status_code == 403


async def test_logout_ends_session(env):
    client, resp = await sign_in(env)
    csrf = resp.json()["csrf"]
    assert (await client.post("/v1/auth/logout")).status_code == 403
    out = await client.post("/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 200
    assert (await client.get("/v1/me")).status_code == 401
    assert env.svc.db.one("SELECT COUNT(*) c FROM sessions")["c"] == 0


async def test_session_is_sliding_30_days(env):
    client, resp = await sign_in(env)
    db = env.svc.db
    row = db.one("SELECT id_sha256, expires_at FROM sessions")
    first_expiry = row["expires_at"]
    assert abs(first_expiry - time.time() - 30 * 86400) < 5
    fresh = await client.get("/v1/me")
    assert "set-cookie" not in fresh.headers
    db.execute(
        "UPDATE sessions SET last_seen=?, expires_at=? WHERE id_sha256=?",
        [time.time() - 7200, time.time() + 86400, row["id_sha256"]],
    )
    again = await client.get("/v1/me")
    assert again.status_code == 200 and "Max-Age=2592000" in again.headers["set-cookie"]
    assert db.one("SELECT expires_at FROM sessions")["expires_at"] > time.time() + 29 * 86400
    db.execute("UPDATE sessions SET expires_at=?", [time.time() - 1])
    assert (await client.get("/v1/me")).status_code == 401


async def test_failed_logins_lock_out_even_the_right_password(env):
    env.svc.webauth.set_password("partner", PASSWORD)
    client = anon_client(env)
    for _ in range(env.cfg.security.login_lockout_failures):
        r = await client.post(LOGIN, json={"username": "partner", "password": "wrong-password-1"})
        assert r.status_code in (401, 429)
    locked = await client.post(LOGIN, json={"username": "partner", "password": PASSWORD})
    assert locked.status_code == 429 and int(locked.headers["retry-after"]) > 0
    assert "set-cookie" not in locked.headers
    env.svc.db.execute("UPDATE login_failures SET ts=ts-100000")
    assert (
        await client.post(LOGIN, json={"username": "partner", "password": PASSWORD})
    ).status_code == 200


async def test_lockout_is_per_address_and_per_account(env):
    env.cfg.security.trusted_proxies = ["127.0.0.1"]
    env.svc.webauth.set_password("partner", PASSWORD)
    proxy = anon_client(env, peer="127.0.0.1")

    def attempt(ip, password="wrong-password-1", name="partner"):
        return proxy.post(
            LOGIN,
            json={"username": name, "password": password},
            headers={"X-Forwarded-For": ip},
        )

    for _ in range(env.cfg.security.login_lockout_failures):
        await attempt("198.51.100.7")
    assert (await attempt("198.51.100.7", PASSWORD)).status_code == 429
    assert (await attempt("198.51.100.8", PASSWORD)).status_code == 200
    env.svc.db.execute("DELETE FROM login_failures")
    for i in range(env.cfg.security.login_user_lockout_failures):
        await attempt(f"192.0.2.{i + 1}")
    assert (await attempt("192.0.2.200", PASSWORD)).status_code == 429


async def test_failed_token_logins_lock_the_address(env):
    client = anon_client(env)
    for _ in range(env.cfg.security.login_lockout_failures):
        await client.post(LOGIN, json={"token": "utb_guess"})
    assert (await client.post(LOGIN, json={"token": TOKEN})).status_code == 429


async def test_change_password_needs_current_and_ends_other_sessions(env):
    client, resp = await sign_in(env)
    other, _ = await sign_in(env, anon_client(env))
    csrf = resp.json()["csrf"]
    path = "/v1/me/password"
    new = "another long password 42"
    weak = await client.put(
        path,
        json={"current_password": PASSWORD, "new_password": "short"},
        headers={"X-CSRF-Token": csrf},
    )
    assert weak.status_code == 400 and "at least" in weak.json()["error"]
    wrong = await client.put(
        path,
        json={"current_password": "nope-nope-nope", "new_password": new},
        headers={"X-CSRF-Token": csrf},
    )
    assert wrong.status_code == 403
    ok = await client.put(
        path,
        json={"current_password": PASSWORD, "new_password": new},
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status_code == 200 and ok.json()["csrf"] != csrf
    assert (await client.get("/v1/me")).status_code == 200
    assert (await other.get("/v1/me")).status_code == 401
    fresh = anon_client(env)
    assert (
        await fresh.post(LOGIN, json={"username": "owner", "password": PASSWORD})
    ).status_code == 401
    assert (await fresh.post(LOGIN, json={"username": "owner", "password": new})).status_code == 200


async def test_bearer_can_set_first_password(env):
    r = await env.client.put("/v1/me/password", json={"new_password": PASSWORD})
    assert r.status_code == 200 and r.json()["csrf"] is None
    assert env.svc.webauth.has_password("owner")


async def test_session_endpoint_and_csrf_value(env):
    client, resp = await sign_in(env)
    info = (await client.get("/v1/auth/session")).json()
    assert info["via"] == "cookie" and info["csrf"] == resp.json()["csrf"]
    bearer = (await env.client.get("/v1/auth/session")).json()
    assert bearer["via"] == "token" and bearer["csrf"] is None
    assert csrf_token("x") != csrf_token("y")


async def test_cli_user_passwd_and_user_add_validation(tmp_path, capsys, monkeypatch):
    import io

    from utubot.cli import main

    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\ndata_dir = "{tmp_path}/d"\n[security]\nscrypt_n = 1024\n'
        '[[users]]\nname = "owner"\nadmin = true\n'
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("a long enough password\n"))
    assert main(["--config", str(cfg_path), "user", "passwd", "owner", "--stdin"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert main(["--config", str(cfg_path), "user", "passwd", "owner", "--stdin"]) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO("a long enough password\n"))
    assert main(["--config", str(cfg_path), "user", "passwd", "ghost", "--stdin"]) == 1
    assert main(["--config", str(cfg_path), "user", "add", "bad name"]) == 1
    out = capsys.readouterr()
    assert "password set for owner" in out.out and "at least" in out.err
    from utubot.config import load_config
    from utubot.db import Database
    from utubot.passwords import verify_password as check

    db = Database(load_config(cfg_path).db_path)
    row = db.one("SELECT hash FROM user_passwords WHERE user='owner'")
    assert check("a long enough password", row["hash"])
    assert "a long enough password" not in row["hash"]


async def test_odd_csrf_and_origin_headers_are_refused_not_crashed(env):
    client, resp = await sign_in(env)
    body = {"key": "builtin/tldr"}
    for headers in (
        {"X-CSRF-Token": b"caf\xe9" * 16},
        {"X-CSRF-Token": resp.json()["csrf"], "Origin": "http://[::1"},
        {"X-CSRF-Token": resp.json()["csrf"], "Origin": "null"},
    ):
        res = await client.put("/v1/prompts/default", json=body, headers=headers)
        assert res.status_code == 403, headers


async def test_password_change_keeps_the_browser_signed_in_even_when_every_request_refreshes(env):
    env.cfg.security.session_refresh_s = 0
    client, resp = await sign_in(env)
    csrf = resp.json()["csrf"]
    new = "another long password 42"
    ok = await client.put(
        "/v1/me/password",
        json={"current_password": PASSWORD, "new_password": new},
        headers={"X-CSRF-Token": csrf},
    )
    assert ok.status_code == 200
    cookies = [v for v in ok.headers.get_list("set-cookie") if v.startswith("utubot_session=")]
    assert len(cookies) == 1, cookies
    fresh = ok.json()["csrf"]
    assert fresh and fresh != csrf
    me = await client.get("/v1/me")
    assert me.status_code == 200 and me.json()["user"] == "owner"
    again = await client.put(
        "/v1/prompts/default", json={"key": "builtin/tldr"}, headers={"X-CSRF-Token": fresh}
    )
    assert again.status_code == 200
    assert env.svc.webauth.user_sessions("owner") == 1


async def test_admin_setting_own_password_keeps_the_session(env):
    env.cfg.security.session_refresh_s = 0
    client, resp = await sign_in(env)
    other, _ = await sign_in(env, anon_client(env))
    done = await client.put(
        "/v1/users/owner/password",
        json={"password": "yet another long password"},
        headers={"X-CSRF-Token": resp.json()["csrf"]},
    )
    assert done.status_code == 200 and done.json()["csrf"]
    assert (
        len([v for v in done.headers.get_list("set-cookie") if v.startswith("utubot_session=")])
        == 1
    )
    assert (await client.get("/v1/me")).status_code == 200
    assert (await other.get("/v1/me")).status_code == 401
    # someone else's password: the admin's own session is untouched
    other_pw = await client.put(
        "/v1/users/partner/password",
        json={"password": "partner long password"},
        headers={"X-CSRF-Token": done.json()["csrf"]},
    )
    assert other_pw.status_code == 200 and "csrf" not in other_pw.json()
    assert (await client.get("/v1/me")).status_code == 200


def test_default_scrypt_cost_is_2_17(cfg):
    from utubot.config import SecurityConfig

    sec = SecurityConfig()
    assert (sec.scrypt_n, sec.scrypt_r, sec.scrypt_p) == (2**17, 8, 1)
    stored = hash_password("a password of twelve", sec)
    assert stored.startswith("scrypt$131072$8$1$")
    assert verify_password("a password of twelve", stored)
    assert not verify_password("a password of twelvf", stored)


def test_verify_refuses_absurd_stored_parameters():
    salt = "AAAAAAAAAAAAAAAAAAAAAA=="
    key = "A" * 44
    for params in ("2147483648$8$1", "1024$9999$1", "1024$8$9999", "1024$0$1", "3$8$1", "1000$8$1"):
        assert not verify_password("x", f"scrypt${params}${salt}${key}")


async def test_old_hashes_verify_and_are_upgraded_on_login(env):
    sec = env.cfg.security
    sec.scrypt_n = 2**9
    env.svc.webauth.set_password("owner", PASSWORD)
    old = env.svc.db.one("SELECT hash FROM user_passwords WHERE user='owner'")["hash"]
    assert old.startswith("scrypt$512$8$1$")
    sec.scrypt_n = 2**10
    client = anon_client(env)
    wrong = await client.post(LOGIN, json={"username": "owner", "password": "wrong-password-1"})
    assert wrong.status_code == 401
    assert env.svc.db.one("SELECT hash FROM user_passwords WHERE user='owner'")["hash"] == old
    ok = await client.post(LOGIN, json={"username": "owner", "password": PASSWORD})
    assert ok.status_code == 200
    new = env.svc.db.one("SELECT hash FROM user_passwords WHERE user='owner'")["hash"]
    assert new.startswith("scrypt$1024$8$1$") and new != old
    assert verify_password(PASSWORD, new)
    assert (await client.get("/v1/me")).status_code == 200
    # a stronger stored hash is left alone when the configured cost drops
    sec.scrypt_n = 2**9
    again = await anon_client(env).post(LOGIN, json={"username": "owner", "password": PASSWORD})
    assert again.status_code == 200
    assert env.svc.db.one("SELECT hash FROM user_passwords WHERE user='owner'")["hash"] == new


async def test_upgrade_does_not_overwrite_a_password_changed_meanwhile(env, monkeypatch):
    import utubot.webauth as webauth

    sec = env.cfg.security
    sec.scrypt_n = 2**9
    env.svc.webauth.set_password("owner", PASSWORD)
    sec.scrypt_n = 2**10
    real = webauth.verify_password

    def verify_then_change(password, stored):
        ok = real(password, stored)
        env.svc.db.execute(
            "UPDATE user_passwords SET hash=? WHERE user='owner'", ["scrypt$changed"]
        )
        return ok

    monkeypatch.setattr(webauth, "verify_password", verify_then_change)
    assert env.svc.webauth.check_password("owner", PASSWORD) is True
    row = env.svc.db.one("SELECT hash FROM user_passwords WHERE user='owner'")
    assert row["hash"] == "scrypt$changed"
