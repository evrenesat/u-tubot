from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx

from tests.conftest import OTHER_TOKEN, PASSWORD, TOKEN, anon_client
from utubot import appchannel
from utubot.auth import hash_token

WEB = Path(__file__).parents[1] / "src" / "utubot" / "web"
PUBLIC = {
    ("GET", "/"),
    ("GET", "/ui/{path:path}"),
    ("GET", "/v1/health"),
    ("GET", "/setup.json"),
    ("POST", "/v1/pair"),
    ("GET", "/app/update.json"),
    ("GET", "/app/info.json"),
    ("GET", "/app/latest/{abi}.apk"),
    ("GET", "/app/{filename}"),
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/logout"),
}
SEGMENT = re.compile(r"\{[^}]+\}")


def asset_urls(html: str) -> list[str]:
    return re.findall(r'(?:src|href)="(/ui/[^"]+)"', html)


def module_imports(source: str) -> list[str]:
    return re.findall(r'from\s+"(\./[^"]+|\.\./[^"]+)"', source)


async def test_shell_is_static_with_csp_and_no_inline_code(env):
    anon = anon_client(env)
    page = await anon.get("/")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]
    csp = page.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "style-src 'self'" in csp and "default-src 'none'" in csp
    assert (
        "unsafe-inline" not in csp and "unsafe-eval" not in csp and "frame-ancestors 'none'" in csp
    )
    assert page.headers["x-content-type-options"] == "nosniff"
    assert (
        page.headers["x-frame-options"] == "DENY"
        and page.headers["referrer-policy"] == "no-referrer"
    )
    html = page.text
    assert not re.search(r"<script(?![^>]*\bsrc=)", html), "inline script"
    assert "<style" not in html and not re.search(r"\sstyle=", html)
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handler"
    for secret in (TOKEN, OTHER_TOKEN, hash_token(TOKEN), "owner", "partner"):
        assert secret not in html


