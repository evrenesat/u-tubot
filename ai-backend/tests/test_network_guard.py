from __future__ import annotations

import socket
import urllib.request

import httpx
import pytest

from tests.conftest import block_youtube

YOUTUBE = "https://www.youtube.com/watch?v=utubot_demo"


def test_httpx_refuses_youtube_hosts():
    restore = block_youtube()
    try:
        with pytest.raises(AssertionError, match="never reach YouTube"):
            httpx.get(YOUTUBE, timeout=2.0)
    finally:
        restore()


def test_resolver_refuses_youtube_names_but_keeps_the_loopback_working():
    restore = block_youtube()
    try:
        with pytest.raises(AssertionError, match="never reach YouTube"):
            socket.getaddrinfo("www.youtube.com", 443)
        with pytest.raises(AssertionError, match="never reach YouTube"):
            socket.gethostbyname("googlevideo.com")
        with pytest.raises(AssertionError, match="never reach YouTube"):
            urllib.request.urlopen(YOUTUBE, timeout=2.0)  # urllib resolves through the guard
        # A trailing dot (a valid absolute name) and a bytes host are refused the same way.
        with pytest.raises(AssertionError, match="never reach YouTube"):
            socket.getaddrinfo("www.youtube.com.", 443)
        with pytest.raises(AssertionError, match="never reach YouTube"):
            socket.getaddrinfo(b"googlevideo.com", 443)
        # Anything that is not YouTube still resolves: the loopback mock servers keep working.
        assert socket.getaddrinfo("127.0.0.1", 80) is not None
    finally:
        restore()
