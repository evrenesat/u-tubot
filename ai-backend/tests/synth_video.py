"""A synthetic clip for the watched tests: hard cuts, colour, motion and a still stretch.

Built with ffmpeg only, no download and no model. The four parts are 10 s red (still), 15 s
`testsrc2` (motion), 15 s green (still) and 20 s `testsrc2` (motion): hard cuts at 10, 25 and 40
seconds and a long quiet stretch for the shared-grid rule.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

PARTS = (
    ("color=c=red:s=360x240:r=10:d=10", 10.0),
    ("testsrc2=size=360x240:rate=10:duration=15", 15.0),
    ("color=c=green:s=360x240:r=10:d=15", 15.0),
    ("testsrc2=size=360x240:rate=10:duration=20", 20.0),
)
CUTS = (10.0, 25.0, 40.0)
DURATION_S = 60.0


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def make_video(directory: Path) -> Path:
    """Render the 60 s clip; raises RuntimeError when ffmpeg is missing or fails."""
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg is not installed")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "synth.mp4"
    inputs: list[str] = []
    for source, _seconds in PARTS:
        inputs.extend(["-f", "lavfi", "-i", source])
    graph = (
        "".join(f"[{index}:v]" for index in range(len(PARTS))) + f"concat=n={len(PARTS)}:v=1:a=0[v]"
    )
    command = ["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", graph]
    command.extend(
        ["-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    )
    command.append(str(target))
    subprocess.run(command, check=True, capture_output=True)
    return target
