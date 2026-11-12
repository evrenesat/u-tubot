from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path

import pytest

from tests.fakes import FakeClock, settle
from utubot.captions import pipeline as pipeline_mod
from utubot.captions.jobs import JobQueue
from utubot.captions.pipeline import CaptionPipeline, audio_filter, download_audio, sweep_media
from utubot.config import Config, YoutubeConfig
from utubot.db import Database
from utubot.llm import BACKGROUND, INTERACTIVE
from utubot.transcripts import TranscriptService
from utubot.youtube import (
    CLASS_MEDIA,
    REASON_LIVE,
    REASON_TOO_LONG,
    YoutubeBlocked,
    YoutubeGate,
    YoutubeVideoError,
    ytdlp_runtime_options,
)

VID = "abcdefghijk"
NEEDS_FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
MAX_DURATION_S = 3 * 3600


def test_audio_filter_rejects_live_and_too_long_videos_from_the_real_info():
    verdict: dict[str, str] = {}
    check = audio_filter(MAX_DURATION_S, verdict)
    assert check({"duration": 600}, incomplete=False) is None
    assert check({}, incomplete=True) is None
    assert check({"duration": MAX_DURATION_S + 1}, incomplete=False)
    assert verdict["reason"] == REASON_TOO_LONG
    assert check({"is_live": True, "duration": 10}, incomplete=False)
    assert verdict["reason"] == REASON_LIVE
    assert check({"live_status": "is_upcoming"}, incomplete=False)


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: runs the match filter and progress hooks like the real one."""

    info: dict = {}
    created: list[dict] = []

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.created.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        if self.opts["match_filter"](self.info, incomplete=False):
            return None
        for hook in self.opts["progress_hooks"]:
            hook({"status": "downloading"})
        Path(self.opts["outtmpl"].replace("%(ext)s", "webm")).write_bytes(b"audio")
        return self.info

    def prepare_filename(self, info):
        return self.opts["outtmpl"].replace("%(ext)s", "webm")


@pytest.fixture
def fake_ydl(monkeypatch):
    FakeYDL.created = []
    FakeYDL.info = {"duration": 600}
    monkeypatch.setattr(pipeline_mod.yt_dlp, "YoutubeDL", FakeYDL)
    return FakeYDL


async def test_download_audio_passes_duration_and_size_limits_and_signals_the_start(
    tmp_path, fake_ydl
):
    started: list[int] = []
    path = await download_audio(
        VID,
        tmp_path,
        lambda: started.append(1),
        fmt="bestaudio/best",
        max_duration_s=MAX_DURATION_S,
        max_bytes=123456,
    )
    opts = fake_ydl.created[0]
    assert opts["max_filesize"] == 123456 and callable(opts["match_filter"])
    assert path.exists() and started == [1]


ORIGINAL_NOTE = "English (United States) original (default), low"
DUBBED_NOTE = "Spanish (United States) dubbed-auto, low"


def track(format_id: str, abr: float, note: str) -> dict:
    return {
        "format_id": format_id,
        "format_note": note,
        "acodec": "opus",
        "vcodec": "none",
        "abr": abr,
        "protocol": "https",
        "url": f"https://media.invalid/{format_id}",
    }


async def test_download_audio_selects_the_original_track_not_the_cheapest_dub(tmp_path, fake_ydl):
    await download_audio(
        VID,
        tmp_path,
        lambda: None,
        fmt="bestaudio/best",
        max_duration_s=MAX_DURATION_S,
        max_bytes=1 << 20,
    )
    select = fake_ydl.created[0]["format"]
    formats = [track("249-1", 40, DUBBED_NOTE), track("249-0", 50, ORIGINAL_NOTE)]
    assert [f["format_id"] for f in select({"formats": formats})] == ["249-0"]


async def test_download_audio_falls_back_to_the_configured_yt_dlp_selector(
    tmp_path, fake_ydl, monkeypatch
):
    asked: list[str] = []

    def build_format_selector(self, spec):
        asked.append(spec)
        return lambda ctx: iter([{"format_id": f"by-{spec}"}])

    monkeypatch.setattr(FakeYDL, "build_format_selector", build_format_selector, raising=False)
    await download_audio(
        VID,
        tmp_path,
        lambda: None,
        fmt="worstaudio",
        max_duration_s=MAX_DURATION_S,
        max_bytes=1 << 20,
    )
    select = fake_ydl.created[0]["format"]
    assert asked == ["worstaudio"]
    assert [f["format_id"] for f in select({"formats": []})] == ["by-worstaudio"]


async def test_download_audio_passes_the_js_runtime_options_to_yt_dlp(tmp_path, fake_ydl):
    cfg = YoutubeConfig(js_runtime="deno", js_runtime_path="/opt/deno/bin/deno")
    await download_audio(
        VID,
        tmp_path,
        lambda: None,
        fmt="bestaudio/best",
        max_duration_s=MAX_DURATION_S,
        max_bytes=1,
        extra_opts=ytdlp_runtime_options(cfg),
    )
    assert fake_ydl.created[0]["js_runtimes"] == {"deno": {"path": "/opt/deno/bin/deno"}}


async def test_a_429_while_downloading_audio_is_attributed_to_the_media_class(
    tmp_path, fake_ydl, monkeypatch
):
    def refuse(self, url, download=True):
        raise pipeline_mod.yt_dlp.utils.DownloadError("ERROR: HTTP Error 429: Too Many Requests")

    monkeypatch.setattr(FakeYDL, "extract_info", refuse)
    with pytest.raises(YoutubeBlocked) as exc:
        await download_audio(
            VID,
            tmp_path,
            lambda: None,
            fmt="bestaudio/best",
            max_duration_s=MAX_DURATION_S,
            max_bytes=1,
        )
    assert exc.value.klass == CLASS_MEDIA


def test_the_runtime_is_always_passed_on_and_looked_up_on_path_without_a_path():
    assert ytdlp_runtime_options(YoutubeConfig()) == {"js_runtimes": {"deno": {}}}
    assert ytdlp_runtime_options(YoutubeConfig(js_runtime="bun")) == {"js_runtimes": {"bun": {}}}
    cfg = YoutubeConfig(
        js_runtime="node", js_runtime_path="/usr/bin/node", remote_components=["ejs:github"]
    )
    assert ytdlp_runtime_options(cfg) == {
        "js_runtimes": {"node": {"path": "/usr/bin/node"}},
        "remote_components": ["ejs:github"],
    }
    only_components = YoutubeConfig(remote_components=["ejs:npm"])
    assert ytdlp_runtime_options(only_components) == {
        "js_runtimes": {"deno": {}},
        "remote_components": ["ejs:npm"],
    }


def test_yt_dlp_accepts_a_runtime_without_a_path_and_the_lock_carries_the_floor():
    import re
    import tomllib
    from pathlib import Path

    import yt_dlp

    cfg = YoutubeConfig(js_runtime="node", remote_components=["ejs:github"])
    with yt_dlp.YoutubeDL({"quiet": True, **ytdlp_runtime_options(cfg)}) as ydl:
        assert ydl.params["js_runtimes"] == {"node": {}}
        assert ydl.params["remote_components"] == {"ejs:github"}
    root = Path(__file__).resolve().parents[1]
    requirement = next(
        r
        for r in tomllib.loads((root / "pyproject.toml").read_text())["project"]["dependencies"]
        if r.startswith("yt-dlp")
    )
    floor = requirement.removeprefix("yt-dlp>=")
    assert floor >= "2025.11.12"  # first release with `remote_components`
    assert re.search(
        rf'name = "yt-dlp", specifier = ">={re.escape(floor)}"', (root / "uv.lock").read_text()
    )


def test_the_default_downloader_and_the_metadata_fetch_use_the_configured_runtime(
    tmp_path, monkeypatch
):
    from utubot.transcripts import YoutubeFetcher

    cfg = Config()
    cfg.server.data_dir = str(tmp_path / "data")
    cfg.youtube.js_runtime_path = "/opt/deno/bin/deno"
    seen: list[dict] = []

    class Capture(FakeYDL):
        def __init__(self, opts):
            seen.append(opts)
            super().__init__(opts)

        def extract_info(self, url, download=True):
            return {"id": "x", "title": "t", "formats": [{}]}

    monkeypatch.setattr(pipeline_mod.yt_dlp, "YoutubeDL", Capture)
    YoutubeFetcher(cfg)._extract(VID)
    assert seen[0]["js_runtimes"] == {"deno": {"path": "/opt/deno/bin/deno"}}
    assert seen[0]["skip_download"] is True


@pytest.mark.parametrize(
    ("info", "reason"),
    [
        ({"duration": MAX_DURATION_S + 60}, REASON_TOO_LONG),
        ({"duration": 60, "is_live": True}, REASON_LIVE),
    ],
)
async def test_download_audio_aborts_over_the_limit_before_downloading(
    tmp_path, fake_ydl, info, reason
):
    fake_ydl.info = info
    started: list[int] = []
    with pytest.raises(YoutubeVideoError) as exc:
        await download_audio(
            VID,
            tmp_path,
            lambda: started.append(1),
            fmt="bestaudio/best",
            max_duration_s=MAX_DURATION_S,
            max_bytes=1,
        )
    assert exc.value.reason == reason and started == []
    assert list(tmp_path.iterdir()) == []


async def test_a_file_skipped_by_max_filesize_is_a_too_long_failure(
    tmp_path, fake_ydl, monkeypatch
):
    monkeypatch.setattr(FakeYDL, "extract_info", lambda self, url, download=True: FakeYDL.info)
    with pytest.raises(YoutubeVideoError) as exc:
        await download_audio(
            VID,
            tmp_path,
            lambda: None,
            fmt="bestaudio/best",
            max_duration_s=MAX_DURATION_S,
            max_bytes=1,
        )
    assert exc.value.reason == REASON_TOO_LONG


@NEEDS_FFMPEG
async def test_pipeline_aborts_a_too_long_download_before_asr(env):
    env.cfg.captions.max_duration_s = 1
    env.fetcher.text = None
    pipeline = env.svc.jobs.pipeline
    with pytest.raises(YoutubeVideoError) as exc:
        await pipeline.transcribe(VID, lambda f: None)
    assert exc.value.reason == REASON_TOO_LONG
    assert env.llm.audio_calls == []
    assert not (env.cfg.media_dir / VID).exists()


def test_sweep_removes_only_old_orphan_directories(tmp_path):
    old, fresh = tmp_path / "oldoldoldol", tmp_path / "freshfreshf"
    for d in (old, fresh):
        d.mkdir()
        (d / "audio.webm").write_bytes(b"x")
    stale = time.time() - 2 * 3600
    os.utime(old, (stale, stale))
    (tmp_path / "stray.txt").write_text("keep")
    assert sweep_media(tmp_path, 3600) == 1
    assert not old.exists() and fresh.exists() and (tmp_path / "stray.txt").exists()
    assert sweep_media(tmp_path / "missing", 3600) == 0


async def test_orphan_media_is_swept_on_startup_unless_media_is_kept(env):
    media = env.cfg.media_dir
    await env.svc.jobs.stop()
    stale = time.time() - 2 * 3600
    for keep in (False, True):
        env.cfg.captions.keep_media = keep
        orphan = media / f"orphan{int(keep)}xxxx"
        orphan.mkdir(parents=True, exist_ok=True)
        os.utime(orphan, (stale, stale))
        env.svc.jobs.start()
        await env.svc.jobs.stop()
        assert orphan.exists() is keep
    env.svc.jobs.start()


# ---- a long download must not stall interactive fetches ----------------------------------------


class Rig:
    def __init__(self, tmp_path):
        self.cfg = Config()
        self.cfg.server.data_dir = str(tmp_path / "data")
        self.cfg.youtube.min_interval_s = 0.0
        self.cfg.youtube.jitter_s = 0.0
        self.clock = FakeClock()
        self.db = Database(tmp_path / "t.sqlite")
        self.gate = YoutubeGate(self.cfg.youtube, self.db, self.clock)
        self.release = asyncio.Event()
        self.started_flag = asyncio.Event()
        self.fetches: list[str] = []

        async def fetcher(video_id):
            from utubot.transcripts import FetchResult

            self.fetches.append(video_id)
            return FetchResult({"title": "t", "duration_s": 60}, "[00:00] caption text", "en")

        async def downloader(video_id, out_dir, started):
            started()
            self.started_flag.set()
            await self.release.wait()
            raise RuntimeError("stop here")

        self.transcripts = TranscriptService(self.cfg, self.db, fetcher, self.gate)
        self.pipeline = CaptionPipeline(
            self.cfg, self.db, asr=None, downloader=downloader, gate=self.gate
        )
        self.jobs = JobQueue(self.cfg, self.db, self.pipeline, self.transcripts)


async def test_interactive_fetches_do_not_wait_behind_a_whole_audio_download(tmp_path):
    rig = Rig(tmp_path)
    download = asyncio.create_task(rig.pipeline.transcribe(VID, lambda f: None))
    await asyncio.wait_for(rig.started_flag.wait(), 5)
    await settle()
    transcript = await asyncio.wait_for(rig.transcripts.get("otherotherot", INTERACTIVE), 5)
    assert transcript.text and not download.done()
    background = await asyncio.wait_for(rig.transcripts.get("thirdthirdth", BACKGROUND), 5)
    assert background.text and not download.done()
    rig.release.set()
    with pytest.raises(RuntimeError):
        await download
