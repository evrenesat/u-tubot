from __future__ import annotations

import json
import time

import httpx

from tests.conftest import OTHER_TOKEN, TOKEN
from utubot.cli import main
from utubot.config import load_config
from utubot.security import client_ip

VID = "abcdefghijk"


def anon(env):
    return httpx.AsyncClient(transport=env.client._transport, base_url="http://utubot")


async def pair_code(env, user="partner"):
    r = await env.client.post("/v1/admin/pair", json={"user": user})
    assert r.status_code == 200, r.text
    return r.json()["code"]


async def test_endpoints_require_token_and_docs_disabled(env):
    a = anon(env)
    for method, path in [
        ("GET", "/v1/me"),
        ("POST", "/v1/assess"),
        ("GET", f"/v1/videos/{VID}/summary"),
        ("GET", f"/v1/videos/{VID}/captions"),
        ("GET", "/v1/prompts"),
        ("POST", "/v1/admin/pair"),
        ("GET", "/v1/admin/users"),
        ("POST", "/v1/feedback"),
    ]:
        r = await a.request(method, path, json={} if method == "POST" else None)
        assert r.status_code == 401, (method, path, r.status_code)
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert (await a.get(path)).status_code == 404
    page = (await a.get("/")).text
    assert "bearer" not in page.lower().split("<script>")[0]


async def test_video_id_strict(env):
    for bad in ("short", "abcdefghijkl", "abc.efghijk", "abc%20efghij"):
        r = await env.client.get(f"/v1/videos/{bad}/insight")
        assert r.status_code in (400, 404), bad
    r = await env.client.post("/v1/assess", json={"videos": [{"video_id": "x;rm -rf"}]})
    assert r.status_code == 400


async def test_pairing_flow_and_single_use(env):
    code = await pair_code(env)
    a = anon(env)
    r = await a.post("/v1/pair", json={"code": code, "device": "Living room TV"})
    assert r.status_code == 200 and r.json()["user"] == "partner"
    token = r.json()["token"]
    me = await a.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["user"] == "partner" and me.json()["admin"] is False
    again = await a.post("/v1/pair", json={"code": code, "device": "x"})
    assert again.status_code == 403
    users = (await env.client.get("/v1/admin/users")).json()["users"]
    devices = next(u for u in users if u["name"] == "partner")["devices"]
    assert devices[0]["device"] == "Living room TV"
    assert (await env.client.delete(f"/v1/admin/devices/{devices[0]['id']}")).status_code == 200
    gone = await a.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert gone.status_code == 401
    assert token not in json.dumps(users)


async def test_pair_code_expiry(env):
    env.cfg.security.pair_code_ttl_s = 1
    code = await pair_code(env)
    time.sleep(1.2)
    r = await anon(env).post("/v1/pair", json={"code": code, "device": "x"})
    assert r.status_code == 403


async def test_pair_lockout_after_failures(env):
    env.cfg.security.pair_attempts_per_ip_per_min = 100
    code = await pair_code(env)
    a = anon(env)
    for _ in range(env.cfg.security.pair_lockout_failures):
        assert (await a.post("/v1/pair", json={"code": "000000", "device": "x"})).status_code == 403
    r = await a.post("/v1/pair", json={"code": code, "device": "x"})
    assert r.status_code == 429


async def test_pair_rate_limited(env):
    a = anon(env)
    env.cfg.security.pair_lockout_failures = 1000
    codes = []
    for _ in range(env.cfg.security.pair_attempts_per_ip_per_min + 1):
        codes.append((await a.post("/v1/pair", json={"code": "111111", "device": "x"})).status_code)
    assert (
        codes[-1] == 429
        and "Retry-After" in (await a.post("/v1/pair", json={"code": "1", "device": "x"})).headers
    )


