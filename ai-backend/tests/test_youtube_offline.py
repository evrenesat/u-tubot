from __future__ import annotations

from pathlib import Path

import httpx
import pytest_asyncio

from tests.test_youtube_fixtures import DEMO_ID
from utubot.app import build_services, create_app
from utubot.auth import hash_token
from utubot.captions.asr import make_asr
from utubot.config import Config, UserConfig, UserPolicy
from utubot.status import StatusService
from utubot.youtube_fixtures import OfflineYoutubeFetcher, default_fixture_dir

TOKEN = "utb_testtoken"


def offline_cfg(tmp_path: Path) -> Config:
    cfg = Config()
    cfg.youtube.offline = True
    cfg.youtube.fixtures_dir = str(default_fixture_dir())
    cfg.server.data_dir = str(tmp_path / "data")
    cfg.security.scrypt_n = 2**10
    cfg.users = [
        UserConfig(name="owner", token_sha256=hash_token(TOKEN), admin=True, policy=UserPolicy())
    ]
    return cfg


def test_build_services_wires_the_offline_fetcher(tmp_path):
    cfg = offline_cfg(tmp_path)
    svc = build_services(cfg)
    assert isinstance(svc.transcripts.fetcher, OfflineYoutubeFetcher)
    assert svc.gate.offline is True


def test_status_reports_offline(tmp_path):
    cfg = offline_cfg(tmp_path)
    svc = build_services(cfg)
    assert (
        StatusService(cfg, svc.db, svc.gate, svc.llm.usage, svc.transcription.engines).home(
            "owner"
        )["youtube"]["offline"]
        is True
    )
    online = offline_cfg(tmp_path)
    online.youtube.offline = False
    svc2 = build_services(online)
    assert (
        StatusService(online, svc2.db, svc2.gate, svc2.llm.usage, svc2.transcription.engines).home(
            "owner"
        )["youtube"]["offline"]
        is False
    )


@pytest_asyncio.fixture
async def offline_env(tmp_path, mock_llm, clock):
    """The real app, offline, with no fetcher of its own: fixtures and the mock LLM answer."""
    cfg = offline_cfg(tmp_path)
    asr = make_asr(cfg.captions, transport=httpx.ASGITransport(app=mock_llm.app))
    app = create_app(
        cfg,
        llm_transport=httpx.ASGITransport(app=mock_llm.app),
        clock=clock,
        asr=asr,
        downloader=None,
        prompt_transport=None,
    )
    async with app.router.lifespan_context(app):
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://utubot",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        yield type("Env", (), {"client": client, "app": app, "svc": app.state.svc, "cfg": cfg})
        await client.aclose()


async def test_app_offline_serves_a_recorded_video_summary(offline_env):
    """The whole summary flow works against recorded answers: no YouTube, no real LLM."""
    env = offline_env
    assert isinstance(env.svc.transcripts.fetcher, OfflineYoutubeFetcher)
    resp = await env.client.get(f"/v1/videos/{DEMO_ID}/summary", params={"wait_ms": 5000})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready" and body["text"], body
    transcript = (await env.client.get(f"/v1/videos/{DEMO_ID}/transcript")).json()
    assert transcript["transcript_status"] == "ok" and transcript["source"] == "youtube_captions", (
        transcript
    )


async def test_app_offline_reports_an_unrecorded_video_without_touching_anything(offline_env):
    resp = await offline_env.client.get("/v1/videos/zzzzzzzzzzz/summary", params={"wait_ms": 500})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed", body
    assert "offline" in body["error"].lower(), body
