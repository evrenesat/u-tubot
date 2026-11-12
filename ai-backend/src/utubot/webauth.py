"""Web sign-in: passwords, cookie sessions, CSRF tokens and login lockout.

The browser UI signs in with a username and password, or by pasting a user token (kept for
compatibility); either way it receives an HttpOnly session cookie and never keeps a token in
page storage. Sessions are stored by SHA-256 only, so a copy of the database cannot be replayed.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass

from .auth import (
    Auth,
    PairError,
    Unauthorized,
    append_user,
    check_user_name,
    set_user_admin,
    users_file_names,
)
from .config import Config, UserConfig
from .db import Database
from .passwords import check_strength, dummy_hash, hash_password, needs_rehash, verify_password

SESSION_PREFIX = "utbs_"
SESSION_BYTES = 32
CSRF_SALT = "utubot-csrf:"
AGENT_MAX_CHARS = 200
SCOPE_NAME_MAX_CHARS = 64
SESSION_TOKEN_ID = "session"
VIA_PASSWORD = "password"
VIA_TOKEN = "token"
GENERIC_LOGIN_ERROR = "invalid username or password"
GENERIC_TOKEN_ERROR = "invalid token"
LOCKED_MESSAGE = "too many failed sign-ins; try again later"


class LoginError(Exception):
    def __init__(self, message: str, status: int = 401, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


@dataclass
class SessionInfo:
    user: UserConfig
    id_hash: str
    expires_at: float
    refreshed: bool


def hash_session(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(session_token: str) -> str:
    """Per-session CSRF value, derived from the (secret) session token; the page sends it as a header."""
    return hashlib.sha256((CSRF_SALT + session_token).encode()).hexdigest()


def csrf_valid(session_token: str, supplied: str | None) -> bool:
    if not supplied:
        return False
    return hmac.compare_digest(
        csrf_token(session_token).encode(), supplied.encode("utf-8", "replace")
    )


class WebAuth:
    def __init__(self, cfg: Config, db: Database, auth: Auth):
        self.cfg, self.db, self.auth = cfg, db, auth
        self._dummy: str | None = None
        self._hashing = threading.BoundedSemaphore(max(1, cfg.security.scrypt_max_concurrent))

    def _sec(self):
        return self.cfg.security

    # ---- passwords ------------------------------------------------------------------------

    def has_password(self, name: str) -> bool:
        return self.db.one("SELECT 1 FROM user_passwords WHERE user=?", [name]) is not None

    def set_password(self, name: str, password: str) -> None:
        """Hash (CPU heavy: call off the event loop) and store; every session of the user ends."""
        if self.auth.user_config(name) is None:
            raise PairError("unknown user", 404)
        self._check_strength(password)
        with self._hashing:
            hashed = hash_password(password, self._sec())
        self.db.execute(
            "INSERT OR REPLACE INTO user_passwords(user,hash,updated_at) VALUES(?,?,?)",
            [name, hashed, time.time()],
        )
        self.end_user_sessions(name)

    def _check_strength(self, password: str) -> None:
        try:
            check_strength(password, self._sec())
        except ValueError as exc:
            raise PairError(str(exc)) from exc

    def check_password(self, name: str, password: str) -> bool:
        """Constant-effort check. A correct password whose hash is weaker than the current
        `scrypt_*` cost is hashed again (the user stays signed in)."""
        row = self.db.one("SELECT hash FROM user_passwords WHERE user=?", [name])
        with self._hashing:
            if row is None:
                if self._dummy is None:
                    self._dummy = dummy_hash(self._sec())
                verify_password(password, self._dummy)
                return False
            ok = verify_password(password, row["hash"])
            upgraded = (
                hash_password(password, self._sec())
                if ok and needs_rehash(row["hash"], self._sec())
                else None
            )
        if upgraded:
            self.db.execute(
                "UPDATE user_passwords SET hash=?, updated_at=? WHERE user=? AND hash=?",
                [upgraded, time.time(), name, row["hash"]],
            )
        return ok

    # ---- lockout --------------------------------------------------------------------------

    def _retry_after(self, scope: str, limit: int, window_s: int, now: float) -> int:
        rows = self.db.all(
            "SELECT ts FROM login_failures WHERE scope=? AND ts>? ORDER BY ts DESC LIMIT ?",
            [scope, now - window_s, limit],
        )
        if len(rows) < limit:
            return 0
        return max(1, int(rows[-1]["ts"] + window_s - now) + 1)

    def locked_for(self, ip: str, name: str | None, now: float | None = None) -> int:
        """Seconds until a sign-in may be tried again; 0 when it may be tried now."""
        sec = self._sec()
        now = now or time.time()
        waits = [
            self._retry_after(f"ip:{ip}", sec.login_lockout_failures, sec.login_lockout_s, now),
            self._retry_after("all", sec.login_global_failures, sec.login_global_window_s, now),
        ]
        if name is not None:
            scope = f"user:{name[:SCOPE_NAME_MAX_CHARS]}"
            waits.append(
                self._retry_after(scope, sec.login_user_lockout_failures, sec.login_lockout_s, now)
            )
        return max(waits)

    def _record_failure(self, ip: str, name: str | None, now: float) -> None:
        sec = self._sec()
        self.db.execute(
            "DELETE FROM login_failures WHERE ts<?",
            [now - max(sec.login_global_window_s, sec.login_lockout_s)],
        )
        scopes = [f"ip:{ip}", "all"]
        if name is not None:
            scopes.append(f"user:{name[:SCOPE_NAME_MAX_CHARS]}")
        for scope in scopes:
            self.db.execute("INSERT INTO login_failures(scope,ts) VALUES(?,?)", [scope, now])

    def _fail(self, ip: str, name: str | None, message: str) -> LoginError:
        now = time.time()
        self._record_failure(ip, name, now)
        wait = self.locked_for(ip, name, now)
        if wait:
            return LoginError(LOCKED_MESSAGE, 429, wait)
        return LoginError(message, 401)

    # ---- sign-in --------------------------------------------------------------------------

    def login_password(
        self, name: str, password: str, ip: str, agent: str
    ) -> tuple[str, UserConfig]:
        """Check the credentials (CPU heavy: call off the event loop); returns a session token."""
        wait = self.locked_for(ip, name)
        if wait:
            raise LoginError(LOCKED_MESSAGE, 429, wait)
        user = self.auth.user_config(name) if isinstance(name, str) else None
        ok = self.check_password(user.name if user else "", password)
        if not (user and ok):
            raise self._fail(ip, name if isinstance(name, str) else None, GENERIC_LOGIN_ERROR)
        self.db.execute(
            "DELETE FROM login_failures WHERE scope=?", [f"user:{name[:SCOPE_NAME_MAX_CHARS]}"]
        )
        return self.create_session(user.name, ip, agent, VIA_PASSWORD), user

    def login_token(self, token: str, ip: str, agent: str) -> tuple[str, UserConfig]:
        wait = self.locked_for(ip, None)
        if wait:
            raise LoginError(LOCKED_MESSAGE, 429, wait)
        try:
            principal = self.auth.resolve(token)
        except Unauthorized:
            raise self._fail(ip, None, GENERIC_TOKEN_ERROR) from None
        return self.create_session(principal.user.name, ip, agent, VIA_TOKEN), principal.user

    # ---- sessions -------------------------------------------------------------------------

    def create_session(self, user: str, ip: str, agent: str, via: str) -> str:
        sec = self._sec()
        now = time.time()
        token = SESSION_PREFIX + secrets.token_urlsafe(SESSION_BYTES)
        self.db.execute("DELETE FROM sessions WHERE expires_at<?", [now])
        self.db.execute(
            "INSERT INTO sessions(id_sha256,user,created_at,last_seen,expires_at,ip,agent,via)"
            " VALUES(?,?,?,?,?,?,?,?)",
            [
                hash_session(token),
                user,
                now,
                now,
                now + sec.session_ttl_s,
                ip,
                " ".join(agent.split())[:AGENT_MAX_CHARS],
                via,
            ],
        )
        self.db.execute(
            "DELETE FROM sessions WHERE user=? AND id_sha256 NOT IN ("
            "SELECT id_sha256 FROM sessions WHERE user=? ORDER BY last_seen DESC LIMIT ?)",
            [user, user, sec.max_sessions_per_user],
        )
        return token

    def resolve_session(self, token: str | None) -> SessionInfo | None:
        if not token or not token.startswith(SESSION_PREFIX):
            return None
        sec = self._sec()
        now = time.time()
        digest = hash_session(token)
        row = self.db.one(
            "SELECT user, last_seen, expires_at FROM sessions WHERE id_sha256=?", [digest]
        )
        if row is None or row["expires_at"] <= now:
            return None
        user = self.auth.user_config(row["user"])
        if user is None:
            return None
        refreshed = now - row["last_seen"] >= sec.session_refresh_s
        expires = row["expires_at"]
        if refreshed:
            expires = now + sec.session_ttl_s
            self.db.execute(
                "UPDATE sessions SET last_seen=?, expires_at=? WHERE id_sha256=?",
                [now, expires, digest],
            )
        return SessionInfo(user, digest, expires, refreshed)

    def end_session(self, token: str | None) -> None:
        if token:
            self.db.execute("DELETE FROM sessions WHERE id_sha256=?", [hash_session(token)])

    def end_user_sessions(self, user: str, keep_token: str | None = None) -> None:
        keep = hash_session(keep_token) if keep_token else ""
        self.db.execute("DELETE FROM sessions WHERE user=? AND id_sha256<>?", [user, keep])

    def user_sessions(self, user: str) -> int:
        now = time.time()
        row = self.db.one(
            "SELECT COUNT(*) c FROM sessions WHERE user=? AND expires_at>?", [user, now]
        )
        return int(row["c"])

    # ---- user administration --------------------------------------------------------------

    def describe_user(self, name: str) -> dict:
        user = self.auth.user_config(name)
        if user is None:
            raise PairError("unknown user", 404)
        return {
            "name": name,
            "admin": user.admin,
            "has_password": self.has_password(name),
            "has_token": bool(user.token_sha256),
            "devices": len(self.auth.list_devices(name)),
            "sessions": self.user_sessions(name),
            "admin_editable": self.admin_editable(name),
        }

    def admin_editable(self, name: str) -> bool:
        """Only users that live in users.toml and not in config.toml can change role here."""
        return name not in self.cfg.config_user_names and name in users_file_names(
            self.cfg.users_path
        )

    def create_user(self, name: str, admin: bool, password: str | None) -> None:
        check_user_name(name)
        if self.auth.user_config(name) is not None:
            raise PairError("user already exists", 409)
        if password is not None:
            self._check_strength(password)
        append_user(self.cfg.users_path, name, "", admin=admin)
        if self.auth.user_config(name) is None:
            raise PairError("could not create the user", 500)
        if password is not None:
            self.set_password(name, password)

    def set_admin(self, name: str, admin: bool) -> None:
        if self.auth.user_config(name) is None:
            raise PairError("unknown user", 404)
        if not self.admin_editable(name):
            raise PairError("this user is declared in config.toml; change `admin` there", 409)
        if not set_user_admin(self.cfg.users_path, name, admin):
            raise PairError("unknown user", 404)
