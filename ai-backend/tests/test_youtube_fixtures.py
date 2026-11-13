from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from tests.fakes import FakeClock
from utubot.config import Config
from utubot.db import Database
from utubot.transcripts import TranscriptService, YoutubeFetcher
from utubot.youtube import CLASS_MEDIA, FETCH_CLASSES, YoutubeGate, YoutubeOffline
from utubot.youtube_fixtures import (
    OfflineYoutubeFetcher,
    default_fixture_dir,
    guard_recording,
    load_cassette,
    record_cassette,
    sanitize_info,
    save_cassette,
)

DEMO_ID = "utubot_demo"
TRACK_URL = "https://www.youtube.com/api/timedtext?v=utubot_demo&sig=SECRET&lang=en&fmt=json3"


@pytest.fixture
def demo() -> dict:
    cassette = load_cassette(default_fixture_dir(), DEMO_ID)
    assert cassette is not None, "the demo cassette must be committed"
    return cassette


def siggy_info() -> dict:
    """A yt-dlp answer carrying exactly the things that must never reach a cassette."""
    return {
        "id": DEMO_ID,
        "title": "Signed",
        "duration": 30,
        "description": "watch https://example.com/watch?v=x&t=1s here " + "x" * 3000,
        "formats": [
            {
                "format_id": "251",
                "ext": "webm",
                "url": "https://rr3---sn.googlevideo.com/videoplayback?id=abc&sig=SIGNED&ratebypass=yes",
                "http_headers": {"User-Agent": "ua"},
            }
        ],
        "subtitles": {},
        "automatic_captions": {
            "en": [
                {"ext": "json3", "url": TRACK_URL},
                {"ext": "vtt", "url": "https://www.youtube.com/api/timedtext?v=x&sig=OTHER"},
            ]
        },
        "heatmap": [{"x": i, "url": "https://i.ytimg.com/an_webp/x?sigh=SIGN"} for i in range(3)],
    }


def url_keys(value) -> list[str]:
    """Every `url` key left anywhere in a structure."""
    if isinstance(value, dict):
        return (["url"] if "url" in value else []) + [
            u for v in value.values() for u in url_keys(v)
        ]
    if isinstance(value, list):
        return [u for item in value for u in url_keys(item)]
    return []


def signed_tokens(value) -> list[str]:
    flat = json.dumps(value)
    return [token for token in ("sig=", "sigh=", "SIGNED", "SECRET") if token in flat]


def gate_svc(tmp_path: Path, cfg: Config, fetcher) -> tuple[YoutubeGate, TranscriptService]:
    cfg.youtube.min_interval_s = cfg.youtube.jitter_s = 0.0
    db = Database(tmp_path / "t.sqlite")
    gate = YoutubeGate(cfg.youtube, db, FakeClock())
    return gate, TranscriptService(cfg, db, fetcher, gate)


def test_sanitize_strips_every_url_and_signature():
    clean = sanitize_info(siggy_info())
    assert url_keys(clean) == []
    assert signed_tokens(clean) == []
    flat = json.dumps(clean)
    assert "http_headers" not in flat and "User-Agent" not in flat
    # The structure the fetchers and pickers need survives.
    assert clean["formats"][0]["format_id"] == "251"
    assert [f["ext"] for f in clean["automatic_captions"]["en"]] == ["json3", "vtt"]
    assert len(clean["heatmap"]) == 3
    # A description keeps its link but loses the query (and stays capped).
    assert "https://example.com/watch" in clean["description"]
    assert "?v=x" not in clean["description"] and "&t=1s" not in clean["description"]
    assert len(clean["description"]) <= 2000


def test_cassette_roundtrip_and_demo_shape(tmp_path, demo):
    info, track = siggy_info(), {"lang": "en", "ext": "json3", "text": '{"events":[]}'}
    path = save_cassette(tmp_path, DEMO_ID, info, track, note="test", yt_dlp_version="test-1")
    saved = json.loads(path.read_text())
    assert saved["info"] == sanitize_info(info)
    assert saved["track"] == track and saved["video_id"] == DEMO_ID
    assert saved["yt_dlp_version"] == "test-1" and saved["note"] == "test"
    assert load_cassette(tmp_path, "missing_id0") is None
    # The committed demo cassette is git-safe too and complete enough for the fetcher.
    assert url_keys(demo) == [] and signed_tokens(demo) == []
    assert demo["info"]["id"] == DEMO_ID and demo["track"]["ext"] == "json3"


