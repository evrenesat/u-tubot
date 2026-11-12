from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable

import httpx

IPAddr = ipaddress.IPv4Address | ipaddress.IPv6Address
Resolver = Callable[[str, int], Awaitable[list[str]]]

DEFAULT_PORTS = {"http": 80, "https": 443}
SIX_TO_FOUR = ipaddress.ip_network("2002::/16")
NAT64 = ipaddress.ip_network("64:ff9b::/96")
CGNAT = ipaddress.ip_network("100.64.0.0/10")
ULA = ipaddress.ip_network("fc00::/7")


class UrlRejected(ValueError):
    """Raised with a short, body-free reason that is safe to show to the caller."""


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UrlRejected("host could not be resolved") from exc
    return sorted({info[4][0] for info in infos})


def _embedded_v4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    found = []
    if ip.ipv4_mapped:
        found.append(ip.ipv4_mapped)
    if ip in SIX_TO_FOUR:
        found.append(ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF))
    if ip in NAT64:
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if ip.teredo:
        found.append(ip.teredo[1])
    return found


def is_blocked_ip(ip: IPAddr) -> bool:
    if isinstance(ip, ipaddress.IPv6Address):
        if any(is_blocked_ip(v4) for v4 in _embedded_v4(ip)):
            return True
        if ip in ULA:
            return True
    elif ip in CGNAT:
        return True
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


async def validate_url(
    url: httpx.URL,
    allow_hosts: Iterable[str] = (),
    resolver: Resolver = system_resolver,
) -> str:
    """Check one hop and return the IP the connection must be pinned to."""
    if url.scheme not in DEFAULT_PORTS:
        raise UrlRejected("url must be http(s)")
    host = url.host
    if not host:
        raise UrlRejected("url has no host")
    allowed = host.lower() in {h.lower() for h in allow_hosts}
    port = url.port or DEFAULT_PORTS[url.scheme]
    if not allowed and port != DEFAULT_PORTS[url.scheme]:
        raise UrlRejected("non-default ports are not allowed")
    try:
        literal = [str(ipaddress.ip_address(host))]
    except ValueError:
        literal = []
    addrs = literal or await resolver(host, port)
    if not addrs:
        raise UrlRejected("host could not be resolved")
    if not allowed:
        for addr in addrs:
            try:
                blocked = is_blocked_ip(ipaddress.ip_address(addr))
            except ValueError:
                blocked = True
            if blocked:
                raise UrlRejected("url points to a disallowed address")
    return addrs[0]


def guarded_get(
    url: str,
    *,
    allow_hosts: Iterable[str],
    max_redirects: int,
    timeout_s: float,
    transport: httpx.AsyncBaseTransport | None = None,
    resolver: Resolver = system_resolver,
) -> _GuardedGet:
    """Async context manager yielding a streaming response; every hop is validated and pinned."""
    return _GuardedGet(url, allow_hosts, max_redirects, timeout_s, transport, resolver)


class _GuardedGet:
    def __init__(self, url, allow_hosts, max_redirects, timeout_s, transport, resolver):
        self.url = httpx.URL(url)
        self.allow_hosts = list(allow_hosts)
        self.max_redirects = max_redirects
        self.resolver = resolver
        self.client = httpx.AsyncClient(
            follow_redirects=False, timeout=timeout_s, transport=transport
        )
        self.resp: httpx.Response | None = None

    async def __aenter__(self) -> httpx.Response:
        url = self.url
        for _ in range(self.max_redirects + 1):
            ip = await validate_url(url, self.allow_hosts, self.resolver)
            pinned = url.copy_with(host=ip)
            request = self.client.build_request(
                "GET",
                pinned,
                headers={"Host": url.netloc.decode()},
                extensions={"sni_hostname": url.host},
            )
            resp = await self.client.send(request, stream=True)
            if resp.is_redirect and resp.headers.get("location"):
                target = url.join(resp.headers["location"])
                await resp.aclose()
                url = target
                continue
            self.resp = resp
            return resp
        raise UrlRejected("too many redirects")

    async def __aexit__(self, *exc) -> None:
        if self.resp is not None:
            await self.resp.aclose()
        await self.client.aclose()
