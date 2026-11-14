"""Pull published GitHub releases of the app into the update channel (`utubot app sync-github`).

The release workflow attaches `release.json` (version, versionCode, ABIs, SHA-256 per APK) to every release. A release is
published into the channel only when its versionCode is newer than the channel's, every download matches its SHA-256 and
every APK's signing certificate equals the pinned one (`[app] signing_cert_sha256`). The signature is checked by `apksigner`
when `[app] apksigner_path` is set and by the built-in reader (`apksig`) otherwise. The APK's own manifest (`apkmanifest`) must
agree with the release metadata: package `dev.utubot.tv`, its versionName and, when release.json gives one, its versionCode.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from . import apkmanifest, apksig, appchannel
from .config import Config

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
USER_AGENT = "utubot-sync"
APPLICATION_ID = "dev.utubot.tv"
TAG_PREFIX = "utubot-v"
TAG_RE = re.compile(rf"^{TAG_PREFIX}(\d+)\.(\d+)\.(\d+)$")
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
APK_FILE_RE = re.compile(
    rf"^{re.escape(appchannel.APK_NAME_PREFIX)}_(\d+\.\d+\.\d+)_("
    + "|".join(appchannel.ABIS)
    + r")\.apk$"
)
BULLET_RE = re.compile(r"^\s*[-*]\s+(\S.*)$")
CERT_RE = re.compile(r"certificate SHA-256 digest: ([0-9a-fA-F]{64})")
RELEASE_MANIFEST = "release.json"
CHECKSUMS = "SHA256SUMS"
MANIFEST_SCHEMA = 1
HASH_CHUNK_BYTES = appchannel.HASH_CHUNK_BYTES
MAX_METADATA_BYTES = 1 << 20
MAX_CHANGELOG_LINES = 20
# Same rule as the Gradle build: versionCode = major * 1000000 + minor * 1000 + patch.
VERSION_CODE_MAJOR_STEP = 1_000_000
VERSION_CODE_MINOR_STEP = 1_000
EXIT_TEMPFAIL = 75


class SyncError(Exception):
    """The release cannot be published: bad metadata, failed verification, wrong configuration."""


class TransientError(SyncError):
    """GitHub could not be reached or is rate limiting; try again later."""


@dataclass
class SyncResult:
    status: str  # no-release | up-to-date | would-publish | published
    version_name: str | None = None
    version_code: int | None = None
    lines: list[str] = field(default_factory=list)


@dataclass
class ReleaseFile:
    abi: str
    name: str
    sha256: str
    url: str


@dataclass
class ReleaseInfo:
    version_name: str
    version_code: int
    changelog: list[str]
    files: list[ReleaseFile]
    has_manifest: bool


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.match(text.strip()) if isinstance(text, str) else None
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def derive_version_code(version: tuple[int, int, int]) -> int:
    major, minor, patch = version
    return major * VERSION_CODE_MAJOR_STEP + minor * VERSION_CODE_MINOR_STEP + patch


def normalize_pin(text: str) -> str:
    pin = text.replace(":", "").strip().lower()
    if pin and not SHA256_RE.match(pin):
        raise SyncError("[app] signing_cert_sha256 must be 64 hex digits (colons allowed)")
    return pin


def new_client(cfg: Config) -> httpx.Client:
    return httpx.Client(
        timeout=cfg.app.sync_timeout_s,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def _request(
    client: httpx.Client, url: str, headers: dict[str, str] | None = None
) -> httpx.Response:
    try:
        response = client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise TransientError(f"cannot reach {httpx.URL(url).host}: {type(exc).__name__}") from exc
    if response.status_code == 429 or (
        response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0"
    ):
        raise TransientError(
            "GitHub rate limit reached; set a token in the env var named by [app] github_token_env"
        )
    if response.status_code >= 500:
        raise TransientError(f"GitHub answered HTTP {response.status_code}")
    if response.status_code != 200:
        raise SyncError(f"GET {httpx.URL(url).path} answered HTTP {response.status_code}")
    return response


def _api_headers(cfg: Config) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": GITHUB_API_VERSION}
    token = os.environ.get(cfg.app.github_token_env, "") if cfg.app.github_token_env else ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def pick_release(
    releases: list[Any], include_prerelease: bool
) -> tuple[dict, tuple[int, int, int]] | None:
    """The newest non-draft release whose tag is utubot-vX.Y.Z (by version, not by date)."""
    best: tuple[dict, tuple[int, int, int]] | None = None
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        if release.get("prerelease") and not include_prerelease:
            continue
        match = TAG_RE.match(str(release.get("tag_name", "")))
        if not match:
            continue
        version = (int(match[1]), int(match[2]), int(match[3]))
        if best is None or version > best[1]:
            best = (release, version)
    return best


def _asset_url(repo: str, tag: str, asset: dict) -> str:
    """The public download URL of an asset, accepted only when it points into this repository's releases."""
    url = str(asset.get("browser_download_url", ""))
    expected = f"https://github.com/{repo}/releases/download/{tag}/".lower()
    if not url.lower().startswith(expected):
        raise SyncError(f"asset {asset.get('name')!r} has an unexpected download URL")
    return url


