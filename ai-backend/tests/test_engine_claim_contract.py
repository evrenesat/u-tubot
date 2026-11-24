"""The frozen engine claim contract stays in step with the cut-modes plan (P0)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "ai" / "ENGINE_CLAIM_CONTRACT.md"
PLAN = ROOT / "ai" / "CUT_MODES_PLAN.md"

CONFIG_KEYS = (
    "url",
    "token_env",
    "engine",
    "ttl_s",
    "renew_every_s",
    "renew_retry_s",
    "claim_wait_max_s",
    "release_idle_s",
    "claim_retry_max",
)
STATES = ("draining", "active", "released", "expired", "failed")
ASK_REASONS = (
    "held",
    "other_mode",
    "engine_down",
    "actuator_failed",
    "runs_busy",
    "drain_timeout",
    "max_reached",
    "cooldown",
    "budget",
)


def _text(path):
    return path.read_text(encoding="utf-8")


def test_the_plan_links_to_the_frozen_contract_and_back():
    assert "ENGINE_CLAIM_CONTRACT.md" in _text(PLAN)
    assert "ai/CUT_MODES_PLAN.md" in _text(CONTRACT)


def test_contract_names_every_config_key():
    text = _text(CONTRACT)
    for key in CONFIG_KEYS:
        assert f"`{key}`" in text, key


def test_contract_names_the_endpoints_states_and_reasons():
    text = _text(CONTRACT)
    for endpoint in (
        "POST <url>",
        "POST <url>/<id>/renew",
        "DELETE <url>/<id>",
        "GET <url>?engine=<name>&client_ref=<ref>",
        "GET <url>/<id>",
    ):
        assert endpoint in text, endpoint
    for field in ("client_ref", "expires_at", "max_expires_at", "ready_by", "waiting_for", "link"):
        assert field in text, field
    for state in STATES:
        assert f"`{state}`" in text, state
    for reason in ASK_REASONS:
        assert f"`{reason}`" in text, reason


def test_every_reason_has_a_sentence_and_matches_the_plan():
    text = _text(CONTRACT)
    section = text.split("## `409` and failed-claim reasons", 1)[1].split("## D-P11", 1)[0]
    rows = {
        match.group(1): match.group(0)
        for match in re.finditer(r"^\| `([a-z_]+)` \|.*$", section, re.MULTILINE)
    }
    assert set(rows) == set(ASK_REASONS)
    for reason, row in rows.items():
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        assert len(cells) >= 3 and cells[-1], reason
    assert "The engine is in use by the owner right now." in rows["held"]
    assert "Other work on the engine did not finish in time." in rows["runs_busy"]

    plan_section = _text(PLAN).split("### P.3.3", 1)[1].split("### P.3.4", 1)[0]
    for reason in ASK_REASONS:
        assert f"`{reason}`" in plan_section, reason


def test_contract_records_the_take_it_at_once_decision():
    assert "D-P11" in _text(CONTRACT)
    assert "switched to the cloud replacement in mid-conversation" in _text(CONTRACT)
    assert "Nothing running there is stopped, paused or switched to another model" not in _text(
        PLAN
    )
