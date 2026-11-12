from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import httpx
import pytest

from utubot import appsync
from utubot.cli import main
from utubot.config import AppConfig, Config, ServerConfig

FIXTURES = Path(__file__).parent / "fixtures"
SIGNED_APK = (FIXTURES / "signed-v2.apk.bin").read_bytes()
SIGNED_APK_CERT = "cf434ab77f7f706af4224aacf9dd43b9b75eea61cbb09d729c746667c8d8a6b3"
REPO = "example/u-tubot"
PIN = "ab" * 32
OTHER_PIN = "cd" * 32
ABIS = ("arm64-v8a", "armeabi-v7a", "universal")
API_RELEASES = f"https://api.github.com/repos/{REPO}/releases?per_page=20"
DOWNLOAD_BASE = f"https://github.com/{REPO}/releases/download"


def apk_bytes(version: str, abi: str) -> bytes:
    return f"APK {version} {abi}\n".encode() * 50


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_cfg(tmp_path: Path, **app) -> Config:
    app_cfg = {
        "github_repo": REPO,
        "signing_cert_sha256": PIN,
        "apksigner_path": str(fake_apksigner(tmp_path)),
        **app,
    }
    return Config(
        server=ServerConfig(
            data_dir=str(tmp_path / "data"),
            app_dir=str(tmp_path / "app"),
            public_base_url="https://utubot.example.com",
        ),
        app=AppConfig(**app_cfg),
    )


def fake_apksigner(tmp_path: Path) -> Path:
    """Prints the certificate in $FAKE_CERT and fails when $FAKE_REJECT is set, like apksigner verify --print-certs."""
    path = tmp_path / "fake-apksigner"
    if not path.exists():
        tmp_path.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "#!/bin/sh\n"
            'if [ -n "$FAKE_REJECT" ]; then echo "DOES NOT VERIFY" >&2; exit 1; fi\n'
            'echo "Signer #1 certificate DN: CN=test"\n'
            'echo "Signer #1 certificate SHA-256 digest: ${FAKE_CERT:-' + PIN + '}"\n'
        )
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


class Github:
    """A mocked GitHub: the release list, the release assets and a log of every request."""

    def __init__(self) -> None:
        self.releases: list[dict] = []
        self.files: dict[str, bytes] = {}
        self.requests: list[httpx.Request] = []
        self.status: int | None = None
        self.headers: dict[str, str] = {}

    def add_release(
        self,
        version: str,
        code: int | None,
        *,
        abis=ABIS,
        manifest: bool = True,
        sums: bool = False,
        draft: bool = False,
        prerelease: bool = False,
        body: str = "",
        tamper: str | None = None,
        apk_data: bytes | None = None,
    ) -> None:
        tag = f"utubot-v{version}"
        assets = []
        apks = {abi: apk_data or apk_bytes(version, abi) for abi in abis}
        files_meta = {}
        for abi, data in apks.items():
            name = f"u-tubot_{version}_{abi}.apk"
            served = data + b"x" if tamper == abi else data
            self.files[f"{DOWNLOAD_BASE}/{tag}/{name}"] = served
            assets.append(self.asset(tag, name))
            files_meta[abi] = {"file": name, "sha256": digest(data), "size": len(data)}
        if manifest:
            meta = {
                "schema": 1,
                "tag": tag,
                "version_name": version,
                "version_code": code,
                "abis": list(abis),
                "files": files_meta,
                "changelog": ["first", "second"],
            }
            self.files[f"{DOWNLOAD_BASE}/{tag}/release.json"] = json.dumps(meta).encode()
            assets.append(self.asset(tag, "release.json"))
        if sums:
            text = "".join(f"{m['sha256']}  {m['file']}\n" for m in files_meta.values())
            self.files[f"{DOWNLOAD_BASE}/{tag}/SHA256SUMS"] = text.encode()
            assets.append(self.asset(tag, "SHA256SUMS"))
        self.releases.append(
            {
                "tag_name": tag,
                "draft": draft,
                "prerelease": prerelease,
                "body": body,
                "assets": assets,
            }
        )

    @staticmethod
    def asset(tag: str, name: str) -> dict:
        return {"name": name, "browser_download_url": f"{DOWNLOAD_BASE}/{tag}/{name}"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status:
            return httpx.Response(self.status, headers=self.headers)
        url = str(request.url)
        if url == API_RELEASES:
            return httpx.Response(200, json=self.releases)
        if url in self.files:
            return httpx.Response(200, content=self.files[url])
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler), follow_redirects=True)

    def downloads(self) -> list[str]:
        return [str(r.url) for r in self.requests if r.url.host == "github.com"]


