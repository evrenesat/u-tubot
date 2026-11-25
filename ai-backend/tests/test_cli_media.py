"""`utubot media import`: offline archive intake for watched benches and tests."""

from __future__ import annotations

from pathlib import Path

from utubot.cli import main
from utubot.config import load_config
from utubot.db import Database
from utubot.media_archive import KIND_AUDIO, KIND_VIDEO, MediaArchive

VID = "abcdefghijk"


def cfg_path(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        f'[server]\ndata_dir = "{tmp_path}/d"\n[youtube]\noffline = true\n'
        '[[users]]\nname = "owner"\nadmin = true\n'
    )
    return path


def test_imports_a_video_and_serves_it_from_the_archive(tmp_path, capsys):
    config = cfg_path(tmp_path)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"synthetic-video-bytes" * 8)
    size = source.stat().st_size
    assert main(["--config", str(config), "media", "import", VID, str(source)]) == 0
    out = capsys.readouterr().out
    assert KIND_VIDEO in out and VID in out
    cfg = load_config(config)
    db = Database(cfg.db_path)
    archive = MediaArchive(cfg, db)
    entry = archive.lookup(VID, KIND_VIDEO)
    assert entry is not None and entry["size"] == size
    assert archive.path_of(entry).read_bytes() == b"synthetic-video-bytes" * 8
    assert not source.exists(), "the scratch file is moved into the archive"
    db.close()


def test_imports_an_audio_file_beside_the_video(tmp_path, capsys):
    config = cfg_path(tmp_path)
    first = tmp_path / "a.mp4"
    first.write_bytes(b"video-bytes")
    second = tmp_path / "b.wav"
    second.write_bytes(b"audio-bytes")
    assert main(["--config", str(config), "media", "import", VID, str(first)]) == 0
    assert (
        main(["--config", str(config), "media", "import", VID, str(second), "--kind", KIND_AUDIO])
        == 0
    )
    cfg = load_config(config)
    db = Database(cfg.db_path)
    rows = db.all("SELECT kind, sha256 FROM media_archive WHERE video_id=? ORDER BY kind", [VID])
    assert [row["kind"] for row in rows] == [KIND_AUDIO, KIND_VIDEO]
    assert rows[0]["sha256"] != rows[1]["sha256"]
    db.close()


def test_bad_video_id_fails_before_touching_the_archive(tmp_path, capsys):
    config = cfg_path(tmp_path)
    source = tmp_path / "bad.mp4"
    source.write_bytes(b"bytes")
    assert main(["--config", str(config), "media", "import", "../bad", str(source)]) == 1
    assert "error" in capsys.readouterr().err and source.exists()
