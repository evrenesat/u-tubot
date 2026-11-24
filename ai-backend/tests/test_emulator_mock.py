"""The emulator mock backend's cut modes (scripts/emulator_mock_backend.py)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "emulator_mock_backend.py"
VID = "abcdefghijk"


@pytest.fixture
def mock():
    spec = importlib.util.spec_from_file_location("emulator_mock_backend", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.CUTS_CONFIG.update(delay=8.0, watched_delay=20.0, watched_available=False)
    module.CUT_REQUESTS.clear()
    module.CUT_READY.clear()
    return module


def test_cut_document_carries_a_structured_source_and_mode(mock):
    doc = mock.cut_document(120_000, VID, mode="watched")
    assert doc["source"] == {"kind": "youtube", "key": f"youtube:{VID}"}
    assert doc["mode"] == "watched"


def test_preset_states_are_per_mode_and_watched_is_unavailable_by_default(mock):
    assert mock.preset_state(VID, "cut-no-filler", "quick") == "none"
    assert mock.preset_state(VID, "cut-no-filler", "watched") == "unavailable"
    mock.CUT_READY[(VID, "watched")] = {"preset_id": "cut-no-filler", "duration_ms": 60_000}
    mock.CUTS_CONFIG["watched_available"] = True
    assert mock.preset_state(VID, "cut-no-filler", "watched") == "ready"
    assert mock.preset_state(VID, "cut-no-filler", "quick") == "none"
    fields = mock.preset_fields(VID, "cut-no-filler", "No filler", "watched")
    assert fields["cut"]["mode"] == "watched" and fields["cut"]["watched"]["partial"] is False


def test_request_documents_carry_the_mode(mock):
    request = {
        "id": "cut1",
        "video_id": VID,
        "state": "building",
        "source": "TV",
        "mode": "watched",
        "preset_id": "cut-no-filler",
        "created_at": "2026-01-01T00:00:00Z",
        "ready_at": None,
    }
    doc = mock.cut_request_doc(request)
    assert doc["mode"] == "watched" and doc["state"] == "building"
