from __future__ import annotations

import asyncio
import heapq
import itertools
import json
import logging
import random
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from .classes import NORMAL, RANK, current_class, normalize_class
from .config import DEFAULT_PROVIDER, Config, LLMTask
from .db import Database
from .feature import FeatureStore, cost_for, run_accumulate
from .usage import (
    METRIC_LLM_CALLS,
    METRIC_LLM_COMPLETION_TOKENS,
    METRIC_LLM_ERRORS,
    METRIC_LLM_PROMPT_TOKENS,
    Usage,
)

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
THINK_OPEN_RE = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)
FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


log = logging.getLogger("utubot.llm")

INTERACTIVE = 0
BACKGROUND = 1
RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
HTTP_ERROR_FLOOR = 400
HTTP_SERVER_ERROR_FLOOR = 500
JITTER_LOW = 0.5
TRUNCATION_RETRY_FACTOR = 2
CUT_MARK = " …"
MIN_HTTP_TIMEOUT_S = 0.001
JSON_NUDGE = "Reply with JSON only, no prose, no reasoning."
RETRYABLE_TRANSPORT = (httpx.NetworkError, httpx.ConnectTimeout, httpx.RemoteProtocolError)


class LLMError(RuntimeError):
    """Model call failed. `failover` means another model may still succeed."""

    def __init__(self, message: str, *, failover: bool = False):
        super().__init__(message)
        self.failover = failover


class LLMBadJSONError(LLMError):
    """The model kept answering with text that holds no JSON (after the JSON nudges)."""


class LLMBusyError(LLMError):
    """The endpoint kept answering busy (429/503/connection errors) until the deadline."""

    def __init__(self, message: str):
        super().__init__(message, failover=True)


class PriorityLimiter:
    """Slot limiter; prime waiters, then interactive ones, go first.

    `reserve` keeps background work off some slots and `reserved_prime` keeps normal work off one
    more, so a prime request never waits for normal work to drain.
    """

    def __init__(self, limit: int, reserve: int = 0, reserved_prime: int = 0):
        self.limit = max(1, limit)
        self.reserve = max(0, min(reserve, self.limit - 1))
        self.reserved_prime = max(0, min(reserved_prime, self.limit - 1))
        self.in_use = 0
        self._waiters: list[tuple[int, int, int, asyncio.Future]] = []
        self._seq = itertools.count()

    def _free_for(self, priority: int, klass: str) -> bool:
        if klass == "prime":
            return self.in_use < self.limit
        cap = self.limit - self.reserved_prime
        if priority != INTERACTIVE:
            cap -= self.reserve
        return self.in_use < max(1, min(self.limit, cap))

    @staticmethod
    def _rank(priority: int, klass: str) -> tuple[int, int]:
        return RANK[klass], priority

    async def acquire(self, priority: int, klass: str = NORMAL) -> None:
        klass = normalize_class(klass)
        key = self._rank(priority, klass)
        ahead = any(
            ((w_class_rank, w_priority) <= key and not fut.done())
            for w_class_rank, w_priority, _, fut in self._waiters
        )
        if self._free_for(priority, klass) and not ahead:
            self.in_use += 1
            return
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (key[0], key[1], next(self._seq), fut))
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self.release()
            raise

    def release(self) -> None:
        self.in_use -= 1
        while self._waiters:
            class_rank, priority, _, fut = self._waiters[0]
            if fut.done():
                heapq.heappop(self._waiters)
                continue
            klass = "prime" if class_rank == RANK["prime"] else NORMAL
            if not self._free_for(priority, klass):
                return
            heapq.heappop(self._waiters)
            self.in_use += 1
            fut.set_result(None)


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def error_code_suffix(resp: httpx.Response) -> str:
    try:
        err = resp.json()["error"]
        code = err.get("code") if isinstance(err, dict) else None
    except (KeyError, ValueError, TypeError, AttributeError):
        return ""
    return f" (code={str(code)[:60]})" if code else ""


@dataclass
class ChatResult:
    text: str
    truncated: bool


@dataclass
class Completion:
    text: str
    reasoning: bool
    finish_reason: str | None


def strip_thinking(text: str) -> str:
    text = THINK_RE.sub("", text)
    if "</think>" in text.lower():
        text = THINK_OPEN_RE.sub("", text)
    return text.strip()


