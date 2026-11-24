"""The ASR WAV keeps the audio stream's container start time."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from utubot.captions.asr import (
    audio_start_offset,
    ffmpeg_available,
    start_offset_filter,
    transcode_wav,
    wav_duration,
)

pytestmark = pytest.mark.skipif(
    not ffmpeg_available() or not shutil.which("ffprobe"), reason="ffmpeg/ffprobe is not installed"
)

BASE_S = 1.0


def make_webm(path: Path, offset: float) -> Path:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-itsoffset",
            str(offset),
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={BASE_S}",
            "-c:a",
            "libopus",
            str(path),
        ],
        check=True,
    )
    return path


def test_the_filter_pads_a_positive_offset_and_trims_a_negative_one():
    assert start_offset_filter(0.0) is None
    assert start_offset_filter(0.0004) is None
    assert start_offset_filter(0.05) == "adelay=50:all=1"
    assert start_offset_filter(-0.05) == "atrim=start=0.050000,asetpts=PTS-STARTPTS"


async def test_an_unreadable_file_has_no_offset(tmp_path):
    assert await audio_start_offset(tmp_path / "missing.webm") == 0.0


async def test_a_positive_container_offset_becomes_leading_silence(tmp_path):
    source = make_webm(tmp_path / "late.webm", 0.05)
    offset = await audio_start_offset(source)
    assert offset > 0.001
    target = tmp_path / "late.wav"
    assert await transcode_wav(source, target) == pytest.approx(offset)
    assert wav_duration(target) == pytest.approx(BASE_S + offset, abs=0.02)


async def test_a_negative_container_offset_still_transcodes(tmp_path):
    source = make_webm(tmp_path / "early.webm", -0.05)
    offset = await audio_start_offset(source)
    assert offset < 0
    target = tmp_path / "early.wav"
    assert await transcode_wav(source, target) == pytest.approx(offset)
    assert wav_duration(target) <= BASE_S + 0.002
