from __future__ import annotations

import httpx

from tests.conftest import TOKEN
from utubot.auth import append_user, hash_token
from utubot.cli import main
from utubot.config import load_config


async def test_health_open_and_auth_required(env):
    anon = httpx.AsyncClient(transport=env.client._transport, base_url="http://utubot")
    assert (await anon.get("/v1/health")).json()["ok"] is True
    r = await anon.get("/v1/me")
    assert r.status_code == 401 and r.json() == {"error": "unauthorized"}
    bad = await anon.get("/v1/me", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    assert (await anon.get("/")).status_code == 200


async def test_me_returns_policy(env):
    r = await env.client.get("/v1/me")
    body = r.json()
    assert body["user"] == "owner" and body["policy"]["hide_topics"] == ["reaction videos"]
    assert body["features"]["captions"] is True


async def test_invalid_video_id(env):
    assert (await env.client.get("/v1/videos/..%2Fetc/insight")).status_code in (400, 404)
    assert (await env.client.get("/v1/videos/a/summary")).status_code == 400


async def test_feedback(env):
    r = await env.client.post(
        "/v1/feedback", json={"video_id": "abcdefghijk", "kind": "clickbait", "correct": False}
    )
    assert r.json() == {"ok": True}
    assert env.svc.db.one("SELECT COUNT(*) c FROM feedback")["c"] == 1


def test_user_add_cli_and_hot_reload(tmp_path, capsys, monkeypatch):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        f'[server]\ndata_dir = "{tmp_path}/d"\n[[users]]\nname = "owner"\n'
        '[users.policy]\nhide_topics = ["x"]\n'
    )
    assert main(["--config", str(cfg_path), "user", "add", "owner"]) == 0
    out = capsys.readouterr().out
    token = next(line.split(": ")[1] for line in out.splitlines() if line.startswith("token"))
    cfg = load_config(cfg_path)
    owner = next(u for u in cfg.users if u.name == "owner")
    assert owner.token_sha256 == hash_token(token) and owner.policy.hide_topics == ["x"]
    assert token not in (tmp_path / "d" / "users.toml").read_text()
    append_user(cfg.users_path, "partner", hash_token("zzz"))
    assert {u.name for u in load_config(cfg_path).users} == {"owner", "partner"}
    assert TOKEN
