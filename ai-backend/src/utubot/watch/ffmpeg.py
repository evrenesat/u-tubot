"""Blocking `ffmpeg`/`ffprobe` calls for the grid stage, adapted from scene-analyser.

The central `run_ffmpeg` in `captions/asr.py` discards stdout and cannot stream raw frames or
return stderr, so the watch stage has its own small wrapper. The caller runs the whole grid stage
in one worker thread (`asyncio.to_thread`); a cancel event terminates the child.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

PTS_TIME_RE = re.compile(r"pts_time:([0-9.]+)")
POLL_S = 0.1
STDERR_MAX_CHARS = 300


class FfmpegError(RuntimeError):
    """A child program failed; the message carries trimmed stderr and no path or URL."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _args(program: str, args: list[str], threads: int) -> list[str]:
    out = [program]
    if program == "ffmpeg":
        out.extend(["-threads", str(threads)])
    out.extend(args)
    return out


def _wait(process: subprocess.Popen, cancel: threading.Event | None, timeout_s: float) -> int:
    deadline = time.monotonic() + timeout_s
    while True:
        if cancel is not None and cancel.is_set():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise FfmpegError("the ffmpeg job was cancelled")
        code = process.poll()
        if code is not None:
            return code
        if time.monotonic() > deadline:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            raise FfmpegError("the ffmpeg job timed out")
        time.sleep(POLL_S)


def trimmed(stderr: bytes | str) -> str:
    text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " ".join(lines)[-STDERR_MAX_CHARS:] or "ffmpeg failed"


def run(
    args: list[str],
    *,
    cancel: threading.Event | None = None,
    threads: int,
    timeout_s: float,
    stdout_path: Path | None = None,
) -> None:
    """One blocking program call; stdout goes to a file or is discarded, stderr is trimmed."""
    out = subprocess.DEVNULL
    handle = None
    if stdout_path is not None:
        handle = open(stdout_path, "wb")
        out = handle
    process = subprocess.Popen(
        _args("ffmpeg", args, threads),
        stdout=out,
        stderr=subprocess.PIPE,
    )
    try:
        code = _wait(process, cancel, timeout_s)
        stderr = process.stderr.read() if process.stderr is not None else b""
    finally:
        if process.stderr is not None:
            process.stderr.close()
        if handle is not None:
            handle.close()
    if code != 0:
        raise FfmpegError(f"ffmpeg failed: {trimmed(stderr)}")


def capture(
    program: str, args: list[str], *, cancel: threading.Event | None, threads: int, timeout_s: float
) -> str:
    """stdout and stderr of one blocking probe; ffprobe passes its own arguments unchanged."""
    process = subprocess.Popen(
        _args(program, args, threads),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        code = _wait(process, cancel, timeout_s)
        stdout = process.stdout.read() if process.stdout is not None else b""
        stderr = process.stderr.read() if process.stderr is not None else b""
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
    if code != 0:
        raise FfmpegError(f"{program} failed: {trimmed(stderr)}")
    return (stdout.decode("utf-8", errors="replace") or "") + (
        "\n" + stderr.decode("utf-8", errors="replace") if stderr else ""
    )


def stream_raw(
    args: list[str],
    *,
    frame_size: int,
    cancel: threading.Event | None,
    threads: int,
    timeout_s: float,
) -> Iterator[bytes]:
    """Grey raw frames from the child's stdout, one `frame_size` read at a time."""
    process = subprocess.Popen(
        _args("ffmpeg", args, threads),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None or process.stderr is None:
        raise FfmpegError("ffmpeg did not open its output streams")
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise FfmpegError("the ffmpeg job was cancelled")
            raw = process.stdout.read(frame_size)
            if not raw:
                break
            if len(raw) != frame_size:
                raise FfmpegError("ffmpeg returned an incomplete frame")
            yield raw
        code = _wait(process, cancel, timeout_s)
        stderr = process.stderr.read()
    finally:
        process.stdout.close()
        process.stderr.close()
    if code != 0:
        raise FfmpegError(f"ffmpeg failed: {trimmed(stderr)}")


def video_duration(
    video_path: str, *, cancel: threading.Event | None, threads: int, timeout_s: float
) -> float:
    text = capture(
        "ffprobe",
        [
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
        ],
        cancel=cancel,
        threads=threads,
        timeout_s=timeout_s,
    ).strip()
    if not text or text == "N/A":
        text = capture(
            "ffprobe",
            [
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            cancel=cancel,
            threads=threads,
            timeout_s=timeout_s,
        ).strip()
    try:
        return float(text.splitlines()[0])
    except (ValueError, IndexError):
        raise FfmpegError("ffprobe could not read the video duration") from None


def video_dimensions(
    video_path: str, *, cancel: threading.Event | None, threads: int, timeout_s: float
) -> tuple[int, int]:
    text = (
        capture(
            "ffprobe",
            [
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0",
                video_path,
            ],
            cancel=cancel,
            threads=threads,
            timeout_s=timeout_s,
        )
        .strip()
        .splitlines()[0]
    )
    parts = text.split(",")
    try:
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        raise FfmpegError("ffprobe could not read the frame size") from None


def scene_cuts(
    video_path: str,
    threshold: float,
    *,
    cancel: threading.Event | None,
    threads: int,
    timeout_s: float,
) -> list[float]:
    """Shot boundaries from ffmpeg's own scene score; parsed from stderr's showinfo lines."""
    text = capture(
        "ffmpeg",
        [
            "-i",
            video_path,
            "-vf",
            f"select='gt(scene,{threshold})',showinfo",
            "-f",
            "null",
            "-",
        ],
        cancel=cancel,
        threads=threads,
        timeout_s=timeout_s,
    )
    return [float(match) for match in PTS_TIME_RE.findall(text)]
