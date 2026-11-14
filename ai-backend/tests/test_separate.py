"""Optional vocal separation (demucs) ahead of speech to text."""

from __future__ import annotations

import asyncio
import wave
from pathlib import Path

from utubot.captions.separate import DemucsSeparator, make_separator
from utubot.config import CaptionsConfig


def make_wav(path: Path, seconds: float = 0.2) -> Path:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0" * int(seconds * 16000))
    return path


def test_make_separator_off_by_default():
    assert make_separator(CaptionsConfig()) is None


def test_make_separator_skips_a_missing_tool():
    cfg = CaptionsConfig(
        separation="demucs", separation_cmd=["definitely-not-on-path-xyz", "--run"]
    )
    assert make_separator(cfg) is None


def test_separator_runs_the_command_and_returns_the_vocals_stem(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    wav = make_wav(work / "audio16k.wav")

    async def fake_demucs(wav_path: Path, work_path: Path) -> None:
        # stand in for the demucs run: write the layout the separator looks for
        stem = work_path / "separated" / "htdemucs" / "audio16k"
        stem.mkdir(parents=True, exist_ok=True)
        make_wav(stem / "vocals.wav")

    separator = DemucsSeparator(["true", "--two-stems", "vocals"], timeout_s=30)
    real_separate = separator.separate

    async def separate(wav_path, work_path):
        await fake_demucs(wav_path, work_path)
        return await real_separate(wav_path, work_path)

    # the command must exist for create_subprocess_exec; `true` succeeds and writes nothing,
    # so the fake_demucs side effect provides the stem
    vocals = asyncio.run(separate(wav, work))
    assert vocals is not None and vocals.name == "vocals.wav"


def test_separator_returns_none_when_the_run_fails(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    wav = make_wav(work / "audio16k.wav")
    separator = DemucsSeparator(["false"], timeout_s=30)
    assert asyncio.run(separator.separate(wav, work)) is None


def test_separator_returns_none_without_a_vocals_stem(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    wav = make_wav(work / "audio16k.wav")
    separator = DemucsSeparator(["true"], timeout_s=30)
    assert asyncio.run(separator.separate(wav, work)) is None


def test_separator_gives_up_after_the_timeout(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    wav = make_wav(work / "audio16k.wav")
    separator = DemucsSeparator(["sleep", "5"], timeout_s=0.2)
    assert asyncio.run(separator.separate(wav, work)) is None
