#!/usr/bin/env python3
"""Push the new u-tubot APK to the owner's own devices over wireless ADB.

Optional dev tool, off by default, never run in CI or by the release workflow: after a release it fetches the universal APK of the
GitHub release (checked against the release's SHA256SUMS), or takes a local debug build with --apk, and for every device in the
gitignored device list (one host:port per line) runs `adb connect <host>:<port>` and `adb -s <host>:<port> install -r`.

    scripts/dev_install.py                                  # universal APK of the latest release
    scripts/dev_install.py --release utubot-v0.3.4          # a specific release
    scripts/dev_install.py --apk <path to a debug APK>      # install a local build instead
    scripts/dev_install.py --devices adb-devices --adb adb  # the device list (default: adb-devices), the adb binary
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEVICES_FILE = REPO_ROOT / "adb-devices"
GITHUB_API = "https://api.github.com"
GITHUB_RELEASES = "https://github.com"
API_TIMEOUT_S = 30
APK_TIMEOUT_S = 300
ADB_TIMEOUT_S = 60
INSTALL_TIMEOUT_S = 300


def parse_devices(text: str) -> list[str]:
    """The host:port lines of a device list; blank lines and # comments are skipped."""
    devices: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        host, sep, port = line.rpartition(":")
        if not sep or not host or not port.isdigit():
            raise ValueError(f"line {number}: expected <host>:<port>, got {line!r}")
        if not 0 < int(port) <= 65535:
            raise ValueError(f"line {number}: port out of range, expected 1-65535, got {line!r}")
        devices.append(f"{host}:{port}")
    return devices


def repo_from_remote(remote: str) -> str:
    """The owner/repo of a git remote URL, for example https://github.com/evrenesat/u-tubot.git."""
    url = remote.strip()
    if "//" in url:
        url = url.split("//", 1)[1]
    parts = url.rstrip("/").removesuffix(".git").split("/")
    if len(parts) < 2 or not parts[-2] or not parts[-1]:
        raise ValueError(f"cannot read the repository from the remote {remote!r}")
    return "/".join(parts[-2:])


def resolve_repo(repo: str | None) -> str:
    """The GitHub repository, from --repo or the origin remote."""
    if repo:
        return repo
    out = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True, timeout=30
    )
    if out.returncode != 0:
        raise ValueError("no origin remote (run git remote add origin <url>)")
    return repo_from_remote(out.stdout)


def latest_release_tag(repo: str) -> str:
    """The tag of the latest GitHub release of a repository."""
    with urllib.request.urlopen(
        f"{GITHUB_API}/repos/{repo}/releases/latest", timeout=API_TIMEOUT_S
    ) as resp:
        data = json.loads(resp.read())
    tag = data.get("tag_name") or ""
    if not tag:
        raise ValueError(f"no release for {repo}")
    return tag


def fetch_release_apk(repo: str, tag: str, out_dir: Path) -> Path:
    """Download the universal APK of a release and check it against the release's SHA256SUMS."""
    version = tag.removeprefix("utubot-v")
    filename = f"u-tubot_{version}_universal.apk"
    base = f"{GITHUB_RELEASES}/{repo}/releases/download/{tag}"
    with urllib.request.urlopen(f"{base}/{filename}", timeout=APK_TIMEOUT_S) as resp:
        data = resp.read()
    with urllib.request.urlopen(f"{base}/SHA256SUMS", timeout=API_TIMEOUT_S) as resp:
        sums = resp.read().decode()
    expected = None
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == filename:
            expected = parts[0]
            break
    if expected is None:
        raise ValueError(f"{filename} is not in the release's SHA256SUMS")
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"the SHA-256 of {filename} does not match the release's SHA256SUMS")
    out = out_dir / filename
    out.write_bytes(data)
    return out


def _run_adb(adb: str, args: list[str], timeout: int) -> int:
    try:
        done = subprocess.run([adb, *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"  adb failed: {exc}", file=sys.stderr)
        return 1
    for line in (done.stdout or "") + (done.stderr or ""):
        if line.strip():
            print(f"  {line.rstrip()}")
    return done.returncode


def install_on_device(adb: str, host_port: str, apk: Path) -> bool:
    print(f"{host_port}:")
    if _run_adb(adb, ["connect", host_port], ADB_TIMEOUT_S) != 0:
        print("  connect failed", file=sys.stderr)
        return False
    if _run_adb(adb, ["-s", host_port, "install", "-r", str(apk)], INSTALL_TIMEOUT_S) != 0:
        print("  install failed", file=sys.stderr)
        return False
    print("  installed")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Push the new u-tubot APK to the owner's devices over wireless ADB (optional, off by default)"
    )
    parser.add_argument(
        "--apk",
        help="APK to install (e.g. a local debug build); when omitted the release APK is fetched",
    )
    parser.add_argument("--release", help="release tag to fetch (default: the latest release)")
    parser.add_argument(
        "--devices",
        default=str(DEFAULT_DEVICES_FILE),
        help="device list, one host:port per line (default: adb-devices)",
    )
    parser.add_argument("--repo", help="GitHub repository owner/repo (default: the origin remote)")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "temp"),
        help="where to store the downloaded APK (default: temp/, gitignored)",
    )
    parser.add_argument("--adb", default="adb", help="path to the adb binary (default: adb)")
    args = parser.parse_args(argv)
    if args.apk and args.release:
        print("error: give --apk or --release, not both", file=sys.stderr)
        return 1
    try:
        if args.apk:
            apk = Path(args.apk)
            if not apk.is_file():
                raise ValueError(f"APK not found: {apk}")
        else:
            repo = resolve_repo(args.repo)
            tag = args.release or latest_release_tag(repo)
            apk = fetch_release_apk(repo, tag, Path(args.out))
            print(f"fetched {tag}: {apk}")
        devices_file = Path(args.devices)
        if not devices_file.is_file():
            raise ValueError(
                f"device list not found: {devices_file} (gitignored, one host:port per line)"
            )
        devices = parse_devices(devices_file.read_text())
        if not devices:
            raise ValueError(f"no devices in {devices_file}")
        ok = True
        for device in devices:
            if not install_on_device(args.adb, device, apk):
                ok = False
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if not ok:
        print("one or more devices failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
