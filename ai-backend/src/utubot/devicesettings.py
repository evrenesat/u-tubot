"""Web settings: per-key revisions, per-TV overrides, the audit and the device channel.

See `ai/WEB_SETTINGS_PLAN.md` and `ai/CONTRACT.md` ("Web settings"). Values keep their one store: policy keys in
`policy_overrides` (through `UserPolicy`), the rest of the user's schema keys in `settings_values` (device `''`),
a TV's own values in `settings_values` under its device id. The user's version (`policy_overrides.version`) is the
single counter; every key change records `settings_rev` (the version it changed at) and one `settings_audit` row.
Conflicts are decided by arrival order and revisions, never by a device clock.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .auth import Forbidden
from .config import Config, UserConfig
from .db import Database
from .settings import SettingsError, SettingsService, configured_models, resolved_fields
from .settingsschema import SYNCED_PHASE, InvalidValue, Schema, check_value

USER_DEVICE = ""
APPLIED, SUPERSEDED, INVALID, NOT_REMOTE = "applied", "superseded", "invalid", "not_remote"
VIA_WEB, VIA_TV, VIA_ADMIN, VIA_MIGRATION = "web", "tv", "admin", "migration"
SECONDS_PER_DAY = 86400
LONG_POLL_STEP_S = 0.2
MAX_REPORT_ENTRIES = 20
MAX_REPORT_KEY_CHARS = 40
MAX_REPORT_VALUE_CHARS = 100


def clean_report(report: dict) -> dict[str, Any]:
    """A bounded summary of what a TV reports: a few short scalar entries, always valid JSON."""
    out: dict[str, Any] = {}
    for key, value in report.items():
        if len(out) >= MAX_REPORT_ENTRIES:
            break
        scalar = isinstance(value, bool | int | float) or (
            isinstance(value, str) and len(value) <= MAX_REPORT_VALUE_CHARS
        )
        if isinstance(key, str) and len(key) <= MAX_REPORT_KEY_CHARS and scalar:
            out[key] = value
    return out


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


class DeviceSettings:
    def __init__(self, cfg: Config, db: Database, auth, settings: SettingsService, schema: Schema):
        self.cfg, self.db, self.auth, self.settings, self.schema = cfg, db, auth, settings, schema
        self.opts = cfg.settings_sync
        settings.sync = self

    # ---- layers -------------------------------------------------------------------------

    def _rows(self, table: str, name: str, device_id: str) -> dict[str, Any]:
        rows = self.db.all(f"SELECT * FROM {table} WHERE user=? AND device_id=?", [name, device_id])
        return {r["key"]: r for r in rows}

    def rev_of(self, name: str, device_id: str, key: str) -> int:
        row = self.db.one(
            "SELECT rev FROM settings_rev WHERE user=? AND device_id=? AND key=?",
            [name, device_id, key],
        )
        return int(row["rev"]) if row else 0

    def user_layer(self, name: str) -> dict[str, dict[str, Any]]:
        """`{key: {"v", "rev", "from"}}` for every synced key at the user level."""
        user = self.auth.user_config(name)
        if user is None:
            raise SettingsError(404, "unknown user")
        fields = resolved_fields(self.cfg, user.policy)
        override = self.auth.policy_override(name)
        stored = self._rows("settings_values", name, USER_DEVICE)
        revs = self._rows("settings_rev", name, USER_DEVICE)
        models = configured_models(self.cfg)
        out: dict[str, dict[str, Any]] = {}
        for key, s in self.schema.by_key.items():
            if s.get("phase", 1) > SYNCED_PHASE or s["remote"] == "none":
                continue
            store = s["store"]
            if store.startswith("policy:"):
                field = store.split(":", 1)[1]
                value, src = fields[field], "user" if field in override else "default"
            elif store == "values":
                if key in stored:
                    value, src = json.loads(stored[key]["json"]), "user"
                else:
                    value, src = self._values_default(s), "default"
            elif store.startswith("prompts:"):
                which = store.split(":", 1)[1]
                value = (
                    self.settings.prompts.default_key(name)
                    if which == "default"
                    else self.settings.prompts.panel_key(name)
                )
                src = "user" if self.settings.prompts.has_override(name).get(which) else "default"
            elif store.startswith("models:"):
                task = store.split(":", 1)[1]
                value = user.policy.models.get(task) or models[task]
                src = "user" if task in override.get("models", {}) else "default"
            else:
                continue
            rev = int(revs[key]["rev"]) if key in revs else 0
            out[key] = {"v": value, "rev": rev, "from": src}
        return out

    def document_values(self, name: str) -> dict[str, dict[str, Any]]:
        """The user's own level as the settings document shows it: no setting that belongs to one TV."""
        return {
            k: v
            for k, v in self.user_layer(name).items()
            if self.schema.by_key[k]["scope"] != "device"
        }

    def _values_default(self, s: dict[str, Any]) -> Any:
        name = s.get("setup_default")
        return getattr(self.cfg.setup.defaults, name) if name else s["default"]

    def resolve(
        self, name: str, device_id: str, schema_version: int | None = None
    ) -> dict[str, dict[str, Any]]:
        """What this TV uses for every key it may see: its own value, else the user's."""
        layer = self.user_layer(name)
        own = self._rows("settings_values", name, device_id)
        own_rev = self._rows("settings_rev", name, device_id)
        out: dict[str, dict[str, Any]] = {}
        for s in self.schema.synced(schema_version):
            key = s["key"]
            tomb = int(own_rev[key]["rev"]) if key in own_rev else 0
            if key in own:
                # its own value: the user's later changes do not touch this TV
                value = json.loads(own[key]["json"])
                out[key] = {"v": value, "rev": tomb or int(own[key]["rev"]), "from": "device"}
            else:
                out[key] = {**layer[key], "rev": max(layer[key]["rev"], tomb)}
        return out

    # ---- audit and revisions ------------------------------------------------------------

    def _set_rev(self, name: str, device_id: str, key: str, rev: int) -> None:
        self.db.execute(
            "INSERT INTO settings_rev(user,device_id,key,rev) VALUES(?,?,?,?)"
            " ON CONFLICT(user,device_id,key) DO UPDATE SET rev=excluded.rev",
            [name, device_id, key, rev],
        )

    def _audit(
        self,
        name: str,
        device_id: str,
        key: str,
        old: Any,
        new: Any,
        *,
        by: str | None,
        via: str,
        actor: str | None = None,
        outcome: str = APPLIED,
    ) -> None:
        now = time.time()
        self.db.execute(
            "INSERT INTO settings_audit(user,device_id,key,old_json,new_json,by_user,via,"
            "actor_device_id,at,outcome) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [name, device_id, key, _dumps(old), _dumps(new), by, via, actor, now, outcome],
        )
        self.db.execute(
            "DELETE FROM settings_audit WHERE user=? AND at<?",
            [name, now - self.opts.audit_days * SECONDS_PER_DAY],
        )
        self.db.execute(
            "DELETE FROM settings_audit WHERE user=? AND id NOT IN"
            " (SELECT id FROM settings_audit WHERE user=? ORDER BY id DESC LIMIT ?)",
            [name, name, self.opts.audit_max_rows_per_user],
        )

    def _bump(self, name: str) -> int:
        self.auth.touch_settings(name)
        return self.auth.settings_version(name)[0]

    # ---- the user level (called by the document PUT) ------------------------------------

    def split_document_keys(self, body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Take the dotted schema keys out of a PUT body: returns (body without them, `values` keys)."""
        settings = body.get("settings")
        if not isinstance(settings, dict):
            return body, {}
        dotted = {k: v for k, v in settings.items() if "." in k and not isinstance(v, dict)}
        if not dotted:
            return body, {}
        rest = {k: v for k, v in settings.items() if k not in dotted}
        policy_map = self.schema.policy_keys()
        values: dict[str, Any] = {}
        for key, value in dotted.items():
            s = self.schema.by_key.get(key)
            if s is None or s["remote"] != "rw" or s.get("phase", 1) > SYNCED_PHASE:
                raise SettingsError(400, f"unknown setting {key}")
            if s["scope"] == "device":
                raise SettingsError(400, f"{key} belongs to one TV; change it on that TV's tab")
            if s["store"] == "values":
                values[key] = self._checked(key, s, value)
            elif key in policy_map:
                field = policy_map[key]
                from .settings import FIELD_SECTION

                rest.setdefault(FIELD_SECTION[field], {})[field] = value
            elif s["store"].startswith("prompts:"):
                rest.setdefault("prompts", {})[s["store"].split(":", 1)[1]] = value
            elif s["store"].startswith("models:"):
                rest.setdefault("models", {})[s["store"].split(":", 1)[1]] = value
            else:
                raise SettingsError(400, f"unknown setting {key}")
        return {**body, "settings": rest}, values

    def _checked(self, key: str, s: dict[str, Any], value: Any) -> Any:
        if value is None:
            return None
        try:
            return check_value(s, value)
        except InvalidValue as exc:
            raise SettingsError(400, f"invalid setting {key}: {exc}") from exc

    def write_user_values(self, name: str, values: dict[str, Any], version: int) -> None:
        for key, value in values.items():
            if value is None:
                self.db.execute(
                    "DELETE FROM settings_values WHERE user=? AND device_id=? AND key=?",
                    [name, USER_DEVICE, key],
                )
            else:
                self._store_value(name, USER_DEVICE, key, value, version)

    def _store_value(self, name: str, device_id: str, key: str, value: Any, rev: int) -> None:
        self.db.execute(
            "INSERT INTO settings_values(user,device_id,key,json,rev,changed_at) VALUES(?,?,?,?,?,?)"
            " ON CONFLICT(user,device_id,key) DO UPDATE SET json=excluded.json, rev=excluded.rev,"
            " changed_at=excluded.changed_at",
            [name, device_id, key, _dumps(value), rev, time.time()],
        )

    def record_document_change(
        self,
        name: str,
        before: dict[str, dict[str, Any]],
        version: int,
        *,
        via: str,
        by: str | None,
    ) -> None:
        after = self.user_layer(name)
        for key, entry in after.items():
            old = before.get(key, {}).get("v")
            if old != entry["v"]:
                self._set_rev(name, USER_DEVICE, key, version)
                self._audit(name, USER_DEVICE, key, old, entry["v"], by=by, via=via)

    # ---- the device channel -------------------------------------------------------------

    def _state(self, device_id: str) -> Any:
        return self.db.one("SELECT * FROM device_settings_state WHERE device_id=?", [device_id])

    def _touch_state(
        self,
        name: str,
        device_id: str,
        *,
        applied_version: int | None = None,
        schema_version: int | None = None,
        app_version: str | None = None,
        report: dict | None = None,
        migrated: bool = False,
    ) -> None:
        now = time.time()
        self.db.execute(
            "INSERT OR IGNORE INTO device_settings_state(device_id,user) VALUES(?,?)",
            [device_id, name],
        )
        sets, params = ["last_sync_at=?"], [now]
        if applied_version is not None:
            sets += ["applied_version=?", "applied_at=?"]
            params += [applied_version, now]
        if schema_version is not None:
            sets.append("schema_version=?")
            params.append(schema_version)
        if app_version is not None:
            sets.append("app_version=?")
            params.append(app_version[:64])
        if report is not None:
            sets.append("report_json=?")
            params.append(_dumps(clean_report(report)))
        if migrated:
            sets.append("migrated_at=?")
            params.append(now)
        self.db.execute(
            f"UPDATE device_settings_state SET {', '.join(sets)} WHERE device_id=?",
            [*params, device_id],
        )

    def document_for(self, name: str, device_id: str, schema_version: int | None) -> dict[str, Any]:
        version = self.auth.settings_version(name)[0]
        return {
            "version": version,
            "schema_version": self.schema.version,
            "settings": self.resolve(name, device_id, schema_version),
        }

    def pull(self, name: str, device_id: str, have: int | None, schema_version: int | None):
        """One answer: the document, or `unchanged` when `have` is the current version."""
        version = self.auth.settings_version(name)[0]
        state = self._state(device_id)
        applied = None
        if have is not None and 0 <= have <= version:
            if state is None or have != state["applied_version"]:
                applied = have
        self._touch_state(name, device_id, applied_version=applied, schema_version=schema_version)
        if have is not None and have == version:
            return {"version": version, "unchanged": True}
        return self.document_for(name, device_id, schema_version)

    def push(self, name: str, device_id: str, body: dict[str, Any]) -> dict[str, Any]:
        changes = body.get("changes") or []
        if not isinstance(changes, list) or len(changes) > self.opts.max_changes_per_post:
            raise SettingsError(400, "too many changes")
        schema_version = body.get("schema_version")
        if not isinstance(schema_version, int):
            schema_version = None
        state = self._state(device_id)
        from_schema = body.get("from_schema")
        upgrade = (
            isinstance(from_schema, int)
            and not isinstance(from_schema, bool)
            and schema_version is not None
            and from_schema < schema_version
        )
        first = bool(body.get("initial")) and (
            state is None or state["migrated_at"] is None or upgrade
        )
        # a TV that was in step before an app update sends the keys that update brought with
        # `from_schema`: only those keys take its own values, the rest is a normal sync
        newer_than = from_schema if upgrade and state is not None and state["migrated_at"] else None
        results: list[dict[str, Any]] = []
        keys = {s["key"]: s for s in self.schema.synced(schema_version)}
        for change in changes:
            if not isinstance(change, dict):
                results.append({"key": None, "outcome": INVALID})
                continue
            key = change.get("key")
            outcome = self._apply_change(name, device_id, keys, change, first, newer_than)
            results.append({"key": key, "outcome": outcome})
        applied = body.get("applied_version")
        version = self.auth.settings_version(name)[0]
        report = body.get("report") if isinstance(body.get("report"), dict) else None
        app_version = body.get("app_version")
        self._touch_state(
            name,
            device_id,
            applied_version=applied
            if isinstance(applied, int) and 0 <= applied <= version
            else None,
            schema_version=schema_version,
            app_version=app_version if isinstance(app_version, str) else None,
            report=report,
            migrated=first,
        )
        doc = self.document_for(name, device_id, schema_version)
        doc["results"] = results
        return doc

    def _apply_change(
        self,
        name: str,
        device_id: str,
        keys: dict[str, Any],
        change: dict[str, Any],
        first: bool,
        newer_than: int | None = None,
    ) -> str:
        key = change.get("key")
        s = keys.get(key) if isinstance(key, str) else None
        if s is None or not s.get("device_override"):
            return NOT_REMOTE
        try:
            value = check_value(s, change.get("value"))
        except InvalidValue:
            return INVALID
        current = self.resolve(name, device_id)[key]
        base = change.get("base_rev")
        # First sync: a value the user set on the TV is the TV's real behaviour and wins; an untouched
        # default is base-checked like any change, so it never replaces a newer web value.
        trusted = (
            first
            and change.get("user_set") is True
            and (newer_than is None or s["since"] > newer_than)
        )
        if not trusted and (not isinstance(base, int) or base != current["rev"]):
            if value != current["v"]:
                self._audit(
                    name,
                    device_id,
                    key,
                    current["v"],
                    value,
                    by=name,
                    via=VIA_TV,
                    actor=device_id,
                    outcome=SUPERSEDED,
                )
            return SUPERSEDED
        if value == current["v"]:
            return APPLIED
        version = self._bump(name)
        self._store_value(name, device_id, key, value, version)
        self._set_rev(name, device_id, key, version)
        self._audit(
            name,
            device_id,
            key,
            current["v"],
            value,
            by=name,
            via=VIA_MIGRATION if first else VIA_TV,
            actor=device_id,
        )
        return APPLIED

    # ---- the web side -------------------------------------------------------------------

    def owned_device(self, user: UserConfig, device_id: str) -> dict[str, Any]:
        row = self.db.one(
            "SELECT id,device,created_at,last_used FROM device_tokens WHERE id=? AND user=?",
            [device_id, user.name],
        )
        if row is None:
            raise SettingsError(404, "unknown device")
        return dict(row)

    def device_view(self, user: UserConfig, device_id: str) -> dict[str, Any]:
        device = self.owned_device(user, device_id)
        state = self._state(device_id)
        doc = self.document_for(user.name, device_id, self._device_schema(state))
        doc["device"] = {"id": device_id, "name": device["device"], **self._state_view(state)}
        return doc

    @staticmethod
    def _device_schema(state: Any) -> int | None:
        """The schema version a TV last reported (`None` for one that never synced: it may get any key)."""
        return (
            int(state["schema_version"]) if state is not None and state["schema_version"] else None
        )

    def _state_view(self, state: Any) -> dict[str, Any]:
        if state is None:
            return {"syncs": False}
        report = json.loads(state["report_json"]) if state["report_json"] else {}
        return {
            "syncs": state["last_sync_at"] is not None,
            "applied_version": state["applied_version"],
            "applied_at": state["applied_at"],
            "last_sync_at": state["last_sync_at"],
            "schema_version": state["schema_version"],
            "app_version": state["app_version"],
            "migrated": state["migrated_at"] is not None,
            "report": report,
        }

    def status(self, user: UserConfig) -> dict[str, Any]:
        version = self.auth.settings_version(user.name)[0]
        devices = []
        for device in self.auth.list_devices(user.name):
            state = self._state(device["id"])
            view = self._state_view(state)
            overrides = sorted(self._rows("settings_values", user.name, device["id"]))
            pending: list[str] = []
            if state is not None and view["syncs"]:
                resolved = self.resolve(user.name, device["id"], self._device_schema(state))
                for key, entry in resolved.items():
                    if entry["rev"] > int(state["applied_version"] or 0):
                        pending.append(key)
            devices.append(
                {
                    "id": device["id"],
                    "device": device["device"],
                    "last_used": device["last_used"],
                    **view,
                    "overrides": [k for k in overrides if k in self.schema.by_key],
                    "pending": sorted(pending),
                }
            )
        return {"version": version, "now": time.time(), "devices": devices}

    def put_device(
        self, user: UserConfig, device_id: str, body: Any, *, via: str
    ) -> dict[str, Any]:
        """The web changes one TV's own values (`null` removes one)."""
        self.owned_device(user, device_id)
        if not isinstance(body, dict) or not isinstance(body.get("settings"), dict):
            raise SettingsError(400, 'body must be {"settings": {...}}')
        name = user.name
        current = self.auth.settings_version(name)[0]
        supplied = body.get("version")
        if supplied is None:
            raise SettingsError(
                428, "send the settings version you loaded with the change", version=current
            )
        if supplied != current:
            raise SettingsError(
                409, "settings changed since you loaded them; reload", version=current
            )
        keys = {
            s["key"]: s for s in self.schema.synced(self._device_schema(self._state(device_id)))
        }
        staged: dict[str, Any] = {}
        for key, value in body["settings"].items():
            s = keys.get(key)
            if s is None or not s.get("device_override"):
                raise SettingsError(400, f"{key} is not a setting this TV can follow")
            staged[key] = self._checked(key, s, value)
        before = self.resolve(name, device_id)
        if staged:
            version = self._bump(name)
            for key, value in staged.items():
                if value is None:
                    self.db.execute(
                        "DELETE FROM settings_values WHERE user=? AND device_id=? AND key=?",
                        [name, device_id, key],
                    )
                    self._set_rev(name, device_id, key, version)
                else:
                    self._store_value(name, device_id, key, value, version)
                    self._set_rev(name, device_id, key, version)
            after = self.resolve(name, device_id)
            for key in staged:
                if before[key]["v"] != after[key]["v"]:
                    self._audit(
                        name,
                        device_id,
                        key,
                        before[key]["v"],
                        after[key]["v"],
                        by=user.name,
                        via=via,
                    )
        return self.device_view(user, device_id)

    def history(
        self, user: UserConfig, *, limit: int, key: str | None, device: str | None
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, self.opts.history_max))
        where, params = ["user=?"], [user.name]
        if key:
            where.append("key=?")
            params.append(key)
        if device:
            where.append("device_id=?")
            params.append(device)
        names = {d["id"]: d["device"] for d in self.auth.list_devices(user.name)}
        rows = self.db.all(
            f"SELECT * FROM settings_audit WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
            [*params, limit],
        )
        out = []
        for r in rows:
            s = self.schema.by_key.get(r["key"], {})
            out.append(
                {
                    "id": r["id"],
                    "at": r["at"],
                    "key": r["key"],
                    "title": s.get("title", r["key"]),
                    "device_id": r["device_id"] or None,
                    "device": names.get(r["device_id"]) if r["device_id"] else None,
                    "old": json.loads(r["old_json"]) if r["old_json"] is not None else None,
                    "new": json.loads(r["new_json"]) if r["new_json"] is not None else None,
                    "by": r["by_user"],
                    "via": r["via"],
                    "actor": names.get(r["actor_device_id"]) if r["actor_device_id"] else None,
                    "outcome": r["outcome"],
                }
            )
        return out

    def forget_device(self, device_id: str) -> None:
        for table in ("settings_values", "settings_rev"):
            self.db.execute(f"DELETE FROM {table} WHERE device_id=?", [device_id])
        self.db.execute("DELETE FROM device_settings_state WHERE device_id=?", [device_id])


