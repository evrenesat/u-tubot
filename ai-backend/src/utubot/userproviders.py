"""Per-user upstream: a user brings their own AI provider (base url + key) for their calls.

Issue 212 (multi-user). Each person can store one OpenAI-compatible upstream of their own; their
cuts and answers then run on it instead of the owner's modelgate budget, and the per-user daily cost
budget and request cap (``[usage]``) still apply. The key is needed to make the call, so it is stored
on the server (never logged, never returned in an API response or a log line) exactly like the env-var
provider keys are held in memory: the self-hosted backend is trusted, and the key travels to the
upstream either way.

Two things ride a per-request context variable (mirroring ``classes.bind_class``): the caller's user
name and, when they have one, their upstream. Both are bound at the top of a request and at the top of
a background job claim, so the LLM router and the per-user limits see the right person wherever the
call runs.
"""

from __future__ import annotations

import hashlib
import re
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .db import Database
from .secretstore import PROVIDER_KEY

# The provider identity the LLM router uses while a user upstream is active: it is not in
# ``[llm.providers]``, so the router must treat it as "use the bound base url and key".
USER_PROVIDER = "self"
KEY_HASH_PREFIX = 16


@dataclass
class UserProvider:
    """One user's own upstream: where their calls go and which key authenticates them."""

    base_url: str
    api_key: str


