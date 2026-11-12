from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from .bg import TaskRegistry, wait_task
from .config import Config, UserPolicy
from .db import Database
from .errors import public_error
from .llm import LLMClient
from .prompts import DEFAULT_SYSTEM, Prompt, PromptStore, render
from .transcripts import Transcript, TranscriptService, fmt_ts

NO_TRANSCRIPT = "(No transcript is available; rely on the title, channel and description only.)"
MAP_SYSTEM = (
    "You condense one part of a long video transcript into terse factual notes. Keep concrete "
    "claims, numbers, names and [mm:ss] markers. No commentary."
)
INSIGHT_SYSTEM = (
    "You analyse a YouTube video for a TV viewer. Return ONLY JSON: "
    '{"title_question":<string|null>,"answer":<2-3 sentences or null>,'
    '"answer_confidence":0-1,"summary":<plain text, max 1000 chars>,'
    '"key_points":[<3-6 short strings>],"essential_s":<seconds of unique useful content>}. '
    "Be faithful to the transcript. Reply text in {language}."
)
ASK_SYSTEM = (
    "You answer a viewer's question about a YouTube video using only its transcript. "
    "Be direct, at most 4 sentences. If the video does not say, say so. Reply in {language}."
)
TRUNCATION_MARK = "\n[... middle omitted ...]\n"
HEAD_FRACTION = 0.6
ADHOC_KEY = "adhoc"
ASK_CACHE_MAX = 500


def tokens_of(text: str, chars_per_token: int) -> int:
    return len(text) // chars_per_token


def truncate_smart(text: str, budget_chars: int) -> str:
    if len(text) <= budget_chars:
        return text
    head = int(budget_chars * HEAD_FRACTION)
    tail = budget_chars - head
    return text[:head] + TRUNCATION_MARK + text[-tail:]


