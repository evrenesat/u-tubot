"""The settings schema (`ai/settings/schema.json`): the one place that names a setting.

Loaded from the wheel (`utubot/settings_schema.json`) or, in a checkout, from `ai/settings/`. Clients, the web
page and the device channel render and validate from it; nothing else lists settings by hand.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

PACKAGED = Path(__file__).with_name("settings_schema.json")
CHECKOUT = Path(__file__).resolve().parents[3] / "ai" / "settings" / "schema.json"
TYPES = ("bool", "int", "float", "enum", "string", "list", "model", "prompt", "secret")
SCOPES = ("user", "device")
REMOTES = ("rw", "ro", "none")
MAX_TITLE_CHARS = 60
MAX_DESCRIPTION_CHARS = 160
MAX_STRING_CHARS = 200
SYNCED_PHASE = 2
TV_CLIENT = "tv"


class SchemaError(ValueError):
    pass


class InvalidValue(ValueError):
    pass


def load(path: Path | None = None) -> dict[str, Any]:
    source = path or (PACKAGED if PACKAGED.exists() else CHECKOUT)
    schema = json.loads(source.read_text(encoding="utf-8"))
    validate(schema)
    return schema


@lru_cache(maxsize=1)
def default_schema() -> Schema:
    return Schema(load())


def _in_range(setting: dict[str, Any], value: Any) -> bool:
    low, high = setting.get("min"), setting.get("max")
    return (low is None or value >= low) and (high is None or value <= high)


def check_value(setting: dict[str, Any], value: Any) -> Any:
    """Return the value in its stored form, or raise `InvalidValue`."""
    kind = setting["type"]
    if kind == "bool":
        if not isinstance(value, bool):
            raise InvalidValue("must be true or false")
        return value
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise InvalidValue("must be a number")
        if kind == "int":
            if isinstance(value, float) and not value.is_integer():
                raise InvalidValue("must be a whole number")
            value = int(value)
        if not _in_range(setting, value):
            raise InvalidValue(f"must be between {setting.get('min')} and {setting.get('max')}")
        return value
    if kind == "enum":
        if value not in {c["value"] for c in setting["choices"]}:
            raise InvalidValue("not one of the choices")
        return value
    if kind in ("string", "model", "prompt"):
        if not isinstance(value, str):
            raise InvalidValue("must be text")
        if len(value) > setting.get("max_len", MAX_STRING_CHARS):
            raise InvalidValue("too long")
        return value
    if kind == "list":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise InvalidValue("must be a list of text")
        if len(value) > setting["max_items"] or any(len(v) > setting["max_len"] for v in value):
            raise InvalidValue("list too long")
        return value
    raise InvalidValue("this setting cannot be changed here")


def validate(schema: dict[str, Any]) -> None:
    if not isinstance(schema.get("schema_version"), int):
        raise SchemaError("schema_version must be an integer")
    groups = {g["id"] for g in schema["groups"]}
    seen: set[str] = set()
    for s in schema["settings"]:
        key = s.get("key", "?")
        if key in seen:
            raise SchemaError(f"duplicate key {key}")
        seen.add(key)
        for field in ("title", "description", "type", "scope", "remote", "store", "group", "since"):
            if s.get(field) in (None, ""):
                raise SchemaError(f"{key}: missing {field}")
        if s["group"] not in groups:
            raise SchemaError(f"{key}: unknown group {s['group']}")
        if len(s["title"]) > MAX_TITLE_CHARS or len(s["description"]) > MAX_DESCRIPTION_CHARS:
            raise SchemaError(f"{key}: title or description too long")
        if s["type"] not in TYPES or s["scope"] not in SCOPES or s["remote"] not in REMOTES:
            raise SchemaError(f"{key}: bad type, scope or remote")
        if s["type"] != "secret" and s["type"] not in ("model",):
            try:
                check_value(s, s.get("default"))
            except InvalidValue as exc:
                raise SchemaError(f"{key}: default {exc}") from exc
        if s["type"] == "model" and s.get("default") != "":
            raise SchemaError(f"{key}: a model default is empty")
        if s.get("device_override") and s["scope"] == "device" and s["store"].startswith("policy"):
            raise SchemaError(f"{key}: a device setting has no user store")


class Schema:
    def __init__(self, doc: dict[str, Any]):
        self.doc = doc
        self.version: int = doc["schema_version"]
        self.by_key: dict[str, dict[str, Any]] = {s["key"]: s for s in doc["settings"]}

    def policy_keys(self) -> dict[str, str]:
        """Schema key -> `UserPolicy` field for every key stored in `policy_overrides`."""
        return {
            k: s["store"].split(":", 1)[1]
            for k, s in self.by_key.items()
            if s["store"].startswith("policy:")
        }

    def synced(self, schema_version: int | None = None) -> list[dict[str, Any]]:
        """The keys a TV may read and write through the device channel."""
        limit = self.version if schema_version is None else min(schema_version, self.version)
        return [
            s
            for s in self.doc["settings"]
            if TV_CLIENT in s.get("clients", ())
            and s.get("phase", 1) <= SYNCED_PHASE
            and s["since"] <= limit
            and s["remote"] == "rw"
        ]

    def public(self) -> dict[str, Any]:
        return self.doc
