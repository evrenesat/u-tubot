from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from .config import Config
from .db import Database
from .urlguard import Resolver, UrlRejected, guarded_get, system_resolver

log = logging.getLogger("utubot.prompts")

BUILTIN_SET_ID = "builtin"
DEFAULT_BUILTIN_KEY = "builtin/tldr"
SET_FORMAT_VERSION = 1
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TEMPLATE_VARS = (
    "title",
    "channel",
    "duration",
    "description",
    "transcript",
    "language",
    "question",
)
VAR_RE = re.compile(r"\{(" + "|".join(TEMPLATE_VARS) + r")\}")
MAX_PROMPTS_PER_SET = 50
MAX_TEXT_CHARS = 20000
MAX_TOKENS_LIMIT = 8000

DEFAULT_SYSTEM = (
    "You summarize YouTube videos for a viewer on a TV remote. Be concrete and faithful to the "
    "transcript, never invent details. Plain text, no preamble. Reply in {language}."
)


class PromptError(ValueError):
    pass


class Prompt(BaseModel):
    id: str
    label: str
    default: bool = False
    system: str = ""
    template: str
    max_tokens: int = 700
    model: str | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("id must match [A-Za-z0-9._-]{1,64}")
        return v

    @field_validator("template")
    @classmethod
    def _template(cls, v: str) -> str:
        if not v.strip() or len(v) > MAX_TEXT_CHARS:
            raise ValueError("template empty or too long")
        return v

    @field_validator("system")
    @classmethod
    def _system(cls, v: str) -> str:
        if len(v) > MAX_TEXT_CHARS:
            raise ValueError("system too long")
        return v

    @field_validator("max_tokens")
    @classmethod
    def _max(cls, v: int) -> int:
        if not 16 <= v <= MAX_TOKENS_LIMIT:
            raise ValueError(f"max_tokens must be 16..{MAX_TOKENS_LIMIT}")
        return v

    def content_hash(self) -> str:
        blob = json.dumps(
            [self.system, self.template, self.max_tokens, self.model], ensure_ascii=False
        )
        return hashlib.sha256(blob.encode()).hexdigest()