@pytest.fixture
def github() -> Github:
    return Github()


def sync(cfg: Config, github: Github, **kwargs):
    return appsync.sync_github(cfg, REPO, client=github.client(), **kwargs)


def test_publishes_the_newest_release_and_verifies_every_apk(tmp_path, github):
    github.add_release("0.3.0", 3000)
    github.add_release("0.3.1", 3001)
    github.add_release("0.2.9", 2009)
    cfg = make_cfg(tmp_path)
    result = sync(cfg, github)
    assert result.status == "published"
    assert (result.version_name, result.version_code) == ("0.3.1", 3001)
    app_dir = tmp_path / "app"
    for abi in ABIS:
        assert (app_dir / f"u-tubot_0.3.1_{abi}.apk").read_bytes() == apk_bytes("0.3.1", abi)
    latest = json.loads((app_dir / "latest.json").read_text())
    assert latest["version_code"] == 3001
    assert latest["changelog"] == ["first", "second"]
    update = json.loads((app_dir / "update.json").read_text())
    assert update["0.3.1"]["versionCode"] == 3001
    assert update["package"]["downloadUrlList_arm64-v8a"] == [
        "https://utubot.example.com/app/u-tubot_0.3.1_arm64-v8a.apk"
    ]
    assert not [p for p in app_dir.iterdir() if p.name.startswith(".sync-")]


def test_second_run_is_a_no_op_without_downloading(tmp_path, github):
    github.add_release("0.3.1", 3001)
    cfg = make_cfg(tmp_path)
    sync(cfg, github)
    first_downloads = len(github.downloads())
    result = sync(cfg, github)
    assert result.status == "up-to-date"
    assert len(github.downloads()) == first_downloads + 1  # only release.json is fetched again


def test_older_or_equal_release_does_not_replace_the_channel(tmp_path, github):
    github.add_release("0.3.1", 3001)
    cfg = make_cfg(tmp_path)
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "latest.json").write_text(
        json.dumps({"version_name": "0.4.0", "version_code": 4000})
    )
    assert sync(cfg, github).status == "up-to-date"
    assert not any(app_dir.glob("*.apk"))


def test_version_code_decides_not_the_date_or_list_order(tmp_path, github):
    github.add_release("0.3.0", 3000)
    github.add_release("0.10.0", 10000)
    github.add_release("0.9.0", 9000)
    assert sync(make_cfg(tmp_path), github).version_name == "0.10.0"


def test_drafts_and_prereleases_are_skipped_unless_asked(tmp_path, github):
    github.add_release("0.3.0", 3000)
    github.add_release("0.3.1", 3001, draft=True)
    github.add_release("0.3.2", 3002, prerelease=True)
    assert sync(make_cfg(tmp_path), github).version_name == "0.3.0"
    assert sync(make_cfg(tmp_path / "pre"), github, include_prerelease=True).version_name == "0.3.2"


def test_no_matching_release(tmp_path, github):
    github.releases.append({"tag_name": "v1.0", "assets": []})
    assert sync(make_cfg(tmp_path), github).status == "no-release"


def test_sha256_mismatch_publishes_nothing(tmp_path, github):
    github.add_release("0.3.1", 3001, tamper="armeabi-v7a")
    cfg = make_cfg(tmp_path)
    with pytest.raises(appsync.SyncError, match="does not match"):
        sync(cfg, github)
    assert not (tmp_path / "app" / "update.json").exists()
    assert not any((tmp_path / "app").glob("*.apk"))


def test_certificate_must_match_the_pin(tmp_path, github, monkeypatch):
    github.add_release("0.3.1", 3001)
    monkeypatch.setenv("FAKE_CERT", OTHER_PIN)
    with pytest.raises(appsync.SyncError, match="not the pinned"):
        sync(make_cfg(tmp_path), github)
    assert not (tmp_path / "app" / "update.json").exists()


