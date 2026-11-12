"""scripts/utubot_release.py, the helpers of the release workflow (it lives next to the workflows, not in the package)."""

from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "utubot_release.py"
spec = importlib.util.spec_from_file_location("utubot_release", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def fake_aapt2(
    tmp_path: Path, code: int = 3004, version: str = "0.3.4", package: str = "dev.utubot.tv"
) -> str:
    path = tmp_path / "aapt2"
    path.write_text(
        "#!/bin/sh\n"
        f"echo \"package: name='{package}' versionCode='{code}' versionName='{version}' platformBuildVersionName='17'\"\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def make_apks(directory: Path, version: str, abis=("arm64-v8a", "universal")) -> None:
    directory.mkdir(exist_ok=True)
    for abi in abis:
        (directory / f"u-tubot_{version}_{abi}.apk").write_bytes(f"apk {abi}".encode())


def test_next_version_counts_the_patch_of_the_series():
    assert release.next_version("0.3", ["0.2.0", "0.2.2"]) == "0.3.0"
    assert release.next_version("0.3", ["0.2.2", "0.3.0", "0.3.4", "junk"]) == "0.3.5"
    assert release.next_version("0.10", ["0.9.12", "0.10.1"]) == "0.10.2"
    assert release.next_version("0.3", []) == "0.3.0"


def test_next_version_refuses_to_go_backwards_or_take_a_bad_series():
    with pytest.raises(ValueError, match="not newer"):
        release.next_version("0.2", ["0.2.2", "0.3.0"])
    for bad in ("0", "0.3.1", "a.b", ""):
        with pytest.raises(ValueError, match="must hold"):
            release.next_version(bad, [])


def test_previous_version():
    existing = ["0.2.0", "0.2.2", "0.3.0", "0.3.1"]
    assert release.previous_version("0.3.1", existing) == "0.3.0"
    assert release.previous_version("0.3.2", existing) == "0.3.1"
    assert release.previous_version("0.2.0", existing) is None


def test_unreleased_section_and_what_a_release_already_carried():
    text = (
        "# Changelog\n\n## Unreleased\n\n- new thing\n- old thing\n\n## 0.2.2 (date)\n\n- shipped\n"
    )
    section = release.unreleased_section(text)
    assert section == "- new thing\n- old thing"
    assert release.lines_not_in(section, "intro\n- old thing\n") == "- new thing"
    assert release.lines_not_in(section, "- new thing\n- old thing") == ""
    assert release.unreleased_section("## 0.2.2\n- x") == ""


def test_bullets_become_the_changelog():
    assert release.bullets("- one\n* two\ntext\n\nFull changelog: x") == ["one", "two"]


def test_wrapped_bullets_are_joined():
    text = "- first line\n  second line\n  third\n- next\n\n  indented after a blank is not part of it\nplain"
    assert release.bullets(text) == ["first line second line third", "next"]


def test_manifest_lists_hashes_codes_and_abis(tmp_path):
    make_apks(tmp_path / "rel", "0.3.4", abis=("universal", "arm64-v8a", "x86"))
    manifest = release.build_manifest(
        tmp_path / "rel", "utubot-v0.3.4", "0.3.4", fake_aapt2(tmp_path), ["a"], "ab" * 32
    )
    assert manifest["version_code"] == 3004
    assert manifest["abis"] == ["arm64-v8a", "x86", "universal"]
    assert manifest["files"]["universal"]["sha256"] == release.file_sha256(
        tmp_path / "rel" / "u-tubot_0.3.4_universal.apk"
    )
    assert manifest["signing_cert_sha256"] == "ab" * 32
    release.write_checksums(tmp_path / "rel", manifest)
    sums = (tmp_path / "rel" / "SHA256SUMS").read_text().splitlines()
    assert [line.split("  ")[1] for line in sums] == sorted(line.split("  ")[1] for line in sums)
    assert len(sums) == 3


def test_manifest_rejects_wrong_name_package_or_version(tmp_path):
    make_apks(tmp_path / "rel", "0.3.4")
    with pytest.raises(ValueError, match="does not look like"):
        release.build_manifest(tmp_path / "rel", "t", "0.3.5", fake_aapt2(tmp_path), [], None)
    with pytest.raises(ValueError, match="expected dev.utubot.tv"):
        release.build_manifest(
            tmp_path / "rel", "t", "0.3.4", fake_aapt2(tmp_path, version="0.3.3"), [], None
        )
    with pytest.raises(ValueError, match="expected dev.utubot.tv"):
        release.build_manifest(
            tmp_path / "rel", "t", "0.3.4", fake_aapt2(tmp_path, package="other.app"), [], None
        )
    with pytest.raises(ValueError, match="no u-tubot"):
        release.build_manifest(tmp_path / "none", "t", "0.3.4", fake_aapt2(tmp_path), [], None)


def test_manifest_command_writes_the_files(tmp_path, capsys):
    make_apks(tmp_path / "rel", "0.3.4")
    notes = tmp_path / "notes.md"
    notes.write_text("- fixed it\n\nSigning certificate SHA-256: `x`\n")
    argv = [
        "manifest",
        "--dir",
        str(tmp_path / "rel"),
        "--tag",
        "utubot-v0.3.4",
        "--version",
        "0.3.4",
        "--aapt2",
        fake_aapt2(tmp_path),
        "--notes",
        str(notes),
    ]
    assert release.main(argv) == 0
    data = json.loads((tmp_path / "rel" / "release.json").read_text())
    assert data["changelog"] == ["fixed it"]
    assert "signing_cert_sha256" not in data
    assert release.main(argv[:6] + ["0.3.5"] + argv[7:]) == 1
    assert "error:" in capsys.readouterr().err


def test_notes_use_only_unreleased_lines_not_in_the_previous_release(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## Unreleased\n\n- shipped before\n- brand new\n")
    monkeypatch.setattr(release, "gh_api", lambda path, jq: "- shipped before\n")
    text = release.release_notes("o/r", "0.3.1", "sha", changelog, ["0.3.0"], "ab" * 32)
    assert text.startswith("- brand new\n")
    assert "shipped before" not in text
    assert f"`{'ab' * 32}`" in text
    assert "compare/utubot-v0.3.0...utubot-v0.3.1" in text


def test_notes_fall_back_to_the_commit_log_without_merges(tmp_path, monkeypatch):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## 0.3.0\n\n- done\n")
    calls = []

    def fake_gh(path, jq):
        calls.append(path)
        return "" if "releases/tags" in path else "fix/app: one\nfeat/app: two"

    monkeypatch.setattr(release, "gh_api", fake_gh)
    text = release.release_notes("o/r", "0.3.1", "sha", changelog, ["0.3.0"], None)
    assert text.startswith("- fix/app: one\n- feat/app: two")
    assert any("compare/utubot-v0.3.0...sha" in c for c in calls)


def test_notes_never_fail(tmp_path, monkeypatch, capsys):
    def broken(path, jq):
        raise subprocess.CalledProcessError(1, "gh")

    monkeypatch.setattr(release, "gh_api", broken)
    out = tmp_path / "notes.md"
    tags = tmp_path / "tags.txt"
    tags.write_text("0.3.0\n")
    argv = [
        "notes",
        "--repo",
        "o/r",
        "--version",
        "0.3.1",
        "--sha",
        "s",
        "--tags",
        str(tags),
        "--out",
        str(out),
    ]
    assert release.main(argv + ["--changelog", str(tmp_path / "missing.md")]) == 0
    assert out.read_text().startswith("See CHANGELOG.md.")
    monkeypatch.setattr(
        release, "release_notes", lambda *a: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    assert release.main(argv + ["--changelog", str(tmp_path / "missing.md")]) == 0
    assert "fell back to a stub" in capsys.readouterr().out
