"""The live model list of every configured provider, cached, with a "new" mark for fresh arrivals."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .config import Config
from .db import Database
from .llm import LLMClient, LLMError

KEY_CONFIGURED = "configured"
KEY_MISSING = "missing"
KEY_NOT_NEEDED = "not needed"
BASELINE = 0.0


class ModelNotListed(Exception):
    pass


@dataclass
class _Entry:
    models: list[str] = field(default_factory=list)
    fetched_at: float = 0.0
    error: str | None = None
    error_at: float = 0.0
    added: list[str] = field(default_factory=list)
    ever_ok: bool = False


def safe_base_url(url: str) -> str:
    """scheme://host[:port]/path without userinfo or query, for admins."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    return f"{parts.scheme}://{host}{parts.path}"


class ModelCatalog:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        llm: LLMClient,
        clock: Callable[[], float] = time.time,
    ):
        self.cfg, self.db, self.llm, self._clock = cfg, db, llm, clock
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_forced = 0.0

    def provider_names(self) -> list[str]:
        default = self.cfg.llm.default_provider
        names = sorted(self.cfg.llm.providers)
        return sorted(names, key=lambda n: (n != default, n))

    def key_state(self, provider: str) -> str:
        env = self.cfg.llm.providers[provider].api_key_env
        if not env:
            return KEY_NOT_NEEDED
        return KEY_CONFIGURED if self.cfg.api_key(provider) else KEY_MISSING

    def value_for(self, provider: str, model: str) -> str:
        return model if provider == self.cfg.llm.default_provider else f"{provider}:{model}"

    def split(self, value: str) -> tuple[str, str]:
        """(provider, model) the way `LLMClient.resolve` reads a task model."""
        providers = self.cfg.llm.providers
        prefix, sep, rest = value.partition(":")
        if sep and prefix in providers:
            return prefix, rest
        return self.cfg.llm.default_provider, value

    def _fresh(self, entry: _Entry | None, now: float) -> bool:
        if entry is None:
            return False
        c = self.cfg.models
        if entry.error is not None:
            return now - entry.error_at < c.error_ttl_s
        return now - entry.fetched_at < c.cache_ttl_s

    async def _fetch(self, provider: str, force: bool = False) -> None:
        lock = self._locks.setdefault(provider, asyncio.Lock())
        async with lock:
            now = self._clock()
            if self._fresh(self._entries.get(provider), now) and not force:
                return
            entry = self._entries.setdefault(provider, _Entry())
            try:
                ids = await self.llm.list_models(provider, self.cfg.models.timeout_s)
            except LLMError as exc:
                entry.error, entry.error_at = str(exc), self._clock()
                return
            ids = sorted(set(ids))[: self.cfg.models.max_models_per_provider]
            entry.models, entry.error, entry.fetched_at = ids, None, self._clock()
            entry.added = self._remember(provider, ids, entry.fetched_at)
            entry.ever_ok = True

    def _remember(self, provider: str, ids: list[str], now: float) -> list[str]:
        known = {
            r["model"]
            for r in self.db.all("SELECT model FROM model_seen WHERE provider=?", [provider])
        }
        baseline = not known
        added = [i for i in ids if i not in known]
        for model in added:
            self.db.execute(
                "INSERT OR IGNORE INTO model_seen(provider,model,first_seen) VALUES(?,?,?)",
                [provider, model, BASELINE if baseline else now],
            )
        return [] if baseline else added

    def _first_seen(self, provider: str) -> dict[str, float]:
        rows = self.db.all("SELECT model, first_seen FROM model_seen WHERE provider=?", [provider])
        return {r["model"]: float(r["first_seen"]) for r in rows}

    async def refresh(self, *, force: bool, admin: bool = False) -> dict:
        """Fetch what is stale (or everything when forced and the minimum interval has passed)."""
        now = self._clock()
        forced = force and now - self._last_forced >= self.cfg.models.refresh_min_interval_s
        if forced:
            self._last_forced = now
        await asyncio.gather(*(self._fetch(p, forced) for p in self.provider_names()))
        return self.listing(admin=admin, refreshed=forced)

    def listing(self, *, admin: bool = False, refreshed: bool = False) -> dict:
        now = self._clock()
        window = self.cfg.models.new_for_s
        providers = []
        newest = 0.0
        for name in self.provider_names():
            entry = self._entries.get(name) or _Entry()
            seen = self._first_seen(name)
            models = [
                {
                    "id": mid,
                    "value": self.value_for(name, mid),
                    "new": seen.get(mid, BASELINE) > BASELINE and now - seen[mid] <= window,
                }
                for mid in entry.models
            ]
            item = {
                "name": name,
                "default": name == self.cfg.llm.default_provider,
                "key": self.key_state(name),
                "ok": entry.error is None and entry.ever_ok,
                "error": entry.error,
                "stale": entry.error is not None and entry.ever_ok,
                "fetched_at": entry.fetched_at or None,
                "added": [self.value_for(name, m) for m in entry.added],
                "models": models,
            }
            if admin:
                item["base_url"] = safe_base_url(self.cfg.llm.providers[name].base_url)
            providers.append(item)
            newest = max(newest, entry.fetched_at)
        return {
            "fetched_at": newest or None,
            "cache_ttl_s": self.cfg.models.cache_ttl_s,
            "refreshed": refreshed,
            "providers": providers,
        }

    async def check(self, value: str) -> None:
        """Raise ModelNotListed unless `value` is a model some provider lists right now."""
        provider, model = self.split(value)
        await self._fetch(provider)
        entry = self._entries.get(provider)
        if entry is None or not entry.ever_ok:
            reason = entry.error if entry and entry.error else "not fetched"
            raise ModelNotListed(
                f"cannot check {value!r}: the model list of provider {provider!r} is unavailable "
                f"({reason})"
            )
        if model not in entry.models:
            raise ModelNotListed(f"{value!r} is not in the model list of provider {provider!r}")
