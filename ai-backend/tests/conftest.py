from __future__ import annotations

import socket

import httpx
import pytest
import pytest_asyncio
import yt_dlp

from tests.fakes import FakeClock
from tests.mock_openai import MockOpenAI
from utubot.app import create_app
from utubot.auth import hash_token
from utubot.captions.asr import make_asr
from utubot.config import Config, UserConfig, UserPolicy
from utubot.transcripts import FetchResult

YOUTUBE_HOST_SUFFIXES = (
    "youtube.com",
    "youtu.be",
    "googlevideo.com",
    "ytimg.com",
    "youtube-nocookie.com",
)
YDL_METHODS = ("extract_info", "download", "urlopen", "process_ie_result")
# Resolver-level chokepoint: catches urllib, raw sockets and every library that resolves DNS,
# even one the httpx/yt-dlp patches above would miss.
RESOLVERS = ("getaddrinfo", "gethostbyname")
NO_YOUTUBE = "tests and demos never reach YouTube: use a fake fetcher, downloader or yt-dlp"


def block_youtube():
    """Make any real request to YouTube (yt-dlp, timedtext, googlevideo) fail loudly.

    yt-dlp's extract/download/urlopen raise, the real httpx transports refuse YouTube hosts, and
    the resolver refuses to look a YouTube name up at all (a last line for anything unpatched).
    Tests that stand in for `yt_dlp.YoutubeDL` replace the class itself and are not affected.
    Returns the function that undoes it.
    """
    real_ydl = yt_dlp.YoutubeDL
    originals = {name: getattr(real_ydl, name) for name in YDL_METHODS}
    sync_send = httpx.HTTPTransport.handle_request
    async_send = httpx.AsyncHTTPTransport.handle_async_request
    real_resolvers = {name: getattr(socket, name) for name in RESOLVERS}

    def refuse(*_args, **_kwargs):
        raise AssertionError(NO_YOUTUBE)

    def guard(host: str) -> None:
        name = host.lower().rstrip(".")  # a trailing dot is a valid absolute DNS name
        if name.endswith(YOUTUBE_HOST_SUFFIXES):
            raise AssertionError(f"{NO_YOUTUBE} ({host})")

    def sync_guarded(self, request):
        guard(request.url.host)
        return sync_send(self, request)

    async def async_guarded(self, request):
        guard(request.url.host)
        return await async_send(self, request)

    for name in YDL_METHODS:
        setattr(real_ydl, name, refuse)
    httpx.HTTPTransport.handle_request = sync_guarded
    httpx.AsyncHTTPTransport.handle_async_request = async_guarded

    def resolve_guarded(name):
        original = real_resolvers[name]

        def guarded(host, *args, **kwargs):
            if isinstance(host, bytes):
                guard(host.decode("idna"))
            elif isinstance(host, str):
                guard(host)
            return original(host, *args, **kwargs)

        return guarded

    for name in RESOLVERS:
        setattr(socket, name, resolve_guarded(name))

    def restore() -> None:
        for name, original in originals.items():
            setattr(real_ydl, name, original)
        httpx.HTTPTransport.handle_request = sync_send
        httpx.AsyncHTTPTransport.handle_async_request = async_send
        for name, original in real_resolvers.items():
            setattr(socket, name, original)

    return restore


@pytest.fixture(autouse=True)
def no_youtube():
    restore = block_youtube()
    yield
    restore()


TOKEN = "utb_testtoken"
OTHER_TOKEN = "utb_othertoken"
TRANSCRIPT = "[00:00] Welcome. [00:20] The answer is yes. " * 5


class FakeFetcher:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.text: str | None = TRANSCRIPT
        self.fail = False
        self.error: Exception | None = None
        self.meta_extra: dict = {}
        self.meta_calls: list[str] = []
        self.meta_error: Exception | None = None

    def _meta(self, video_id: str) -> dict:
        return {
            "video_id": video_id,
            "title": f"Title {video_id}",
            "channel": "Chan",
            "duration_s": 900,
            **self.meta_extra,
        }

    async def meta(self, video_id: str) -> FetchResult:
        """The metadata-only request (`YoutubeFetcher.meta`)."""
        self.meta_calls.append(video_id)
        if self.meta_error is not None:
            raise self.meta_error
        return FetchResult(self._meta(video_id), None, None, answered=("metadata",))

    async def __call__(self, video_id: str) -> FetchResult:
        self.calls.append(video_id)
        if self.error is not None:
            raise self.error
        if self.fail:
            raise RuntimeError("youtube blocked")
        return FetchResult(self._meta(video_id), self.text, "en")


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def mock_llm() -> MockOpenAI:
    return MockOpenAI()


@pytest.fixture
def fetcher() -> FakeFetcher:
    return FakeFetcher()


@pytest.fixture
def cfg(tmp_path) -> Config:
    c = Config()
    c.server.data_dir = str(tmp_path / "data")
    c.llm.providers["default"].base_url = "http://mock/v1"
    c.assess.default_wait_ms = 2000
    c.summary.default_wait_ms = 5000
    c.security.trusted_proxies = []
    c.captions.job_poll_s = 0.05
    c.youtube.min_interval_s = 0.0
    c.youtube.jitter_s = 0.0
    c.captions.asr_url = "http://mock/v1/audio/transcriptions"
    c.security.scrypt_n = 2**10
    c.models.refresh_min_interval_s = 0
    c.users = [
        UserConfig(
            name="owner",
            token_sha256=hash_token(TOKEN),
            admin=True,
            policy=UserPolicy(hide_topics=["reaction videos"], mark_topics=["celebrity gossip"]),
        ),
        UserConfig(name="partner", token_sha256=hash_token(OTHER_TOKEN), policy=UserPolicy()),
    ]
    return c


PASSWORD = "correct horse battery staple"


def anon_client(
    env, *, base_url: str = "http://utubot", peer: str | None = None
) -> httpx.AsyncClient:
    """A client without the bearer header, with its own cookie jar; `peer` sets the socket address."""
    transport = (
        httpx.ASGITransport(app=env.app, client=(peer, 50000)) if peer else env.client._transport
    )
    return httpx.AsyncClient(transport=transport, base_url=base_url)


@pytest_asyncio.fixture
async def env(cfg, mock_llm, fetcher, clock, tmp_path):
    asr = make_asr(cfg.captions, transport=httpx.ASGITransport(app=mock_llm.app))

    async def fake_download(video_id, out_dir, started=None):
        import subprocess

        path = out_dir / "audio.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=2",
                str(path),
            ],
            check=True,
        )
        return path

    app = create_app(
        cfg,
        llm_transport=httpx.ASGITransport(app=mock_llm.app),
        fetcher=fetcher,
        clock=clock,
        asr=asr,
        downloader=fake_download,
        prompt_transport=None,
    )
    async with app.router.lifespan_context(app):
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://utubot",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        yield type(
            "Env",
            (),
            {
                "client": client,
                "app": app,
                "svc": app.state.svc,
                "llm": mock_llm,
                "fetcher": fetcher,
                "clock": clock,
                "cfg": cfg,
            },
        )
        await client.aclose()
