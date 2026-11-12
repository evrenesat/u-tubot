from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .config import Config, UserConfig, UserPolicy, load_config
from .db import Database

TOKEN_BYTES = 32
TOKEN_PREFIX = "utb_"
PAIR_SALT = "utubot-pair:"
CONFIG_TOKEN_ID = "config"


class Unauthorized(Exception):
    pass


class Forbidden(Exception):
    pass


class PairError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Principal:
    user: UserConfig
    token_id: str


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_code(code: str) -> str:
    return hashlib.sha256((PAIR_SALT + code).encode()).hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTES)


def append_user(users_path: Path, name: str, token_hash: str, admin: bool = False) -> None:
    users_path.parent.mkdir(parents=True, exist_ok=True)
    existing = users_path.read_text() if users_path.exists() else ""
    blocks = [b for b in existing.split("[[users]]") if b.strip() and f'name = "{name}"' not in b]
    extra = "admin = true\n" if admin else ""
    blocks.append(f'\nname = "{name}"\ntoken_sha256 = "{token_hash}"\n{extra}')
    users_path.write_text("".join(f"[[users]]{b}" for b in blocks))
    users_path.chmod(0o600)


class Auth:
    def __init__(self, cfg: Config, db: Database):
        self.cfg, self.db = cfg, db
        self._mtime = self._stat()

    def _stat(self) -> float:
        path = self.cfg.users_path
        return path.stat().st_mtime if path.exists() else 0.0

    def _refresh(self) -> None:
        mtime = self._stat()
        if mtime != self._mtime:
            self._mtime = mtime
            self.cfg.users = load_config(self.cfg.config_path or None).users

    def user_config(self, name: str) -> UserConfig | None:
        self._refresh()
        base = next((u for u in self.cfg.users if u.name == name), None)
        if base is None:
            return None
        row = self.db.one("SELECT json FROM policy_overrides WHERE user=?", [name])
        if not row:
            return base
        merged = {**base.policy.model_dump(), **json.loads(row["json"])}
        return base.model_copy(update={"policy": UserPolicy(**merged)})

    def user_names(self) -> list[str]:
        self._refresh()
        return [u.name for u in self.cfg.users]

    def resolve(self, token: str | None) -> Principal:
        self._refresh()
        if not token:
            raise Unauthorized
        digest = hash_token(token)
        matched: str | None = None
        for user in self.cfg.users:
            if user.token_sha256 and hmac.compare_digest(user.token_sha256, digest):
                matched = user.name
        token_id = CONFIG_TOKEN_ID
        if matched is None:
            row = self.db.one(
                "SELECT id, user, token_sha256 FROM device_tokens WHERE token_sha256=?", [digest]
            )
            if row and hmac.compare_digest(row["token_sha256"], digest):
                matched, token_id = row["user"], row["id"]
                self.db.execute(
                    "UPDATE device_tokens SET last_used=? WHERE id=?", [time.time(), row["id"]]
                )
        if matched is None:
            raise Unauthorized
        user = self.user_config(matched)
        if user is None:
            raise Unauthorized
        return Principal(user, token_id)

    def set_policy(self, name: str, patch: dict) -> UserPolicy:
        user = self.user_config(name)
        if user is None:
            raise PairError("unknown user", 404)
        row = self.db.one("SELECT json FROM policy_overrides WHERE user=?", [name])
        current = json.loads(row["json"]) if row else {}
        merged_override = {**current, **patch}
        unknown = set(patch) - set(UserPolicy.model_fields)
        if unknown:
            raise PairError(f"unknown policy fields: {sorted(unknown)}")
        try:
            policy = UserPolicy(**{**user.policy.model_dump(), **patch})
        except ValidationError as exc:
            raise PairError(f"invalid policy: {exc.errors()[0]['msg']}") from exc
        self.db.execute(
            "INSERT OR REPLACE INTO policy_overrides(user,json) VALUES(?,?)",
            [name, json.dumps(merged_override)],
        )
        return policy

    def create_pair_code(self, name: str) -> tuple[str, int]:
        sec = self.cfg.security
        if self.user_config(name) is None:
            raise PairError("unknown user", 404)
        now = time.time()
        self.db.execute("DELETE FROM pair_codes WHERE expires_at < ? OR used=1", [now])
        for _ in range(20):
            code = str(secrets.randbelow(10**sec.pair_code_digits)).zfill(sec.pair_code_digits)
            if not self.db.one("SELECT 1 FROM pair_codes WHERE code_sha256=?", [hash_code(code)]):
                break
        self.db.execute(
            "INSERT INTO pair_codes(id,user,code_sha256,expires_at,created_at) VALUES(?,?,?,?,?)",
            [uuid.uuid4().hex[:12], name, hash_code(code), now + sec.pair_code_ttl_s, now],
        )
        return code, sec.pair_code_ttl_s

    def _locked(self, ip: str, now: float) -> bool:
        sec = self.cfg.security
        per_ip = self.db.one(
            "SELECT COUNT(*) c FROM pair_failures WHERE ip=? AND ts>?",
            [ip, now - sec.pair_lockout_s],
        )["c"]
        if per_ip >= sec.pair_lockout_failures:
            return True
        total = self.db.one(
            "SELECT COUNT(*) c FROM pair_failures WHERE ts>?", [now - sec.pair_global_window_s]
        )["c"]
        return total >= sec.pair_global_failures

    def redeem(self, code: str, device: str, ip: str) -> tuple[str, str]:
        sec = self.cfg.security
        now = time.time()
        self.db.execute("DELETE FROM pair_failures WHERE ts < ?", [now - sec.pair_global_window_s])
        if self._locked(ip, now):
            raise PairError("too many failed attempts", 429)
        digest = hash_code(code.strip())
        row = self.db.one(
            "SELECT id, user, code_sha256 FROM pair_codes WHERE code_sha256=? AND used=0"
            " AND expires_at>?",
            [digest, now],
        )
        claimed = bool(row and hmac.compare_digest(row["code_sha256"], digest))
        if claimed:
            claimed = (
                self.db.execute_rc(
                    "UPDATE pair_codes SET used=1 WHERE id=? AND used=0", [row["id"]]
                )
                == 1
            )
        if not claimed:
            self.db.execute("INSERT INTO pair_failures(ip,ts) VALUES(?,?)", [ip, now])
            raise PairError("invalid or expired code", 403)
        count = self.db.one("SELECT COUNT(*) c FROM device_tokens WHERE user=?", [row["user"]])["c"]
        if count >= sec.max_devices_per_user:
            raise PairError("device limit reached; revoke one first", 409)
        token = new_token()
        label = " ".join(device.split())[: sec.max_device_name_chars] or "device"
        self.db.execute(
            "INSERT INTO device_tokens(id,user,token_sha256,device,created_at) VALUES(?,?,?,?,?)",
            [uuid.uuid4().hex[:12], row["user"], hash_token(token), label, now],
        )
        return token, row["user"]

    def list_devices(self, user: str | None = None) -> list[dict]:
        sql = "SELECT id,user,device,created_at,last_used FROM device_tokens"
        rows = self.db.all(
            sql + (" WHERE user=?" if user else "") + " ORDER BY created_at", [user] if user else []
        )
        return [dict(r) for r in rows]

    def revoke(self, device_id: str) -> bool:
        return self.db.execute_rc("DELETE FROM device_tokens WHERE id=?", [device_id]) > 0