class UserBudgetError(RuntimeError):
    """A user has reached their daily cost budget; the call is refused before it is sent."""

    def __init__(self, message: str, status: int = 429):
        super().__init__(message)
        self.status = status
        self.retry_after_s = self._seconds_to_utc_midnight()

    @staticmethod
    def _seconds_to_utc_midnight() -> int:
        from datetime import datetime, timedelta

        tomorrow = (datetime.now(UTC) + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return max(1, int((tomorrow - datetime.now(UTC)).total_seconds()))


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _host_of(base_url: str) -> str:
    """The scheme + host of a stored base url for display (a url may carry a token in its path)."""
    from urllib.parse import urlsplit

    split = urlsplit(base_url.strip())
    netloc = split.netloc
    if "@" in netloc:  # a stray user:pass before the host, keep only the host part
        netloc = netloc.rsplit("@", 1)[-1]
    scheme = split.scheme + ":" if split.scheme else ""
    return f"{scheme}//{netloc}".rstrip("/") if netloc else base_url.strip()


# --- per-request context (the caller and, when set, their upstream) ---------------------------

_CURRENT_USER: ContextVar[str | None] = ContextVar("utubot_call_user", default=None)
_CURRENT_PROVIDER: ContextVar[UserProvider | None] = ContextVar(
    "utubot_call_provider", default=None
)


def bind_call(user: str | None, provider: UserProvider | None) -> tuple[Token, Token]:
    """Bind the caller of the model calls that follow (a user name and, optionally, their upstream).

    Returns the two tokens needed to undo the bind; both context variables are set together so a
    request or background job sees one consistent (user, upstream) pair.
    """
    user_token = _CURRENT_USER.set(user)
    provider_token = _CURRENT_PROVIDER.set(provider)
    return (user_token, provider_token)


def unbind_call(tokens: tuple[Token, Token]) -> None:
    _CURRENT_USER.reset(tokens[0])
    _CURRENT_PROVIDER.reset(tokens[1])


def current_user() -> str | None:
    return _CURRENT_USER.get()


def current_user_provider() -> UserProvider | None:
    return _CURRENT_PROVIDER.get()


# --- the stored upstreams -----------------------------------------------------------------------


class UserProviders:
    """The one upstream each user has stored, and the live key used to run their calls."""

    def __init__(self, db: Database, store: Any = None):
        self._db = db
        self._store = store  # SecretStore: with its master key the api key is kept encrypted there

    def _encrypting(self) -> bool:
        return self._store is not None and self._store.available

    def migrate_keys(self) -> int:
        """Move every clear-text key into the secret store and blank the old column (idempotent).

        A row is blanked only after its key decrypts back to the same value. Returns how many moved.
        Without a master key nothing moves and the column stays as it was.
        """
        if not self._encrypting():
            return 0
        moved = 0
        for row in self._db.all("SELECT user, api_key FROM user_providers WHERE api_key != ''"):
            key = row["api_key"]
            self._store.set(
                row["user"], PROVIDER_KEY, key, via="migration", audit=False, quiet=True
            )
            if self._store.get(row["user"], PROVIDER_KEY) == key:
                self._db.execute("UPDATE user_providers SET api_key='' WHERE user=?", [row["user"]])
                moved += 1
        if moved:
            self._db.scrub()
        return moved

    def restore_clear_keys(self) -> int:
        """Rollback: write every encrypted key back to the old column (needs the master key)."""
        if not self._encrypting():
            return 0
        restored = 0
        for row in self._db.all("SELECT user FROM user_providers WHERE api_key = ''"):
            key = self._store.get(row["user"], PROVIDER_KEY)
            if key:
                self._db.execute(
                    "UPDATE user_providers SET api_key=? WHERE user=?", [key, row["user"]]
                )
                restored += 1
        return restored

    def set(self, user: str, base_url: str, api_key: str) -> dict[str, Any]:
        """Store (or replace) a user's upstream. `base_url` is trimmed of surrounding spaces; the
        key is stored and hashed, never returned."""
        base = base_url.strip().rstrip("/")
        if not base:
            raise ValueError("a base url is required")
        if not re.match(r"^https?://[^/\s]+", base, re.IGNORECASE):
            raise ValueError("the base url must be http(s)://host/v1")
        if not api_key:
            raise ValueError("an api key is required")
        now = datetime.now(UTC).timestamp()
        encrypted = self._encrypting()
        if encrypted:
            self._store.set(
                user, PROVIDER_KEY, api_key, via="web", by=user, audit=False, quiet=True
            )
        self._db.execute(
            "INSERT INTO user_providers(user,base_url,api_key_hash,api_key,updated_at)"
            " VALUES(?,?,?,?,?) ON CONFLICT(user) DO UPDATE SET base_url=excluded.base_url,"
            " api_key_hash=excluded.api_key_hash, api_key=excluded.api_key, updated_at=excluded.updated_at",
            [user, base, _hash_key(api_key), "" if encrypted else api_key, now],
        )
        return self.describe(user)

    def remove(self, user: str) -> bool:
        if self._encrypting():
            self._store.delete(user, PROVIDER_KEY, via="web", audit=False, quiet=True)
        return self._db.execute_rc("DELETE FROM user_providers WHERE user=?", [user]) > 0

    def get_live(self, user: str) -> tuple[str, str] | None:
        """The live `(base url, api key)` a call uses for `user`, or None when they have none."""
        row = self._db.one("SELECT base_url, api_key FROM user_providers WHERE user=?", [user])
        if row is None:
            return None
        key = row["api_key"]
        if not key and self._encrypting():
            key = self._store.get(user, PROVIDER_KEY) or ""
        return (row["base_url"], key) if key else None

    def describe(self, user: str) -> dict[str, Any] | None:
        """What the UI can show for a user's upstream: the host and a short key fingerprint, never
        the key itself."""
        row = self._db.one("SELECT base_url, api_key_hash FROM user_providers WHERE user=?", [user])
        if row is None:
            return None
        return {
            "host": _host_of(row["base_url"]),
            "key_sha256": row["api_key_hash"][:KEY_HASH_PREFIX],
        }

    def list(self) -> list[str]:
        rows = self._db.all("SELECT user FROM user_providers ORDER BY user")
        return [r["user"] for r in rows]


# --- per-user daily usage (cost and call count) -------------------------------------------------


class PerUserUsage:
    """A user's cumulative model cost and call count per UTC day, for the daily budget and the admin
    page. Cost is estimated from tokens and ``[usage] price_usd_per_million`` like the per-feature
    telemetry; an alias with no price adds nothing."""

    def __init__(self, db: Database, store: Any = None):
        self._db = db
        self._store = store  # SecretStore: with its master key the api key is kept encrypted there

    def _encrypting(self) -> bool:
        return self._store is not None and self._store.available

    def migrate_keys(self) -> int:
        """Move every clear-text key into the secret store and blank the old column (idempotent).

        A row is blanked only after its key decrypts back to the same value. Returns how many moved.
        Without a master key nothing moves and the column stays as it was.
        """
        if not self._encrypting():
            return 0
        moved = 0
        for row in self._db.all("SELECT user, api_key FROM user_providers WHERE api_key != ''"):
            key = row["api_key"]
            self._store.set(
                row["user"], PROVIDER_KEY, key, via="migration", audit=False, quiet=True
            )
            if self._store.get(row["user"], PROVIDER_KEY) == key:
                self._db.execute("UPDATE user_providers SET api_key='' WHERE user=?", [row["user"]])
                moved += 1
        if moved:
            self._db.scrub()
        return moved

    def restore_clear_keys(self) -> int:
        """Rollback: write every encrypted key back to the old column (needs the master key)."""
        if not self._encrypting():
            return 0
        restored = 0
        for row in self._db.all("SELECT user FROM user_providers WHERE api_key = ''"):
            key = self._store.get(row["user"], PROVIDER_KEY)
            if key:
                self._db.execute(
                    "UPDATE user_providers SET api_key=? WHERE user=?", [key, row["user"]]
                )
                restored += 1
        return restored

    @staticmethod
    def today() -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def add(self, user: str, cost: float | None, calls: int = 1) -> None:
        if self._db is None or calls <= 0 or user is None:
            return
        cost = float(cost or 0.0)
        self._db.execute(
            "INSERT INTO user_usage(user,day,cost,calls) VALUES(?,?,?,?) "
            "ON CONFLICT(user,day) DO UPDATE SET cost=cost+excluded.cost, calls=calls+excluded.calls",
            [user, self.today(), cost, calls],
        )

    def daily(self, user: str) -> tuple[float, int]:
        row = self._db.one(
            "SELECT COALESCE(SUM(cost),0) AS cost, COALESCE(SUM(calls),0) AS calls "
            "FROM user_usage WHERE user=? AND day=?",
            [user, self.today()],
        )
        if not row:
            return 0.0, 0
        return float(row["cost"]), int(row["calls"])

    def for_user(self, user: str) -> dict[str, Any]:
        cost, calls = self.daily(user)
        return {"cost": round(cost, 6), "calls": calls, "day": self.today()}

    def for_admin(self, window_days: int, now: float | None = None) -> list[dict[str, Any]]:
        """Every user's total cost and calls over the look-back window, most usage first."""
        from datetime import datetime, timedelta

        now_dt = datetime.now(UTC) if now is None else datetime.fromtimestamp(now, UTC)
        since = (now_dt - timedelta(days=window_days)).strftime("%Y-%m-%d")
        rows = self._db.all(
            "SELECT user, SUM(cost) AS cost, SUM(calls) AS calls FROM user_usage "
            "WHERE day >= ? GROUP BY user ORDER BY 1",
            [since],
        )
        return [
            {
                "user": r["user"],
                "cost": round(float(r["cost"] or 0.0), 6),
                "calls": int(r["calls"] or 0),
            }
            for r in rows
        ]
