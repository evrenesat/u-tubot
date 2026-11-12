from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any

from .bg import TaskRegistry, wait_task
from .config import TASK_ANALYSIS, TASK_ANSWER, Config, UserPolicy
from .db import Database
from .errors import public_error
from .llm import BACKGROUND, CUT_MARK, INTERACTIVE, ChatResult, LLMClient
from .prompts import DEFAULT_SYSTEM, TASK_GLANCE, TASK_SUMMARY, Prompt, PromptStore, render
from .transcribe import OK, Transcription
from .transcripts import Transcript, TranscriptService, fmt_ts

MAP_SYSTEM = (
    "You condense one part of a long video transcript into terse factual notes. Keep concrete "
    "claims, numbers, names and [mm:ss] markers. No commentary. If the video's title poses or "
    "implies a question, or teases a reveal or curiosity gap, put any passage of this part that "
    "answers or reveals it first, on a line starting 'ANSWER:' with the exact names, numbers and "
    "[mm:ss]. Write nothing about it when this part does not."
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
SUMMARY_TASK = "summary"
SUMMARY_BG_TASK = "summary-bg"


def summary_task_key(
    video_id: str, store_key: str, chash: str, language: str, priority: int
) -> tuple[str, str, str, str, str]:
    """Interactive and background runs of one summary are separate tasks with separate failures."""
    kind = SUMMARY_TASK if priority == INTERACTIVE else SUMMARY_BG_TASK
    return (kind, video_id, store_key, chash, language)


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
        transcription: Transcription,
    ):
        self.cfg, self.db, self.llm = cfg, db, llm
        self.transcripts, self.prompts, self.transcription = transcripts, prompts, transcription
        self.registry = TaskRegistry(cfg.summary.failure_cooldown_s)
        self._ask_results: dict[Any, tuple[str, float | None]] = {}
        self._auto_long_active = 0

    def _auto(
        self,
        fields: dict[str, Any],
        user: str | None,
        policy: UserPolicy,
        video_id: str,
        qmeta: dict[str, Any],
        passive: bool = False,
    ) -> dict[str, Any]:
        """`needs_transcript` becomes a started transcription when the user's policy allows it."""
        return self.transcription.auto(
            fields, user=user, policy=policy, video_id=video_id, hint=qmeta, passive=passive
        )

    def wait_cap(self, wait_ms: int | None) -> int:
        s = self.cfg.summary
        return max(0, min(wait_ms if wait_ms is not None else s.default_wait_ms, s.wait_ms_cap))

    async def source(
        self, video_id: str, qmeta: dict[str, Any], priority: int = INTERACTIVE
    ) -> Transcript:
        """The video's real transcript. Never a stand-in built from the title."""
        transcript = await self.transcripts.get(video_id, priority)
        for key, value in qmeta.items():
            transcript.meta.setdefault(key, value)
        return transcript

    async def condensed(self, transcript: Transcript, priority: int = INTERACTIVE) -> str:
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
        focus = self._focus(transcript)
        notes = await asyncio.gather(
            *(
                self.llm.chat_result(
                    self.cfg.llm.analysis,
                    [
                        {"role": "system", "content": MAP_SYSTEM},
                        {
                            "role": "user",
                            "content": f"{focus}Part {i + 1}/{len(chunks)}:\n{chunk}",
                        },
                    ],
                    max_tokens=s.condensed_max_tokens,
                    priority=priority,
                )
                for i, chunk in enumerate(chunks)
            )
        )
        merged = truncate_smart(
            "\n\n".join(n.text + CUT_MARK if n.truncated else n.text for n in notes), budget_chars
        )
        if not any(n.truncated for n in notes):
            self.db.execute(
                "INSERT OR REPLACE INTO condensed(video_id,budget,text,created_at) VALUES(?,?,?,?)",
                [transcript.video_id, s.token_budget, merged, time.time()],
            )
        return merged

    def _focus(self, transcript: Transcript) -> str:
        title = str(transcript.meta.get("title") or "")
        question = self._title_question(transcript.video_id)
        lines = [f"Video title: {title}\n"] if title else []
        if question:
            lines.append(f"Question the title poses: {question}\n")
        return "".join(lines) + ("\n" if lines else "")

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
            "transcript": body,
            "language": policy.language,
            "question": question,
        }

    def _title_question(self, video_id: str) -> str:
        row = self.db.one("SELECT json FROM triage WHERE video_id=? LIMIT 1", [video_id])
        return (json.loads(row["json"]).get("title_question") or "") if row else ""

    async def _generate(
        self,
        prompt: Prompt,
        transcript: Transcript,
        policy: UserPolicy,
        question: str = "",
        priority: int = INTERACTIVE,
    ) -> ChatResult:
        body = await self.condensed(transcript, priority)
        values = self._values(
            transcript, body, policy, question or self._title_question(transcript.video_id)
        )
        system = render(prompt.system or DEFAULT_SYSTEM, values)
        user = render(prompt.template, values)
        llm = self.cfg.llm
        task = llm.glance_task() if prompt.task == TASK_GLANCE else llm.summary
        result = await self.llm.chat_result(
            task,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=prompt.model,
            max_tokens=prompt.max_tokens,
            priority=priority,
        )
        return ChatResult(clean_text(result.text), result.truncated)

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

    def _find_summary(
        self, policy: UserPolicy, video_id: str, store_key: str, chash: str, adhoc: bool
    ):
        ttl = self.cfg.summary.adhoc_ttl_s if adhoc else None
        hit = self._cached_summary(video_id, store_key, chash, policy.language, ttl)
        if hit is None and not adhoc:
            hit = self._cached_summary(
                video_id, ADHOC_KEY, chash, policy.language, self.cfg.summary.adhoc_ttl_s
            )
        return hit

    def _start_summary(
        self,
        policy: UserPolicy,
        video_id: str,
        prompt: Prompt,
        store_key: str,
        chash: str,
        qmeta: dict[str, Any],
        priority: int,
    ) -> asyncio.Task:
        task_key = summary_task_key(video_id, store_key, chash, policy.language, priority)

        async def job() -> tuple[str, str]:
            transcript = await self.source(video_id, qmeta, priority)
            generated = await self._generate(prompt, transcript, policy, priority=priority)
            text = generated.text + CUT_MARK if generated.truncated else generated.text
            used_key = ADHOC_KEY if generated.truncated else store_key
            self.db.execute(
                "INSERT OR REPLACE INTO summaries(video_id,prompt_key,content_hash,language,text,"
                "source,created_at) VALUES(?,?,?,?,?,?,?)",
                [video_id, used_key, chash, policy.language, text, transcript.source, time.time()],
            )
            return text, transcript.source

        task = self.registry.start(task_key, job)
        if priority == INTERACTIVE:
            bg_key = summary_task_key(video_id, store_key, chash, policy.language, BACKGROUND)
            self.registry.cancel(bg_key)
        return task

    async def summary(
        self,
        policy: UserPolicy,
        video_id: str,
        prompt: Prompt,
        key: str,
        qmeta: dict[str, Any],
        wait_ms: int | None,
        adhoc: bool = False,
        *,
        user: str | None = None,
        passive: bool = False,
    ) -> dict[str, Any]:
        chash = prompt.content_hash()
        store_key = ADHOC_KEY if adhoc else key
        base = {
            "video_id": video_id,
            "prompt": key,
            "text": None,
            "source": None,
            "error": None,
            "transcript_status": None,
        }
        hit = self._find_summary(policy, video_id, store_key, chash, adhoc)
        if hit:
            return {
                **base,
                "status": "ready",
                "text": hit["text"],
                "source": hit["source"],
                "transcript_status": OK,
            }
        task_key = summary_task_key(video_id, store_key, chash, policy.language, INTERACTIVE)
        failure = self.registry.recent_failure(task_key)
        if failure:
            return {**base, "status": "failed", "error": failure}
        blocked = self.transcription.blocked(video_id, qmeta, promote=not passive)
        if blocked:
            return {**base, **self._auto(blocked, user, policy, video_id, qmeta, passive)}
        task = self._start_summary(policy, video_id, prompt, store_key, chash, qmeta, INTERACTIVE)
        if not await wait_task(task, self.wait_cap(wait_ms)):
            return {**base, "status": "pending"}
        exc = task.exception()
        if exc is not None:
            problem = self.transcription.problem(video_id, exc, qmeta)
            if problem:
                return {**base, **self._auto(problem, user, policy, video_id, qmeta, passive)}
            return {**base, "status": "failed", "error": public_error(exc, "content task")}
        text, source = task.result()
        return {**base, "status": "ready", "text": text, "source": source, "transcript_status": OK}

    @staticmethod
    def with_user_model(prompt: Prompt, policy: UserPolicy) -> Prompt:
        """The prompt as this user runs it: its own `model`, else the user's choice for its task.

        The model is part of the prompt's content hash, so summaries made with different models are
        cached apart.
        """
        task = TASK_GLANCE if prompt.task == TASK_GLANCE else TASK_SUMMARY
        chosen = policy.models.get(task)
        if prompt.model is None and chosen:
            return prompt.model_copy(update={"model": chosen})
        return prompt

    def auto_long_enabled(self, policy: UserPolicy) -> bool:
        if policy.auto_long is None:
            return self.cfg.summary.auto_long
        return policy.auto_long

    def schedule_long(
        self,
        user: str,
        policy: UserPolicy,
        video_id: str,
        qmeta: dict[str, Any],
        panel_key: str,
    ) -> bool:
        """Queue the user's default (long) summary at background priority after a panel summary."""
        if not self.auto_long_enabled(policy):
            return False
        key = self.prompts.default_key(user)
        prompt = self.prompts.resolve(user, key)
        if prompt is None or key == panel_key:
            return False
        prompt = self.with_user_model(prompt, policy)
        chash = prompt.content_hash()
        if self._find_summary(policy, video_id, key, chash, adhoc=False):
            return False
        if self._auto_long_active >= self.cfg.summary.auto_long_max_concurrent:
            return False
        for priority in (INTERACTIVE, BACKGROUND):
            task_key = summary_task_key(video_id, key, chash, policy.language, priority)
            if self.registry.running(task_key) or self.registry.recent_failure(task_key):
                return False
        task = self._start_summary(policy, video_id, prompt, key, chash, qmeta, BACKGROUND)
        self._auto_long_active += 1
        task.add_done_callback(self._auto_long_done)
        return True

    def _auto_long_done(self, _task: asyncio.Task) -> None:
        self._auto_long_active -= 1

    async def insight(
        self,
        policy: UserPolicy,
        video_id: str,
        qmeta: dict[str, Any],
        wait_ms: int | None,
        *,
        user: str | None = None,
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
            "transcript_status": None,
        }
        cached = self.db.get_json(
            "insights", "video_id=? AND language=?", [video_id, policy.language]
        )
        if cached:
            return {**base, **cached, "status": "ready", "transcript_status": OK}
        task_key = ("insight", video_id, policy.language)
        failure = self.registry.recent_failure(task_key)
        if failure:
            return {**base, "status": "failed", "error": failure}
        blocked = self.transcription.blocked(video_id, qmeta, promote=True)
        if blocked:
            return {**base, **self._auto(blocked, user, policy, video_id, qmeta)}

        async def job() -> None:
            transcript = await self.source(video_id, qmeta)
            body = await self.condensed(transcript)
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
                model=policy.models.get(TASK_ANALYSIS),
                priority=INTERACTIVE,
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
        exc = task.exception()
        if exc is not None:
            problem = self.transcription.problem(video_id, exc, qmeta)
            if problem:
                return {**base, **self._auto(problem, user, policy, video_id, qmeta)}
            return {**base, "status": "failed", "error": public_error(exc, "content task")}
        cached = self.db.get_json(
            "insights", "video_id=? AND language=?", [video_id, policy.language]
        )
        return {**base, **(cached or {}), "status": "ready", "transcript_status": OK}

    async def ask(
        self,
        policy: UserPolicy,
        video_id: str,
        question: str,
        qmeta: dict[str, Any],
        wait_ms: int | None,
        *,
        user: str | None = None,
    ) -> dict[str, Any]:
        qhash = hashlib.sha256(question.encode()).hexdigest()[:16]
        task_key = ("ask", video_id, qhash, policy.language, policy.models.get(TASK_ANSWER))
        results = self._ask_results

        async def job() -> str:
            transcript = await self.source(video_id, qmeta)
            body = await self.condensed(transcript)
            values = self._values(transcript, body, policy, question)
            user = (
                f"Title: {values['title']}\nChannel: {values['channel']}\n\n"
                f"Transcript:\n{values['transcript']}\n\nQuestion: {question}"
            )
            if len(results) >= ASK_CACHE_MAX:
                results.clear()
            answer = await self.llm.chat_result(
                self.cfg.llm.answer,
                [
                    {"role": "system", "content": render(ASK_SYSTEM, values)},
                    {"role": "user", "content": user},
                ],
                model=policy.models.get(TASK_ANSWER),
                priority=INTERACTIVE,
            )
            if answer.truncated:
                expires = time.time() + self.cfg.summary.adhoc_ttl_s
                results[task_key] = (answer.text + CUT_MARK, expires)
            else:
                results[task_key] = (answer.text, None)
            return results[task_key][0]

        base: dict[str, Any] = {"answer": None, "transcript_status": None}
        cached = results.get(task_key)
        if cached and (cached[1] is None or cached[1] > time.time()):
            return {**base, "answer": cached[0], "status": "ready", "transcript_status": OK}
        blocked = self.transcription.blocked(video_id, qmeta, promote=True)
        if blocked:
            return {**base, **self._auto(blocked, user, policy, video_id, qmeta)}
        task = self.registry.start(task_key, job)
        if not await wait_task(task, self.wait_cap(wait_ms)):
            return {**base, "status": "pending"}
        exc = task.exception()
        if exc is not None:
            problem = self.transcription.problem(video_id, exc, qmeta)
            if problem:
                return {**base, **self._auto(problem, user, policy, video_id, qmeta)}
            return {**base, "status": "failed", "error": public_error(exc, "content task")}
        return {**base, "answer": task.result(), "status": "ready", "transcript_status": OK}
