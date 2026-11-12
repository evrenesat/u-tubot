from __future__ import annotations

import httpx

from utubot.cli import main


def anon(env) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://utubot")


def publish(cfg_path, *args):
    return main(["--config", str(cfg_path), "app", "publish", *map(str, args)])


def make_cfg(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text(
        f'[server]\ndata_dir="{tmp_path}/d"\napp_dir="{tmp_path}/app"\n'
        'public_base_url="https://utubot.example.com"\n'
    )
    return path


async def test_setup_json_is_public_and_complete(env):
    env.cfg.server.public_base_url = "https://utubot.example.com/"
    env.cfg.setup.name = "Family server"
    env.cfg.setup.defaults.mark_only = True
    r = await anon(env).get("/setup.json")
    assert r.status_code == 200
    assert r.json() == {
        "utubot_setup": 1,
        "name": "Family server",
        "backend_url": "https://utubot.example.com",
        "update_url": "https://utubot.example.com/app/update.json",
        "pairing": True,
        "defaults": {
            "assess": True,
            "mark_only": True,
            "answer_in_menu": True,
            "summary_panel": False,
            "auto_captions": True,
        },
    }


async def test_setup_json_lists_prompt_sets_and_is_rate_limited(env):
    env.cfg.setup.prompt_set_urls = ["https://example.com/p.json"]
    env.cfg.security.rate_per_ip_per_min = 3
    a = anon(env)
    body = (await a.get("/setup.json")).json()
    assert body["prompt_set_urls"] == ["https://example.com/p.json"]
    await a.get("/setup.json")
    await a.get("/setup.json")
    assert (await a.get("/setup.json")).status_code == 429


async def test_publish_several_abis_and_aliases(env, tmp_path):
    env.cfg.server.app_dir = str(tmp_path / "app")
    env.cfg.server.public_base_url = "https://utubot.example.com"
    cfg_path = make_cfg(tmp_path)
    files = []
    for abi in ("arm64-v8a", "armeabi-v7a", "universal"):
        f = tmp_path / f"u-tubot_0.2.0_{abi}.apk"
        f.write_bytes(f"apk-{abi}".encode())
        files.append(f)
    assert publish(cfg_path, *files, "--version-name", "0.2.0", "--version-code", "2") == 0
    a = anon(env)
    package = (await a.get("/app/update.json")).json()["package"]
    assert package["downloadUrlList_arm64-v8a"] == [
        "https://utubot.example.com/app/u-tubot_0.2.0_arm64-v8a.apk"
    ]
    assert package["downloadUrlList_armeabi-v7a"] == [
        "https://utubot.example.com/app/u-tubot_0.2.0_armeabi-v7a.apk"
    ]
    assert package["downloadUrlList"] == [
        "https://utubot.example.com/app/u-tubot_0.2.0_universal.apk"
    ]
    alias = await a.get("/app/latest/arm64-v8a.apk")
    assert alias.status_code == 302
    assert alias.headers["location"] == "https://utubot.example.com/app/u-tubot_0.2.0_arm64-v8a.apk"
    assert (await a.get("/app/u-tubot_0.2.0_arm64-v8a.apk")).content == b"apk-arm64-v8a"
    assert (await a.get("/app/latest/x86.apk")).status_code == 404
    assert (await a.get("/app/latest/..%2Fx.apk")).status_code == 404


async def test_publish_new_version_moves_alias(env, tmp_path):
    env.cfg.server.app_dir = str(tmp_path / "app")
    cfg_path = make_cfg(tmp_path)
    for version, code in (("0.2.0", 2), ("0.3.0", 3)):
        f = tmp_path / f"u-tubot_{version}_arm64-v8a.apk"
        f.write_bytes(b"x")
        assert publish(cfg_path, f, "--version-name", version, "--version-code", str(code)) == 0
    alias = await anon(env).get("/app/latest/arm64-v8a.apk")
    assert alias.headers["location"].endswith("u-tubot_0.3.0_arm64-v8a.apk")


def test_publish_rejects_unknown_abi_and_duplicates(tmp_path, capsys):
    cfg_path = make_cfg(tmp_path)
    a = tmp_path / "one.apk"
    b = tmp_path / "two.apk"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    args = ("--version-name", "1", "--version-code", "1")
    assert publish(cfg_path, a, b, *args) == 1
    assert "cannot tell the ABI" in capsys.readouterr().err
    assert publish(cfg_path, a, *args, "--abi", "mips") == 1
    c = tmp_path / "x_x86.apk"
    d = tmp_path / "y_x86.apk"
    c.write_bytes(b"x")
    d.write_bytes(b"x")
    assert publish(cfg_path, c, d, *args) == 1
    assert "two APKs for x86" in capsys.readouterr().err


async def test_app_info_is_public_and_hides_empty_codes(env, tmp_path):
    env.cfg.server.app_dir = str(tmp_path / "app")
    a = anon(env)
    empty = (await a.get("/app/info.json")).json()
    assert empty["version_name"] is None and empty["files"] == {}
    cfg_path = make_cfg(tmp_path)
    f = tmp_path / "u-tubot_0.2.0_arm64-v8a.apk"
    f.write_bytes(b"x")
    publish(cfg_path, f, "--version-name", "0.2.0", "--version-code", "2", "--changelog", "hello")
    env.cfg.app.downloader_codes = {"arm64-v8a": "123456", "armeabi-v7a": ""}
    info = (await a.get("/app/info.json")).json()
    assert info["version_name"] == "0.2.0" and info["changelog"] == ["hello"]
    assert info["files"]["arm64-v8a"]["path"] == "/app/latest/arm64-v8a.apk"
    assert len(info["files"]["arm64-v8a"]["sha256"]) == 64
    assert info["downloader_codes"] == {"arm64-v8a": "123456"}


async def test_landing_page_has_download_section_and_no_secrets(env):
    page = (await anon(env).get("/")).text
    assert 'id="download"' in page
    assert "http://" not in page


async def _publish_arm(env, tmp_path):
    env.cfg.server.app_dir = str(tmp_path / "app")
    f = tmp_path / "u-tubot_0.2.0_arm64-v8a.apk"
    f.write_bytes(b"x")
    assert publish(make_cfg(tmp_path), f, "--version-name", "0.2.0", "--version-code", "2") == 0


async def test_latest_redirect_uses_public_base_url_regardless_of_host(env, tmp_path):
    await _publish_arm(env, tmp_path)
    env.cfg.server.public_base_url = "https://pub.example.com/"
    r = await anon(env).get("/app/latest/arm64-v8a.apk", headers={"Host": "internal.ts.net"})
    assert r.status_code == 302
    assert r.headers["location"] == "https://pub.example.com/app/u-tubot_0.2.0_arm64-v8a.apk"


async def test_latest_redirect_is_relative_when_public_base_url_unset(env, tmp_path):
    await _publish_arm(env, tmp_path)
    for unset in ("", "http://127.0.0.1:8790"):
        env.cfg.server.public_base_url = unset
        r = await anon(env).get("/app/latest/arm64-v8a.apk", headers={"Host": "internal.ts.net"})
        assert r.headers["location"] == "/app/u-tubot_0.2.0_arm64-v8a.apk"