async def test_every_asset_is_served_with_its_media_type(env):
    anon = anon_client(env)
    html = (await anon.get("/")).text
    seen: set[str] = set()
    queue = asset_urls(html)
    types = {".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}
    while queue:
        url = queue.pop()
        if url in seen:
            continue
        seen.add(url)
        res = await anon.get(url)
        assert res.status_code == 200, url
        assert res.headers["content-type"].split(";")[0] == types[Path(url).suffix], url
        assert (
            "content-security-policy" in res.headers and res.headers["cache-control"] == "no-cache"
        )
        if url.endswith(".js"):
            base = Path(url).parent
            for rel in module_imports(res.text):
                queue.append(_resolve(base, rel))
    assert "/ui/js/main.js" in seen and "/ui/app.css" in seen and len(seen) >= 12


def _resolve(base: Path, rel: str) -> str:
    parts: list[str] = []
    for part in [*base.parts[1:], *rel.split("/")]:
        if part == "..":
            parts.pop()
        elif part != ".":
            parts.append(part)
    return "/" + "/".join(parts)


async def test_ui_paths_cannot_escape_the_ui_folder(env):
    anon = anon_client(env)
    for bad in (
        "/ui/../index.html",
        "/ui/%2e%2e/index.html",
        "/ui/js/../../../config.py",
        "/ui/nope.js",
        "/ui/js",
        "/ui/js/main.js.map",
        "/ui/app.css/../../app.py",
        "/ui/%00",
        "/ui//etc/passwd",
    ):
        res = await anon.get(bad)
        assert res.status_code in (400, 404), bad
        assert "FastAPI" not in res.text and "import " not in res.text.split("\n")[0]


def test_ui_code_never_builds_markup_from_strings():
    forbidden = re.compile(
        r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function|setAttribute\(\s*[\"']on|srcdoc"
    )
    for path in (WEB / "ui").rglob("*.js"):
        assert not forbidden.search(path.read_text()), path
    css = (WEB / "ui" / "app.css").read_text()
    assert "@import" not in css and "url(http" not in css


async def test_api_responses_carry_security_headers_and_are_not_cached(env):
    res = await env.client.get("/v1/me")
    assert res.headers["cache-control"] == "no-store"
    assert (
        "content-security-policy" in res.headers
        and res.headers["x-content-type-options"] == "nosniff"
    )
    denied = await anon_client(env).get("/v1/me")
    assert denied.status_code == 401 and "content-security-policy" in denied.headers


async def test_every_data_route_requires_authentication(env):
    anon = anon_client(env)
    checked = 0
    for route in env.app.routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            if (method, route.path) in PUBLIC:
                continue
            url = SEGMENT.sub("abcdefghijk", route.path)
            res = await anon.request(method, url, json={})
            assert res.status_code == 401, f"{method} {route.path} answered {res.status_code}"
            checked += 1
    assert checked >= 40


async def test_admin_only_routes_forbid_ordinary_users(env):
    other = httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    cases = [
        ("GET", "/v1/users", None),
        ("POST", "/v1/users", {"name": "newbie"}),
        ("PUT", "/v1/users/owner", {"admin": False}),
        ("PUT", "/v1/users/owner/password", {"password": PASSWORD}),
        ("GET", "/v1/users/owner/settings", None),
        ("PUT", "/v1/users/owner/settings", {"settings": {}}),
        ("GET", "/v1/admin/users", None),
        ("POST", "/v1/admin/pair", {"user": "owner"}),
        ("DELETE", "/v1/admin/devices/x", None),
        ("PUT", "/v1/admin/users/owner/policy", {}),
    ]
    for method, url, body in cases:
        res = await other.request(method, url, json=body)
        assert res.status_code == 403, f"{method} {url}"
        assert res.json() == {"error": "forbidden"}
    assert (await other.get("/v1/me/settings")).status_code == 200


async def test_admin_creates_users_and_sets_passwords(env):
    r = await env.client.post("/v1/users", json={"name": "newbie", "password": PASSWORD})
    assert r.status_code == 200
    assert r.json() == {
        "name": "newbie",
        "admin": False,
        "has_password": True,
        "has_token": False,
        "devices": 0,
        "sessions": 0,
        "admin_editable": True,
    }
    login = await anon_client(env).post(
        "/v1/auth/login", json={"username": "newbie", "password": PASSWORD}
    )
    assert login.status_code == 200 and login.json()["admin"] is False
    assert (await env.client.post("/v1/users", json={"name": "newbie"})).status_code == 409
    assert (await env.client.post("/v1/users", json={"name": "bad name!"})).status_code == 400
    assert (
        await env.client.post("/v1/users", json={"name": "weakling", "password": "short"})
    ).status_code == 400
    assert env.svc.auth.user_config("weakling") is None
    promoted = await env.client.put("/v1/users/newbie", json={"admin": True})
    assert promoted.json()["admin"] is True
    assert "admin = true" in env.cfg.users_path.read_text()
    demoted = await env.client.put("/v1/users/newbie", json={"admin": False})
    assert demoted.json()["admin"] is False and "admin = true" not in env.cfg.users_path.read_text()
    assert (await env.client.put("/v1/users/owner", json={"admin": False})).status_code == 409
    assert (await env.client.put("/v1/users/partner", json={"admin": True})).status_code == 409
    assert (await env.client.put("/v1/users/ghost", json={"admin": True})).status_code == 404
    reset = await env.client.put(
        "/v1/users/newbie/password", json={"password": "a different passphrase"}
    )
    assert reset.status_code == 200
    again = anon_client(env)
    assert (
        await again.post("/v1/auth/login", json={"username": "newbie", "password": PASSWORD})
    ).status_code == 401
    assert (
        await again.post(
            "/v1/auth/login", json={"username": "newbie", "password": "a different passphrase"}
        )
    ).status_code == 200
    listing = (await env.client.get("/v1/users")).json()["users"]
    assert [u["name"] for u in listing] == ["owner", "partner", "newbie"]
    assert all("token_sha256" not in u and "hash" not in u for u in listing)


async def test_password_only_user_pairs_a_tv_with_own_code(env):
    await env.client.post("/v1/users", json={"name": "newbie", "password": PASSWORD})
    me = anon_client(env)
    csrf = (
        await me.post("/v1/auth/login", json={"username": "newbie", "password": PASSWORD})
    ).json()["csrf"]
    code = (await me.post("/v1/me/pair", headers={"X-CSRF-Token": csrf})).json()
    assert len(code["code"]) == 6 and code["expires_in_s"] == 900
    tv = await anon_client(env).post("/v1/pair", json={"code": code["code"], "device": "Den TV"})
    assert tv.status_code == 200 and tv.json()["user"] == "newbie"
    devices = (await me.get("/v1/me/devices")).json()["devices"]
    assert [d["device"] for d in devices] == ["Den TV"]
    other = httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    assert (await other.delete(f"/v1/me/devices/{devices[0]['id']}")).status_code == 404
    assert (
        await me.delete(f"/v1/me/devices/{devices[0]['id']}", headers={"X-CSRF-Token": csrf})
    ).status_code == 200
    assert (await me.get("/v1/me/devices")).json()["devices"] == []


async def test_status_reports_gate_usage_and_jobs(env):
    base = (await env.client.get("/v1/status")).json()
    assert (
        base["version"]
        and base["youtube"]["state"] == "closed"
        and base["youtube"]["healthy"] is True
    )
    assert base["usage"]["llm"]["calls"] == 0 and base["usage"]["analyses"] == {
        "used": 0,
        "cap": 30,
    }
    await env.client.get("/v1/videos/abcdefghijk/summary", params={"wait_ms": 5000})
    env.svc.gate.report_block("test", 120)
    env.svc.jobs.enqueue_transcript("owner", "abcdefghijk", "A title")
    now = (await env.client.get("/v1/status")).json()
    assert (
        now["usage"]["llm"]["calls"] >= 1 and now["usage"]["transcripts"]["youtube_captions"] == 1
    )
    assert now["youtube"]["state"] == "open" and 100 < now["youtube"]["cooldown_remaining_s"] <= 120
    assert now["jobs"]["waiting"] == 1
    assert now["usage"]["day"] == time.strftime("%Y-%m-%d", time.gmtime())
    text = json.dumps(now)
    assert "http://" not in text and "sha256" not in text


def github_release_handler(counter: list[int], status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        counter.append(1)
        if status != 200:
            return httpx.Response(status)
        assert request.url.path == "/repos/owner/repo/releases"
        return httpx.Response(
            200,
            json=[
                {
                    "tag_name": "utubot-v0.3.1",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-11-01T10:00:00Z",
                    "html_url": "https://github.com/owner/repo/releases/tag/utubot-v0.3.1",
                },
                {
                    "tag_name": "utubot-v0.3.4",
                    "draft": False,
                    "prerelease": False,
                    "published_at": "2026-11-10T10:00:00Z",
                    "html_url": "https://github.com/owner/repo/releases/tag/utubot-v0.3.4",
                },
                {"tag_name": "utubot-v0.9.0", "draft": True, "prerelease": False},
                {"tag_name": "v1", "draft": False},
            ],
        )

    return handler


async def test_updates_page_data(env):
    env.cfg.server.app_dir = str(Path(env.cfg.server.data_dir) / "app")
    first = (await env.client.get("/v1/updates")).json()
    assert first["channel"] == {"published": False} and first["last_sync"] is None
    assert first["github"] == {"configured": False}
    env.cfg.app.github_repo = "owner/repo"
    calls: list[int] = []
    env.svc.updates._transport = httpx.MockTransport(github_release_handler(calls))
    app_dir = env.cfg.app_dir
    app_dir.mkdir(parents=True)
    (app_dir / "latest.json").write_text(
        json.dumps(
            {
                "version_name": "0.3.2",
                "version_code": 3002,
                "changelog": ["Faster"],
                "files": {"arm64-v8a": {"file": "u-tubot_0.3.2_arm64-v8a.apk", "size": 9}},
            }
        )
    )
    appchannel.record_sync(env.cfg, "up-to-date", "0.3.2")
    info = (await env.client.get("/v1/updates")).json()
    assert info["channel"]["version_name"] == "0.3.2" and info["channel"]["files"] == {
        "arm64-v8a": {"file": "u-tubot_0.3.2_arm64-v8a.apk", "size": 9}
    }
    assert info["github"]["latest"]["version"] == "0.3.4" and info["behind"] is True
    assert info["github"]["latest"]["url"].startswith("https://github.com/")
    assert info["last_sync"]["status"] == "up-to-date" and info["last_sync"]["checked_at"] > 0
    await env.client.get("/v1/updates")
    assert len(calls) == 1
    assert (await env.client.post("/v1/updates/refresh")).status_code == 200
    assert len(calls) == 1, "a forced check right after a fetch is served from the cache"
    env.svc.updates._cached_at -= env.cfg.app.release_check_min_interval_s + 1
    forced = await env.client.post("/v1/updates/refresh")
    assert forced.status_code == 200 and len(calls) == 2


async def test_updates_github_failure_is_reported_not_raised(env):
    env.cfg.app.github_repo = "owner/repo"
    calls: list[int] = []
    env.svc.updates._transport = httpx.MockTransport(github_release_handler(calls, status=503))
    info = (await env.client.get("/v1/updates")).json()
    assert info["github"]["error"] == "GitHub answered HTTP 503" and info["behind"] is None
    env.cfg.app.github_repo = ""
    env.svc.updates._cache = None
    assert (await env.client.get("/v1/updates")).json()["github"] == {"configured": False}


async def test_jobs_cancel_and_retry(env):
    jobs = env.svc.jobs
    env.svc.gate.report_block("test", 600)
    waiting = jobs.enqueue_transcript("owner", "abcdefghijk", "One")
    r = await env.client.post(f"/v1/jobs/{waiting['id']}/cancel")
    assert r.status_code == 200
    listed = (await env.client.get("/v1/jobs")).json()["jobs"]
    assert listed[0]["state"] == "cancelled" and listed[0]["error"] == "Cancelled"
    assert (await env.client.post(f"/v1/jobs/{waiting['id']}/cancel")).status_code == 409
    again = await env.client.post(f"/v1/jobs/{waiting['id']}/retry")
    assert again.status_code == 200
    assert (await env.client.get("/v1/jobs")).json()["jobs"][0]["state"] == "waiting"
    assert (await env.client.post(f"/v1/jobs/{waiting['id']}/retry")).status_code == 409
    other = httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    assert (await other.post(f"/v1/jobs/{waiting['id']}/cancel")).status_code == 404
    assert (await other.post(f"/v1/jobs/{waiting['id']}/retry")).status_code == 404
    assert (await env.client.post("/v1/jobs/nope/cancel")).status_code == 404
    env.svc.db.execute("UPDATE jobs SET status='running' WHERE id=?", [waiting["id"]])
    assert (await env.client.post(f"/v1/jobs/{waiting['id']}/cancel")).status_code == 409
    env.svc.db.execute("UPDATE jobs SET status='failed', error='boom' WHERE id=?", [waiting["id"]])
    second = jobs.enqueue_transcript("owner", "bcdefghijkl", "Two")
    clash = jobs._insert("owner", "abcdefghijk", "transcript", "auto", None, "One again")
    assert clash["id"] != waiting["id"] and second
    assert (await env.client.post(f"/v1/jobs/{waiting['id']}/retry")).status_code == 409
    env.svc.db.execute("UPDATE jobs SET status='failed' WHERE id=?", [clash["id"]])
    assert (await env.client.post(f"/v1/jobs/{waiting['id']}/retry")).status_code == 200


async def test_resolve_video_references(env):
    vid = "dQw4w9WgXcQ"
    good = [
        vid,
        f"  {vid}  ",
        f"https://www.youtube.com/watch?v={vid}",
        f"https://youtube.com/watch?v={vid}&t=42s&list=PLx",
        f"https://m.youtube.com/watch?v={vid}",
        f"youtube.com/watch?v={vid}",
        f"https://youtu.be/{vid}?si=abc",
        f"https://www.youtube.com/shorts/{vid}",
        f"https://www.youtube.com/live/{vid}?feature=share",
        f"https://www.youtube.com/embed/{vid}",
        f"https://music.youtube.com/watch?v={vid}",
    ]
    for text in good:
        r = await env.client.post("/v1/videos/resolve", json={"text": text})
        assert r.json() == {"video_id": vid}, text
    bad = [
        "",
        "nope",
        "https://example.com/watch?v=" + vid,
        "https://evil.example/https://youtu.be/" + vid,
        f"https://www.youtube.com/watch?v={vid}x",
        "https://www.youtube.com/watch",
        "https://www.youtube.com/channel/UC123456789012345678901",
        "javascript:alert(1)",
        "https://youtube.com.evil.example/watch?v=" + vid,
    ]
    for text in bad:
        r = await env.client.post("/v1/videos/resolve", json={"text": text})
        assert r.status_code == 400, text


async def test_prompt_validate_reports_field_messages(env):
    ok = await env.client.post(
        "/v1/prompts/validate",
        json={
            "tubeai_prompt_set": 1,
            "id": "ok",
            "name": "Ok",
            "prompts": [{"id": "a", "label": "A", "template": "{transcript}"}],
        },
    )
    assert ok.json() == {"ok": True, "id": "ok", "name": "Ok", "prompts": 1}
    bad = await env.client.post(
        "/v1/prompts/validate",
        json={
            "tubeai_prompt_set": 1,
            "id": "bad id",
            "name": "X",
            "prompts": [{"id": "a", "label": "A", "template": ""}],
        },
    )
    assert (
        bad.status_code == 400
        and "id:" in bad.json()["error"]
        and "template" in bad.json()["error"]
    )
    assert (await env.client.get("/v1/prompts")).json()["sets"][-1]["id"] == "builtin"


async def test_no_secret_material_in_account_responses(env):
    await env.client.put("/v1/me/password", json={"new_password": PASSWORD})
    blobs = []
    for path in (
        "/v1/me",
        "/v1/me/settings",
        "/v1/status",
        "/v1/users",
        "/v1/admin/users",
        "/v1/auth/session",
        "/v1/updates",
        "/v1/models",
        "/v1/me/devices",
    ):
        blobs.append((await env.client.get(path)).text)
    joined = "\n".join(blobs)
    for secret in (
        TOKEN,
        OTHER_TOKEN,
        hash_token(TOKEN),
        hash_token(OTHER_TOKEN),
        PASSWORD,
        "scrypt$",
    ):
        assert secret not in joined
