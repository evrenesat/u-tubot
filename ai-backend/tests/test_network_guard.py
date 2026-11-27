from __future__ import annotations

import socket
import urllib.request

import httpx
import pytest

from tests.conftest import VIOLATIONS, block_youtube, is_youtube_host

YOUTUBE = "https://www.youtube.com/watch?v=utubot_demo"


def test_httpx_refuses_youtube_hosts():
    restore = block_youtube()
    try:
        with pytest.raises(AssertionError, match="never reach YouTube"):
            httpx.get(YOUTUBE, timeout=2.0)
    finally:
        restore()
        VIOLATIONS.clear()  # these refusals are the point of the test, not a leak


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
        VIOLATIONS.clear()  # these refusals are the point of the test, not a leak


@pytest.mark.parametrize(
    "host",
    [
        "www.youtube.com",
        "youtube.com",
        "youtube.com.",
        "WWW.YouTube.COM",
        "youtu.be",
        "music.youtube.com",
        "i.ytimg.com",
        "ｙｏｕｔｕｂｅ.com",  # fullwidth letters: IDNA maps them to ASCII
    ],
)
def test_youtube_hosts_are_blocked(host):
    assert is_youtube_host(host)


@pytest.mark.parametrize("host", ["notyoutube.com", "youtube.com.evil.com", "142.250.1.1"])
def test_other_hosts_are_not_blocked(host):
    assert not is_youtube_host(host)