SETTINGS_OFF = "web settings are not switched on on this server"
NO_DEVICE = "this route is for a paired TV; a browser session or config token has no device"
NOT_JSON = "body must be JSON"


def install_settings_routes(app: FastAPI, d: Any) -> None:
    svc = d.svc
    ds: DeviceSettings = svc.device_settings
    cfg = svc.cfg
    current_user = d.current_user

    def on() -> None:
        if not cfg.settings_sync.enabled:
            raise HTTPException(404, SETTINGS_OFF)

    def device_of(request: Request) -> str:
        device_id = svc.auth.device_id_of(getattr(request.state, "principal", None))
        if device_id is None:
            raise HTTPException(400, NO_DEVICE)
        return device_id

    def browser_only(request: Request) -> None:
        """A paired TV's token must not read or change its sibling TVs' settings."""
        if svc.auth.device_id_of(getattr(request.state, "principal", None)) is not None:
            raise Forbidden

    @app.get("/v1/settings/schema")
    async def settings_schema(user: UserConfig = Depends(current_user)):
        on()
        resp = JSONResponse(ds.schema.public())
        resp.headers["ETag"] = f'"{ds.schema.version}"'
        return resp

    @app.get("/v1/device/settings")
    async def device_settings_get(
        request: Request,
        have: int | None = Query(None, ge=0),
        schema: int | None = Query(None, ge=0),
        wait_ms: int | None = Query(None, ge=0),
        user: UserConfig = Depends(current_user),
    ):
        on()
        device_id = device_of(request)
        answer = ds.pull(user.name, device_id, have, schema)
        wait_s = min(wait_ms or 0, cfg.settings_sync.long_poll_max_ms) / 1000.0
        if answer.get("unchanged") and wait_s > 0:
            # the long poll: hold the request until the user's version moves, then answer at once
            deadline = time.monotonic() + wait_s
            while time.monotonic() < deadline:
                await asyncio.sleep(min(LONG_POLL_STEP_S, max(0.0, deadline - time.monotonic())))
                if ds.auth.settings_version(user.name)[0] != have:
                    answer = ds.document_for(user.name, device_id, schema)
                    break
                if await request.is_disconnected():
                    break
        resp = JSONResponse(answer)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.post("/v1/device/settings")
    async def device_settings_post(request: Request, user: UserConfig = Depends(current_user)):
        on()
        device_id = device_of(request)
        limit = cfg.settings_sync.max_body_bytes
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > limit:
            raise HTTPException(413, "too many changes")
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > limit:
                raise HTTPException(413, "too many changes")
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise HTTPException(400, NOT_JSON) from None
        if not isinstance(body, dict):
            raise HTTPException(400, NOT_JSON)
        resp = JSONResponse(ds.push(user.name, device_id, body))
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/v1/me/settings/status")
    async def settings_status(request: Request, user: UserConfig = Depends(current_user)):
        on()
        browser_only(request)
        return ds.status(user)

    @app.get("/v1/me/settings/history")
    async def settings_history(
        request: Request,
        limit: int = Query(50, ge=1),
        key: str | None = None,
        device: str | None = None,
        user: UserConfig = Depends(current_user),
    ):
        on()
        browser_only(request)
        return {"entries": ds.history(user, limit=limit, key=key, device=device)}

    @app.get("/v1/me/devices/{device_id}/settings")
    async def device_settings_view(
        device_id: str, request: Request, user: UserConfig = Depends(current_user)
    ):
        on()
        browser_only(request)
        return ds.device_view(user, device_id)

    @app.put("/v1/me/devices/{device_id}/settings")
    async def device_settings_put(
        device_id: str,
        body: dict[str, Any],
        request: Request,
        user: UserConfig = Depends(current_user),
    ):
        on()
        browser_only(request)
        return ds.put_device(user, device_id, body, via=VIA_WEB)
