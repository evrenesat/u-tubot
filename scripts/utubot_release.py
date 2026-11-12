#!/usr/bin/env python3
"""Helpers of the u-tubot release workflow (.github/workflows/utubot-release.yml). Standard library only.

next-version  print the next version of a series from the existing release versions
cert          print the SHA-256 of an APK's signing certificate (nothing when apksigner cannot say)
manifest      write release.json and SHA256SUMS for the APKs in a directory
notes         write the release notes; never fails, a release is not held back by its notes
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

APPLICATION_ID = "dev.utubot.tv"
APK_NAME_RE = re.compile(r"^u-tubot_(?P<version>\d+\.\d+\.\d+)_(?P<abi>[a-z0-9_-]+)\.apk$")
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
SERIES_RE = re.compile(r"^\d+\.\d+$")
BADGING_RE = re.compile(
    r"package: name='(?P<name>[^']+)' versionCode='(?P<code>\d+)' versionName='(?P<version>[^']*)'"
)
BULLET_RE = re.compile(r"^\s*[-*]\s+(\S.*)$")
CERT_RE = re.compile(r"certificate SHA-256 digest: ([0-9a-fA-F]{64})")
ABI_ORDER = ("arm64-v8a", "armeabi-v7a", "x86_64", "x86", "universal")
RELEASE_MANIFEST = "release.json"
CHECKSUMS = "SHA256SUMS"
MANIFEST_SCHEMA = 1
HASH_CHUNK_BYTES = 1 << 20
TOOL_TIMEOUT_S = 120
GH_TIMEOUT_S = 60
MAX_CHANGELOG_LINES = 20
MAX_COMMIT_LINES = 40
UNRELEASED_HEADING = "## Unreleased"
NOTES_FALLBACK = "See CHANGELOG.md."


def parse_version(text: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.match(text.strip())
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def known_versions(lines: list[str]) -> list[tuple[int, int, int]]:
    return sorted(v for v in (parse_version(line) for line in lines) if v)


def next_version(series: str, existing: list[str]) -> str:
    """<series>.<highest patch of the series + 1>, refused when it would not be newer than every existing release."""
    if not SERIES_RE.match(series):
        raise ValueError(f"utubot.version must hold <major>.<minor>, found {series!r}")
    major, minor = (int(part) for part in series.split("."))
    versions = known_versions(existing)
    patches = [v[2] for v in versions if v[:2] == (major, minor)]
    candidate = (major, minor, max(patches) + 1 if patches else 0)
    if versions and candidate <= versions[-1]:
        newest = ".".join(map(str, versions[-1]))
        raise ValueError(
            f"series {series} would give {'.'.join(map(str, candidate))}, not newer than the release {newest}"
        )
    return ".".join(map(str, candidate))


def previous_version(version: str, existing: list[str]) -> str | None:
    current = parse_version(version)
    older = [v for v in known_versions(existing) if current and v < current]
    return ".".join(map(str, older[-1])) if older else None


def _run(argv: list[str]) -> str:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=TOOL_TIMEOUT_S, check=True)
    return done.stdout + done.stderr


def apk_badging(aapt2: str, apk: Path) -> tuple[str, int, str]:
    out = subprocess.run(
        [aapt2, "dump", "badging", str(apk)],
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT_S,
        check=True,
    ).stdout
    match = BADGING_RE.search(out)
    if not match:
        raise ValueError(f"no package line in the badging of {apk.name}")
    return match["name"], int(match["code"]), match["version"]


def signing_cert(apksigner: str, apk: Path) -> str | None:
    """SHA-256 of the signing certificate, or None when apksigner cannot say."""
    try:
        match = CERT_RE.search(_run([apksigner, "verify", "--print-certs", str(apk)]))
    except (OSError, subprocess.SubprocessError):
        return None
    return match[1].lower() if match else None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def bullets(text: str) -> list[str]:
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


def build_manifest(
    directory: Path,
    tag: str,
    version: str,
    aapt2: str,
    changelog: list[str],
    cert: str | None,
) -> dict:
    apks = sorted(directory.glob("u-tubot_*.apk"))
    if not apks:
        raise ValueError(f"no u-tubot_*.apk in {directory}")
    files: dict[str, dict] = {}
    codes: set[int] = set()
    for apk in apks:
        match = APK_NAME_RE.match(apk.name)
        if not match or match["version"] != version:
            raise ValueError(f"{apk.name} does not look like u-tubot_{version}_<abi>.apk")
        package, code, apk_version = apk_badging(aapt2, apk)
        if package != APPLICATION_ID or apk_version != version:
            raise ValueError(
                f"{apk.name} is {package} {apk_version}, expected {APPLICATION_ID} {version}"
            )
        codes.add(code)
        files[match["abi"]] = {
            "file": apk.name,
            "sha256": file_sha256(apk),
            "size": apk.stat().st_size,
        }
    if len(codes) != 1:
        raise ValueError(f"the APKs disagree on versionCode: {sorted(codes)}")
    abis = [abi for abi in ABI_ORDER if abi in files] + sorted(set(files) - set(ABI_ORDER))
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "tag": tag,
        "version_name": version,
        "version_code": codes.pop(),
        "abis": abis,
        "files": {abi: files[abi] for abi in abis},
        "changelog": changelog,
    }
    if cert:
        manifest["signing_cert_sha256"] = cert
    return manifest


def write_checksums(directory: Path, manifest: dict) -> None:
    lines = [f"{meta['sha256']}  {meta['file']}\n" for meta in manifest["files"].values()]
    (directory / CHECKSUMS).write_text(
        "".join(sorted(lines, key=lambda line: line.split("  ", 1)[1]))
    )


def unreleased_section(changelog_text: str) -> str:
    out: list[str] = []
    inside = False
    for line in changelog_text.splitlines():
        if line.startswith("## "):
            inside = line.strip().lower() == UNRELEASED_HEADING.lower()
            continue
        if inside:
            out.append(line)
    return "\n".join(out).strip()


def lines_not_in(section: str, released_body: str) -> str:
    """The lines of the Unreleased section that the previous release notes do not already carry."""
    released = {line.strip() for line in released_body.splitlines() if line.strip()}
    kept = [line for line in section.splitlines() if line.strip() and line.strip() not in released]
    return "\n".join(kept)


def gh_api(path: str, jq: str) -> str:
    done = subprocess.run(
        ["gh", "api", path, "--jq", jq],
        capture_output=True,
        text=True,
        timeout=GH_TIMEOUT_S,
        check=True,
    )
    return done.stdout.strip()


def commit_log(repo: str, previous_tag: str | None, sha: str) -> str:
    """Subjects of the commits since the previous release, merge commits left out."""
    if not previous_tag:
        return ""
    subjects = gh_api(
        f"repos/{repo}/compare/{previous_tag}...{sha}",
        '[.commits[].commit.message | split("\\n")[0]] | map(select(startswith("Merge ") | not)) | .[]',
    )
    lines = [f"- {subject}" for subject in subjects.splitlines() if subject.strip()]
    return "\n".join(lines[:MAX_COMMIT_LINES])


def release_notes(
    repo: str, version: str, sha: str, changelog_path: Path, existing: list[str], cert: str | None
) -> str:
    previous = previous_version(version, existing)
    previous_tag = f"utubot-v{previous}" if previous else None
    body = ""
    try:
        section = unreleased_section(changelog_path.read_text(encoding="utf-8"))
        released = (
            gh_api(f"repos/{repo}/releases/tags/{previous_tag}", ".body // empty")
            if previous_tag
            else ""
        )
        body = lines_not_in(section, released)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"::warning::CHANGELOG notes unavailable: {exc}")
    if not body:
        try:
            body = commit_log(repo, previous_tag, sha)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"::warning::commit log unavailable: {exc}")
    parts = [body or NOTES_FALLBACK]
    if cert:
        parts.append(f"Signing certificate SHA-256: `{cert}`")
    if previous_tag:
        parts.append(
            f"Full changelog: https://github.com/{repo}/compare/{previous_tag}...utubot-v{version}"
        )
    return "\n\n".join(parts) + "\n"


def read_lines(path: str) -> list[str]:
    return Path(path).read_text().splitlines() if path != "-" else sys.stdin.read().splitlines()


def cmd_next_version(args: argparse.Namespace) -> int:
    try:
        print(next_version(args.series.strip(), read_lines(args.tags)))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_cert(args: argparse.Namespace) -> int:
    print(signing_cert(args.apksigner, Path(args.apk)) or "")
    return 0


def cmd_manifest(args: argparse.Namespace) -> int:
    directory = Path(args.dir)
    notes = Path(args.notes)
    try:
        manifest = build_manifest(
            directory,
            args.tag,
            args.version,
            args.aapt2,
            bullets(notes.read_text(encoding="utf-8")) if notes.is_file() else [],
            args.cert or None,
        )
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    (directory / RELEASE_MANIFEST).write_text(json.dumps(manifest, indent=2) + "\n")
    write_checksums(directory, manifest)
    print(
        f"{manifest['version_name']} versionCode {manifest['version_code']}: {', '.join(manifest['abis'])}"
    )
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    text = NOTES_FALLBACK + "\n"
    try:
        text = release_notes(
            args.repo,
            args.version,
            args.sha,
            Path(args.changelog),
            read_lines(args.tags),
            args.cert or None,
        )
    except Exception as exc:  # the notes must never stop a release
        print(f"::warning::release notes fell back to a stub: {exc}")
    Path(args.out).write_text(text, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    nxt = sub.add_parser("next-version")
    nxt.add_argument("--series", required=True, help="major.minor, the content of utubot.version")
    nxt.add_argument(
        "--tags",
        default="-",
        help="file of existing release versions, one per line (default stdin)",
    )
    nxt.set_defaults(func=cmd_next_version)
    cert = sub.add_parser("cert")
    cert.add_argument("--apksigner", required=True)
    cert.add_argument("apk")
    cert.set_defaults(func=cmd_cert)
    man = sub.add_parser("manifest")
    man.add_argument("--dir", required=True, help="directory holding u-tubot_<version>_<abi>.apk")
    man.add_argument("--tag", required=True)
    man.add_argument("--version", required=True)
    man.add_argument("--aapt2", required=True)
    man.add_argument("--cert", help="signing certificate SHA-256 to record")
    man.add_argument(
        "--notes", required=True, help="notes file whose bullet lines become the changelog"
    )
    man.set_defaults(func=cmd_manifest)
    notes = sub.add_parser("notes")
    notes.add_argument("--repo", required=True)
    notes.add_argument("--version", required=True)
    notes.add_argument("--sha", required=True)
    notes.add_argument("--changelog", required=True, help="path of CHANGELOG.md")
    notes.add_argument(
        "--tags", required=True, help="file of existing release versions, one per line"
    )
    notes.add_argument("--cert", help="signing certificate SHA-256 to print in the notes")
    notes.add_argument("--out", required=True)
    notes.set_defaults(func=cmd_notes)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