async def test_admin_only_routes(env):
    partner = {"Authorization": f"Bearer {OTHER_TOKEN}"}
    a = anon(env)
    assert (
        await a.post("/v1/admin/pair", json={"user": "owner"}, headers=partner)
    ).status_code == 403
    assert (await a.get("/v1/admin/users", headers=partner)).status_code == 403
    r = await a.put("/v1/admin/users/owner/policy", json={"hide_topics": []}, headers=partner)
    assert r.status_code == 403
    own = await a.put("/v1/me/policy", json={"hide_topics": ["asmr"]}, headers=partner)
    assert own.status_code == 200 and own.json()["hide_topics"] == ["asmr"]
    assert (await a.get("/v1/me", headers=partner)).json()["policy"]["hide_topics"] == ["asmr"]
    admin = await env.client.put("/v1/admin/users/partner/policy", json={"language": "tr"})
    assert admin.json()["language"] == "tr" and admin.json()["hide_topics"] == ["asmr"]
    bad = await env.client.put("/v1/admin/users/partner/policy", json={"nope": 1})
    assert bad.status_code == 400
    assert (await env.client.post("/v1/admin/pair", json={"user": "ghost"})).status_code == 404


async def test_token_rate_limit(env):
    env.cfg.security.rate_per_token_per_min = 3
    codes = [(await env.client.get("/v1/me")).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    other = await env.client.get("/v1/me", headers={"Authorization": f"Bearer {OTHER_TOKEN}"})
    assert other.status_code == 200


async def test_ip_rate_limit_and_forwarded_for(env):
    env.cfg.security.rate_per_ip_per_min = 2
    a = anon(env)
    assert [(await a.get("/v1/health")).status_code for _ in range(3)] == [200, 200, 429]
    env.svc.limiter._hits.clear()
    spoof = {"X-Forwarded-For": "1.2.3.4"}
    results = [(await a.get("/v1/health", headers=spoof)).status_code for _ in range(3)]
    assert results == [200, 200, 429]
    env.svc.limiter._hits.clear()
    env.cfg.security.trusted_proxies = ["127.0.0.1"]
    for ip, expect in [("1.1.1.1", 200), ("1.1.1.1", 200), ("1.1.1.1", 429), ("2.2.2.2", 200)]:
        r = await a.get("/v1/health", headers={"X-Forwarded-For": ip})
        assert r.status_code == expect, ip


def test_client_ip_rules():
    trusted = ["10.0.0.0/8", "127.0.0.1"]
    assert client_ip("203.0.113.5", "1.1.1.1", trusted) == "203.0.113.5"
    assert client_ip("127.0.0.1", "9.9.9.9, 10.1.1.1", trusted) == "9.9.9.9"
    assert client_ip("127.0.0.1", "6.6.6.6, 9.9.9.9", trusted) == "9.9.9.9"
    assert client_ip("127.0.0.1", None, trusted) == "127.0.0.1"
    default = ["127.0.0.1", "::1", "100.64.0.7"]
    assert client_ip("127.0.0.1", "198.51.100.7, 100.64.0.7", default) == "198.51.100.7"
    assert client_ip("127.0.0.1", "6.6.6.6, 198.51.100.7, 100.64.0.7", default) == "198.51.100.7"
    assert client_ip("127.0.0.1", "1.1.1.1", []) == "127.0.0.1"


def test_client_ip_header_needs_the_proxy_secret():
    trusted = ["127.0.0.1"]
    xff = "100.64.0.7"  # what a second proxy hop leaves in X-Forwarded-For
    named = {"header_value": "198.51.100.9", "expected_secret": "s3cret"}
    assert (
        client_ip("127.0.0.1", xff, trusted, **named, presented_secret="s3cret") == "198.51.100.9"
    )
    assert client_ip("127.0.0.1", xff, trusted, **named, presented_secret="nope") == "100.64.0.7"
    assert client_ip("127.0.0.1", xff, trusted, **named) == "100.64.0.7"
    assert client_ip("127.0.0.1", xff, trusted, header_value="198.51.100.9") == "100.64.0.7"
    unset = {"header_value": "198.51.100.9", "presented_secret": "s3cret"}
    assert client_ip("127.0.0.1", xff, trusted, **unset, expected_secret=None) == "100.64.0.7"
    assert client_ip("127.0.0.1", xff, trusted, **unset, expected_secret="") == "100.64.0.7"
    assert (
        client_ip("203.0.113.5", xff, trusted, **named, presented_secret="s3cret") == "203.0.113.5"
    )
    for junk in ("not-an-ip", "1.2.3.4, 5.6.7.8", "", "1.2.3.4:80"):
        got = client_ip(
            "127.0.0.1",
            xff,
            trusted,
            header_value=junk,
            expected_secret="s3cret",
            presented_secret="s3cret",
        )
        assert got == "100.64.0.7", junk
    v6 = client_ip(
        "127.0.0.1",
        None,
        trusted,
        header_value=" 2001:db8::1 ",
        expected_secret="k",
        presented_secret="k",
    )
    assert v6 == "2001:db8::1"


async def test_client_ip_header_end_to_end(env, monkeypatch):
    env.cfg.security.trusted_proxies = ["127.0.0.1"]
    env.cfg.security.rate_per_ip_per_min = 2
    a = anon(env)
    via = {"X-Forwarded-For": "100.64.0.7"}
    named = {**via, "X-Utubot-Client-IP": "198.51.100.1", "X-Utubot-Proxy-Secret": "s3cret"}

    async def codes(headers, n=3):
        env.svc.limiter._hits.clear()
        return [(await a.get("/v1/health", headers=headers)).status_code for _ in range(n)]

    # not configured: both headers are ignored, every client looks like the last hop
    assert await codes(named) == [200, 200, 429]
    env.cfg.security.client_ip_header = "X-Utubot-Client-IP"
    # configured but no secret in the environment: still ignored
    assert await codes(named) == [200, 200, 429]
    monkeypatch.setenv("UTUBOT_PROXY_SECRET", "s3cret")
    env.svc.limiter._hits.clear()
    for _ in range(2):
        assert (await a.get("/v1/health", headers=named)).status_code == 200
    assert (await a.get("/v1/health", headers=named)).status_code == 429
    other = {**named, "X-Utubot-Client-IP": "198.51.100.2"}
    assert (await a.get("/v1/health", headers=other)).status_code == 200
    # a spoofed header without the secret (or with a wrong one) is ignored: one shared bucket
    spoofed = [{**via, "X-Utubot-Client-IP": f"203.0.113.{i}"} for i in range(1, 4)]
    wrong = [{**s, "X-Utubot-Proxy-Secret": "guess"} for s in spoofed]
    env.svc.limiter._hits.clear()
    got = [(await a.get("/v1/health", headers=h)).status_code for h in spoofed]
    assert got == [200, 200, 429]
    env.svc.limiter._hits.clear()
    got = [(await a.get("/v1/health", headers=h)).status_code for h in wrong]
    assert got == [200, 200, 429]


async def test_login_lockout_follows_the_named_client(env, monkeypatch):
    from tests.conftest import PASSWORD

    env.cfg.security.trusted_proxies = ["127.0.0.1"]
    env.cfg.security.client_ip_header = "X-Utubot-Client-IP"
    monkeypatch.setenv("UTUBOT_PROXY_SECRET", "s3cret")
    env.svc.webauth.set_password("partner", PASSWORD)
    a = anon(env)

    def login(ip, password):
        return a.post(
            "/v1/auth/login",
            json={"username": "partner", "password": password},
            headers={
                "X-Forwarded-For": "100.64.0.7",
                "X-Utubot-Client-IP": ip,
                "X-Utubot-Proxy-Secret": "s3cret",
            },
        )

    for _ in range(env.cfg.security.login_lockout_failures):
        await login("198.51.100.1", "wrong-password-1")
    assert (await login("198.51.100.1", PASSWORD)).status_code == 429
    assert (await login("198.51.100.2", PASSWORD)).status_code == 200


async def test_body_size_cap(env):
    env.cfg.security.max_body_bytes = 1000
    big = {"videos": [{"video_id": VID, "title": "x" * 5000}]}
    r = await env.client.post("/v1/assess", json=big)
    assert r.status_code == 413


async def test_app_update_channel_and_traversal(env, tmp_path, capsys):
    env.cfg.server.app_dir = str(tmp_path / "app")
    a = anon(env)
    assert (await a.get("/app/update.json")).status_code == 404
    apk = tmp_path / "in.apk"
    apk.write_bytes(b"PK-fake-apk")
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(f'[server]\ndata_dir="{tmp_path}/d"\napp_dir="{tmp_path}/app"\n')
    for version, code in (("1.0.0", 1), ("1.1.0", 2)):
        rc = main(
            [
                "--config",
                str(cfg_path),
                "app",
                "publish",
                str(apk),
                "--version-name",
                version,
                "--version-code",
                str(code),
                "--changelog",
                "first\nsecond",
            ]
        )
        assert rc == 0
    manifest = (await a.get("/app/update.json")).json()
    assert list(manifest) == ["package", "1.1.0", "1.0.0"]
    assert manifest["1.1.0"] == {"versionCode": 2, "changelog": ["first", "second"]}
    assert manifest["package"]["downloadUrlList"] == [
        "http://127.0.0.1:8790/app/u-tubot_1.1.0_universal.apk"
    ]
    got = await a.get("/app/u-tubot_1.1.0_universal.apk")
    assert got.status_code == 200 and got.content == b"PK-fake-apk"
    for bad in (
        "/app/..%2Fupdate.json",
        "/app/tubeai.sqlite",
        "/app/%2e%2e/x.apk",
        "/app/update.json.apk",
    ):
        assert (await a.get(bad)).status_code == 404, bad
    assert (
        main(
            [
                "--config",
                str(cfg_path),
                "app",
                "publish",
                "nope.apk",
                "--version-name",
                "1",
                "--version-code",
                "1",
            ]
        )
        == 1
    )


def test_cli_pair_devices_revoke(tmp_path, capsys):
    cfg_path = tmp_path / "c.toml"
    cfg_path.write_text(f'[server]\ndata_dir="{tmp_path}/d"\n[[users]]\nname="owner"\n')
    assert main(["--config", str(cfg_path), "user", "pair", "owner"]) == 0
    assert "pairing code for owner:" in capsys.readouterr().out
    assert main(["--config", str(cfg_path), "user", "pair", "ghost"]) == 1
    assert main(["--config", str(cfg_path), "user", "devices"]) == 0
    assert main(["--config", str(cfg_path), "user", "revoke", "nope"]) == 1
    main(["--config", str(cfg_path), "user", "add", "boss", "--admin"])
    assert next(u for u in load_config(cfg_path).users if u.name == "boss").admin is True


async def test_providers_and_model_override(env, monkeypatch):
    from utubot.config import ProviderConfig

    monkeypatch.setenv("TEST_CLAUDE_KEY", "claude-secret")
    env.cfg.llm.providers["claude"] = ProviderConfig(
        base_url="http://claudehost/v1", api_key_env="TEST_CLAUDE_KEY"
    )
    pset = {
        "tubeai_prompt_set": 1,
        "id": "mine",
        "name": "m",
        "prompts": [
            {"id": "c", "label": "c", "template": "{transcript}", "model": "claude:opus-x"}
        ],
    }
    assert (await env.client.put("/v1/prompts/sets/mine", json=pset)).status_code == 200
    r = await env.client.get(
        f"/v1/videos/{VID}/summary", params={"prompt": "mine/c", "wait_ms": 5000}
    )
    assert r.json()["status"] == "ready"
    assert env.llm.calls[-1]["model"] == "opus-x"
    assert env.llm.requests[-1] == {"host": "claudehost", "auth": "Bearer claude-secret"}
    env.cfg.llm.summary.provider = "claude"
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert env.llm.requests[-1]["host"] == "claudehost" and env.llm.calls[-1]["model"] == "worker"
    ask = await env.client.post(f"/v1/videos/{VID}/ask", json={"question": "q", "wait_ms": 5000})
    assert ask.json()["status"] == "ready" and env.llm.requests[-1]["host"] == "mock"
    assert TOKEN


def test_default_trusted_proxies():
    from utubot.config import Config

    assert Config().security.trusted_proxies == ["127.0.0.1", "::1"]


def test_example_config_loads():
    from pathlib import Path

    cfg = load_config(Path(__file__).parent.parent / "config.example.toml")
    assert cfg.llm.default_provider == "local"
    assert cfg.llm.providers["local"].api_key_env is None
    assert cfg.llm.triage.reasoning_effort == "none"
    assert cfg.users[0].admin is True


def test_provider_defaults_are_generic():
    from utubot.config import Config

    cfg = Config()
    provider = cfg.llm.providers[cfg.llm.default_provider]
    assert cfg.llm.default_provider == "default"
    assert provider.base_url == "http://127.0.0.1:8000/v1"
    assert provider.api_key_env is None
    assert cfg.api_key("default") is None


def test_provider_api_key_env_per_provider(monkeypatch):
    from utubot.config import Config, ProviderConfig

    cfg = Config()
    cfg.llm.providers["cloud"] = ProviderConfig(base_url="http://x/v1", api_key_env="CLOUD_KEY")
    monkeypatch.setenv("CLOUD_KEY", "k1")
    assert cfg.api_key("cloud") == "k1"
    assert cfg.api_key("default") is None