def test_apksigner_rejection_publishes_nothing(tmp_path, github, monkeypatch):
    github.add_release("0.3.1", 3001)
    monkeypatch.setenv("FAKE_REJECT", "1")
    with pytest.raises(appsync.SyncError, match="DOES NOT VERIFY"):
        sync(make_cfg(tmp_path), github)
    assert not (tmp_path / "app" / "update.json").exists()


def test_configured_but_missing_apksigner_refuses_instead_of_weakening_the_check(tmp_path, github):
    github.add_release("0.3.1", 3001)
    cfg = make_cfg(tmp_path, apksigner_path=str(tmp_path / "nowhere" / "apksigner"))
    with pytest.raises(appsync.SyncError, match="apksigner_path"):
        sync(cfg, github)
    assert not (tmp_path / "app").exists()


def builtin_cfg(tmp_path: Path, **app) -> Config:
    return make_cfg(
        tmp_path, **{"apksigner_path": "", "signing_cert_sha256": SIGNED_APK_CERT, **app}
    )


def test_builtin_verifier_publishes_a_correctly_signed_apk(tmp_path, github):
    github.add_release("0.3.1", 3001, apk_data=SIGNED_APK)
    result = sync(builtin_cfg(tmp_path), github)
    assert result.status == "published"
    assert (tmp_path / "app" / "u-tubot_0.3.1_arm64-v8a.apk").read_bytes() == SIGNED_APK


def test_builtin_verifier_refuses_another_certificate(tmp_path, github):
    github.add_release("0.3.1", 3001, apk_data=SIGNED_APK)
    with pytest.raises(appsync.SyncError, match="not the pinned"):
        sync(builtin_cfg(tmp_path, signing_cert_sha256=OTHER_PIN), github)
    assert not (tmp_path / "app" / "update.json").exists()


def test_builtin_verifier_refuses_an_apk_changed_after_signing(tmp_path, github):
    changed = bytearray(SIGNED_APK)
    changed[0] ^= 0xFF
    github.add_release("0.3.1", 3001, apk_data=bytes(changed))
    with pytest.raises(appsync.SyncError, match="changed after signing"):
        sync(builtin_cfg(tmp_path), github)
    assert not any((tmp_path / "app").glob("*.apk"))


def test_builtin_verifier_refuses_an_unsigned_apk(tmp_path, github):
    github.add_release("0.3.1", 3001)
    with pytest.raises(appsync.SyncError, match="failed signature verification"):
        sync(builtin_cfg(tmp_path), github)


def test_a_pin_is_required_to_publish(tmp_path, github):
    github.add_release("0.3.1", 3001)
    with pytest.raises(appsync.SyncError, match="signing_cert_sha256"):
        sync(make_cfg(tmp_path, signing_cert_sha256=""), github)


def test_pin_accepts_colons_and_upper_case(tmp_path, github):
    github.add_release("0.3.1", 3001)
    pin = ":".join(PIN[i : i + 2] for i in range(0, len(PIN), 2)).upper()
    assert sync(make_cfg(tmp_path, signing_cert_sha256=pin), github).status == "published"


def test_malformed_pin_is_refused(tmp_path, github):
    github.add_release("0.3.1", 3001)
    with pytest.raises(appsync.SyncError, match="64 hex"):
        sync(make_cfg(tmp_path, signing_cert_sha256="12345"), github)


def test_dry_run_downloads_no_apk_and_writes_nothing(tmp_path, github):
    github.add_release("0.3.1", 3001)
    result = sync(make_cfg(tmp_path), github, dry_run=True)
    assert result.status == "would-publish"
    assert github.downloads() == [f"{DOWNLOAD_BASE}/utubot-v0.3.1/release.json"]
    assert not (tmp_path / "app").exists()


def test_dry_run_warns_about_missing_pin_and_apksigner(tmp_path, github):
    github.add_release("0.3.1", 3001)
    cfg = make_cfg(tmp_path, signing_cert_sha256="", apksigner_path=str(tmp_path / "missing"))
    lines = sync(cfg, github, dry_run=True).lines
    assert any("signing_cert_sha256 is not set" in line for line in lines)
    assert any("not an executable" in line for line in lines)


