"""The e2e harness: the test variant in the pinned Firefox, the fixture pages on 127.0.0.1, the mock backend on
127.0.0.2 and 127.0.0.3, and the refusing proxy as the only route out. Selenium is offline (SE_OFFLINE) and the
binary paths are explicit; no test opens YouTube.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest
from selenium import webdriver
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service

HERE = Path(__file__).resolve().parent
EXTENSION = HERE.parents[1]
REPO = EXTENSION.parent
LOCK = json.loads((HERE / "tools.lock").read_text(encoding="utf-8"))
TOOLS = Path(os.environ.get("E2E_TOOLS_DIR", HERE / ".tools"))


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_health(base: str, deadline: float = 20.0) -> None:
    ended = time.time() + deadline

    while time.time() < ended:
        try:
            with urllib.request.urlopen(base + "/v1/health", timeout=1) as answer:
                if answer.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.05)

    raise RuntimeError(f"the mock backend did not start at {base}")


class Suite:
    def __init__(self) -> None:
        self.port = free_port()
        self.fixture_base = f"http://127.0.0.1:{self.port}"
        self.backend_base = f"http://127.0.0.2:{self.port}"
        self.second_base = f"http://127.0.0.3:{self.port}"
        self.processes: list[subprocess.Popen] = []
        self._start_mock()
        self._start_fixture()
        self.proxy = None
        self._start_proxy()
        self.driver = None
        self.extension_id = ""
        self.extension_base = ""
        self._start_firefox()

    def _start_mock(self) -> None:
        command = [
            "python3",
            str(REPO / "scripts" / "emulator_mock_backend.py"),
            "--port",
            str(self.port),
            "--host",
            "127.0.0.2",
            "--host",
            "127.0.0.3",
            "--base",
            self.backend_base,
        ]
        self.processes.append(subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        wait_health(self.backend_base)

    def _start_fixture(self) -> None:
        import sys

        sys.path.insert(0, str(HERE))
        from fixture_server import serve

        from threading import Thread

        self.fixture_server = serve(HERE.parent / "fixtures" / "site", "127.0.0.1", self.port)
        Thread(target=self.fixture_server.serve_forever, daemon=True).start()

    def _start_proxy(self) -> None:
        import sys

        sys.path.insert(0, str(HERE))
        from refusing_proxy import RefusingProxy

        self.proxy = RefusingProxy().start()

    def _profile(self) -> FirefoxProfile:
        directory = Path(tempfile.mkdtemp(prefix="utubot-e2e-profile-"))
        preferences = (HERE / "user.js").read_text(encoding="utf-8").replace("__PROXY_PORT__", str(self.proxy.port))
        (directory / "user.js").write_text(preferences, encoding="utf-8")
        return FirefoxProfile(str(directory))

    def _start_firefox(self) -> None:
        firefox = Path(os.environ.get("FIREFOX_BIN", TOOLS / "firefox" / "firefox"))
        geckodriver = Path(os.environ.get("GECKODRIVER_BIN", TOOLS / "geckodriver"))
        if not firefox.is_file() or not geckodriver.is_file():
            raise RuntimeError("run tools/e2e/download_tools.py or set FIREFOX_BIN and GECKODRIVER_BIN")

        os.environ["SE_OFFLINE"] = "true"
        os.environ["MOZ_DISABLE_NONLOCAL_CONNECTIONS"] = "1"
        options = FirefoxOptions()
        options.binary_location = str(firefox)
        options.add_argument("-headless")
        options.profile = self._profile()
        service = Service(executable_path=str(geckodriver))
        self.driver = webdriver.Firefox(options=options, service=service)
        self.driver.install_web_extension(str(EXTENSION / "dist" / "firefox-test"), permanent=False)
        self.extension_id = "extension@utubot.dev"
        self.extension_base = self._extension_base()

    def _extension_base(self) -> str:
        profile = Path(self.driver.capabilities.get("moz:profile", ""))
        prefs = profile / "prefs.js"
        for _ in range(100):
            try:
                text = prefs.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            match = re.search(r'user_pref\("extensions\.webextensions\.uuids", "(.*)"\);', text)
            if match:
                unescaped = match.group(1).replace('\\"', '"')
                value = json.loads(unescaped)
                uuid = value.get(self.extension_id, "")
                if uuid:
                    return f"moz-extension://{uuid}/"
            time.sleep(0.05)
        raise RuntimeError("the extension UUID did not appear in the profile prefs")

    def page(self, path: str) -> str:
        return self.extension_base + path

    def fixture(self, path: str) -> str:
        return self.fixture_base + "/" + path.lstrip("/")

    def proxy_log(self) -> list[dict[str, str]]:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.proxy.port}/__log", timeout=2) as answer:
            return json.loads(answer.read())["requests"]

    def close(self) -> None:
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
        if self.proxy is not None:
            self.proxy.stop()
        self.fixture_server.shutdown()
        self.fixture_server.server_close()
        for process in self.processes:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


@pytest.fixture(scope="session")
def suite() -> Suite:
    suite = Suite()
    try:
        yield suite
    finally:
        suite.close()


def pytest_collection_modifyitems(config, items):
    final = [item for item in items if item.name.startswith("test_zz_the_refusing_proxy")]
    items[:] = [item for item in items if item not in final] + final
