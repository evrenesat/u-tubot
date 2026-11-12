"""Read-only status for the web UI home and update pages. Nothing here contains a secret."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from . import __version__, appchannel, appsync
from .captions.engines import AsrRouter
from .config import Config
from .db import Database
from .usage import (
    METRIC_LLM_CALLS,
    METRIC_LLM_COMPLETION_TOKENS,
    METRIC_LLM_ERRORS,
    METRIC_LLM_PROMPT_TOKENS,
    Usage,
)
from .youtube import YoutubeGate

STARTED_AT = time.time()


def day_start(now: float | None = None) -> float:
    moment = datetime.fromtimestamp(now or time.time(), UTC)
    return moment.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class StatusService:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        gate: YoutubeGate,
        usage: Usage,
        engines: AsrRouter | None = None,
    ):
        self.cfg, self.db, self.gate, self.usage, self.engines = cfg, db, gate, usage, engines

    def home(self, user: str) -> dict[str, Any]:
        counters = self.usage.today()
        since = day_start()
        by_source = {
            r["source"]: int(r["n"])
            for r in self.db.all(
                "SELECT source, COUNT(*) n FROM transcripts WHERE fetched_at>=? GROUP BY source",
                [since],
            )
        }
        jobs = {
            r["status"]: int(r["n"])
            for r in self.db.all(
                "SELECT status, COUNT(*) n FROM jobs WHERE user=? GROUP BY status", [user]
            )
        }
        used = self.db.one(
            "SELECT count FROM tier2_usage WHERE user=? AND day=?",
            [user, datetime.now(UTC).strftime("%Y-%m-%d")],
        )
        gate = self.gate
        return {
            "version": __version__,
            "uptime_s": int(time.time() - STARTED_AT),
            "youtube": {
                "state": gate.state(),
                "healthy": gate.healthy(),
                "cooldown_remaining_s": int(gate.cooldown_remaining()),
                "background_waiting": gate.background_waiting(),
                "classes": gate.snapshot(),
            },
            "asr": {"engines": self.engines.status() if self.engines else []},
            "usage": {
                "day": datetime.now(UTC).strftime("%Y-%m-%d"),
                "llm": {
                    "calls": counters.get(METRIC_LLM_CALLS, 0),
                    "errors": counters.get(METRIC_LLM_ERRORS, 0),
                    "prompt_tokens": counters.get(METRIC_LLM_PROMPT_TOKENS, 0),
                    "completion_tokens": counters.get(METRIC_LLM_COMPLETION_TOKENS, 0),
                },
                "transcripts": {
                    "youtube_captions": by_source.get("youtube_captions", 0),
                    "asr": by_source.get("asr", 0),
                },
                "analyses": {
                    "used": int(used["count"]) if used else 0,
                    "cap": self.cfg.assess.tier2_daily_cap_per_user,
                },
            },
            "jobs": {
                "waiting": jobs.get("queued", 0),
                "processing": jobs.get("running", 0),
                "failed": jobs.get("failed", 0),
            },
        }


class UpdatesStatus:
    """The update channel on this server and the newest GitHub release (cached)."""

    def __init__(
        self,
        cfg: Config,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.cfg, self._transport, self._clock = cfg, transport, clock
        self._cache: dict[str, Any] | None = None
        self._cached_at = 0.0

    async def github(self, force: bool = False) -> dict[str, Any]:
        repo = self.cfg.app.github_repo
        if not repo:
            return {"configured": False}
        now = self._clock()
        if self._cache is not None:
            age = now - self._cached_at
            ttl = (
                self.cfg.app.release_check_error_ttl_s
                if self._cache.get("error")
                else self.cfg.app.release_check_ttl_s
            )
            if age < (self.cfg.app.release_check_min_interval_s if force else ttl):
                return self._cache
        self._cache, self._cached_at = await self._fetch(repo), now
        return self._cache

    async def _fetch(self, repo: str) -> dict[str, Any]:
        base: dict[str, Any] = {"configured": True, "repo": repo, "checked_at": self._clock()}
        if not appsync.REPO_RE.match(repo):
            return {**base, "error": "github_repo must look like OWNER/NAME"}
        url = f"{appsync.GITHUB_API}/repos/{repo}/releases?per_page={self.cfg.app.sync_releases_per_page}"
        try:
            async with httpx.AsyncClient(
                timeout=self.cfg.app.sync_timeout_s,
                headers={**appsync._api_headers(self.cfg), "User-Agent": appsync.USER_AGENT},
                transport=self._transport,
            ) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            return {**base, "error": f"GitHub unreachable ({type(exc).__name__})"}
        if resp.status_code != httpx.codes.OK:
            return {**base, "error": f"GitHub answered HTTP {resp.status_code}"}
        try:
            releases = resp.json()
        except ValueError:
            return {**base, "error": "GitHub returned an unreadable release list"}
        picked = appsync.pick_release(releases if isinstance(releases, list) else [], False)
        if picked is None:
            return {**base, "latest": None}
        release, version = picked
        return {
            **base,
            "latest": {
                "tag": release.get("tag_name"),
                "version": ".".join(str(n) for n in version),
                "published_at": release.get("published_at"),
                "url": release.get("html_url"),
            },
        }

    async def snapshot(self, force: bool = False) -> dict[str, Any]:
        channel = appchannel.channel_info(self.cfg)
        github = await self.github(force)
        latest = (github.get("latest") or {}).get("version")
        current = channel.get("version_name") if channel.get("published") else None
        behind = None
        if latest and current:
            have, want = appsync.parse_version(current), appsync.parse_version(latest)
            behind = bool(have and want and want > have)
        return {
            "channel": channel,
            "github": github,
            "behind": behind,
            "last_sync": appchannel.load_sync(self.cfg),
            "update_url": f"{self.cfg.server.public_base_url.rstrip('/')}/app/{appchannel.UPDATE_FILE}",
        }
