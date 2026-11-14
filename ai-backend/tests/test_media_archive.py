"""The media archive: nothing downloaded is thrown away, nothing is downloaded twice.

No test here (or anywhere in this suite) reaches YouTube: the store is exercised with plain
files, and the pipeline tests use the fake downloader of the `env` fixture.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import httpx
import pytest

from tests.conftest import OTHER_TOKEN
from utubot.captions.pipeline import sweep_media
from utubot.db import Database
from utubot.media_archive import (
    KIND_AUDIO,
    KIND_VIDEO,
    MediaArchive,
    MediaArchiveError,
    MediaArchiveFull,
)
from utubot.transcripts import SOURCE_ASR

VID = "abcdefghijk"
OTHER = "other0video"
THIRD = "third0video"
NEEDS_FFMPEG = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg missing")
MEDIA = b"original language audio bytes"


def write_media(tmp_path: Path, name: str, content: bytes, suffix: str = ".webm") -> Path:
    path = tmp_path / f"{name}{suffix}"
    path.write_bytes(content)
    return path


def archive_of(cfg, db) -> MediaArchive:
    return MediaArchive(cfg, db)


def test_store_keeps_the_file_content_addressed_and_records_the_row(tmp_path, cfg):
    arc = archive_of(cfg, Database(tmp_path / "t.sqlite"))
    src = write_media(tmp_path, "audio", MEDIA)
    entry = arc.store(
        VID,
        src,
        format_id="250",
        codec="opus",
        bitrate_kbps=50.0,
        language="en",
        original=1,
        job_id="job1",
    )
    kept = arc.path_of(entry)
    assert kept.is_file() and kept.read_bytes() == MEDIA
    assert not src.exists(), "the scratch copy goes once the archive has the file"
    assert entry["sha256"] and len(entry["sha256"]) == 64
    assert entry["size"] == len(MEDIA) and entry["kind"] == KIND_AUDIO
    assert entry["format_id"] == "250" and entry["original"] == 1 and entry["ext"] == "webm"
    assert str(entry["path"]).startswith("files/")
    row = arc.lookup(VID)
    assert row is not None and row["sha256"] == entry["sha256"] and row["job_id"] == "job1"


def test_identical_bytes_are_stored_once(tmp_path, cfg):
    arc = archive_of(cfg, Database(tmp_path / "t.sqlite"))
    first = arc.store(VID, write_media(tmp_path, "a", MEDIA))
    second = arc.store(OTHER, write_media(tmp_path, "b", MEDIA))
    assert first["sha256"] == second["sha256"]
    assert len(list((arc.root / "files").rglob("*.*"))) == 1
    assert arc.usage() == 2 * len(MEDIA), "usage counts entries, not unique files"
    assert arc.count() == 2


def test_lookup_prefers_the_original_track_then_the_newest(tmp_path, cfg):
    arc = archive_of(cfg, Database(tmp_path / "t.sqlite"))
    dubbed = arc.store(VID, write_media(tmp_path, "dub", b"dubbed"), original=0, language="es")
    time.sleep(0.01)
    original = arc.store(VID, write_media(tmp_path, "orig", MEDIA), original=1, language="en")
    assert arc.lookup(VID)["sha256"] == original["sha256"]
    older_original = arc.store(VID, write_media(tmp_path, "old", b"older"), original=1)
    arc.db.execute(
        "UPDATE media_archive SET fetched_at=? WHERE sha256=?",
        [time.time() - 100, older_original["sha256"]],
    )
    assert arc.lookup(VID)["sha256"] == original["sha256"]
    assert dubbed["sha256"] != original["sha256"]


def test_a_row_whose_file_vanished_is_dropped_so_the_video_is_fetched_again(tmp_path, cfg):
    arc = archive_of(cfg, Database(tmp_path / "t.sqlite"))
    entry = arc.store(VID, write_media(tmp_path, "a", MEDIA))
    arc.path_of(entry).unlink()
    assert arc.lookup(VID) is None
    assert arc.count() == 0


def test_require_room_stops_new_downloads_at_the_quota(tmp_path, cfg):
    cfg.archive.quota_bytes = len(MEDIA)
    arc = archive_of(cfg, Database(tmp_path / "t.sqlite"))
    arc.require_room()
    arc.store(VID, write_media(tmp_path, "a", MEDIA))
    with pytest.raises(MediaArchiveFull) as exc:
        arc.require_room()
    assert exc.value.usage == len(MEDIA) and exc.value.quota == len(MEDIA)
    assert (
        "admin must free space" in exc.value.message and "nothing is deleted" in exc.value.message
    )


def test_a_file_that_pushes_usage_over_the_quota_is_kept_anyway(tmp_path, cfg):
    cfg.archive.quota_bytes = len(MEDIA) + 1
    arc = archive_of(cfg, Database(tmp_path / "t.sqlite"))
    arc.store(VID, write_media(tmp_path, "a", MEDIA))
    entry = arc.store(OTHER, write_media(tmp_path, "b", MEDIA))
    assert arc.path_of(entry).is_file()
    assert arc.status()["state"] == "full"


def test_status_reports_ok_warn_and_full(tmp_path, cfg):
    cfg.archive.quota_bytes = 320  # warn from 288 bytes on
    cfg.archive.warn_frac = 0.9
    arc = archive_of(cfg, Database(tmp_path / "t.sqlite"))
    assert arc.status() == {"files": 0, "usage_bytes": 0, "quota_bytes": 320, "state": "ok"}
    arc.store(VID, write_media(tmp_path, "a", MEDIA))
    assert arc.status()["state"] == "ok"
    arc.store(OTHER, write_media(tmp_path, "b", b"x" * 270))
    assert arc.status()["state"] == "warn"
    arc.store(THIRD, write_media(tmp_path, "c", b"y" * len(MEDIA)))
    assert arc.status()["state"] == "full" and arc.status()["usage_bytes"] >= 320


def test_remove_is_explicit_and_never_takes_a_file_another_entry_uses(tmp_path, cfg):
    arc = archive_of(cfg, Database(tmp_path / "t.sqlite"))
    shared = arc.store(VID, write_media(tmp_path, "a", MEDIA))
    arc.store(OTHER, write_media(tmp_path, "b", MEDIA))
    alone = arc.store(THIRD, write_media(tmp_path, "c", b"unique"))
    removed, freed = arc.remove(VID)
    assert (removed, freed) == (1, 0), "the bytes stay: OTHER still uses the same file"
    assert arc.path_of(shared).is_file()
    assert arc.count() == 2
    assert arc.remove(VID) == (0, 0)
    assert arc.lookup(VID) is None and arc.lookup(OTHER) is not None
    removed, freed = arc.remove(THIRD)
    assert (removed, freed) == (1, len(b"unique"))
    assert not arc.path_of(alone).exists(), "a file only this video used goes"


def test_scratch_sweep_clears_staging_leftovers_but_never_recorded_files(tmp_path, cfg):
    arc = archive_of(cfg, Database(tmp_path / "t.sqlite"))
    entry = arc.store(VID, write_media(tmp_path, "a", MEDIA))
    stale = arc.tmp / "leftover.webm"
    stale.write_bytes(b"half copied")
    arc.sweep_scratch()
    assert not stale.exists() and arc.path_of(entry).is_file() and arc.count() == 1


def test_the_scratch_sweep_of_media_dir_never_touches_the_archive(env):
    arc = env.svc.archive
    env.cfg.media_dir.mkdir(parents=True, exist_ok=True)
    src = write_media(env.cfg.media_dir, "keepme", MEDIA)
    entry = arc.store(VID, src)
    orphan = env.cfg.media_dir / "orphanold"
    orphan.mkdir(exist_ok=True)
    (orphan / "audio.webm").write_bytes(b"x")
    os.utime(orphan, (time.time() - 2 * 3600,) * 2)
    assert sweep_media(env.cfg.media_dir, 3600) == 1
    assert arc.path_of(entry).is_file() and arc.lookup(VID) is not None
    assert not orphan.exists()


@NEEDS_FFMPEG
async def test_a_store_failure_fails_the_job_and_keeps_the_download(env):
    env.fetcher.text = None
    blocker = env.cfg.archive_dir  # a file where the archive root should be: every store fails
    blocker.write_text("not a directory")
    pipeline = env.svc.jobs.pipeline
    work = env.cfg.media_dir / VID
    with pytest.raises(MediaArchiveError):
        await pipeline.transcribe(VID, lambda f: None)
    assert work.exists(), "the download stays: the archive could not keep it, so nothing is deleted"
    assert (work / "audio.wav").is_file()


async def _run_transcript_job(env) -> dict:
    out = env.svc.transcription.request("owner", VID)
    job = env.svc.jobs.get(out["job_id"])
    assert await env.svc.jobs.run_one() is True
    return env.svc.jobs.get(job["id"])


async def _run_captions_job(env) -> dict:
    env.svc.jobs.enqueue("owner", VID, "auto", None)
    assert await env.svc.jobs.run_one() is True
    row = env.svc.db.one(
        "SELECT id FROM jobs WHERE kind='captions' AND video_id=? ORDER BY created_at DESC", [VID]
    )
    return env.svc.jobs.get(row["id"])


@NEEDS_FFMPEG
async def test_the_first_job_downloads_and_stores_the_second_reads_the_archive(env, monkeypatch):
    env.fetcher.text = None
    pipeline = env.svc.jobs.pipeline
    calls: list[str] = []

    async def counting(video_id, out_dir, started=None):
        calls.append(video_id)
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

    monkeypatch.setattr(pipeline, "downloader", counting)
    first = await _run_transcript_job(env)
    assert first["status"] == "ready" and calls == [VID]
    entry = env.svc.archive.lookup(VID)
    assert entry is not None and entry["size"] > 0
    events = env.svc.jobs.events.list(first["id"])
    stored = [e for e in events if e["stage"] == "media_archive" and e["status"] == "ok"]
    assert stored and stored[0]["detail"]["bytes"] == entry["size"]
    downloaded = [e for e in events if e["stage"] == "audio_download" and e["status"] == "ok"]
    assert downloaded[0]["detail"]["source"] == "downloaded"

    second = await _run_captions_job(env)
    assert second["status"] == "ready" and calls == [VID], "the audio was not fetched again"
    again = [
        e
        for e in env.svc.jobs.events.list(second["id"])
        if e["stage"] == "audio_download" and e["status"] == "ok"
    ]
    assert again[0]["detail"]["source"] == "from_archive"
    assert not [e for e in env.svc.jobs.events.list(second["id"]) if e["stage"] == "media_archive"]
    row = env.svc.db.one("SELECT source FROM transcripts WHERE video_id=?", [VID])
    assert row["source"] == SOURCE_ASR


@NEEDS_FFMPEG
async def test_a_full_archive_fails_the_job_before_any_download(env, monkeypatch):
    env.fetcher.text = None
    env.cfg.archive.quota_bytes = 10
    env.svc.archive.store(OTHER, write_media(Path(env.cfg.data_dir), "filler", b"x" * 10))
    calls: list[str] = []

    async def counting(video_id, out_dir, started=None):
        calls.append(video_id)
        raise AssertionError("no download may start")

    monkeypatch.setattr(env.svc.jobs.pipeline, "downloader", counting)
    job = await _run_transcript_job(env)
    assert job["status"] == "failed" and calls == []
    assert "media archive is full" in job["error"]
    event = [e for e in env.svc.jobs.events.list(job["id"]) if e["stage"] == "failed"]
    assert event and event[0]["detail"]["error_class"] == "MediaArchiveFull"


async def test_admin_archive_endpoints_are_admin_only_and_remove_entries(env):
    arc = env.svc.archive
    entry = arc.store(VID, write_media(Path(env.cfg.data_dir), "m", MEDIA))
    assert (await env.client.get("/v1/admin/archive")).status_code == 200
    other = httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}"},
    )
    assert (await other.get("/v1/admin/archive")).status_code == 403
    doc = (await env.client.get("/v1/admin/archive")).json()
    assert doc["files"] == 1 and doc["entries"][0]["sha256"] == entry["sha256"]
    assert doc["entries"][0]["video_id"] == VID and doc["usage_bytes"] == len(MEDIA)

    filtered = (await env.client.get("/v1/admin/archive", params={"video_id": OTHER})).json()
    assert filtered["entries"] == [] and filtered["files"] == 1

    env.svc.jobs.pipeline.cache.put(VID, "asr", "k", {"cached": True})
    removed = await env.client.delete("/v1/admin/archive/" + VID)
    assert removed.status_code == 200 and removed.json()["removed"] == 1
    assert removed.json()["bytes_freed"] == len(MEDIA)
    assert removed.json()["stage_cache_rows_removed"] == 1
    assert env.svc.jobs.pipeline.cache.get(VID, "asr", "k") is None
    assert not arc.path_of(entry).exists() and arc.count() == 0
    assert (await env.client.delete("/v1/admin/archive/" + VID)).status_code == 404
    await other.aclose()


async def test_admin_status_carries_the_archive_state(env):
    doc = (await env.client.get("/v1/admin/status")).json()
    assert doc["archive"]["state"] == "ok" and doc["archive"]["files"] == 0


def test_the_video_kind_is_a_distinct_entry_for_later_pipelines(tmp_path, cfg):
    arc = archive_of(cfg, Database(tmp_path / "t.sqlite"))
    arc.store(VID, write_media(tmp_path, "a", MEDIA), kind=KIND_AUDIO)
    frame = arc.store(VID, write_media(tmp_path, "v", b"frames", suffix=".mp4"), kind=KIND_VIDEO)
    assert arc.lookup(VID, KIND_AUDIO)["sha256"] != frame["sha256"]
    assert arc.lookup(VID, KIND_VIDEO)["sha256"] == frame["sha256"]
    assert arc.lookup(VID, KIND_VIDEO)["ext"] == "mp4"


def test_an_archive_inside_the_media_scratch_dir_is_refused(tmp_path, cfg):
    cfg.archive.path = str(cfg.media_dir / "archive")
    with pytest.raises(ValueError) as exc:
        archive_of(cfg, Database(tmp_path / "t.sqlite"))
    assert "orphan sweep" in str(exc.value)


def test_a_failing_store_keeps_the_scratch_file(tmp_path, cfg):
    arc = archive_of(cfg, Database(tmp_path / "t.sqlite"))
    blocker = cfg.archive_dir
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("not a directory")
    src = write_media(tmp_path, "audio", MEDIA)
    with pytest.raises(MediaArchiveError) as exc:
        arc.store(VID, src, work=cfg.media_dir / VID)
    assert exc.value.work == cfg.media_dir / VID
    assert src.is_file(), "nothing was recorded, so the download must survive"