def split_chunks(text: str, chunk_chars: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.split("\n"):
        if size + len(line) > chunk_chars and current:
            chunks.append("\n".join(current))
            current, size = [], 0
        while len(line) > chunk_chars:
            chunks.append(line[:chunk_chars])
            line = line[chunk_chars:]
        current.append(line)
        size += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


def clean_text(text: str) -> str:
    return text.strip()


class ContentService:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        llm: LLMClient,
        transcripts: TranscriptService,
        prompts: PromptStore,
    ):
        self.cfg, self.db, self.llm = cfg, db, llm
        self.transcripts, self.prompts = transcripts, prompts
        self.registry = TaskRegistry(cfg.summary.failure_cooldown_s)
        self._ask_results: dict[Any, str] = {}

    def wait_cap(self, wait_ms: int | None) -> int:
        s = self.cfg.summary
        return max(0, min(wait_ms if wait_ms is not None else s.default_wait_ms, s.wait_ms_cap))

    async def source(self, video_id: str, qmeta: dict[str, Any]) -> Transcript:
        try:
            transcript = await self.transcripts.get(video_id)
        except Exception:
            if not qmeta.get("title"):
                raise
            return Transcript(video_id, "", None, "metadata_only", dict(qmeta))
        for key, value in qmeta.items():
            transcript.meta.setdefault(key, value)
        return transcript

    async def condensed(self, transcript: Transcript) -> str:
        s = self.cfg.summary
        budget_chars = s.token_budget * s.chars_per_token
        text = transcript.text
        if len(text) <= budget_chars:
            return text
        if s.strategy == "truncate":
            return truncate_smart(text, budget_chars)
        row = self.db.one(
            "SELECT text FROM condensed WHERE video_id=? AND budget=?",
            [transcript.video_id, s.token_budget],
        )
        if row:
            return row["text"]
        chunks = split_chunks(text, s.chunk_tokens * s.chars_per_token)
        notes = await asyncio.gather(
            *(
                self.llm.chat(
                    self.cfg.llm.analysis,
                    [
                        {"role": "system", "content": MAP_SYSTEM},
                        {"role": "user", "content": f"Part {i + 1}/{len(chunks)}:\n{chunk}"},
                    ],
                    max_tokens=s.condensed_max_tokens,
                )
                for i, chunk in enumerate(chunks)
            )
        )
        merged = truncate_smart("\n\n".join(notes), budget_chars)
        self.db.execute(
            "INSERT OR REPLACE INTO condensed(video_id,budget,text,created_at) VALUES(?,?,?,?)",
            [transcript.video_id, s.token_budget, merged, time.time()],
        )
        return merged

    def _values(
        self, transcript: Transcript, body: str, policy: UserPolicy, question: str = ""
    ) -> dict[str, str]:
        meta = transcript.meta
        duration = meta.get("duration_s")
        return {
            "title": str(meta.get("title") or ""),
            "channel": str(meta.get("channel") or ""),
            "duration": fmt_ts(duration) if duration else "",
            "description": str(meta.get("description") or "")[:1500],
            "transcript": body or NO_TRANSCRIPT,
            "language": policy.language,
            "question": question,
        }

    def _title_question(self, video_id: str) -> str:
        row = self.db.one("SELECT json FROM triage WHERE video_id=? LIMIT 1", [video_id])
        return (json.loads(row["json"]).get("title_question") or "") if row else ""

    async def _generate(
        self, prompt: Prompt, transcript: Transcript, policy: UserPolicy, question: str = ""
    ) -> str:
        body = await self.condensed(transcript) if transcript.text else ""
        values = self._values(
            transcript, body, policy, question or self._title_question(transcript.video_id)
        )
        system = render(prompt.system or DEFAULT_SYSTEM, values)
        user = render(prompt.template, values)
        text = await self.llm.chat(
            self.cfg.llm.summary,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=prompt.model,
            max_tokens=prompt.max_tokens,
        )
        return clean_text(text)

    def _cached_summary(
        self, video_id: str, key: str, chash: str, language: str, ttl_s: float | None = None
    ):
        row = self.db.one(
            "SELECT text, source, created_at FROM summaries WHERE video_id=? AND prompt_key=?"
            " AND content_hash=? AND language=?",
            [video_id, key, chash, language],
        )
        if row and (ttl_s is None or time.time() - row["created_at"] <= ttl_s):
            return row
        return None

    async def summary(
        self,
        policy: UserPolicy,
        video_id: str,
        prompt: Prompt,
        key: str,
        qmeta: dict[str, Any],
        wait_ms: int | None,
        adhoc: bool = False,
    ) -> dict[str, Any]:
        chash = prompt.content_hash()
        store_key = ADHOC_KEY if adhoc else key
        ttl = self.cfg.summary.adhoc_ttl_s if adhoc else None
        base = {"video_id": video_id, "prompt": key, "text": None, "source": None, "error": None}
        hit = self._cached_summary(video_id, store_key, chash, policy.language, ttl)
        if hit:
            return {**base, "status": "ready", "text": hit["text"], "source": hit["source"]}
        task_key = ("summary", video_id, store_key, chash, policy.language)
        failure = self.registry.recent_failure(task_key)
        if failure:
            return {**base, "status": "failed", "error": failure}

        async def job() -> None:
            transcript = await self.source(video_id, qmeta)
            text = await self._generate(prompt, transcript, policy)
            self.db.execute(
                "INSERT OR REPLACE INTO summaries(video_id,prompt_key,content_hash,language,text,"
                "source,created_at) VALUES(?,?,?,?,?,?,?)",
                [video_id, store_key, chash, policy.language, text, transcript.source, time.time()],
            )

        task = self.registry.start(task_key, job)
        if not await wait_task(task, self.wait_cap(wait_ms)):
            return {**base, "status": "pending"}
        if task.exception() is not None:
            return {
                **base,
                "status": "failed",
                "error": public_error(task.exception(), "content task"),
            }
        hit = self._cached_summary(video_id, store_key, chash, policy.language)
        return {**base, "status": "ready", "text": hit["text"], "source": hit["source"]}

    async def insight(
        self, policy: UserPolicy, video_id: str, qmeta: dict[str, Any], wait_ms: int | None
    ) -> dict[str, Any]:
        base: dict[str, Any] = {
            "video_id": video_id,
            "error": None,
            "title_question": None,
            "answer": None,
            "answer_confidence": None,
            "summary": None,
            "key_points": [],
            "inflation": None,
            "source": None,
        }
        cached = self.db.get_json(
            "insights", "video_id=? AND language=?", [video_id, policy.language]
        )
        if cached:
            return {**base, **cached, "status": "ready"}
        task_key = ("insight", video_id, policy.language)
        failure = self.registry.recent_failure(task_key)
        if failure:
            return {**base, "status": "failed", "error": failure}

        async def job() -> None:
            transcript = await self.source(video_id, qmeta)
            body = await self.condensed(transcript) if transcript.text else ""
            values = self._values(transcript, body, policy)
            user = (
                f"Title: {values['title']}\nChannel: {values['channel']}\n"
                f"Duration seconds: {transcript.meta.get('duration_s')}\n"
                f"Description: {values['description']}\n\nTranscript:\n{values['transcript']}"
            )
            data = await self.llm.chat_json(
                self.cfg.llm.analysis,
                [
                    {"role": "system", "content": render(INSIGHT_SYSTEM, values)},
                    {"role": "user", "content": user},
                ],
            )
            if not isinstance(data, dict):
                raise ValueError("insight output is not an object")
            duration = transcript.meta.get("duration_s")
            inflation = None
            try:
                essential = float(data.get("essential_s"))
                if duration:
                    essential = max(0.0, min(essential, float(duration)))
                    inflation = {
                        "duration_s": int(duration),
                        "essential_s": int(essential),
                        "ratio": round(essential / duration, 3),
                    }
            except (TypeError, ValueError):
                pass
            points = [str(p) for p in (data.get("key_points") or []) if str(p).strip()]
            result = {
                "title_question": data.get("title_question") or None,
                "answer": data.get("answer") or None,
                "answer_confidence": data.get("answer_confidence"),
                "summary": str(data.get("summary") or "")[: self.cfg.summary.max_summary_chars],
                "key_points": points[:8],
                "inflation": inflation,
                "source": transcript.source,
            }
            self.db.execute(
                "INSERT OR REPLACE INTO insights(video_id,language,json,created_at) VALUES(?,?,?,?)",
                [video_id, policy.language, json.dumps(result), time.time()],
            )

        task = self.registry.start(task_key, job)
        if not await wait_task(task, self.wait_cap(wait_ms)):
            return {**base, "status": "pending"}
        if task.exception() is not None:
            return {
                **base,
                "status": "failed",
                "error": public_error(task.exception(), "content task"),
            }
        cached = self.db.get_json(
            "insights", "video_id=? AND language=?", [video_id, policy.language]
        )
        return {**base, **(cached or {}), "status": "ready"}

    async def ask(
        self,
        policy: UserPolicy,
        video_id: str,
        question: str,
        qmeta: dict[str, Any],
        wait_ms: int | None,
    ) -> dict[str, Any]:
        qhash = hashlib.sha256(question.encode()).hexdigest()[:16]
        task_key = ("ask", video_id, qhash, policy.language)
        results = self._ask_results

        async def job() -> None:
            transcript = await self.source(video_id, qmeta)
            body = await self.condensed(transcript) if transcript.text else ""
            values = self._values(transcript, body, policy, question)
            user = (
                f"Title: {values['title']}\nChannel: {values['channel']}\n\n"
                f"Transcript:\n{values['transcript']}\n\nQuestion: {question}"
            )
            if len(results) >= ASK_CACHE_MAX:
                results.clear()
            results[task_key] = await self.llm.chat(
                self.cfg.llm.answer,
                [
                    {"role": "system", "content": render(ASK_SYSTEM, values)},
                    {"role": "user", "content": user},
                ],
            )

        if task_key in results:
            return {"answer": results[task_key], "status": "ready"}
        task = self.registry.start(task_key, job)
        if not await wait_task(task, self.wait_cap(wait_ms)):
            return {"answer": None, "status": "pending"}
        if task.exception() is not None:
            return {
                "answer": None,
                "status": "failed",
                "error": public_error(task.exception(), "content task"),
            }
        return {"answer": results.get(task_key), "status": "ready"}
