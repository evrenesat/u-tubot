from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .config import Config, UserConfig, UserPolicy, resolve_users
from .db import Database

TOKEN_BYTES = 32
TOKEN_PREFIX = "utb_"
PAIR_SALT = "utubot-pair:"
CONFIG_TOKEN_ID = "config"


class Unauthorized(Exception):
    pass


class Forbidden(Exception):
    pass


class VersionConflict(Exception):
    def __init__(self, version: int):
        super().__init__("settings changed")
        self.version = version


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


USER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")
USER_BLOCK = "[[users]]"


def check_user_name(name: str) -> str:
    if not isinstance(name, str) or not USER_NAME_RE.match(name):
        raise PairError(
            "user name: 1-32 characters from A-Z a-z 0-9 . _ -, starting with a letter or digit"
        )
    return name


def append_user(users_path: Path, name: str, token_hash: str, admin: bool = False) -> None:
    """Write (or replace) a user block in users.toml; an empty hash makes a password-only user."""
    check_user_name(name)
    users_path.parent.mkdir(parents=True, exist_ok=True)
    existing = users_path.read_text() if users_path.exists() else ""
    blocks = [b for b in existing.split(USER_BLOCK)[1:] if b.strip() and not _block_is(b, name)]
    extra = "admin = true\n" if admin else ""
    blocks.append(f'\nname = "{name}"\ntoken_sha256 = "{token_hash}"\n{extra}')
    users_path.write_text("".join(f"{USER_BLOCK}{b}" for b in blocks))
    users_path.chmod(0o600)


def _block_is(block: str, name: str) -> bool:
    return re.search(rf'^name\s*=\s*"{re.escape(name)}"\s*$', block, re.MULTILINE) is not None


def users_file_names(users_path: Path) -> set[str]:
    if not users_path.exists():
        return set()
    return set(re.findall(r'^name\s*=\s*"([^"]*)"\s*$', users_path.read_text(), re.MULTILINE))


def set_user_admin(users_path: Path, name: str, admin: bool) -> bool:
    """Flip `admin` on a user block of users.toml; False when the file has no such user."""
    if not users_path.exists():
        return False
    parts = users_path.read_text().split(USER_BLOCK)
    for idx in range(1, len(parts)):
        if not _block_is(parts[idx], name):
            continue
        block = re.sub(r"^admin\s*=.*\n?", "", parts[idx], flags=re.MULTILINE)
        if admin:
            block = re.sub(
                r'^(name\s*=\s*".*"\s*\n)', r"\1admin = true\n", block, count=1, flags=re.MULTILINE
            )
        parts[idx] = block
        users_path.write_text(USER_BLOCK.join(parts))
        users_path.chmod(0o600)
        return True
    return False


def describe_validation(exc: ValidationError) -> str:
    return "invalid policy: " + "; ".join(
        f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" if e["loc"] else e["msg"]
        for e in exc.errors()
    )


def build_policy(base: UserPolicy, override: dict) -> UserPolicy:
    """`base` with the user's override on top; the per-task `models` merge instead of replacing."""
    merged = {**base.model_dump(), **override}
    if "models" in override:
        merged["models"] = {**base.models, **(override["models"] or {})}
    return UserPolicy(**merged)


def merge_policy(base: UserPolicy, override: dict) -> UserPolicy:
    """Base policy with the user's runtime override; a stored value that no longer validates is skipped."""
    try:
        return build_policy(base, override)
    except ValidationError:
        policy = base
        for key, value in override.items():
            try:
                policy = build_policy(policy, {key: value})
            except ValidationError:
                continue
        return policy


class Auth:
    def __init__(self, cfg: Config, db: Database):
        self.cfg, self.db = cfg, db
        self._snapshot = list(cfg.users)
        self._mtime = self._stat()

    def _stat(self) -> float:
        path = self.cfg.users_path
        return path.stat().st_mtime if path.exists() else 0.0

    def _refresh(self) -> None:
        mtime = self._stat()
        if mtime != self._mtime:
            self._mtime = mtime
            declared = self.cfg.declared_users
            self.cfg.users = resolve_users(
                self.cfg, self._snapshot if declared is None else declared
            )

    def user_config(self, name: str) -> UserConfig | None:
        self._refresh()
        base = next((u for u in self.cfg.users if u.name == name), None)
        if base is None:
            return None
        override = self.policy_override(name)
        if not override:
            return base
        return base.model_copy(update={"policy": merge_policy(base.policy, override)})

    def policy_override(self, name: str) -> dict:
        row = self.db.one("SELECT json FROM policy_overrides WHERE user=?", [name])
        return json.loads(row["json"]) if row else {}

    def settings_version(self, name: str) -> tuple[int, float]:
        row = self.db.one("SELECT version, updated_at FROM policy_overrides WHERE user=?", [name])
        return (int(row["version"]), float(row["updated_at"])) if row else (0, 0.0)

    def write_override(self, name: str, override: dict, expected: int | None = None) -> int:
        """Store the user's sparse override and bump the version (one statement); returns the new version.

        With `expected`, the write happens only if the stored version still equals it
        (0 = no row yet); otherwise `VersionConflict` carries the current one.
        """
        payload, now = json.dumps(override), time.time()
        where, extra = (" AND version=?", [expected]) if expected is not None else ("", [])
        changed = self.db.execute_rc(
            "UPDATE policy_overrides SET json=?, version=version+1, updated_at=? WHERE user=?"
            + where,
            [payload, now, name, *extra],
        )
        if changed == 0 and expected in (None, 0):
            changed = self.db.execute_rc(
                "INSERT OR IGNORE INTO policy_overrides(user,json,version,updated_at)"
                " VALUES(?,?,1,?)",
                [name, payload, now],
            )
            if changed == 0 and expected is None:
                return self.write_override(name, override)
        if changed == 0:
            raise VersionConflict(self.settings_version(name)[0])
        return self.settings_version(name)[0]

    def touch_settings(self, name: str) -> None:
        """A setting kept outside the override row (prompt defaults) changed: bump the version."""
        if self.user_config(name) is not None:
            self.write_override(name, self.policy_override(name))

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
        unknown = set(patch) - set(UserPolicy.model_fields)
        if unknown:
            raise PairError(f"unknown policy fields: {sorted(unknown)}")
        override = {**self.policy_override(name), **patch}
        base = self.base_policy(name)
        try:
            policy = build_policy(base, override)
        except ValidationError as exc:
            raise PairError(describe_validation(exc)) from exc
        self.write_override(name, override)
        return policy

    def base_policy(self, name: str) -> UserPolicy:
        """The user's policy before runtime overrides: defaults, `[default_policy]`, `[users.policy]`."""
        self._refresh()
        base = next((u for u in self.cfg.users if u.name == name), None)
        return base.policy if base else UserPolicy()

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

    def revoke(self, device_id: str, user: str | None = None) -> bool:
        """Delete a device token; with `user`, only one that user owns."""
        if user is None:
            return self.db.execute_rc("DELETE FROM device_tokens WHERE id=?", [device_id]) > 0
        rc = self.db.execute_rc(
            "DELETE FROM device_tokens WHERE id=? AND user=?", [device_id, user]
        )
        return rc > 0
