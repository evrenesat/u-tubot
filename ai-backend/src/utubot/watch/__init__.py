"""The picture-aware (Watched) director's cut.

The grid extractor, frame selector, bounded scene memory and TDT validator are adapted from the
owner's public `evrenesat/r2t4` project (`scene-analyser/`, commit 29075554). They are used here
under MIT with the owner's permission; see `LICENSE` and `THIRD_PARTY.md`.
"""

from __future__ import annotations

import importlib.util
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config

NOT_INSTALLED = "Watched cuts are not installed on this server (the `watched` extra is missing)."


def watched_deps_installed() -> bool:
    """Pillow and ffmpeg without importing the watch modules (they import Pillow at top)."""
    return importlib.util.find_spec("PIL") is not None and shutil.which("ffmpeg") is not None


def watched_available(cfg: Config) -> tuple[bool, str | None]:
    """Whether Watched may run here, without importing unavailable modules."""
    if not watched_deps_installed():
        return False, NOT_INSTALLED
    from .service import watched_available as service_available

    return service_available(cfg)


def watched_not_configured(cfg: Config) -> str | None:
    ok, reason = watched_available(cfg)
    return None if ok else reason