async def test_record_cassette_from_stubs_is_sanitized(tmp_path):
    path = await record_cassette(
        Config(),
        DEMO_ID,
        out_dir=tmp_path / "fixtures",
        note="stubbed",
        extract=lambda vid: siggy_info(),
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text='{"events":[]}')),
    )
    saved = json.loads(path.read_text())
    assert url_keys(saved) == [] and signed_tokens(saved) == []
    assert saved["track"] == {"lang": "en", "ext": "json3", "text": '{"events":[]}'}
    assert saved["note"] == "stubbed"


async def test_record_cassette_refuses_the_real_path_under_pytest(tmp_path):
    with pytest.raises(RuntimeError, match="never run it from tests"):
        await record_cassette(Config(), DEMO_ID, out_dir=tmp_path)


def test_guard_refuses_automated_runs():
    with pytest.raises(RuntimeError, match="never run it from tests"):
        guard_recording()


async def test_offline_fetcher_serves_the_demo_cassette(demo):
    fetcher = OfflineYoutubeFetcher(Config(), default_fixture_dir())
    result = await fetcher(DEMO_ID)
    assert result.text and "fixture demo" in result.text
    assert result.lang == "en"
    assert result.meta["title"] == "u·tubot recorded fixture demo"
    assert result.meta["duration_s"] == 620
    with pytest.raises(YoutubeOffline):
        await fetcher("zzzzzzzzzzz")


async def test_offline_fetcher_without_track_answers_no_captions(tmp_path, demo):
    cassette = copy.deepcopy(demo)
    cassette["track"] = None
    (tmp_path / f"{DEMO_ID}.json").write_text(json.dumps(cassette))
    result = await OfflineYoutubeFetcher(Config(), tmp_path)(DEMO_ID)
    assert result.text is None and result.lang is None


async def test_offline_fetcher_through_the_gate(tmp_path):
    """The fixture read goes through the gate untouched; an unknown video is a video error."""
    _, svc = gate_svc(tmp_path, Config(), OfflineYoutubeFetcher(Config(), default_fixture_dir()))
    transcript = await svc.get(DEMO_ID)
    assert "fixture demo" in transcript.text and transcript.source == "youtube_captions"
    assert (await svc.get(DEMO_ID)).text == transcript.text  # the second call is the cache
    with pytest.raises(YoutubeOffline):
        await svc.get("zzzzzzzzzzz")
    # A video the offline server cannot answer is remembered as failed, so the audio fallback
    # (which offline mode refuses too) is never offered for it.
    assert svc.hold("zzzzzzzzzzz")["reason"] == "offline"


async def test_cassette_replays_through_the_real_fetcher(tmp_path, demo):
    """The recorded answers, fed into YoutubeFetcher's seams, produce the same transcript."""
    cfg = Config()
    info = copy.deepcopy(demo["info"])
    for fmt in info["automatic_captions"]["en"]:
        if fmt["ext"] == "json3":
            fmt["url"] = TRACK_URL  # the one URL sanitization strips; the test rebuilds it
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text=demo["track"]["text"])

    _, svc = gate_svc(
        tmp_path, cfg, YoutubeFetcher(cfg, lambda vid: info, httpx.MockTransport(handle))
    )
    transcript = await svc.get(DEMO_ID)
    assert "[00:00] Welcome to the u·tubot fixture demo." in transcript.text
    assert transcript.meta["title"] == "u·tubot recorded fixture demo"
    assert len(seen) == 1 and seen[0].url.host == "www.youtube.com"


async def test_offline_gate_refuses_media_but_not_fixture_reads(tmp_path):
    cfg = Config()
    cfg.youtube.offline = True
    gate = YoutubeGate(cfg.youtube, None, FakeClock())
    assert gate.offline is True

    async def transfer(started) -> None:
        started()

    with pytest.raises(YoutubeOffline):
        await gate.run_started(transfer, classes=(CLASS_MEDIA,))
    with pytest.raises(YoutubeOffline):
        await gate.run(asyncio.sleep, 0, classes=(CLASS_MEDIA,))

    async def noop() -> None:
        return None

    # Fetch classes stay open: the offline fetcher answers them from local cassettes.
    await gate.run(noop, classes=FETCH_CLASSES)
    assert gate.healthy()
    _, svc = gate_svc(tmp_path, cfg, OfflineYoutubeFetcher(cfg, default_fixture_dir()))
    assert "fixture demo" in (await svc.get(DEMO_ID)).text


async def test_offline_mode_refuses_the_real_fetcher(tmp_path):
    """With `[youtube] offline`, even a wired-in real fetcher never runs."""
    cfg = Config()
    cfg.youtube.offline = True

    def extract(vid: str) -> dict:
        raise AssertionError("offline mode must not extract anything")

    _, svc = gate_svc(tmp_path, cfg, YoutubeFetcher(cfg, extract, None))
    with pytest.raises(YoutubeOffline):
        await svc.get(DEMO_ID)
