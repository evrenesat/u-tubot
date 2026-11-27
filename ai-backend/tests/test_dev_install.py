"""scripts/dev_install.py, the optional dev install for the owner's devices (off by default, never in CI)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev_install.py"
spec = importlib.util.spec_from_file_location("dev_install", SCRIPT)
dev_install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev_install)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def fake_urlopen(mapping: dict[str, bytes]) -> object:
    def urlopen(url: str, timeout: int | None = None) -> _FakeResponse:
        return _FakeResponse(mapping[url])

    return urlopen


def fake_run(calls: list[list[str]]) -> object:
    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "ok\n", "")

    return run


def test_parse_devices_skips_blank_lines_and_comments():
    assert dev_install.parse_devices(
        "# the owner's devices\n10.0.0.20:5555\n\n 10.0.0.21:5038 "
    ) == [
        "10.0.0.20:5555",
        "10.0.0.21:5038",
    ]


def test_parse_devices_rejects_bad_lines():
    for bad in ("10.0.0.20", ":5555", "10.0.0.20:abc"):
        with pytest.raises(ValueError, match=r"expected <host>:<port>"):
            dev_install.parse_devices(bad)
    for bad in ("10.0.0.20:0", "10.0.0.20:65536"):
        with pytest.raises(ValueError, match=r"port out of range"):
            dev_install.parse_devices(bad)


def test_repo_from_remote():
    assert (
        dev_install.repo_from_remote("https://github.com/evrenesat/u-tubot.git")
        == "evrenesat/u-tubot"
    )
    assert (
        dev_install.repo_from_remote("https://github.com/evrenesat/u-tubot") == "evrenesat/u-tubot"
    )
    with pytest.raises(ValueError, match="cannot read the repository"):
        dev_install.repo_from_remote("https://github.com/")


def test_resolve_repo_from_origin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        dev_install.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(
            argv, 0, "https://github.com/evrenesat/u-tubot.git\n", ""
        ),
    )
    assert dev_install.resolve_repo(None) == "evrenesat/u-tubot"
    assert dev_install.resolve_repo("other/repo") == "other/repo"


def test_resolve_repo_fails_without_origin(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        dev_install.subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "fatal: not a git repository"),
    )
    with pytest.raises(ValueError, match="origin remote"):
        dev_install.resolve_repo(None)


def test_latest_release_tag(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        dev_install.urllib.request,
        "urlopen",
        fake_urlopen(
            {
                "https://api.github.com/repos/evrenesat/u-tubot/releases/latest": json.dumps(
                    {"tag_name": "utubot-v0.3.4"}
                ).encode()
            }
        ),
    )
    assert dev_install.latest_release_tag("evrenesat/u-tubot") == "utubot-v0.3.4"


def test_fetch_release_apk_checks_the_sum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    apk = b"apk-bytes"
    digest = hashlib.sha256(apk).hexdigest()
    base = "https://github.com/evrenesat/u-tubot/releases/download/utubot-v0.3.4"
    monkeypatch.setattr(
        dev_install.urllib.request,
        "urlopen",
        fake_urlopen(
            {
                f"{base}/u-tubot_0.3.4_universal.apk": apk,
                f"{base}/SHA256SUMS": f"{digest}  u-tubot_0.3.4_universal.apk\n".encode(),
            }
        ),
    )
    out = dev_install.fetch_release_apk("evrenesat/u-tubot", "utubot-v0.3.4", tmp_path)
    assert out == tmp_path / "u-tubot_0.3.4_universal.apk"
    assert out.read_bytes() == apk


def test_fetch_release_apk_fails_on_bad_sum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    apk = b"apk-bytes"
    base = "https://github.com/evrenesat/u-tubot/releases/download/utubot-v0.3.4"
    monkeypatch.setattr(
        dev_install.urllib.request,
        "urlopen",
        fake_urlopen(
            {
                f"{base}/u-tubot_0.3.4_universal.apk": apk,
                f"{base}/SHA256SUMS": ("0" * 64 + "  u-tubot_0.3.4_universal.apk\n").encode(),
            }
        ),
    )
    with pytest.raises(ValueError, match="SHA-256"):
        dev_install.fetch_release_apk("evrenesat/u-tubot", "utubot-v0.3.4", tmp_path)


def test_fetch_release_apk_fails_without_sum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    base = "https://github.com/evrenesat/u-tubot/releases/download/utubot-v0.3.4"
    monkeypatch.setattr(
        dev_install.urllib.request,
        "urlopen",
        fake_urlopen(
            {
                f"{base}/u-tubot_0.3.4_universal.apk": b"apk-bytes",
                f"{base}/SHA256SUMS": b"digest  u-tubot_0.3.4_arm64-v8a.apk\n",
            }
        ),
    )
    with pytest.raises(ValueError, match="not in the release's SHA256SUMS"):
        dev_install.fetch_release_apk("evrenesat/u-tubot", "utubot-v0.3.4", tmp_path)


def test_main_installs_each_device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(dev_install.subprocess, "run", fake_run(calls))
    apk = tmp_path / "u-tubot_0.3.4_universal.apk"
    apk.write_bytes(b"apk")
    devices = tmp_path / "adb-devices"
    devices.write_text("# the owner's devices\n10.0.0.20:5555\n10.0.0.21:5038\n")
    assert dev_install.main(["--apk", str(apk), "--devices", str(devices)]) == 0
    assert calls == [
        ["adb", "connect", "10.0.0.20:5555"],
        ["adb", "-s", "10.0.0.20:5555", "install", "-r", str(apk)],
        ["adb", "connect", "10.0.0.21:5038"],
        ["adb", "-s", "10.0.0.21:5038", "install", "-r", str(apk)],
    ]


def test_main_keeps_going_on_a_failed_device(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        if argv[:3] == ["adb", "-s", "10.0.0.21:5038"]:
            return subprocess.CompletedProcess(argv, 1, "", "Error: install failed")
        return subprocess.CompletedProcess(argv, 0, "ok\n", "")

    monkeypatch.setattr(dev_install.subprocess, "run", run)
    apk = tmp_path / "u-tubot_0.3.4_universal.apk"
    apk.write_bytes(b"apk")
    devices = tmp_path / "adb-devices"
    devices.write_text("10.0.0.20:5555\n10.0.0.21:5038\n")
    assert dev_install.main(["--apk", str(apk), "--devices", str(devices)]) == 1
    assert len(calls) == 4


def test_main_missing_device_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(dev_install.subprocess, "run", fake_run([]))
    apk = tmp_path / "u-tubot_0.3.4_universal.apk"
    apk.write_bytes(b"apk")
    assert dev_install.main(["--apk", str(apk), "--devices", str(tmp_path / "missing")]) == 1
    assert "device list not found" in capsys.readouterr().err


def test_main_missing_apk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(dev_install.subprocess, "run", fake_run([]))
    devices = tmp_path / "adb-devices"
    devices.write_text("10.0.0.20:5555\n")
    assert dev_install.main(["--apk", str(tmp_path / "nope.apk"), "--devices", str(devices)]) == 1
    assert "APK not found" in capsys.readouterr().err


def test_main_refuses_apk_and_release_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(dev_install.subprocess, "run", fake_run([]))
    assert (
        dev_install.main(
            ["--apk", "x", "--release", "utubot-v0.3.4", "--devices", str(tmp_path / "d")]
        )
        == 1
    )
    assert "not both" in capsys.readouterr().err


def test_main_fetches_the_latest_release_and_installs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    apk = b"apk"
    digest = hashlib.sha256(apk).hexdigest()
    base = "https://github.com/evrenesat/u-tubot/releases/download/utubot-v0.3.4"
    monkeypatch.setattr(
        dev_install.urllib.request,
        "urlopen",
        fake_urlopen(
            {
                "https://api.github.com/repos/evrenesat/u-tubot/releases/latest": json.dumps(
                    {"tag_name": "utubot-v0.3.4"}
                ).encode(),
                f"{base}/u-tubot_0.3.4_universal.apk": apk,
                f"{base}/SHA256SUMS": f"{digest}  u-tubot_0.3.4_universal.apk\n".encode(),
            }
        ),
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(dev_install.subprocess, "run", fake_run(calls))
    devices = tmp_path / "adb-devices"
    devices.write_text("10.0.0.20:5555\n")
    assert (
        dev_install.main(
            ["--repo", "evrenesat/u-tubot", "--devices", str(devices), "--out", str(tmp_path)]
        )
        == 0
    )
    assert (tmp_path / "u-tubot_0.3.4_universal.apk").read_bytes() == apk
    assert [
        "adb",
        "-s",
        "10.0.0.20:5555",
        "install",
        "-r",
        str(tmp_path / "u-tubot_0.3.4_universal.apk"),
    ] in calls


def test_main_creates_the_out_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    apk = b"apk"
    digest = hashlib.sha256(apk).hexdigest()
    base = "https://github.com/evrenesat/u-tubot/releases/download/utubot-v0.3.4"
    monkeypatch.setattr(
        dev_install.urllib.request,
        "urlopen",
        fake_urlopen(
            {
                "https://api.github.com/repos/evrenesat/u-tubot/releases/latest": json.dumps(
                    {"tag_name": "utubot-v0.3.4"}
                ).encode(),
                f"{base}/u-tubot_0.3.4_universal.apk": apk,
                f"{base}/SHA256SUMS": f"{digest}  u-tubot_0.3.4_universal.apk\n".encode(),
            }
        ),
    )
    monkeypatch.setattr(dev_install.subprocess, "run", fake_run([]))
    devices = tmp_path / "adb-devices"
    devices.write_text("10.0.0.20:5555\n")
    out_dir = tmp_path / "nested" / "temp"
    assert (
        dev_install.main(
            ["--repo", "evrenesat/u-tubot", "--devices", str(devices), "--out", str(out_dir)]
        )
        == 0
    )
    assert (out_dir / "u-tubot_0.3.4_universal.apk").read_bytes() == apk
