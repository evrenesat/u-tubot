"""A hand-written stand-in site on loopback. It serves tests/fixtures/site only; no YouTube script or page is copied."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


def serve(root: Path, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "fixture"

        def do_GET(self) -> None:
            path = unquote(urlparse(self.path).path).lstrip("/")
            candidate = (root / path).resolve()

            if not candidate.is_file() or root.resolve() not in candidate.parents:
                self.send_error(404)
                return

            body = candidate.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8" if candidate.suffix == ".html" else "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)
