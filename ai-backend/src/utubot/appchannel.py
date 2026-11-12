"""The app update channel: published APKs, update.json (Electric Eel format) and the latest-file index."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

from .config import Config

UNIVERSAL = "universal"
ABIS = ("arm64-v8a", "armeabi-v7a", "x86_64", "x86", UNIVERSAL)
ABI_FROM_NAME_RE = re.compile(r"(?:^|[_-])(arm64-v8a|armeabi-v7a|x86_64|x86|universal)$")
APK_NAME_PREFIX = "u-tubot"
UPDATE_FILE = "update.json"
LATEST_FILE = "latest.json"
HASH_CHUNK_BYTES = 1 << 20


class PublishError(Exception):
    pass


def detect_abi(path: Path) -> str | None:
    match = ABI_FROM_NAME_RE.search(path.stem)
    return match.group(1) if match else None


def apk_filename(version_name: str, abi: str) -> str:
    return f"{APK_NAME_PREFIX}_{version_name}_{abi}.apk"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def build_update_json(
    existing: dict,
    urls: dict[str, str],
    version_name: str,
    version_code: int,
    changelog: list[str],
) -> dict:
    """update.json for the app's checker: `downloadUrlList_<abi>` per architecture, plus a generic list."""
    package: dict[str, list[str]] = {f"downloadUrlList_{abi}": [url] for abi, url in urls.items()}
    generic = urls.get(UNIVERSAL) or next(
        (urls[abi] for abi in ("arm64-v8a", "armeabi-v7a", "x86_64", "x86") if abi in urls), None
    )
    if generic:
        package["downloadUrlList"] = [generic]
    out: dict = {
        "package": package,
        version_name: {"versionCode": version_code, "changelog": changelog},
    }
    for key, value in existing.items():
        if key not in ("package", version_name):
            out[key] = value
    return out


def publish(
    cfg: Config,
    apks: list[Path],
    version_name: str,
    version_code: int,
    changelog: list[str],
    abi_override: str | None = None,
) -> Path:
    """Copy the APKs (one per ABI) into app_dir and rewrite update.json and latest.json."""
    if not apks:
        raise PublishError("no APK given")
    if abi_override and abi_override not in ABIS:
        raise PublishError(f"unknown ABI {abi_override!r}; use one of {', '.join(ABIS)}")
    if abi_override and len(apks) != 1:
        raise PublishError("--abi works with exactly one APK")
    chosen: dict[str, Path] = {}
    for apk in apks:
        if not apk.is_file() or apk.suffix != ".apk":
            raise PublishError(f"{apk} is not an existing .apk file")
        abi = abi_override or detect_abi(apk) or (UNIVERSAL if len(apks) == 1 else None)
        if abi is None:
            raise PublishError(f"cannot tell the ABI of {apk.name}; name it ..._<abi>.apk")
        if abi in chosen:
            raise PublishError(f"two APKs for {abi}: {chosen[abi].name} and {apk.name}")
        chosen[abi] = apk
    app_dir = cfg.app_dir
    app_dir.mkdir(parents=True, exist_ok=True)
    base = cfg.server.public_base_url.rstrip("/")
    urls: dict[str, str] = {}
    files: dict[str, dict] = {}
    for abi in ABIS:
        if abi not in chosen:
            continue
        name = apk_filename(version_name, abi)
        target = app_dir / name
        shutil.copyfile(chosen[abi], target)
        urls[abi] = f"{base}/app/{name}"
        files[abi] = {"file": name, "size": target.stat().st_size, "sha256": _sha256(target)}
    manifest = app_dir / UPDATE_FILE
    existing = json.loads(manifest.read_text()) if manifest.exists() else {}
    manifest.write_text(
        json.dumps(
            build_update_json(existing, urls, version_name, version_code, changelog), indent=2
        )
        + "\n"
    )
    (app_dir / LATEST_FILE).write_text(
        json.dumps(
            {
                "version_name": version_name,
                "version_code": version_code,
                "changelog": changelog,
                "files": files,
            },
            indent=2,
        )
        + "\n"
    )
    return manifest


def load_latest(cfg: Config) -> dict | None:
    path = cfg.app_dir / LATEST_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def public_info(cfg: Config) -> dict:
    """What the landing page shows: no secrets, only published artifacts and configured codes."""
    latest = load_latest(cfg)
    files = {}
    if latest:
        for abi, meta in latest.get("files", {}).items():
            files[abi] = {
                "path": f"/app/latest/{abi}.apk",
                "file": meta["file"],
                "size": meta.get("size"),
                "sha256": meta.get("sha256"),
            }
    codes = {abi: code for abi, code in cfg.app.downloader_codes.items() if code}
    return {
        "name": cfg.setup.name,
        "version_name": latest.get("version_name") if latest else None,
        "version_code": latest.get("version_code") if latest else None,
        "changelog": latest.get("changelog", []) if latest else [],
        "files": files,
        "downloader_codes": codes,
        "update_url": f"{cfg.server.public_base_url.rstrip('/')}/app/{UPDATE_FILE}",
    }