def test_dry_run_names_the_signature_check(tmp_path, github):
    github.add_release("0.3.1", 3001)
    assert any(
        "built-in" in line for line in sync(builtin_cfg(tmp_path), github, dry_run=True).lines
    )
    assert any(
        "fake-apksigner" in line for line in sync(make_cfg(tmp_path), github, dry_run=True).lines
    )


def test_release_without_manifest_falls_back_to_checksums_and_file_names(tmp_path, github):
    github.add_release(
        "0.2.2",
        None,
        abis=("arm64-v8a", "x86"),
        manifest=False,
        sums=True,
        body="- fix one\n  continued\n- fix two",
    )
    cfg = make_cfg(tmp_path)
    result = sync(cfg, github)
    assert result.status == "published"
    assert result.version_code == 2002
    latest = json.loads((tmp_path / "app" / "latest.json").read_text())
    assert sorted(latest["files"]) == ["arm64-v8a", "x86"]
    assert latest["changelog"] == ["fix one continued", "fix two"]
    assert sync(cfg, github).status == "up-to-date"


def test_fallback_compares_version_names_with_the_channel(tmp_path, github):
    github.add_release("0.2.2", None, manifest=False, sums=True)
    cfg = make_cfg(tmp_path)
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "latest.json").write_text(json.dumps({"version_name": "0.2.2", "version_code": 4}))
    assert sync(cfg, github).status == "up-to-date"


def test_fallback_needs_a_checksum_for_every_apk(tmp_path, github):
    github.add_release("0.2.2", None, manifest=False, sums=True)
    sums_url = f"{DOWNLOAD_BASE}/utubot-v0.2.2/SHA256SUMS"
    github.files[sums_url] = github.files[sums_url].splitlines(keepends=True)[0]
    with pytest.raises(appsync.SyncError, match="SHA-256"):
        sync(make_cfg(tmp_path), github)


def test_manifest_asset_name_and_url_are_validated(tmp_path, github):
    github.add_release("0.3.1", 3001)
    meta_url = f"{DOWNLOAD_BASE}/utubot-v0.3.1/release.json"
    meta = json.loads(github.files[meta_url])
    meta["files"]["arm64-v8a"]["file"] = "../evil.apk"
    github.files[meta_url] = json.dumps(meta).encode()
    with pytest.raises(appsync.SyncError):
        sync(make_cfg(tmp_path), github)

    other = Github()
    other.add_release("0.3.1", 3001)
    other.releases[0]["assets"][0]["browser_download_url"] = "https://evil.example.com/x.apk"
    with pytest.raises(appsync.SyncError, match="unexpected download URL"):
        sync(make_cfg(tmp_path / "other"), other)


def test_manifest_must_agree_with_the_tag(tmp_path, github):
    github.add_release("0.3.1", 3001)
    meta_url = f"{DOWNLOAD_BASE}/utubot-v0.3.1/release.json"
    meta = json.loads(github.files[meta_url])
    meta["version_name"] = "0.3.2"
    github.files[meta_url] = json.dumps(meta).encode()
    with pytest.raises(appsync.SyncError, match="tag is"):
        sync(make_cfg(tmp_path), github)


def test_download_size_cap(tmp_path, github):
    github.add_release("0.3.1", 3001)
    with pytest.raises(appsync.SyncError, match="larger than"):
        sync(make_cfg(tmp_path, sync_max_apk_bytes=10), github)


def test_network_and_rate_limit_errors_are_transient(tmp_path, github):
    github.add_release("0.3.1", 3001)
    github.status = 503
    with pytest.raises(appsync.TransientError):
        sync(make_cfg(tmp_path), github)
    github.status = 403
    github.headers = {"x-ratelimit-remaining": "0"}
    with pytest.raises(appsync.TransientError, match="rate limit"):
        sync(make_cfg(tmp_path), github)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = httpx.Client(transport=httpx.MockTransport(boom))
    with pytest.raises(appsync.TransientError):
        appsync.sync_github(make_cfg(tmp_path), REPO, client=client)


def test_missing_repository_is_a_hard_error(tmp_path, github):
    github.status = 404
    with pytest.raises(appsync.SyncError) as caught:
        sync(make_cfg(tmp_path), github)
    assert not isinstance(caught.value, appsync.TransientError)


