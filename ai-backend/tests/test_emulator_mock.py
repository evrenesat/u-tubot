"""The emulator mock backend's cut modes, read from the one stdlib script it serves them from."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "emulator_mock_backend.py"


def load_mock():
    spec = importlib.util.spec_from_file_location("emulator_mock_backend", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_mock_lists_quick_and_watched_modes():
    mock = load_mock()

    assert [mode["id"] for mode in mock.CUT_MODES] == ["quick", "watched"]


def test_a_watched_cut_document_carries_its_shape():
    mock = load_mock()

    doc = mock.cut_document(240_000, "abcdefghijk", mode="watched")

    assert doc["mode"] == "watched"
    assert doc["watched"]["grids"] > 0
    assert doc["kept_ms"] < doc["duration_ms"]


def test_a_mock_preset_state_is_per_mode():
    mock = load_mock()

    mock.CUT_READY["abcdefghijk"] = {
        "mode": "watched",
        "preset_id": "cut-no-filler",
        "failed": False,
    }

    assert mock.preset_state("abcdefghijk", "cut-no-filler", "watched") == "ready"
    assert mock.preset_state("abcdefghijk", "cut-no-filler", "quick") == "none"
