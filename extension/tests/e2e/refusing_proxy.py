"""The only proxy of the e2e runs: it refuses and records every request. Exactly the loopback addresses of the harness are
exempt in the Firefox profile, so a request to any other address reaches this proxy and is recorded. Its `/__log` control
is a direct loopback connection and is not recorded.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


class RefusingProxy:
    def __init__(self, host: str = "127.0.0.1", port: int = 0) -> None:
        self.requests: list[dict[str, str]] = []
        self.lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "refusing-proxy"

            def record(self, method: str) -> None:
                target = self.path
                if target.startswith("http://") or target.startswith("https://"):
                    host = urlsplit(target).hostname or ""
                else:
                    host = (self.headers.get("Host") or "").split(":")[0]
                with owner.lock:
                    owner.requests.append({"method": method, "host": host})

            def refuse(self) -> None:
                self.send_response(502)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_CONNECT(self) -> None:
                with owner.lock:
                    owner.requests.append({"method": "CONNECT", "host": self.path.split(":")[0]})
                self.send_response(502)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self) -> None:
                if self.path == "/__log":
                    body = json.dumps({"requests": owner.requests}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                self.record("GET")
                self.refuse()

            def do_POST(self) -> None:
                self.record("POST")
                self.refuse()

            def do_PUT(self) -> None:
                self.record("PUT")
                self.refuse()

            def do_DELETE(self) -> None:
                self.record("DELETE")
                self.refuse()

            def log_message(self, *_args) -> None:
                return

        self.server = ThreadingHTTPServer((host, port), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self) -> RefusingProxy:
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
