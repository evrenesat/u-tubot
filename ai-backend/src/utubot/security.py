from __future__ import annotations

import hmac
import ipaddress
import time
from collections import defaultdict, deque
from collections.abc import Callable
from urllib.parse import urlsplit

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


PROXY_SECRET_HEADER = "X-Utubot-Proxy-Secret"


def _single_ip(value: str | None) -> str | None:
    """`value` when it is exactly one IP address, else None."""
    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except ValueError:
        return None


def client_ip(
    peer: str | None,
    forwarded_for: str | None,
    trusted_proxies: list[str],
    *,
    header_value: str | None = None,
    presented_secret: str | None = None,
    expected_secret: str | None = None,
) -> str:
    """The real client address.

    A trusted proxy that proves itself with the shared secret may name the client in a dedicated
    header (`[security] client_ip_header`); that survives a second hop that rewrites
    `X-Forwarded-For`. Without a matching secret the header is ignored, and the right-most
    `X-Forwarded-For` entry that is not a trusted proxy is used.
    """
    peer = peer or "unknown"
    nets = _parse_networks(trusted_proxies)
    if not nets or not _in(nets, peer):
        return peer
    if (
        header_value
        and expected_secret
        and presented_secret
        and hmac.compare_digest(presented_secret.encode(), expected_secret.encode())
    ):
        named = _single_ip(header_value)
        if named:
            return named
    if not forwarded_for:
        return peer
    chain = [p.strip() for p in forwarded_for.split(",") if p.strip()]
    for hop in reversed(chain):
        if not _in(nets, hop):
            return hop
    return peer


def is_https(
    scheme: str, peer: str | None, forwarded_proto: str | None, trusted_proxies: list[str]
) -> bool:
    """True when the browser reached us over HTTPS: directly, or through a trusted proxy that says so."""
    if scheme == "https":
        return True
    nets = _parse_networks(trusted_proxies)
    if not forwarded_proto or not peer or not _in(nets, peer):
        return False
    return forwarded_proto.split(",")[0].strip().lower() == "https"


def origin_allowed(origin: str, allowed_hosts: list[str]) -> bool:
    """Same-origin check for a browser `Origin` header against the hosts this server answers as."""
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and parts.netloc.lower() in {
        h.lower() for h in allowed_hosts if h
    }


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