def _fetch_small(client: httpx.Client, url: str) -> bytes:
    body = _request(client, url).content
    if len(body) > MAX_METADATA_BYTES:
        raise SyncError(f"{httpx.URL(url).path} is larger than {MAX_METADATA_BYTES} bytes")
    return body


def _bullets(text: str) -> list[str]:
    """The "- " / "* " items of a Markdown text; indented continuation lines are joined to their item."""
    items: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        match = BULLET_RE.match(line)
        if match:
            current = [match[1].strip()]
            items.append(current)
        elif current is not None and line.strip() and line[0].isspace():
            current.append(line.strip())
        else:
            current = None
    return [" ".join(parts) for parts in items][:MAX_CHANGELOG_LINES]


def _checked_file(abi: object, name: object, sha256: object, version: str, url: str) -> ReleaseFile:
    if abi not in appchannel.ABIS:
        raise SyncError(f"unknown ABI {abi!r} in the release")
    match = APK_FILE_RE.match(str(name))
    if not match or match[1] != version or match[2] != abi:
        raise SyncError(f"{name!r} is not {appchannel.apk_filename(version, str(abi))}")
    digest = str(sha256).lower()
    if not SHA256_RE.match(digest):
        raise SyncError(f"{name} has no valid SHA-256 in the release metadata")
    return ReleaseFile(str(abi), str(name), digest, url)


def _manifest_info(
    data: Any, repo: str, tag: str, version: tuple[int, int, int], assets: dict[str, dict]
) -> ReleaseInfo:
    if not isinstance(data, dict) or data.get("schema", MANIFEST_SCHEMA) != MANIFEST_SCHEMA:
        raise SyncError(f"{RELEASE_MANIFEST} is not a schema {MANIFEST_SCHEMA} manifest")
    version_name = str(data.get("version_name", ""))
    code = data.get("version_code")
    if parse_version(version_name) != version or version_name != tag.removeprefix(TAG_PREFIX):
        raise SyncError(f"{RELEASE_MANIFEST} says version {version_name!r} but the tag is {tag}")
    if not isinstance(code, int) or isinstance(code, bool) or code <= 0:
        raise SyncError(f"{RELEASE_MANIFEST} has no valid version_code")
    files_meta = data.get("files")
    if not isinstance(files_meta, dict) or not files_meta:
        raise SyncError(f"{RELEASE_MANIFEST} lists no APK files")
    files = []
    for abi, meta in files_meta.items():
        meta = meta if isinstance(meta, dict) else {}
        asset = assets.get(str(meta.get("file")))
        if asset is None:
            raise SyncError(
                f"{meta.get('file')!r} from {RELEASE_MANIFEST} is not attached to {tag}"
            )
        files.append(
            _checked_file(
                abi,
                meta.get("file"),
                meta.get("sha256"),
                version_name,
                _asset_url(repo, tag, asset),
            )
        )
    changelog = [str(line) for line in data.get("changelog", []) if isinstance(line, str)]
    return ReleaseInfo(version_name, code, changelog[:MAX_CHANGELOG_LINES], files, True)


def _checksums(text: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            sums[parts[1].strip().lstrip("*")] = parts[0].lower()
    return sums


def _legacy_info(
    client: httpx.Client,
    repo: str,
    release: dict,
    tag: str,
    version: tuple[int, int, int],
    assets: dict[str, dict],
) -> ReleaseInfo:
    """A release without release.json: ABIs from the APK file names, hashes from SHA256SUMS, versionCode derived."""
    sums_asset = assets.get(CHECKSUMS)
    if sums_asset is None:
        raise SyncError(f"{tag} has neither {RELEASE_MANIFEST} nor {CHECKSUMS}")
    sums = _checksums(
        _fetch_small(client, _asset_url(repo, tag, sums_asset)).decode("utf-8", "replace")
    )
    version_name = tag.removeprefix(TAG_PREFIX)
    files = []
    for name, asset in sorted(assets.items()):
        match = APK_FILE_RE.match(name)
        if not match or match[1] != version_name:
            continue
        files.append(
            _checked_file(
                match[2], name, sums.get(name), version_name, _asset_url(repo, tag, asset)
            )
        )
    if not files:
        raise SyncError(f"{tag} has no u-tubot_{version_name}_<abi>.apk assets")
    return ReleaseInfo(
        version_name,
        derive_version_code(version),
        _bullets(str(release.get("body") or "")),
        files,
        False,
    )


def release_info(
    client: httpx.Client, repo: str, release: dict, version: tuple[int, int, int]
) -> ReleaseInfo:
    tag = str(release["tag_name"])
    assets = {
        str(a.get("name")): a
        for a in release.get("assets", [])
        if isinstance(a, dict) and a.get("name")
    }
    manifest_asset = assets.get(RELEASE_MANIFEST)
    if manifest_asset is None:
        return _legacy_info(client, repo, release, tag, version, assets)
    body = _fetch_small(client, _asset_url(repo, tag, manifest_asset))
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise SyncError(f"{RELEASE_MANIFEST} of {tag} is not valid JSON") from exc
    return _manifest_info(data, repo, tag, version, assets)


def is_newer(info: ReleaseInfo, latest: dict | None) -> bool:
    """versionCode decides; a release without release.json has a derived code, so its version name decides."""
    if not latest:
        return True
    if info.has_manifest:
        current = latest.get("version_code")
        return not isinstance(current, int) or info.version_code > current
    current_version = parse_version(str(latest.get("version_name", "")))
    return current_version is None or parse_version(info.version_name) > current_version


def apksigner_certificates(
    cfg: Config, apksigner: str, apk: Path, runner: Callable[..., Any] = subprocess.run
) -> list[str]:
    try:
        done = runner(
            [apksigner, "verify", "--print-certs", str(apk)],
            capture_output=True,
            text=True,
            timeout=cfg.app.apksigner_timeout_s,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SyncError(f"apksigner could not run on {apk.name}: {type(exc).__name__}") from exc
    if done.returncode != 0:
        reason = (done.stderr or done.stdout).strip().splitlines()[:1]
        raise SyncError(
            f"apksigner rejected {apk.name}: {reason[0] if reason else 'no reason given'}"
        )
    return [d.lower() for d in CERT_RE.findall(done.stdout)]


def builtin_certificates(apk: Path) -> list[str]:
    try:
        return [signer.sha256 for signer in apksig.verify_apk(apk)]
    except apksig.SignatureError as exc:
        raise SyncError(f"{apk.name} failed signature verification: {exc}") from exc


def verify_signature(
    cfg: Config,
    apksigner: str | None,
    apk: Path,
    pin: str,
    runner: Callable[..., Any] = subprocess.run,
) -> None:
    """Refuse the APK unless its signature is valid and every signer's certificate is the pinned one."""
    digests = (
        apksigner_certificates(cfg, apksigner, apk, runner)
        if apksigner
        else builtin_certificates(apk)
    )
    if not digests:
        raise SyncError(f"no signing certificate was reported for {apk.name}")
    if any(d != pin for d in digests):
        raise SyncError(f"{apk.name} is signed with certificate {digests[0]}, not the pinned {pin}")


def check_manifest(apk: Path, info: ReleaseInfo) -> None:
    """Refuse the APK unless its own manifest agrees with the release metadata: package, versionName and, when
    release.json supplied one, versionCode. A release without release.json has a derived code, which is not compared."""
    try:
        declared = apkmanifest.read_apk_manifest(apk)
    except apkmanifest.ManifestError as exc:
        raise SyncError(f"{apk.name}: {exc}") from exc
    if declared.package != APPLICATION_ID:
        raise SyncError(f"{apk.name} is package {declared.package!r}, not {APPLICATION_ID!r}")
    if declared.version_name != info.version_name:
        raise SyncError(
            f"{apk.name} declares versionName {declared.version_name!r} but the release is {info.version_name}"
        )
    if info.has_manifest and declared.version_code != info.version_code:
        raise SyncError(
            f"{apk.name} declares versionCode {declared.version_code} but {RELEASE_MANIFEST} says {info.version_code}"
        )


def resolve_apksigner(cfg: Config) -> str | None:
    """The configured apksigner, or None to use the built-in verifier. A configured path that does not run is an error."""
    configured = cfg.app.apksigner_path.strip()
    if not configured:
        return None
    found = shutil.which(configured)
    if not found:
        raise SyncError(
            f"[app] apksigner_path {configured!r} is not an executable file; fix it or unset it to use the built-in verifier"
        )
    return found


def _download(client: httpx.Client, url: str, dest: Path, max_bytes: int) -> str:
    digest = hashlib.sha256()
    size = 0
    try:
        with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise (TransientError if response.status_code >= 500 else SyncError)(
                    f"download of {dest.name} answered HTTP {response.status_code}"
                )
            with dest.open("wb") as out:
                for chunk in response.iter_bytes(HASH_CHUNK_BYTES):
                    size += len(chunk)
                    if size > max_bytes:
                        raise SyncError(f"{dest.name} is larger than the {max_bytes} byte limit")
                    digest.update(chunk)
                    out.write(chunk)
    except httpx.HTTPError as exc:
        raise TransientError(f"download of {dest.name} failed: {type(exc).__name__}") from exc
    return digest.hexdigest()


def prune_old_versions(app_dir: Path, keep: int) -> list[str]:
    """Delete the APK files of all but the newest `keep` versions; other files are never touched."""
    if keep <= 0 or not app_dir.is_dir():
        return []
    by_version: dict[tuple[int, int, int], list[Path]] = {}
    for path in app_dir.iterdir():
        match = APK_FILE_RE.match(path.name)
        if match and path.is_file():
            version = parse_version(match[1])
            if version:
                by_version.setdefault(version, []).append(path)
    removed = []
    for version in sorted(by_version, reverse=True)[keep:]:
        for path in by_version[version]:
            path.unlink()
            removed.append(path.name)
    return sorted(removed)


def sync_github(
    cfg: Config,
    repo: str,
    *,
    include_prerelease: bool = False,
    dry_run: bool = False,
    client: httpx.Client | None = None,
    runner: Callable[..., Any] = subprocess.run,
) -> SyncResult:
    if not REPO_RE.match(repo):
        raise SyncError(f"repository must look like OWNER/NAME, got {repo!r}")
    pin = normalize_pin(cfg.app.signing_cert_sha256)
    own_client = client is None
    client = client or new_client(cfg)
    try:
        listing = _request(
            client,
            f"{GITHUB_API}/repos/{repo}/releases?per_page={cfg.app.sync_releases_per_page}",
            _api_headers(cfg),
        )
        try:
            releases = listing.json()
        except json.JSONDecodeError as exc:
            raise SyncError("GitHub returned an unreadable release list") from exc
        picked = pick_release(releases if isinstance(releases, list) else [], include_prerelease)
        if picked is None:
            return SyncResult("no-release", lines=[f"{repo} has no {TAG_PREFIX}X.Y.Z release"])
        release, version = picked
        info = release_info(client, repo, release, version)
        latest = appchannel.load_latest(cfg)
        channel = (
            f"channel at {latest.get('version_name')} (versionCode {latest.get('version_code')})"
            if latest
            else "channel is empty"
        )
        source = (
            "release.json"
            if info.has_manifest
            else f"{CHECKSUMS} (no {RELEASE_MANIFEST}; versionCode derived)"
        )
        head = f"{release['tag_name']}: {info.version_name}, versionCode {info.version_code}, from {source}; {channel}"
        if not is_newer(info, latest):
            return SyncResult(
                "up-to-date", info.version_name, info.version_code, [head, "nothing to do"]
            )
        names = ", ".join(f.name for f in info.files)
        if dry_run:
            lines = [
                head,
                f"would download {names}",
                "would verify SHA-256, the signing certificate and the APK manifest (package, version), then publish",
            ]
            if not pin:
                lines.append(
                    "WARNING: [app] signing_cert_sha256 is not set; a real run would refuse"
                )
            try:
                apksigner = resolve_apksigner(cfg)
                lines.append(
                    f"signature check: apksigner {apksigner}"
                    if apksigner
                    else "signature check: built-in v2/v3 verifier (no [app] apksigner_path)"
                )
            except SyncError as exc:
                lines.append(f"WARNING: {exc}; a real run would refuse")
            return SyncResult("would-publish", info.version_name, info.version_code, lines)
        if not pin:
            raise SyncError(
                "set [app] signing_cert_sha256 to the release certificate's SHA-256 before syncing"
            )
        apksigner = resolve_apksigner(cfg)
        app_dir = cfg.app_dir
        app_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".sync-", dir=app_dir) as tmp:
            apks = []
            for item in info.files:
                dest = Path(tmp) / item.name
                actual = _download(client, item.url, dest, cfg.app.sync_max_apk_bytes)
                if actual != item.sha256:
                    raise SyncError(
                        f"{item.name}: SHA-256 {actual} does not match the release's {item.sha256}"
                    )
                verify_signature(cfg, apksigner, dest, pin, runner)
                check_manifest(dest, info)
                apks.append(dest)
            try:
                appchannel.publish(cfg, apks, info.version_name, info.version_code, info.changelog)
            except appchannel.PublishError as exc:
                raise SyncError(str(exc)) from exc
        removed = prune_old_versions(app_dir, cfg.app.keep_versions)
        lines = [head, f"published {info.version_name} ({info.version_code}): {names}"]
        if removed:
            lines.append(f"removed old APK files: {', '.join(removed)}")
        return SyncResult("published", info.version_name, info.version_code, lines)
    finally:
        if own_client:
            client.close()