class PromptSet(BaseModel):
    tubeai_prompt_set: int
    id: str
    name: str
    version: str = ""
    prompts: list[Prompt] = Field(default_factory=list)

    @field_validator("tubeai_prompt_set")
    @classmethod
    def _fmt(cls, v: int) -> int:
        if v != SET_FORMAT_VERSION:
            raise ValueError(f"unsupported tubeai_prompt_set version {v}")
        return v

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("id must match [A-Za-z0-9._-]{1,64}")
        return v

    @field_validator("prompts")
    @classmethod
    def _prompts(cls, v: list[Prompt]) -> list[Prompt]:
        if not v:
            raise ValueError("a set needs at least one prompt")
        if len(v) > MAX_PROMPTS_PER_SET:
            raise ValueError("too many prompts")
        ids = [p.id for p in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate prompt ids")
        return v


def validate_prompt_set(data: Any) -> PromptSet:
    if not isinstance(data, dict):
        raise PromptError("prompt set must be a JSON object")
    try:
        return PromptSet.model_validate(data)
    except ValidationError as exc:
        parts = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise PromptError("; ".join(parts)) from exc


def render(text: str, values: dict[str, str]) -> str:
    return VAR_RE.sub(lambda m: values.get(m.group(1), ""), text)


BUILTIN_SET = PromptSet(
    tubeai_prompt_set=SET_FORMAT_VERSION,
    id=BUILTIN_SET_ID,
    name="Built-in",
    version="1",
    prompts=[
        Prompt(
            id="tldr",
            label="TL;DR",
            default=True,
            system=DEFAULT_SYSTEM,
            template=(
                "Title: {title}\nChannel: {channel}\nDuration: {duration}\n\n"
                "Transcript:\n{transcript}\n\n"
                "Give a TL;DR as 5 short bullet points (start each with '- '). Lead with the "
                "single most important takeaway. Max 900 characters total."
            ),
            max_tokens=700,
        ),
        Prompt(
            id="answer-title",
            label="Answer the title",
            system=DEFAULT_SYSTEM,
            template=(
                "Title: {title}\nChannel: {channel}\nDuration: {duration}\n\n"
                "Transcript:\n{transcript}\n\n"
                "The title may pose or imply a question. State that question, then answer it "
                "directly in 2-3 sentences using only what the video says. If the video never "
                "actually answers it, say so. If the title asks nothing, give a 2 sentence "
                "summary instead."
            ),
            max_tokens=400,
        ),
        Prompt(
            id="takeaways",
            label="Key takeaways + timestamps",
            system=DEFAULT_SYSTEM,
            template=(
                "Title: {title}\nDuration: {duration}\n\nTranscript (with [mm:ss] markers):\n"
                "{transcript}\n\n"
                "List the 5-8 key takeaways, each on its own line formatted as "
                "'[mm:ss] takeaway' using the nearest timestamp from the transcript. "
                "Keep each under 110 characters."
            ),
            max_tokens=900,
        ),
        Prompt(
            id="worth-it",
            label="Is it worth watching?",
            system=DEFAULT_SYSTEM,
            template=(
                "Title: {title}\nChannel: {channel}\nDuration: {duration}\n\n"
                "Transcript:\n{transcript}\n\n"
                "Decide if this video is worth the viewer's time. Start with 'Verdict: Watch', "
                "'Verdict: Skim' or 'Verdict: Skip'. Then give 3 short reasons, say roughly how "
                "much of the runtime is real substance versus filler, and name the best part's "
                "timestamp if there is one. Max 700 characters."
            ),
            max_tokens=600,
        ),
        Prompt(
            id="eli-new",
            label="Explain like I'm new",
            system=DEFAULT_SYSTEM,
            template=(
                "Title: {title}\nChannel: {channel}\n\nTranscript:\n{transcript}\n\n"
                "Explain what this video covers for someone with no background. Define any "
                "jargon in plain words, use one everyday analogy, and finish with one sentence "
                "on why it matters. Max 1000 characters."
            ),
            max_tokens=700,
        ),
    ],
)


class PromptStore:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = system_resolver,
    ):
        self.cfg, self.db = cfg, db
        self._transport = transport
        self._resolver = resolver

    def get_set(self, user: str, set_id: str) -> tuple[PromptSet, str | None] | None:
        if set_id == BUILTIN_SET_ID:
            return BUILTIN_SET, None
        row = self.db.one(
            "SELECT json, source_url FROM prompt_sets WHERE user=? AND set_id=?", [user, set_id]
        )
        if not row:
            return None
        return PromptSet.model_validate_json(row["json"]), row["source_url"]

    def list_sets(self, user: str) -> list[tuple[PromptSet, str | None]]:
        out: list[tuple[PromptSet, str | None]] = [(BUILTIN_SET, None)]
        rows = self.db.all(
            "SELECT json, source_url FROM prompt_sets WHERE user=? ORDER BY set_id", [user]
        )
        out.extend((PromptSet.model_validate_json(r["json"]), r["source_url"]) for r in rows)
        return out

    def default_key(self, user: str) -> str:
        row = self.db.one("SELECT prompt_key FROM user_default WHERE user=?", [user])
        if row and self.resolve(user, row["prompt_key"]):
            return row["prompt_key"]
        return DEFAULT_BUILTIN_KEY

    def resolve(self, user: str, key: str) -> Prompt | None:
        set_id, _, prompt_id = key.partition("/")
        found = self.get_set(user, set_id)
        if not found:
            return None
        return next((p for p in found[0].prompts if p.id == prompt_id), None)

    def save_set(self, user: str, pset: PromptSet, source_url: str | None = None) -> None:
        if pset.id == BUILTIN_SET_ID:
            raise PromptError("the builtin set cannot be replaced")
        self.db.execute(
            "INSERT OR REPLACE INTO prompt_sets(user,set_id,json,source_url,updated_at)"
            " VALUES(?,?,?,?,?)",
            [user, pset.id, pset.model_dump_json(), source_url, time.time()],
        )

    def delete_set(self, user: str, set_id: str) -> bool:
        if set_id == BUILTIN_SET_ID:
            raise PromptError("the builtin set cannot be deleted")
        found = self.get_set(user, set_id)
        if not found:
            return False
        self.db.execute("DELETE FROM prompt_sets WHERE user=? AND set_id=?", [user, set_id])
        row = self.db.one("SELECT prompt_key FROM user_default WHERE user=?", [user])
        if row and row["prompt_key"].startswith(f"{set_id}/"):
            self.db.execute("DELETE FROM user_default WHERE user=?", [user])
        return True

    def set_default(self, user: str, key: str) -> None:
        if not self.resolve(user, key):
            raise PromptError(f"unknown prompt {key}")
        self.db.execute(
            "INSERT OR REPLACE INTO user_default(user,prompt_key) VALUES(?,?)", [user, key]
        )

    async def fetch(self, url: str) -> PromptSet:
        limit = self.cfg.summary.max_import_bytes
        body = bytearray()
        try:
            async with guarded_get(
                url,
                allow_hosts=self.cfg.summary.import_allow_hosts,
                max_redirects=self.cfg.summary.import_max_redirects,
                timeout_s=self.cfg.summary.import_timeout_s,
                transport=self._transport,
                resolver=self._resolver,
            ) as resp:
                if resp.status_code >= 400:
                    raise PromptError(f"fetch failed: http {resp.status_code}")
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise PromptError(f"prompt set exceeds {limit} bytes")
        except UrlRejected as exc:
            raise PromptError(f"url not allowed: {exc}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("prompt import fetch failed: %s", type(exc).__name__)
            raise PromptError("fetch failed") from exc
        try:
            data = json.loads(bytes(body).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PromptError("not valid JSON") from exc
        return validate_prompt_set(data)

    async def import_url(self, user: str, url: str) -> PromptSet:
        pset = await self.fetch(url)
        self.save_set(user, pset, source_url=url)
        return pset

    async def refresh_all(self, user: str) -> dict[str, str]:
        rows = self.db.all(
            "SELECT set_id, source_url FROM prompt_sets WHERE user=? AND source_url IS NOT NULL",
            [user],
        )
        report: dict[str, str] = {}
        for row in rows:
            try:
                pset = await self.fetch(row["source_url"])
                if pset.id != row["set_id"]:
                    self.db.execute(
                        "DELETE FROM prompt_sets WHERE user=? AND set_id=?", [user, row["set_id"]]
                    )
                self.save_set(user, pset, source_url=row["source_url"])
                report[pset.id] = "ok"
            except PromptError as exc:
                report[row["set_id"]] = f"error: {exc}"
        return report

    def describe(self, user: str) -> dict[str, Any]:
        default = self.default_key(user)
        sets = []
        for pset, source_url in self.list_sets(user):
            sets.append(
                {
                    "id": pset.id,
                    "name": pset.name,
                    "version": pset.version,
                    "source_url": source_url,
                    "prompts": [
                        {
                            "id": p.id,
                            "key": f"{pset.id}/{p.id}",
                            "label": p.label,
                            "default": f"{pset.id}/{p.id}" == default,
                        }
                        for p in pset.prompts
                    ],
                }
            )
        return {"default": default, "sets": sets}
