"""Optional vocal/music separation ahead of speech to text.

Music under speech makes ASR worse. When `[captions] separation` is not "off", the pipeline runs
`separation_cmd` (demucs by default, two stems) over the 16 kHz WAV and keeps the vocals stem; a
video without music loses almost nothing (the vocals stem of a speech-only mix is the mix), so
there is no music detector in the lean pipeline. The stage is best-effort: when the tool is not
installed, fails or takes too long, the job carries on with the original audio and says so in its
log.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Protocol

from ..config import CaptionsConfig

log = logging.getLogger("utubot.separate")
VOCALS_NAME = "vocals.wav"


class Separator(Protocol):
    async def separate(self, wav: Path, work: Path) -> Path | None: ...


class DemucsSeparator:
    """`separation_cmd` over one WAV; returns the vocals stem, or None when it did not work."""

    def __init__(self, cmd: list[str], timeout_s: float):
        self.cmd = cmd
        self.timeout_s = timeout_s

    async def separate(self, wav: Path, work: Path) -> Path | None:
        out_dir = work / "separated"
        proc = await asyncio.create_subprocess_exec(
            *self.cmd,
            "-o",
            str(out_dir),
            str(wav),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            log.warning("vocal separation timed out after %.0f s", self.timeout_s)
            return None
        if proc.returncode != 0:
            log.warning("vocal separation failed: %s", err.decode(errors="replace")[:200])
            return None
        found = sorted(out_dir.rglob(VOCALS_NAME))
        return found[0] if found else None


def make_separator(cfg: CaptionsConfig) -> DemucsSeparator | None:
    """The configured separator, or None when separation is off or its tool is not installed."""
    if cfg.separation != "demucs":
        return None
    if not cfg.separation_cmd or shutil.which(cfg.separation_cmd[0]) is None:
        return None
    return DemucsSeparator(cfg.separation_cmd, cfg.separation_timeout_s)
