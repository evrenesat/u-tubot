"""Per-user secrets (Real-Debrid token, stream add-on address, the user's own AI provider key), encrypted at rest.

See `ai/WEB_SETTINGS_PLAN.md` section 6. AES-256-GCM with a fresh 96-bit nonce per write; the user and the
key name are the associated data, so a row cannot be moved to another user or field. The master key is 32
random bytes (base64) from an environment variable (`[security] secrets_key_env`), never from the config
file or the database. Without it nothing is stored and every secret route answers 503. A value never goes
to a log line, an error text, the audit or a response: the web gets only "set" and a short hint.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import secrets
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .db import Database

KEY_BYTES = 32
NONCE_BYTES = 12
HINT_CHARS = 4
MAX_VALUE_CHARS = 1000
MAX_PROVIDER_KEY_CHARS = 4096
MIN_TOKEN_CHARS = 8
NOT_SET_UP = "secret storage is not set up on this server"
PROVIDER_KEY = "provider.api_key"
PRIVATE_HOST_SUFFIXES = (".local", ".lan", ".home", ".internal", ".ts.net")
VIA_WEB, VIA_TV, VIA_CLI, VIA_MIGRATION = "web", "tv", "cli", "migration"


class SecretsUnavailable(RuntimeError):
    pass


class InvalidSecret(ValueError):
    pass


def new_master_key() -> str:
    return base64.b64encode(secrets.token_bytes(KEY_BYTES)).decode()


def parse_master_key(text: str | None) -> bytes | None:
    """The 32 key bytes of a base64 master key, or None when it is missing or malformed."""
    if not text:
        return None
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == KEY_BYTES else None


def key_id_of(key: bytes) -> str:
    return hashlib.sha256(b"utubot-secret-key-id" + key).hexdigest()[:8]


def _private_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    if host == "localhost" or host.endswith(PRIVATE_HOST_SUFFIXES) or "." not in host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def check_addon_url(value: str) -> str:
    """The stream add-on address: https, or http for a private host. Returns its host for display."""
    split = urlsplit(value.strip())
    host = split.hostname or ""
    if split.scheme not in ("http", "https") or not host:
        raise InvalidSecret("must be an https:// address")
    if split.scheme == "http" and not _private_host(host):
        raise InvalidSecret("http is only allowed for a private host")
    return host


def hint_of(name: str, value: str) -> str:
    """What the page may show: the last 4 characters of a token, only the host of an address."""
    if name.endswith("addon_url"):
        return check_addon_url(value)
    return value[-HINT_CHARS:]


def check_secret(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise InvalidSecret("must be text")
    if name == PROVIDER_KEY:  # kept exactly as given: its hash is shown to the user
        if not value or len(value) > MAX_PROVIDER_KEY_CHARS:
            raise InvalidSecret("not a usable key")
        return value
    value = value.strip()
    if not value or len(value) > MAX_VALUE_CHARS or any(c.isspace() for c in value):
        raise InvalidSecret(f"must be one word of at most {MAX_VALUE_CHARS} characters")
    if name.endswith("addon_url"):
        check_addon_url(value)
    elif len(value) < MIN_TOKEN_CHARS:
        raise InvalidSecret("too short")
    return value


class SecretStore:
    def __init__(
        self,
        db: Database,
        key: bytes | None,
        touch: Callable[[str], int] | None = None,
    ):
        self.db = db
        self._key = key
        self._aes = AESGCM(key) if key else None
        self.key_id = key_id_of(key) if key else None
        self._touch = touch  # raises the user's settings version and returns it

    @classmethod
    def from_env(cls, db: Database, env_name: str, touch=None) -> SecretStore:
        return cls(db, parse_master_key(os.environ.get(env_name)), touch)

    @property
    def available(self) -> bool:
        return self._aes is not None

    def _need(self) -> AESGCM:
        if self._aes is None:
            raise SecretsUnavailable(NOT_SET_UP)
        return self._aes

    @staticmethod
    def _aad(user: str, name: str) -> bytes:
        return f"{user}\0{name}".encode()

    # ---- writes -----------------------------------------------------------------------------

    def set(
        self,
        user: str,
        name: str,
        value: str,
        *,
        via: str,
        by: str | None = None,
        device_id: str | None = None,
        audit: bool = True,
        quiet: bool = False,
    ) -> dict[str, Any]:
        """Store a secret. `quiet` is for a secret no TV is given (the AI provider key): no revision change."""
        aes = self._need()
        value = check_secret(name, value)
        hint = hint_of(name, value)
        existed = self._row(user, name) is not None
        nonce = os.urandom(NONCE_BYTES)
        cipher = aes.encrypt(nonce, value.encode(), self._aad(user, name))
        rev = 0 if quiet else self._bump(user)
        self.db.execute(
            "INSERT INTO user_secrets(user,key,nonce,ciphertext,key_id,last4,updated_at,rev)"
            " VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(user,key) DO UPDATE SET nonce=excluded.nonce,"
            " ciphertext=excluded.ciphertext, key_id=excluded.key_id, last4=excluded.last4,"
            " updated_at=excluded.updated_at, rev=excluded.rev",
            [user, name, nonce, cipher, self.key_id, hint, time.time(), rev],
        )
        if not quiet:
            self._set_user_rev(user, rev)
        if audit:
            self._audit(user, name, "set" if existed else None, "set", via, by, device_id)
        return self.describe_one(user, name)

    def delete(
        self,
        user: str,
        name: str,
        *,
        via: str,
        by: str | None = None,
        audit: bool = True,
        quiet: bool = False,
    ) -> bool:
        if self._row(user, name) is None:
            return False
        rev = 0 if quiet else self._bump(user)
        self.db.execute("DELETE FROM user_secrets WHERE user=? AND key=?", [user, name])
        if not quiet:
            self._set_user_rev(user, rev)
        if audit:
            self._audit(user, name, "set", "cleared", via, by, None)
        return True

    def _bump(self, user: str) -> int:
        return self._touch(user) if self._touch else int(time.time() * 1000)

    def _set_user_rev(self, user: str, rev: int) -> None:
        self.db.execute(
            "INSERT INTO user_secret_rev(user,rev) VALUES(?,?)"
            " ON CONFLICT(user) DO UPDATE SET rev=excluded.rev",
            [user, rev],
        )

    def _audit(self, user, name, old, new, via, by, device_id) -> None:
        # only the words "set" / "cleared" are ever written, never a value or a hint
        title_key = name if "." in name else f"secrets.{name}"
        self.db.execute(
            "INSERT INTO settings_audit(user,device_id,key,old_json,new_json,by_user,via,"
            "actor_device_id,at,outcome) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [
                user,
                "",
                title_key,
                json.dumps(old),
                json.dumps(new),
                by,
                via,
                device_id,
                time.time(),
                "applied",
            ],
        )

    # ---- reads ------------------------------------------------------------------------------

    def _row(self, user: str, name: str):
        return self.db.one("SELECT * FROM user_secrets WHERE user=? AND key=?", [user, name])

    def get(self, user: str, name: str) -> str | None:
        """The clear value, for the server's own use and for a delivery to the user's TV only."""
        row = self._row(user, name)
        if row is None:
            return None
        return self._decrypt(user, name, row)

    def _decrypt(self, user: str, name: str, row) -> str:
        aes = self._need()
        if row["key_id"] != self.key_id:
            raise SecretsUnavailable("a secret was written with another master key")
        try:
            return aes.decrypt(row["nonce"], row["ciphertext"], self._aad(user, name)).decode()
        except InvalidTag as exc:
            raise SecretsUnavailable("a stored secret did not decrypt") from exc

    def rev(self, user: str) -> int:
        row = self.db.one("SELECT rev FROM user_secret_rev WHERE user=?", [user])
        return int(row["rev"]) if row else 0

    def describe_one(self, user: str, name: str) -> dict[str, Any]:
        row = self._row(user, name)
        if row is None:
            return {"key": name, "set": False}
        return {
            "key": name,
            "set": True,
            "last4": row["last4"],
            "updated_at": row["updated_at"],
        }

    def names(self, user: str) -> list[str]:
        return [
            r["key"]
            for r in self.db.all(
                "SELECT key FROM user_secrets WHERE user=? AND key!=?", [user, PROVIDER_KEY]
            )
        ]

    def delivered_to(self, user: str, devices: dict[str, str]) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT device_id, at FROM user_secret_deliveries WHERE user=? ORDER BY at DESC", [user]
        )
        return [
            {"id": r["device_id"], "device": devices[r["device_id"]], "at": r["at"]}
            for r in rows
            if r["device_id"] in devices
        ]

    def deliver(self, user: str, device_id: str, names: list[str]) -> dict[str, Any]:
        """The values of `names` for one of the user's own paired TVs, and a note of the delivery."""
        values = {}
        for name in names:
            value = self.get(user, name)
            if value is not None:
                values[name] = value
        self.db.execute(
            "INSERT INTO user_secret_deliveries(user,device_id,at) VALUES(?,?,?)"
            " ON CONFLICT(user,device_id) DO UPDATE SET at=excluded.at",
            [user, device_id, time.time()],
        )
        return values

    def forget_device(self, device_id: str) -> None:
        self.db.execute("DELETE FROM user_secret_deliveries WHERE device_id=?", [device_id])

    # ---- operations -------------------------------------------------------------------------

    def check(self) -> dict[str, int]:
        """Decrypt every row; counts only."""
        ok = bad = 0
        for row in self.db.all("SELECT * FROM user_secrets"):
            try:
                self._decrypt(row["user"], row["key"], row)
                ok += 1
            except SecretsUnavailable:
                bad += 1
        return {"ok": ok, "failed": bad}

    def rotate(self, new_key: bytes) -> int:
        """Re-encrypt every row with `new_key`; the caller then switches the environment variable."""
        new = AESGCM(new_key)
        new_id = key_id_of(new_key)
        rows = self.db.all("SELECT * FROM user_secrets")
        plain = [(r, self._decrypt(r["user"], r["key"], r).encode()) for r in rows]
        for row, value in plain:
            nonce = os.urandom(NONCE_BYTES)
            cipher = new.encrypt(nonce, value, self._aad(row["user"], row["key"]))
            self.db.execute(
                "UPDATE user_secrets SET nonce=?, ciphertext=?, key_id=? WHERE user=? AND key=?",
                [nonce, cipher, new_id, row["user"], row["key"]],
            )
        return len(plain)


SECRET_NAME = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