def test_token_goes_only_to_the_api(tmp_path, github, monkeypatch):
    github.add_release("0.3.1", 3001)
    monkeypatch.setenv("UTUBOT_GITHUB_TOKEN", "secret-token")
    sync(make_cfg(tmp_path), github)
    for request in github.requests:
        has_token = request.headers.get("authorization") == "Bearer secret-token"
        assert has_token == (request.url.host == "api.github.com")


def test_prune_keeps_the_newest_versions_and_only_apk_files(tmp_path, github):
    cfg = make_cfg(tmp_path, keep_versions=2)
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    for version in ("0.2.0", "0.2.1", "0.2.2"):
        (app_dir / f"u-tubot_{version}_arm64-v8a.apk").write_bytes(b"old")
    (app_dir / "notes.txt").write_text("keep me")
    (app_dir / "u-tubot_custom.apk").write_bytes(b"not a release name")
    github.add_release("0.3.0", 3000)
    result = sync(cfg, github)
    assert "u-tubot_0.2.0_arm64-v8a.apk" in " ".join(result.lines)
    names = {p.name for p in app_dir.iterdir()}
    assert "u-tubot_0.2.0_arm64-v8a.apk" not in names
    assert "u-tubot_0.2.1_arm64-v8a.apk" not in names
    assert {"u-tubot_0.2.2_arm64-v8a.apk", "notes.txt", "u-tubot_custom.apk"} <= names
    assert "u-tubot_0.3.0_universal.apk" in names


def test_keep_zero_prunes_nothing(tmp_path, github):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "u-tubot_0.1.0_universal.apk").write_bytes(b"old")
    github.add_release("0.3.0", 3000)
    sync(make_cfg(tmp_path), github)
    assert (app_dir / "u-tubot_0.1.0_universal.apk").exists()


def test_repository_name_is_validated(tmp_path, github):
    with pytest.raises(appsync.SyncError, match="OWNER/NAME"):
        appsync.sync_github(make_cfg(tmp_path), "not a repo", client=github.client())


def write_config(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "c.toml"
    path.write_text(
        f'[server]\ndata_dir="{tmp_path}/d"\napp_dir="{tmp_path}/app"\n'
        'public_base_url="https://utubot.example.com"\n'
        f'[app]\ngithub_repo="{REPO}"\nsigning_cert_sha256="{PIN}"\n'
        f'apksigner_path="{fake_apksigner(tmp_path)}"\n{extra}'
    )
    return path


def run_cli(tmp_path, github, monkeypatch, *args) -> int:
    monkeypatch.setattr(appsync, "new_client", lambda cfg: github.client())
    return main(["--config", str(write_config(tmp_path)), "app", "sync-github", *args])


def test_cli_publishes_and_reports(tmp_path, github, monkeypatch, capsys):
    github.add_release("0.3.1", 3001)
    assert run_cli(tmp_path, github, monkeypatch) == 0
    assert "published 0.3.1 (3001)" in capsys.readouterr().out
    assert (tmp_path / "app" / "update.json").exists()
    assert run_cli(tmp_path, github, monkeypatch) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_cli_dry_run(tmp_path, github, monkeypatch, capsys):
    github.add_release("0.3.1", 3001)
    assert run_cli(tmp_path, github, monkeypatch, "--dry-run") == 0
    out = capsys.readouterr().out
    assert "dry run:" in out and "would download" in out
    assert not (tmp_path / "app").exists()


def test_cli_exit_codes(tmp_path, github, monkeypatch, capsys):
    github.add_release("0.3.1", 3001, tamper="universal")
    assert run_cli(tmp_path, github, monkeypatch) == 1
    assert "does not match" in capsys.readouterr().err
    github.status = 503
    assert run_cli(tmp_path, github, monkeypatch) == appsync.EXIT_TEMPFAIL


def test_cli_needs_a_repository(tmp_path, capsys):
    path = tmp_path / "c.toml"
    path.write_text('[server]\ndata_dir="d"\n')
    assert main(["--config", str(path), "app", "sync-github"]) == 1
    assert "github_repo" in capsys.readouterr().err
