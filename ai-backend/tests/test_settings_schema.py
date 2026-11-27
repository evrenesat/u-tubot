"""T1: the settings schema is valid and covers every settable field once."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from utubot import settingsschema as ss
from utubot.config import UserPolicy
from utubot.settings import FIELD_SECTION, PROMPT_KEYS, SECTION_FIELDS

TV_SETTINGS = (
    Path(__file__).resolve().parents[2]
    / "common/src/main/java/com/liskovsoft/smartyoutubetv2/common/utubot/UtubotSettings.java"
)
# never synced: the TV's identity, the connection, local state and developer tools (plan section 2.4)
DEVICE_ONLY = {
    "url",
    "token",
    "update_url",
    "pair_prompt_done",
    "setup_prompt_done",
    "dismissed_update",
    "dismissed_update_code",
    "cut_legend_shown",
    "pending_prompt_sets",
    "films_developer",
    "films_skips",
    "films_imdb_id",
    "films_catalog_url",
}


@pytest.fixture(scope="module")
def schema() -> ss.Schema:
    return ss.default_schema()


def test_the_file_validates_and_has_unique_keys(schema):
    ss.validate(schema.doc)
    assert len(schema.by_key) == len(schema.doc["settings"])


def test_every_policy_field_maps_to_exactly_one_key_and_back(schema):
    mapped = schema.policy_keys()
    fields = [f"{s}.{f}" for s, fs in SECTION_FIELDS.items() for f in fs]
    assert sorted(mapped.values()) == sorted({f for fs in SECTION_FIELDS.values() for f in fs})
    assert len(set(mapped.values())) == len(mapped)
    assert len(fields) == len(mapped)
    for field in mapped.values():
        assert field in FIELD_SECTION and field in UserPolicy.model_fields


def test_prompts_and_models_are_covered(schema):
    stores = {s["store"] for s in schema.doc["settings"]}
    assert {f"prompts:{k}" for k in PROMPT_KEYS} <= stores
    assert {f"models:{t}" for t in ("glance", "summary", "answer", "triage", "analysis")} <= stores


def test_policy_defaults_equal_the_schema_defaults(schema):
    policy = UserPolicy()
    for key, field in schema.policy_keys().items():
        default = getattr(policy, field)
        if default is not None:  # None follows a server setting
            assert default == schema.by_key[key]["default"], key


def test_titles_and_descriptions_are_short_and_present(schema):
    for s in schema.doc["settings"]:
        assert 0 < len(s["title"]) <= ss.MAX_TITLE_CHARS
        assert 0 < len(s["description"]) <= ss.MAX_DESCRIPTION_CHARS


MVP_PREFS = [
    "assess",
    "mark_only",
    "answer_in_menu",
    "summary_panel",
    "panel_delay_ms",
    "auto_captions",
    "auto_cuts",
    "wait_ms",
]


def test_a_schema_one_client_still_gets_the_eight_ai_switches(schema):
    assert [s["tv_pref"] for s in schema.synced(1)] == MVP_PREFS


def test_a_schema_two_client_also_gets_the_per_tv_keys(schema):
    assert [s["tv_pref"] for s in schema.synced()] == [
        *MVP_PREFS,
        "update_checks",
        "auto_scroll_speed",
        "cut_jump",
        "update_interval_minutes",
        "development_mode",
        "browse_refresh_minutes",
    ]


def test_every_key_brought_by_a_version_says_so(schema):
    for s in schema.doc["settings"]:
        assert 1 <= s["since"] <= schema.version, s["key"]
    assert {s["key"] for s in schema.doc["settings"] if s["since"] == 2} == {
        "updates.checks",
        "ai.auto_scroll_speed",
        "ai.cut_jump",
        "updates.interval_minutes",
        "updates.development_mode",
        "browse.refresh_minutes",
    }


def test_a_validator_rejects_a_broken_schema(schema):
    broken = json.loads(json.dumps(schema.doc))
    broken["settings"][0]["default"] = "yes"
    with pytest.raises(ss.SchemaError):
        ss.validate(broken)
    broken = json.loads(json.dumps(schema.doc))
    broken["settings"][1]["title"] = "x" * 61
    with pytest.raises(ss.SchemaError):
        ss.validate(broken)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("ai.panel_delay_ms", -1),
        ("ai.panel_delay_ms", 10001),
        ("ai.assess", "yes"),
        ("ai.wait_ms", 1.5),
    ],
)
def test_invalid_values_are_refused(schema, key, value):
    with pytest.raises(ss.InvalidValue):
        ss.check_value(schema.by_key[key], value)


def test_any_value_in_range_is_accepted_for_the_delay(schema):
    assert ss.check_value(schema.by_key["ai.panel_delay_ms"], 700) == 700


def test_every_tv_preference_is_classified(schema):
    """A new `KEY_*` in UtubotSettings must be in the schema (`tv_pref`) or in the device-only list."""
    source = TV_SETTINGS.read_text(encoding="utf-8")
    keys = set(re.findall(r'private static final String KEY_\w+ = "([a-z_]+)";', source))
    assert keys, "no KEY_ constants found"
    prefs = {s["tv_pref"] for s in schema.doc["settings"] if s.get("tv_pref")}
    assert keys - prefs - DEVICE_ONLY == set()
    assert prefs - keys == set(), "a schema tv_pref the app does not have"
    assert prefs & DEVICE_ONLY == set()
