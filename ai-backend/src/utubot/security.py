from __future__ import annotations

import ipaddress
import time
from collections import defaultdict, deque
from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__("rate limited")
        self.retry_after = retry_after


class RateLimiter:
    def __init__(self, window_s: int):
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._last_sweep = time.monotonic()

    def check(self, key: str, limit: int) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if len(hits) >= limit:
            raise RateLimited(max(1, int(self.window_s - (now - hits[0])) + 1))
        hits.append(now)
        if now - self._last_sweep > self.window_s:
            self._sweep(now)

    def _sweep(self, now: float) -> None:
        self._last_sweep = now
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window_s]:
            del self._hits[key]


def _parse_networks(entries: list[str]):
    nets = []
    for entry in entries:
        try:
            nets.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return nets


def _in(nets, host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(addr in net for net in nets)


def client_ip(peer: str | None, forwarded_for: str | None, trusted_proxies: list[str]) -> str:
    peer = peer or "unknown"
    nets = _parse_networks(trusted_proxies)
    if not nets or not _in(nets, peer) or not forwarded_for:
        return peer
    chain = [p.strip() for p in forwarded_for.split(",") if p.strip()]
    for hop in reversed(chain):
        if not _in(nets, hop):
            return hop
    return peer


class BodyLimitMiddleware:
    def __init__(self, app: ASGIApp, get_max_bytes: Callable[[], int]):
        self.app, self.get_max_bytes = app, get_max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        max_bytes = self.get_max_bytes()
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            await self._reject(send)
            return
        received = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = b'{"error":"request too large"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass
