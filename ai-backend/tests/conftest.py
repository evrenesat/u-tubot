from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from tests.fakes import FakeClock
from tests.mock_openai import MockOpenAI
from utubot.app import create_app
from utubot.auth import hash_token
from utubot.captions.asr import make_asr
from utubot.config import Config, UserConfig, UserPolicy
from utubot.transcripts import FetchResult

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

    async def __call__(self, video_id: str) -> FetchResult:
        self.calls.append(video_id)
        if self.error is not None:
            raise self.error
        if self.fail:
            raise RuntimeError("youtube blocked")
        meta = {
            "video_id": video_id,
            "title": f"Title {video_id}",
            "channel": "Chan",
            "duration_s": 900,
            **self.meta_extra,
        }
        return FetchResult(meta, self.text, "en")


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
