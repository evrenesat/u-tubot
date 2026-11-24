from __future__ import annotations

import contextlib
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
MOCK = REPO / "scripts" / "emulator_mock_backend.py"


def free_port() -> int:
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Mock:
    def __init__(self, user: str | None = None):
        self.port = free_port()
        self.second = f"http://127.0.0.3:{self.port}"
        self.base = f"http://127.0.0.2:{self.port}"
        command = [sys.executable, str(MOCK), "--port", str(self.port), "--host", "127.0.0.2", "--host", "127.0.0.3", "--base", self.base]
        if user:
            command += ["--user", user]
        self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.client = httpx.Client(trust_env=False, timeout=30)
        self.wait_ready()

    def wait_ready(self) -> None:
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                if self.client.get(self.base + "/v1/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        raise RuntimeError("the mock backend did not start")

    def get(self, path: str, **kwargs):
        return self.client.get(self.base + path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.client.post(self.base + path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.client.put(self.base + path, **kwargs)

    def close(self) -> None:
        self.client.close()
        self.process.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.process.wait(timeout=10)


@pytest.fixture
def mock():
    server = Mock()
    try:
        yield server
    finally:
        server.close()


def test_request_log_records_a_request_without_header_values(mock):
    mock.get("/__mock/requests?clear=1")
    mock.get("/v1/health")
    mock.get("/v1/me", headers={"Authorization": "Bearer secret", "Cookie": "session=x", "Origin": "https://example.com"})
    entries = mock.get("/__mock/requests").json()["requests"]
    assert entries[0] == {"method": "GET", "path": "/v1/health", "query": "", "authorization": False, "cookie": False, "origin": False}
    assert entries[1]["authorization"] is True and entries[1]["cookie"] is True and entries[1]["origin"] is True
    assert not any(entry["path"].startswith("/__mock/") for entry in entries)
    assert all("secret" not in repr(entry) for entry in entries)
    assert mock.get("/__mock/requests?clear=1").json() == {"requests": []}
    assert mock.get("/__mock/requests").json() == {"requests": []}


def test_options_answers_405_and_is_logged(mock):
    mock.get("/__mock/requests?clear=1")
    answer = mock.client.options(mock.base + "/v1/me")
    assert answer.status_code == 405
    entries = mock.get("/__mock/requests").json()["requests"]
    assert entries == [{"method": "OPTIONS", "path": "/v1/me", "query": "", "authorization": False, "cookie": False, "origin": False}]


def test_host_listens_on_each_given_address_only(mock):
    assert mock.get("/v1/health").status_code == 200
    assert mock.client.get(mock.second + "/v1/health").status_code == 200
    with pytest.raises(httpx.HTTPError):
        mock.client.get(f"http://127.0.0.1:{mock.port}/v1/health")


def test_pairing_user_control():
    server = Mock(user="alice")
    try:
        pair = server.post("/v1/pair", json={"code": "123456", "device": "Firefox (desktop)"})
        assert pair.json() == {"token": "utb_emulator", "user": "alice"}
        assert server.get("/v1/me").json()["user"] == "alice"
    finally:
        server.close()


def test_setup_can_answer_another_origin_and_takes_the_default_back(mock):
    mock.get("/__mock/setup?backend=" + mock.second)
    assert mock.get("/setup.json").json()["backend_url"] == mock.second
    mock.get("/__mock/setup?backend=")
    assert mock.get("/setup.json").json()["backend_url"] == mock.base


def test_hold_delays_a_matching_request_and_seconds_zero_clears_it(mock):
    video = "aaaaaaaaaaa"
    mock.get("/__mock/set?delay=0")
    mock.get(f"/__mock/hold?path=/v1/videos/{video}/summary&seconds=1")
    started = time.time()
    assert mock.get(f"/v1/videos/{video}/summary").status_code == 200
    assert time.time() - started >= 0.8
    mock.get("/__mock/hold?seconds=0")
    started = time.time()
    mock.get(f"/v1/videos/{video}/summary")
    assert time.time() - started < 0.5


def test_assess_verdicts_delay_and_failure(mock):
    video = "bbbbbbbbbbb"
    mock.get(f"/__mock/assess?video={video}&action=mark&label=Clickbait&status=ready&answer=Yes.")
    verdict = mock.post("/v1/assess", json={"videos": [{"video_id": video}], "section": "home", "wait_ms": 1200}).json()["results"][0]
    assert verdict["action"] == "mark"
    assert verdict["mark_label"] == "Clickbait"
    assert verdict["answer_short"] == "Yes."
    mock.get(f"/__mock/assess?video={video}&action=hide")
    verdict = mock.post("/v1/assess", json={"videos": [{"video_id": video}], "section": "home"}).json()["results"][0]
    assert verdict["action"] == "hide"
    mock.get("/__mock/assess?delay=0.6")
    started = time.time()
    mock.post("/v1/assess", json={"videos": [], "section": "home"})
    assert time.time() - started >= 0.5
    mock.get("/__mock/assess?fail=500")
    assert mock.post("/v1/assess", json={"videos": [], "section": "home"}).status_code == 500
    mock.get("/__mock/assess?fail=0")


def test_panel_prompt_can_be_refused(mock):
    video = "ccccccccccc"
    mock.get("/__mock/set?panel=404")
    assert mock.get(f"/v1/videos/{video}/summary?prompt=panel").status_code == 404
    mock.get("/__mock/set?panel=ok")
    assert mock.get(f"/v1/videos/{video}/summary?prompt=panel").status_code == 200


def test_failed_mode_can_carry_a_reason(mock):
    video = "ddddddddddd"
    mock.get("/__mock/set?mode=failed&reason=private")
    answer = mock.get(f"/v1/videos/{video}/summary").json()
    assert answer["status"] == "failed"
    assert answer["reason"] == "private"
    mock.get("/__mock/set?mode=failed")
    assert "reason" not in mock.get(f"/v1/videos/{video}/summary").json()


def test_prompt_writes_import_refresh_and_default(mock):
    imported = mock.post("/v1/prompts/import", json={"url": "https://example.com/sets/my-prompts.json"}).json()
    assert imported["id"] == "my-prompts.json"
    keys = [prompt["key"] for prompt_set in mock.get("/v1/prompts").json()["sets"] for prompt in prompt_set["prompts"]]
    assert imported["prompts"][0]["key"] in keys
    assert mock.post("/v1/prompts/refresh").json() == {"ok": True}
    changed = mock.put("/v1/prompts/default", json={"key": "builtin/takeaways"}).json()
    assert changed == {"default": "builtin/takeaways"}
    assert mock.get("/v1/prompts").json()["default"] == "builtin/takeaways"
    assert mock.put("/v1/prompts/default", json={"key": "unknown/none"}).status_code == 404


def test_processed_items_empty_failure_and_limit(mock):
    items = mock.get("/v1/processed?limit=2").json()["videos"]
    assert len(items) == 2
    assert items[0]["video_id"] == "dQw4w9WgXcQ"
    assert all("127.0.0.1" in item["thumbnail"] for item in items if item["thumbnail"])
    mock.get("/__mock/processed?state=empty")
    assert mock.get("/v1/processed").json() == {"videos": []}
    mock.get("/__mock/processed?state=fail")
    assert mock.get("/v1/processed").status_code == 500
    mock.get("/__mock/processed?state=items")
    assert mock.get("/v1/processed?limit=0").status_code == 400


def test_defaults_still_answer_as_before(mock):
    setup = mock.get("/setup.json").json()
    assert setup["utubot_setup"] == 1
    assert setup["backend_url"] == mock.base
    assert setup["defaults"] == {"assess": True, "summary_panel": True}
    assert mock.post("/v1/pair", json={"code": "123456", "device": "TV"}).json() == {"token": "utb_emulator", "user": "emu"}
    assert mock.get("/v1/me").json()["user"] == "emu"
    verdict = mock.post("/v1/assess", json={"videos": [{"video_id": "eeeeeeeeeee"}], "section": "home"}).json()["results"][0]
    assert verdict["action"] == "none" and verdict["status"] == "ready"
    assert mock.get("/v1/prompts").json()["default"] == "builtin/tldr"
    assert mock.get("/v1/videos/fffffffffff/summary").json()["status"] == "ready"
    assert mock.get("/v1/videos/fffffffffff/captions").json()["status"] == "none"
    assert mock.get("/v1/videos/fffffffffff/cuts").json()["configured"] is True