def extract_json(text: str) -> Any:
    text = strip_thinking(text)
    candidates = [text]
    candidates.extend(m.strip() for m in FENCE_RE.findall(text))
    for cand in candidates:
        try:
            return json.loads(cand)
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    for idx, ch in enumerate(text):
        if ch in "[{":
            try:
                value, _ = decoder.raw_decode(text[idx:])
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found in model output")


class LLMClient:
    def __init__(
        self,
        cfg: Config,
        transport: httpx.AsyncBaseTransport | None = None,
        db: Database | None = None,
    ):
        self.cfg = cfg
        self.usage = Usage(db)
        self.features = FeatureStore(cfg, db)
        self._limiters: dict[str, PriorityLimiter] = {}
        self._http = httpx.AsyncClient(timeout=cfg.llm.timeout_s, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    def limiter(self, provider: str) -> PriorityLimiter:
        lim = self._limiters.get(provider)
        if lim is None:
            pc = self.cfg.llm.providers[provider]
            # A slot kept for prime only makes sense with the class system; without `[classes]`
            # the route model is used exactly as before, so no slot is reserved.
            reserved_prime = pc.reserved_prime if self.cfg.classes_configured else 0
            lim = self._limiters[provider] = PriorityLimiter(
                pc.max_concurrent, pc.reserved_interactive, reserved_prime
            )
        return lim

    def resolve(self, task: LLMTask, model: str | None) -> tuple[str, str]:
        providers = self.cfg.llm.providers
        provider = task.provider or self.cfg.llm.default_provider
        name = model or task.model
        prefix, sep, rest = name.partition(":")
        if sep and prefix in providers:
            provider, name = prefix, rest
        if provider not in providers:
            raise LLMError(f"unknown llm provider {provider}")
        return provider, name

    def effective_model(self, task: LLMTask, model: str | None, feature: str | None) -> str:
        """The model a run starts with: an explicit one (a prompt or per-user choice) wins, else the
        admin's per-feature override, else the config.toml model. The override only replaces the
        default, so a caller that names a model is routed exactly as before."""
        if model:
            return model
        if feature:
            override = self.features.override_for(feature)
            if override:
                return override
        return task.model

    def chain(
        self, task: LLMTask, model: str | None, feature: str | None = None
    ) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for name in [self.effective_model(task, model, feature), *task.fallback]:
            target = self.resolve(task, name)
            if target not in out:
                out.append(target)
        return out

    @staticmethod
    def alias_value(provider: str, name: str) -> str:
        """The alias the admin sees and picks (what `GET /v1/models` shows): the bare model on the
        default provider, `provider:model` otherwise."""
        return name if provider == DEFAULT_PROVIDER else f"{provider}:{name}"

    def headroom(self, task: LLMTask) -> int:
        override = task.reasoning_headroom_tokens
        return self.cfg.llm.reasoning_headroom_tokens if override is None else override

    def deadline_for(self, priority: int, deadline_s: float | None) -> float:
        if deadline_s is not None:
            return deadline_s
        llm = self.cfg.llm
        return llm.deadline_interactive_s if priority == INTERACTIVE else llm.deadline_background_s

    def _headers(self, provider: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self.cfg.api_key(provider)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        llm = self.cfg.llm
        delay = min(llm.retry_max_s, llm.retry_base_s * 2**attempt)
        delay *= random.uniform(JITTER_LOW, 1.0)
        return max(delay, retry_after or 0.0)

    async def _call(
        self,
        provider: str,
        body: dict[str, Any],
        priority: int,
        deadline_at: float,
        klass: str | None = None,
    ) -> httpx.Response:
        klass = normalize_class(klass if klass is not None else current_class())
        loop = asyncio.get_running_loop()
        llm = self.cfg.llm
        url = llm.providers[provider].base_url.rstrip("/") + "/chat/completions"
        limiter = self.limiter(provider)
        attempt = 0
        while True:
            try:
                await asyncio.wait_for(
                    limiter.acquire(priority, klass), timeout=max(0.0, deadline_at - loop.time())
                )
            except TimeoutError as exc:
                raise LLMBusyError("llm slot wait exceeded deadline") from exc
            retry_after: float | None = None
            try:
                resp = await self._http.post(
                    url,
                    json=body,
                    headers=self._headers(provider),
                    timeout=max(MIN_HTTP_TIMEOUT_S, min(llm.timeout_s, deadline_at - loop.time())),
                )
            except RETRYABLE_TRANSPORT as exc:
                reason = f"connection error {type(exc).__name__}"
            except httpx.HTTPError as exc:
                raise LLMError(f"llm request failed: {type(exc).__name__}", failover=True) from exc
            else:
                if resp.status_code in RETRYABLE_STATUS:
                    reason = f"http {resp.status_code}"
                    retry_after = parse_retry_after(resp.headers.get("retry-after"))
                elif resp.status_code >= HTTP_ERROR_FLOOR:
                    raise LLMError(
                        f"llm http {resp.status_code}{error_code_suffix(resp)}",
                        failover=resp.status_code >= HTTP_SERVER_ERROR_FLOOR,
                    )
                else:
                    return resp
            finally:
                limiter.release()
            attempt += 1
            delay = self._backoff(attempt - 1, retry_after)
            if attempt >= llm.retry_max_attempts or loop.time() + delay > deadline_at:
                raise LLMBusyError(f"llm busy after {attempt} attempts ({reason})")
            log.info("llm %s %s, retry %d in %.1fs", provider, reason, attempt, delay)
            await asyncio.sleep(delay)

    async def complete(
        self,
        task: LLMTask,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        priority: int = BACKGROUND,
        json_mode: bool = False,
        deadline_s: float | None = None,
        deadline_at: float | None = None,
        klass: str | None = None,
        feature: str | None = None,
    ) -> Completion:
        klass = normalize_class(klass if klass is not None else current_class())
        llm = self.cfg.llm
        loop = asyncio.get_running_loop()
        started = loop.time()
        if deadline_at is None:
            deadline_at = loop.time() + self.deadline_for(priority, deadline_s)
        chain = self.chain(task, model, feature)
        last: LLMError | None = None
        for idx, (provider, name) in enumerate(chain):
            body: dict[str, Any] = {
                "model": name,
                "messages": messages,
                "max_tokens": (max_tokens or task.max_tokens) + self.headroom(task),
                "temperature": task.temperature,
            }
            if task.reasoning_effort:
                body["reasoning_effort"] = task.reasoning_effort
            if json_mode and llm.providers[provider].json_mode:
                body["response_format"] = {"type": "json_object"}
            share = (deadline_at - loop.time()) / (len(chain) - idx)
            try:
                resp = await self._call(provider, body, priority, loop.time() + share, klass)
            except LLMError as exc:
                self.usage.add(METRIC_LLM_ERRORS)
                last = exc
                if not exc.failover or idx == len(chain) - 1:
                    raise
                log.warning("llm %s:%s failed (%s), trying fallback", provider, name, exc)
                continue
            prompt_tokens, completion_tokens = self._count(resp)
            alias = self.alias_value(provider, name)
            elapsed_ms = max(0, int((loop.time() - started) * 1000))
            cost = cost_for(self.cfg, alias, prompt_tokens, completion_tokens)
            self.features.usage.record(
                feature, alias, elapsed_ms, prompt_tokens, completion_tokens, cost
            )
            run_accumulate(cost)
            return self._parse(resp)
        raise last or LLMError("no llm model configured")

    def _count(self, resp: httpx.Response) -> tuple[int, int]:
        self.usage.add(METRIC_LLM_CALLS)
        try:
            usage = resp.json().get("usage") or {}
            prompt = int(usage.get("prompt_tokens") or 0)
            completion = int(usage.get("completion_tokens") or 0)
        except (ValueError, TypeError, AttributeError):
            return 0, 0
        self.usage.add(METRIC_LLM_PROMPT_TOKENS, prompt)
        self.usage.add(METRIC_LLM_COMPLETION_TOKENS, completion)
        return prompt, completion

    async def list_models(self, provider: str, timeout_s: float) -> list[str]:
        """Model ids a provider's `GET <base_url>/models` lists; errors carry no URL or key."""
        url = self.cfg.llm.providers[provider].base_url.rstrip("/") + "/models"
        try:
            resp = await self._http.get(url, headers=self._headers(provider), timeout=timeout_s)
        except httpx.HTTPError as exc:
            raise LLMError(f"unreachable ({type(exc).__name__})") from None
        if resp.status_code >= HTTP_ERROR_FLOOR:
            raise LLMError(f"http {resp.status_code}")
        try:
            data = resp.json()
            items = data["data"] if isinstance(data, dict) and "data" in data else data
            ids = [i["id"] if isinstance(i, dict) else i for i in items]
        except (ValueError, KeyError, TypeError):
            raise LLMError("unreadable model list") from None
        return [i for i in ids if isinstance(i, str) and i]

    @staticmethod
    def _parse(resp: httpx.Response) -> Completion:
        try:
            choice = resp.json()["choices"][0]
            message = choice["message"]
            content = message.get("content") or ""
        except (KeyError, IndexError, ValueError, TypeError, AttributeError) as exc:
            raise LLMError("malformed llm response") from exc
        reasoning = bool(message.get("reasoning_content") or message.get("reasoning"))
        finish = choice.get("finish_reason")
        return Completion(strip_thinking(content), reasoning, finish)

    async def chat_result(
        self,
        task: LLMTask,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        priority: int = BACKGROUND,
        deadline_s: float | None = None,
        klass: str | None = None,
        feature: str | None = None,
    ) -> ChatResult:
        klass = normalize_class(klass if klass is not None else current_class())
        answer_budget = max_tokens or task.max_tokens
        deadline_at = asyncio.get_running_loop().time() + self.deadline_for(priority, deadline_s)
        done = await self.complete(
            task,
            messages,
            model=model,
            max_tokens=answer_budget,
            priority=priority,
            deadline_at=deadline_at,
            klass=klass,
            feature=feature,
        )
        if done.finish_reason == "length":
            log.warning("llm output kind=truncated retry=1 reasoning=%s", done.reasoning)
            try:
                done = await self.complete(
                    task,
                    messages,
                    model=model,
                    max_tokens=answer_budget * TRUNCATION_RETRY_FACTOR,
                    priority=priority,
                    deadline_at=deadline_at,
                    klass=klass,
                    feature=feature,
                )
            except LLMError as exc:
                if not done.text:
                    raise
                log.warning("llm truncation retry failed (%s), keeping first answer", exc)
        truncated = done.finish_reason == "length"
        if not done.text:
            kind = "truncated" if truncated else "empty"
            log.warning("llm output unusable kind=%s reasoning_only=%s", kind, done.reasoning)
            raise LLMError(f"model returned no answer ({kind})")
        if truncated:
            log.warning("llm output kind=truncated retry=exhausted")
        return ChatResult(done.text, truncated)

    async def chat(
        self,
        task: LLMTask,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        priority: int = BACKGROUND,
        deadline_s: float | None = None,
        klass: str | None = None,
        feature: str | None = None,
    ) -> str:
        result = await self.chat_result(
            task,
            messages,
            model=model,
            max_tokens=max_tokens,
            priority=priority,
            deadline_s=deadline_s,
            klass=klass,
            feature=feature,
        )
        return result.text + CUT_MARK if result.truncated else result.text

    async def chat_json(
        self,
        task: LLMTask,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        priority: int = BACKGROUND,
        deadline_s: float | None = None,
        klass: str | None = None,
        feature: str | None = None,
    ) -> Any:
        klass = normalize_class(klass if klass is not None else current_class())
        llm = self.cfg.llm
        attempts = 1 + llm.retries_on_bad_json
        convo = list(messages)
        max_tokens: int | None = None
        last = "unknown"
        deadline_at = asyncio.get_running_loop().time() + self.deadline_for(priority, deadline_s)
        for _ in range(attempts):
            done = await self.complete(
                task,
                convo,
                model=model,
                max_tokens=max_tokens,
                priority=priority,
                json_mode=True,
                deadline_at=deadline_at,
                klass=klass,
                feature=feature,
            )
            try:
                return extract_json(done.text)
            except ValueError:
                pass
            truncated = done.finish_reason == "length"
            last = "truncated" if truncated else ("empty" if not done.text else "no-json")
            log.warning(
                "llm json failure kind=%s finish_reason=%s reasoning_only=%s",
                last,
                done.finish_reason,
                done.reasoning and not done.text,
            )
            max_tokens = max(llm.json_retry_max_tokens, task.max_tokens)
            convo = [*messages]
            if done.text and not truncated:
                convo.append({"role": "assistant", "content": done.text})
            convo.append({"role": "user", "content": JSON_NUDGE})
        raise LLMBadJSONError(f"invalid JSON from model: {last}")
