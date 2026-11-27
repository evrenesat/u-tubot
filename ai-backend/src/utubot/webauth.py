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
import uuid
from dataclasses import dataclass

from .auth import (
    Auth,
    PairError,
    Unauthorized,
    append_user,
    check_user_name,
    normalize_user_name,
    set_user_admin,
    set_user_prime,
    users_file_names,
)
from .config import Config, UserConfig
from .db import Database
from .passwords import check_strength, dummy_hash, hash_password, needs_rehash, verify_password
from .userproviders import PerUserUsage, UserProviders

SESSION_PREFIX = "utbs_"
SESSION_BYTES = 32
WEB_LOGIN_PREFIX = "wtl_"
CSRF_SALT = "utubot-csrf:"
AGENT_MAX_CHARS = 200
SCOPE_NAME_MAX_CHARS = 64
SESSION_TOKEN_ID = "session"
VIA_PASSWORD = "password"
VIA_TOKEN = "token"
VIA_TAILSCALE = "tailscale"
VIA_WEB_LOGIN = "web-login"
GENERIC_LOGIN_ERROR = "invalid username or password"
GENERIC_TOKEN_ERROR = "invalid token"
LOCKED_MESSAGE = "too many failed sign-ins; try again later"


class LoginError(Exception):
    def __init__(self, message: str, status: int = 401, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class WebLoginError(Exception):
    """A web sign-in link that is missing, already used or expired."""


@dataclass
class WebLoginResult:
    user: UserConfig
    device: str


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
    def __init__(
        self,
        cfg: Config,
        db: Database,
        auth: Auth,
        user_providers: UserProviders | None = None,
        user_usage: PerUserUsage | None = None,
    ):
        self.cfg, self.db, self.auth = cfg, db, auth
        self.user_providers = user_providers
        self.user_usage = user_usage
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

    @staticmethod
    def _user_scope(name: str) -> str:
        return f"user:{normalize_user_name(name)[:SCOPE_NAME_MAX_CHARS]}"

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
            scope = self._user_scope(name)
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
            scopes.append(self._user_scope(name))
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
        user = self.auth.find_user(name) if isinstance(name, str) else None
        ok = self.check_password(user.name if user else "", password)
        if not (user and ok):
            raise self._fail(ip, name if isinstance(name, str) else None, GENERIC_LOGIN_ERROR)
        self.db.execute("DELETE FROM login_failures WHERE scope=?", [self._user_scope(name)])
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

    # ---- one-time web sign-in -------------------------------------------------------------

    def create_web_login(self, user: str, device: str) -> tuple[str, int]:
        """A short-lived, single-use link that signs the user into the web UI when a browser opens it.

        The TV (or any client with a valid user token) asks for one and opens it on the same device,
        so the browser lands signed in without typing a password. The link is single use and lives
        only `web_login_ttl_s`; the device that asked for it is recorded on the session it makes.
        """
        sec = self._sec()
        now = time.time()
        token = WEB_LOGIN_PREFIX + secrets.token_urlsafe(SESSION_BYTES)
        device = " ".join(device.split())[: sec.max_device_name_chars] or "device"
        self.db.execute("DELETE FROM web_logins WHERE expires_at<? OR used=1", [now])
        self.db.execute(
            "INSERT INTO web_logins(id,user,token_sha256,device,created_at,expires_at,used) "
            "VALUES(?,?,?,?,?,?,0)",
            [
                uuid.uuid4().hex[:12],
                user,
                hash_session(token),
                device,
                now,
                now + sec.web_login_ttl_s,
            ],
        )
        return token, sec.web_login_ttl_s

    def redeem_web_login(self, token: str) -> WebLoginResult:
        """Claim a one-time link and return the owner's user and the device that asked for it.

        The claim is atomic (an `UPDATE ... WHERE used=0`), so a link is spent exactly once even
        under a double open; a missing, expired or already-used link raises `WebLoginError`. The
        session the browser signs in with is made by the caller, whose `agent` carries the device.
        """
        if not token or not token.startswith(WEB_LOGIN_PREFIX):
            raise WebLoginError("invalid link")
        now = time.time()
        row = self.db.one(
            "SELECT id,user,device,expires_at FROM web_logins WHERE token_sha256=? AND used=0"
            " AND expires_at>?",
            [hash_session(token), now],
        )
        if row is None:
            raise WebLoginError("invalid link")
        claimed = (
            self.db.execute_rc(
                "UPDATE web_logins SET used=1, used_at=? WHERE id=? AND used=0", [now, row["id"]]
            )
            == 1
        )
        if not claimed:
            raise WebLoginError("invalid link")
        user = self.auth.user_config(row["user"])
        if user is None:
            raise WebLoginError("invalid link")
        return WebLoginResult(user, row["device"])

    # ---- user administration --------------------------------------------------------------

    def describe_user(self, name: str) -> dict:
        user = self.auth.user_config(name)
        if user is None:
            raise PairError("unknown user", 404)
        return {
            "name": name,
            "admin": user.admin,
            "prime": user.prime,
            "class": user.klass,
            "has_password": self.has_password(name),
            "has_token": bool(user.token_sha256),
            "devices": len(self.auth.list_devices(name)),
            "sessions": self.user_sessions(name),
            "admin_editable": self.admin_editable(name),
            "usage": self.user_usage.for_user(name)
            if self.user_usage
            else {"cost": 0, "calls": 0, "day": ""},
            "usage_window": (
                self.user_usage.for_user_window(name, self.cfg.usage.window_days)
                if self.user_usage
                else {"cost": 0, "calls": 0}
            ),
            "provider": (self.user_providers.describe(name) or {"configured": False})
            if self.user_providers
            else {"configured": False},
        }

    def admin_editable(self, name: str) -> bool:
        """Only users that live in users.toml and not in config.toml can change role here."""
        return name not in self.cfg.config_user_names and name in users_file_names(
            self.cfg.users_path
        )

    def create_user(
        self, name: str, admin: bool, password: str | None, prime: bool = False
    ) -> None:
        check_user_name(name)
        folded = normalize_user_name(name)
        if any(normalize_user_name(n) == folded for n in self.auth.user_names()):
            raise PairError("user already exists", 409)
        if password is not None:
            self._check_strength(password)
        append_user(self.cfg.users_path, name, "", admin=admin, prime=prime)
        if self.auth.user_config(name) is None:
            raise PairError("could not create the user", 500)
        if password is not None:
            self.set_password(name, password)

    def set_admin(self, name: str, admin: bool) -> None:
        self._set_role(name, set_user_admin, "admin", admin)

    def set_prime(self, name: str, prime: bool) -> None:
        self._set_role(name, set_user_prime, "prime", prime)

    def _set_role(self, name: str, setter, field: str, value: bool) -> None:
        if self.auth.user_config(name) is None:
            raise PairError("unknown user", 404)
        if not self.admin_editable(name):
            raise PairError(f"this user is declared in config.toml; change `{field}` there", 409)
        if not setter(self.cfg.users_path, name, value):
            raise PairError("unknown user", 404)
