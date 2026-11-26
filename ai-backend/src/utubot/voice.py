"""Voice control, backend side (ai/VOICE_CONTROL_PLAN.md, sections 2.4 and 2.13; checkpoint 1).

Three small things live here, all additive and all behind ``[voice] enabled``:

* the consent of each paired device (``device_voice``): off until the user switches it on after
  reading what it means, and an all-off switch for every device of the user;
* the user's retention choice (``user_voice``);
* the command history (``voice_commands``): the live server files one record when a command ends
  (text, tool, arguments, outcome, timing marks), the History page reads and deletes them.

No audio is ever stored, here or anywhere. The live server (a later checkpoint) calls these routes
with the token of the device that spoke; it has no privilege of its own.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .config import UserConfig, VoiceConfig
from .db import Database

if TYPE_CHECKING:
    from .webroutes import Deps

CONSENT_VERSION = 1
CONSENT_TEXT = [
    "Voice control listens through this device's microphone only while you hold Talk, or, in robot mode, after the wake word.",
    "The sound goes to this server's own speech engines and is turned into text in memory. No audio is stored, anywhere.",
    "What is kept is the text of each command, what it did and how long it took, for the number of days you choose (0 keeps nothing). You can read and delete it on the History page.",
    "The TV shows a microphone symbol whenever any of your microphones is open. You can switch every device off at once.",
]
LISTEN_PUSH = "push"
LISTEN_WAKE = "wake"
LISTEN_MODES = (LISTEN_PUSH, LISTEN_WAKE)
OUTCOMES = ("ok", "failed", "cancelled", "refused", "clarify", "none")
SECONDS_PER_DAY = 86400
MAX_RETENTION_DAYS = 365
MAX_TOOL_CHARS = 64
MAX_MARKS = 16
MAX_MARK_NAME_CHARS = 32
MAX_MARK_MS = 3_600_000
DEFAULT_HISTORY_LIMIT = 50
VOICE_OFF = "voice is not enabled on this server"


class VoiceError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class DeviceVoicePatch(BaseModel):
    enabled: bool | None = None
    listen_mode: Literal["push", "wake"] | None = None
    speak: bool | None = None
    consent_version: int | None = None


class UserVoicePatch(BaseModel):
    retention_days: int | None = Field(None, ge=0, le=MAX_RETENTION_DAYS)
    all_off: bool | None = None


class CommandRecord(BaseModel):
    text: str = ""
    tool: str = Field("", max_length=MAX_TOOL_CHARS)
    args: dict[str, Any] = Field(default_factory=dict)
    outcome: Literal["ok", "failed", "cancelled", "refused", "clarify", "none"] = "ok"
    marks: dict[str, float] = Field(default_factory=dict)


def _device_row(row: Any) -> dict[str, Any]:
    return {
        "enabled": bool(row["enabled"]),
        "listen_mode": row["listen_mode"],
        "speak": bool(row["speak"]),
        "consented_at": row["consented_at"],
    }


OFF = {"enabled": False, "listen_mode": LISTEN_PUSH, "speak": False, "consented_at": None}


class VoiceService:
    def __init__(self, cfg: VoiceConfig, db: Database, auth: Any):
        self.cfg = cfg
        self.db = db
        self.auth = auth

    # ---- consent --------------------------------------------------------------------------

    def device_state(self, device_id: str | None) -> dict[str, Any]:
        """One device's switches; a device that never chose is off."""
        if not device_id:
            return dict(OFF)
        row = self.db.one("SELECT * FROM device_voice WHERE device_id=?", [device_id])
        return _device_row(row) if row else dict(OFF)

    def set_device(
        self, user: str, device_id: str, patch: DeviceVoicePatch, now: float | None = None
    ) -> dict[str, Any]:
        owned = {d["id"] for d in self.auth.list_devices(user)}
        if device_id not in owned:
            raise VoiceError("unknown device", 404)
        now = time.time() if now is None else now
        current = self.device_state(device_id)
        enabled = current["enabled"] if patch.enabled is None else patch.enabled
        consented_at = current["consented_at"]
        version = None
        if enabled and not current["enabled"]:
            if patch.consent_version != CONSENT_VERSION:
                raise VoiceError(
                    f"consent_version must be {CONSENT_VERSION}: show the consent text first"
                )
            consented_at, version = now, CONSENT_VERSION
        mode = patch.listen_mode or current["listen_mode"]
        speak = current["speak"] if patch.speak is None else patch.speak
        self.db.execute(
            "INSERT INTO device_voice(device_id,user,enabled,listen_mode,speak,consent_version,"
            "consented_at,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(device_id) DO UPDATE SET "
            "enabled=excluded.enabled, listen_mode=excluded.listen_mode, speak=excluded.speak, "
            "consent_version=COALESCE(excluded.consent_version, consent_version), "
            "consented_at=excluded.consented_at, updated_at=excluded.updated_at",
            [device_id, user, int(enabled), mode, int(speak), version, consented_at, now],
        )
        return self.device_state(device_id)

    def all_off(self, user: str, now: float | None = None) -> int:
        """Switch voice off on every device of the user; turning it on again asks for consent again."""
        now = time.time() if now is None else now
        return self.db.execute_rc(
            "UPDATE device_voice SET enabled=0, updated_at=? WHERE user=? AND enabled=1",
            [now, user],
        )

    def retention_days(self, user: str) -> int:
        row = self.db.one("SELECT retention_days FROM user_voice WHERE user=?", [user])
        if row is not None and row["retention_days"] is not None:
            return int(row["retention_days"])
        return self.cfg.retention_days

    def set_retention(self, user: str, days: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        self.db.execute(
            "INSERT INTO user_voice(user,retention_days,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(user) DO UPDATE SET retention_days=excluded.retention_days, "
            "updated_at=excluded.updated_at",
            [user, days, now],
        )
        self.prune(user, now)

    def me(self, user: str, device_id: str | None) -> dict[str, Any]:
        """The `voice` object of GET /v1/me for the calling device."""
        state = self.device_state(device_id)
        return {
            "enabled": state["enabled"],
            "listen_mode": state["listen_mode"],
            "speak": state["speak"],
            "retention_days": self.retention_days(user),
        }

    def overview(self, user: str) -> dict[str, Any]:
        rows = {
            r["device_id"]: r
            for r in self.db.all("SELECT * FROM device_voice WHERE user=?", [user])
        }
        devices = []
        for d in self.auth.list_devices(user):
            state = _device_row(rows[d["id"]]) if d["id"] in rows else dict(OFF)
            devices.append({"id": d["id"], "device": d["device"], **state})
        return {
            "enabled": True,
            "retention_days": self.retention_days(user),
            "default_retention_days": self.cfg.retention_days,
            "consent": {"version": CONSENT_VERSION, "text": CONSENT_TEXT},
            "devices": devices,
        }

    # ---- history --------------------------------------------------------------------------

    def prune(self, user: str, now: float | None = None) -> int:
        now = time.time() if now is None else now
        days = self.retention_days(user)
        return self.db.execute_rc(
            "DELETE FROM voice_commands WHERE user=? AND at<=?",
            [user, now - days * SECONDS_PER_DAY if days else now + 1],
        )

    def add_command(
        self, user: str, device_id: str | None, record: CommandRecord, now: float | None = None
    ) -> int | None:
        """Keep one command record; ``None`` when the user keeps nothing (retention 0)."""
        text = " ".join(record.text.split())
        if len(text) > self.cfg.max_text_chars:
            raise VoiceError(f"text is longer than {self.cfg.max_text_chars} characters", 413)
        args = json.dumps(record.args, ensure_ascii=False, separators=(",", ":"))
        if len(args.encode()) > self.cfg.max_args_bytes:
            raise VoiceError("args are too large", 413)
        marks = self._clean_marks(record.marks)
        now = time.time() if now is None else now
        if self.retention_days(user) == 0:
            self.prune(user, now)
            return None
        self.db.execute(
            "INSERT INTO voice_commands(user,device_id,at,text,tool,args,outcome,marks)"
            " VALUES(?,?,?,?,?,?,?,?)",
            [
                user,
                device_id or "",
                now,
                text,
                record.tool,
                args,
                record.outcome,
                json.dumps(marks),
            ],
        )
        self.prune(user, now)
        row = self.db.one("SELECT MAX(id) m FROM voice_commands WHERE user=?", [user])
        return int(row["m"])

    @staticmethod
    def _clean_marks(marks: dict[str, float]) -> dict[str, float]:
        if len(marks) > MAX_MARKS:
            raise VoiceError(f"at most {MAX_MARKS} marks")
        for name, value in marks.items():
            if not name or len(name) > MAX_MARK_NAME_CHARS:
                raise VoiceError("a mark name is empty or too long")
            if not 0 <= value <= MAX_MARK_MS:
                raise VoiceError("a mark is not a number of milliseconds")
        return {name: round(value, 1) for name, value in marks.items()}

    def commands(self, user: str, limit: int, now: float | None = None) -> list[dict[str, Any]]:
        self.prune(user, now)
        names = {d["id"]: d["device"] for d in self.auth.list_devices(user)}
        rows = self.db.all(
            "SELECT * FROM voice_commands WHERE user=? ORDER BY at DESC, id DESC LIMIT ?",
            [user, limit],
        )
        return [
            {
                "id": r["id"],
                "at": r["at"],
                "device_id": r["device_id"],
                "device": names.get(r["device_id"], ""),
                "text": r["text"],
                "tool": r["tool"],
                "args": json.loads(r["args"]),
                "outcome": r["outcome"],
                "marks": json.loads(r["marks"]),
            }
            for r in rows
        ]

    def delete_command(self, user: str, command_id: int) -> bool:
        return (
            self.db.execute_rc(
                "DELETE FROM voice_commands WHERE id=? AND user=?", [command_id, user]
            )
            > 0
        )

    def delete_all(self, user: str) -> int:
        return self.db.execute_rc("DELETE FROM voice_commands WHERE user=?", [user])


def install_voice_routes(app: FastAPI, d: Deps) -> None:
    svc = d.svc
    voice: VoiceService = svc.voice
    cfg = svc.cfg
    current_user = d.current_user

    def device_of(request: Request) -> str | None:
        principal = getattr(request.state, "principal", None)
        return svc.auth.device_id_of(principal)

    def on() -> None:
        if not cfg.voice.enabled:
            raise HTTPException(404, VOICE_OFF)

    def fail(exc: VoiceError):
        raise HTTPException(exc.status, str(exc)) from exc

    @app.get("/v1/me/voice")
    async def my_voice(user: UserConfig = Depends(current_user)):
        on()
        return voice.overview(user.name)

    @app.put("/v1/me/voice")
    async def put_my_voice(body: UserVoicePatch, user: UserConfig = Depends(current_user)):
        on()
        if body.retention_days is not None:
            voice.set_retention(user.name, body.retention_days)
        if body.all_off:
            voice.all_off(user.name)
        return voice.overview(user.name)

    @app.put("/v1/me/devices/{device_id}/voice")
    async def put_device_voice(
        device_id: str, body: DeviceVoicePatch, user: UserConfig = Depends(current_user)
    ):
        on()
        try:
            return voice.set_device(user.name, device_id, body)
        except VoiceError as exc:
            fail(exc)

    @app.post("/v1/voice/commands")
    async def file_command(
        body: CommandRecord, request: Request, user: UserConfig = Depends(current_user)
    ):
        on()
        svc.limiter.check(f"voice:{user.name}", cfg.voice.commands_per_min)
        device_id = device_of(request)
        if device_id is not None and not voice.device_state(device_id)["enabled"]:
            raise HTTPException(403, "voice is not switched on for this device")
        try:
            stored = voice.add_command(user.name, device_id, body)
        except VoiceError as exc:
            fail(exc)
        return {"stored": stored is not None, "id": stored}

    @app.get("/v1/voice/commands")
    async def list_commands(
        limit: int = Query(DEFAULT_HISTORY_LIMIT, ge=1),
        user: UserConfig = Depends(current_user),
    ):
        on()
        if limit > cfg.voice.history_page_max:
            raise HTTPException(400, f"limit must be 1 to {cfg.voice.history_page_max}")
        return {
            "retention_days": voice.retention_days(user.name),
            "commands": voice.commands(user.name, limit),
        }

    @app.delete("/v1/voice/commands")
    async def delete_commands(user: UserConfig = Depends(current_user)):
        on()
        return {"deleted": voice.delete_all(user.name)}

    @app.delete("/v1/voice/commands/{command_id}")
    async def delete_command(command_id: int, user: UserConfig = Depends(current_user)):
        on()
        if not voice.delete_command(user.name, command_id):
            raise HTTPException(404, "unknown command")
        return {"ok": True}
