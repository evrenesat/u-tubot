from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any

from .bg import TaskRegistry
from .config import TASK_ANALYSIS, TASK_TRIAGE, Config, UserPolicy
from .db import Database
from .llm import BACKGROUND, LLMClient, LLMError
from .models import Flag, Verdict, VideoMeta
from .transcripts import NoCaptions, TranscriptService
from .youtube import FETCH_CLASSES, YoutubeDelayed

TRIAGE_SYSTEM = (
    "You triage YouTube videos for a TV viewer using only the title, channel and metadata. "
    'Return ONLY a JSON object: {"results":[{"id":<int>,"clickbait":0-1,"low_quality":0-1,'
    '"topics":[<matched topics>],"title_question":<string|null>}]}. '
    "clickbait = how much the title/thumbnail text withholds, exaggerates or misleads. "
    "low_quality = likelihood of low-effort, AI-generated narration slop, spam or filler. "
    "topics = ONLY entries copied verbatim from the user's topic list that the video clearly "
    "belongs to (empty list if none). "
    "title_question = the explicit or implied question the title poses, phrased as a question, "
    "null if the title asks nothing. One result per input id, no commentary."
)
DEEP_SYSTEM = (
    "You analyse a YouTube video from its transcript. Return ONLY JSON: "
    '{"answer_short":<string|null>,"answer_confidence":0-1,"essential_s":<number>}. '
    "answer_short = a one-sentence direct answer (max 140 chars) to the question the title poses, "
    "null if there is no question. essential_s = your estimate in seconds of how much of the "
    "video actually carries unique useful information, excluding intros, sponsor reads, "
    "repetition, filler and padding."
)
SHORT_MAX_DURATION_S = 90
SEC_PER_MIN = 60
LABEL_CLICKBAIT = "Clickbait"
LABEL_LOW_QUALITY = "Low quality"


def fmt_duration(seconds: float) -> str:
    if seconds < SHORT_MAX_DURATION_S:
        return f"{round(seconds)}s"
    return f"{round(seconds / SEC_PER_MIN)}m"


def topics_hash(topics: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(topics)).encode()).hexdigest()[:16]


def policy_hash(policy: UserPolicy) -> str:
    return hashlib.sha256(policy.model_dump_json().encode()).hexdigest()[:16]


def clamp(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def normalize_triage(item: dict[str, Any], topics: list[str]) -> dict[str, Any]:
    lookup = {t.lower(): t for t in topics}
    matched: list[str] = []
    for raw in item.get("topics") or []:
        canon = lookup.get(str(raw).strip().lower())
        if canon and canon not in matched:
            matched.append(canon)
    question = item.get("title_question")
    if not isinstance(question, str) or not question.strip() or question.strip().lower() == "null":
        question = None
    return {
        "clickbait": clamp(item.get("clickbait")),
        "low_quality": clamp(item.get("low_quality")),
        "topics": matched,
        "title_question": question.strip() if question else None,
    }


def build_verdict(
    policy: UserPolicy,
    video_id: str,
    triage: dict[str, Any] | None,
    deep: dict[str, Any] | None,
    duration_s: int | None,
    insight_ready: bool,
    captions_ready: bool,
) -> Verdict:
    if triage is None:
        return Verdict(video_id=video_id, status="pending")
    flags: list[Flag] = []
    hide = False
    label: str | None = None
    for topic in triage["topics"]:
        if topic in policy.hide_topics:
            hide = True
            flags.append(Flag(kind="topic", label=topic, severity=1.0, reason="hidden topic"))
        elif topic in policy.mark_topics:
            flags.append(Flag(kind="topic", label=topic, severity=0.7, reason="marked topic"))
            label = label or topic
    clickbait, low = triage["clickbait"], triage["low_quality"]
    if clickbait >= policy.hide_clickbait_above:
        hide = True
    if clickbait >= policy.mark_clickbait_above:
        flags.append(
            Flag(
                kind="clickbait",
                label=LABEL_CLICKBAIT,
                severity=clickbait,
                reason="title withholds or exaggerates",
            )
        )
        label = LABEL_CLICKBAIT
    if low >= policy.hide_low_quality_above:
        hide = True
    if low >= policy.mark_low_quality_above:
        flags.append(
            Flag(
                kind="low_quality",
                label=LABEL_LOW_QUALITY,
                severity=low,
                reason="likely low-effort content",
            )
        )
        label = label or LABEL_LOW_QUALITY
    answer = None
    if deep:
        answer = deep.get("answer_short")
        inflation = deep.get("inflation")
        if (
            inflation
            and inflation["duration_s"] >= policy.inflated_min_duration_s
            and inflation["ratio"] <= policy.mark_inflated_ratio_below
        ):
            text = (
                f"{fmt_duration(inflation['duration_s'])}≈{fmt_duration(inflation['essential_s'])}"
            )
            flags.append(
                Flag(
                    kind="inflated",
                    label="Inflated",
                    severity=1 - inflation["ratio"],
                    reason=f"about {text} of real content",
                )
            )
            label = f"Inflated · {text}"
    if policy.answer_in_label and answer and label:
        label = f"{label} · {answer}"
    action = "hide" if hide else ("mark" if flags else "none")
    return Verdict(
        video_id=video_id,
        status="ready",
        action=action,
        mark_label=label if action != "none" else None,
        flags=flags,
        title_question=triage["title_question"],
        answer_short=answer,
        insight_ready=insight_ready,
        captions_ready=captions_ready,
    )


class Assessor:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        llm: LLMClient,
        transcripts: TranscriptService,
    ):
        self.cfg, self.db, self.llm, self.transcripts = cfg, db, llm, transcripts
        self._inflight: dict[tuple[str, str], asyncio.Future] = {}
        self._bg = asyncio.Semaphore(cfg.assess.background_concurrency)
        self.tier2 = TaskRegistry()
        self._tasks: set[asyncio.Task] = set()
        self._pending: dict[tuple[str, str | None], list[VideoMeta]] = {}
        self._pending_topics: dict[tuple[str, str | None], list[str]] = {}

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _enqueue(
        self, videos: list[VideoMeta], topics: list[str], thash: str, model: str | None
    ) -> None:
        """Batches are shared between users with the same topics and the same triage model."""
        cfg = self.cfg.assess
        qkey = (thash, model)
        queue = self._pending.setdefault(qkey, [])
        self._pending_topics[qkey] = topics
        first = not queue
        queue.extend(videos)
        while len(queue) >= cfg.batch_size:
            batch, queue[:] = queue[: cfg.batch_size], queue[cfg.batch_size :]
            self._spawn(self._run_batch(batch, topics, thash, model))
        if not queue:
            return
        if cfg.coalesce_ms <= 0:
            self._flush(qkey)
        elif first:
            self._spawn(self._flush_later(qkey))

    async def _flush_later(self, qkey: tuple[str, str | None]) -> None:
        await asyncio.sleep(self.cfg.assess.coalesce_ms / 1000.0)
        self._flush(qkey)

    def _flush(self, qkey: tuple[str, str | None]) -> None:
        queue = self._pending.get(qkey)
        if not queue:
            return
        batch = list(queue)
        queue.clear()
        self._spawn(self._run_batch(batch, self._pending_topics[qkey], qkey[0], qkey[1]))

    def _cached_triage(self, video_id: str, thash: str) -> dict[str, Any] | None:
        return self.db.get_json(
            "triage",
            "video_id=? AND topics_hash=?",
            [video_id, thash],
            ttl_s=self.cfg.assess.triage_cache_ttl_s,
        )

    def _deep(self, video_id: str) -> dict[str, Any] | None:
        return self.db.get_json("deep", "video_id=?", [video_id])

    def _flags(self, video_id: str) -> tuple[bool, bool]:
        ins = self.db.one("SELECT 1 FROM insights WHERE video_id=?", [video_id])
        cap = self.db.one("SELECT 1 FROM captions WHERE video_id=?", [video_id])
        return ins is not None, cap is not None

    def verdict_for(self, user: str, policy: UserPolicy, video: VideoMeta) -> Verdict:
        thash = topics_hash([*policy.hide_topics, *policy.mark_topics])
        meta_duration = video.duration_s
        if meta_duration is None:
            meta_duration = (self.transcripts.cached_meta(video.video_id) or {}).get("duration_s")
        deep = self._deep(video.video_id)
        if deep and deep.get("inflation") and meta_duration:
            deep["inflation"]["duration_s"] = meta_duration
        insight, captions = self._flags(video.video_id)
        verdict = build_verdict(
            policy,
            video.video_id,
            self._cached_triage(video.video_id, thash),
            deep,
            meta_duration,
            insight,
            captions,
        )
        if verdict.status == "ready":
            self.db.execute(
                "INSERT OR REPLACE INTO verdicts(user,video_id,policy_hash,json,updated_at)"
                " VALUES(?,?,?,?,?)",
                [user, video.video_id, policy_hash(policy), verdict.model_dump_json(), time.time()],
            )
        return verdict

    async def assess(
        self, user: str, policy: UserPolicy, videos: list[VideoMeta], wait_ms: int
    ) -> list[Verdict]:
        cfg = self.cfg.assess
        wait_ms = max(0, min(wait_ms, cfg.wait_ms_cap))
        topics = [*policy.hide_topics, *policy.mark_topics]
        thash = topics_hash(topics)
        for video in videos:
            self._remember_meta(video)
        waiting: list[asyncio.Future] = []
        todo: list[VideoMeta] = []
        seen: set[str] = set()
        for video in videos:
            if video.video_id in seen:
                continue
            seen.add(video.video_id)
            if self._cached_triage(video.video_id, thash) is not None:
                continue
            key = (video.video_id, thash)
            fut = self._inflight.get(key)
            if fut is None:
                fut = asyncio.get_running_loop().create_future()
                fut.add_done_callback(lambda f: f.exception() if not f.cancelled() else None)
                self._inflight[key] = fut
                todo.append(video)
            waiting.append(fut)
        if todo:
            self._enqueue(todo, topics, thash, policy.models.get(TASK_TRIAGE))
        if waiting and wait_ms:
            await asyncio.wait(waiting, timeout=wait_ms / 1000.0)
        results = []
        for video in videos:
            verdict = self.verdict_for(user, policy, video)
            results.append(verdict)
            self._maybe_schedule_tier2(user, policy, video, verdict)
        return results

    def _remember_meta(self, video: VideoMeta) -> None:
        data = video.model_dump(exclude_none=True)
        if len(data) > 1:
            self.transcripts.store_meta(video.video_id, data)

    async def _run_batch(
        self, batch: list[VideoMeta], topics: list[str], thash: str, model: str | None = None
    ) -> None:
        keys = [(v.video_id, thash) for v in batch]
        try:
            async with self._bg:
                results = await self._triage_call(batch, topics, model)
            for idx, video in enumerate(batch):
                item = results.get(idx)
                if item is None:
                    continue
                self.db.execute(
                    "INSERT OR REPLACE INTO triage(video_id,topics_hash,json,created_at)"
                    " VALUES(?,?,?,?)",
                    [video.video_id, thash, json.dumps(item), time.time()],
                )
        except (LLMError, ValueError):
            pass
        finally:
            for key in keys:
                fut = self._inflight.pop(key, None)
                if fut and not fut.done():
                    fut.set_result(None)

    async def _triage_call(
        self, batch: list[VideoMeta], topics: list[str], model: str | None = None
    ) -> dict[int, dict[str, Any]]:
        cfg = self.cfg.assess
        payload = []
        for idx, v in enumerate(batch):
            payload.append(
                {
                    "id": idx,
                    "title": (v.title or "")[: cfg.title_max_chars],
                    "channel": v.channel,
                    "duration_s": v.duration_s,
                    "published": v.published,
                    "views": v.views,
                    "description": (v.description or "")[: cfg.description_max_chars] or None,
                }
            )
        user_msg = (
            f"User topic list: {json.dumps(topics, ensure_ascii=False)}\n"
            f"Videos: {json.dumps(payload, ensure_ascii=False)}"
        )
        data = await self.llm.chat_json(
            self.cfg.llm.triage,
            [{"role": "system", "content": TRIAGE_SYSTEM}, {"role": "user", "content": user_msg}],
            model=model,
        )
        items = data.get("results") if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ValueError("triage output is not a list")
        out: dict[int, dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(batch):
                out[idx] = normalize_triage(item, topics)
        return out

    def _tier2_wanted(self, policy: UserPolicy, triage: dict[str, Any]) -> bool:
        return bool(
            triage.get("title_question")
            or triage["clickbait"] >= self.cfg.assess.tier2_clickbait_threshold
        )

    def _maybe_schedule_tier2(
        self, user: str, policy: UserPolicy, video: VideoMeta, verdict: Verdict
    ) -> None:
        if verdict.status != "ready" or self._deep(video.video_id) is not None:
            return
        thash = topics_hash([*policy.hide_topics, *policy.mark_topics])
        triage = self._cached_triage(video.video_id, thash)
        if triage is None or not self._tier2_wanted(policy, triage):
            return
        if self.tier2.running(video.video_id) or self.tier2.recent_failure(video.video_id):
            return
        if not self._tier2_gate_ok(video.video_id):
            return
        meta = self.transcripts.cached_meta(video.video_id) or {}
        duration = video.duration_s or meta.get("duration_s")
        if (
            video.is_live
            or video.is_short
            or (duration and duration > self.cfg.transcripts.skip_if_longer_than_s)
        ):
            return
        day = self._take_tier2_slot(user)
        if day is None:
            return
        task = self.tier2.start(
            video.video_id,
            lambda: self._tier2_job(
                user, day, video.video_id, triage, duration, policy.models.get(TASK_ANALYSIS)
            ),
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _tier2_gate_ok(self, video_id: str) -> bool:
        """Background transcript work only while YouTube is happy and nothing useless would run."""
        gate = self.transcripts.gate
        if not gate.healthy(*FETCH_CLASSES):
            return False
        if self.transcripts.cached(video_id) is not None:
            return True
        if self.transcripts.no_captions(video_id) or self.transcripts.hold(video_id):
            return False
        return gate.background_waiting() < self.cfg.youtube.max_background_queue

    def _take_tier2_slot(self, user: str) -> str | None:
        """Count one analysis for today; returns the day taken, None when the cap is reached."""
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        row = self.db.one("SELECT count FROM tier2_usage WHERE user=? AND day=?", [user, day])
        used = row["count"] if row else 0
        if used >= self.cfg.assess.tier2_daily_cap_per_user:
            return None
        self.db.execute(
            "INSERT OR REPLACE INTO tier2_usage(user,day,count) VALUES(?,?,?)",
            [user, day, used + 1],
        )
        return day

    def _refund_tier2_slot(self, user: str, day: str) -> None:
        self.db.execute(
            "UPDATE tier2_usage SET count=MAX(count-1, 0) WHERE user=? AND day=?", [user, day]
        )

    async def _tier2_job(
        self,
        user: str,
        day: str,
        video_id: str,
        triage: dict[str, Any],
        duration: int | None,
        model: str | None = None,
    ) -> None:
        """A delayed fetch (429, cooldown, network) never reached YouTube's data: give the slot back."""
        try:
            await self._deep_analysis(video_id, triage, duration, model)
        except YoutubeDelayed:
            self._refund_tier2_slot(user, day)
            raise

    async def _deep_analysis(
        self, video_id: str, triage: dict[str, Any], duration: int | None, model: str | None = None
    ) -> None:
        try:
            transcript = await self.transcripts.get(video_id, BACKGROUND)
        except NoCaptions:
            return
        async with self._bg:
            meta = transcript.meta
            duration = duration or meta.get("duration_s")
            budget_chars = self.cfg.summary.token_budget * self.cfg.summary.chars_per_token
            text = transcript.text
            if len(text) > budget_chars:
                half = budget_chars // 2
                text = text[:half] + "\n[...]\n" + text[-half:]
            user_msg = (
                f"Title: {meta.get('title')}\nChannel: {meta.get('channel')}\n"
                f"Duration seconds: {duration}\nTitle question: {triage.get('title_question')}\n\n"
                f"Transcript:\n{text}"
            )
            data = await self.llm.chat_json(
                self.cfg.llm.analysis,
                [{"role": "system", "content": DEEP_SYSTEM}, {"role": "user", "content": user_msg}],
                model=model,
            )
        if not isinstance(data, dict):
            raise ValueError("deep analysis is not an object")
        answer = data.get("answer_short")
        deep: dict[str, Any] = {
            "answer_short": answer.strip() if isinstance(answer, str) and answer.strip() else None,
            "answer_confidence": clamp(data.get("answer_confidence")),
            "inflation": None,
        }
        try:
            essential = float(data.get("essential_s"))
        except (TypeError, ValueError):
            essential = None
        if essential is not None and duration:
            essential = max(0.0, min(essential, float(duration)))
            deep["inflation"] = {
                "duration_s": int(duration),
                "essential_s": int(essential),
                "ratio": round(essential / duration, 3),
            }
        self.db.execute(
            "INSERT OR REPLACE INTO deep(video_id,json,created_at) VALUES(?,?,?)",
            [video_id, json.dumps(deep), time.time()],
        )

    async def drain(self) -> None:
        while True:
            pending = [t for t in self._tasks if not t.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)
