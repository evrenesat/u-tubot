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

from .config import Config, LLMTask

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


class LLMBusyError(LLMError):
    """The endpoint kept answering busy (429/503/connection errors) until the deadline."""

    def __init__(self, message: str):
        super().__init__(message, failover=True)


class PriorityLimiter:
    """Slot limiter; interactive waiters go first, background keeps `reserve` slots free."""

    def __init__(self, limit: int, reserve: int = 0):
        self.limit = max(1, limit)
        self.reserve = max(0, min(reserve, self.limit - 1))
        self.in_use = 0
        self._waiters: list[tuple[int, int, asyncio.Future]] = []
        self._seq = itertools.count()

    def _free_for(self, priority: int) -> bool:
        cap = self.limit if priority == INTERACTIVE else self.limit - self.reserve
        return self.in_use < cap

    async def acquire(self, priority: int) -> None:
        if self._free_for(priority) and (priority == INTERACTIVE or not self._waiters):
            self.in_use += 1
            return
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiters, (priority, next(self._seq), fut))
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self.release()
            raise

    def release(self) -> None:
        self.in_use -= 1
        while self._waiters:
            priority, _, fut = self._waiters[0]
            if fut.done():
                heapq.heappop(self._waiters)
                continue
            if not self._free_for(priority):
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
    def __init__(self, cfg: Config, transport: httpx.AsyncBaseTransport | None = None):
        self.cfg = cfg
        self._limiters: dict[str, PriorityLimiter] = {}
        self._http = httpx.AsyncClient(timeout=cfg.llm.timeout_s, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    def limiter(self, provider: str) -> PriorityLimiter:
        lim = self._limiters.get(provider)
        if lim is None:
            pc = self.cfg.llm.providers[provider]
            lim = self._limiters[provider] = PriorityLimiter(
                pc.max_concurrent, pc.reserved_interactive
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

    def chain(self, task: LLMTask, model: str | None) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for name in [model or task.model, *task.fallback]:
            target = self.resolve(task, name)
            if target not in out:
                out.append(target)
        return out

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
        self, provider: str, body: dict[str, Any], priority: int, deadline_at: float
    ) -> httpx.Response:
        loop = asyncio.get_running_loop()
        llm = self.cfg.llm
        url = llm.providers[provider].base_url.rstrip("/") + "/chat/completions"
        limiter = self.limiter(provider)
        attempt = 0
        while True:
            try:
                await asyncio.wait_for(
                    limiter.acquire(priority), timeout=max(0.0, deadline_at - loop.time())
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
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        priority: int = BACKGROUND,
        json_mode: bool = False,
        deadline_s: float | None = None,
        deadline_at: float | None = None,
    ) -> Completion:
        llm = self.cfg.llm
        loop = asyncio.get_running_loop()
        if deadline_at is None:
            deadline_at = loop.time() + self.deadline_for(priority, deadline_s)
        chain = self.chain(task, model)
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
                resp = await self._call(provider, body, priority, loop.time() + share)
            except LLMError as exc:
                last = exc
                if not exc.failover or idx == len(chain) - 1:
                    raise
                log.warning("llm %s:%s failed (%s), trying fallback", provider, name, exc)
                continue
            return self._parse(resp)
        raise last or LLMError("no llm model configured")

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
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        priority: int = BACKGROUND,
        deadline_s: float | None = None,
    ) -> ChatResult:
        answer_budget = max_tokens or task.max_tokens
        deadline_at = asyncio.get_running_loop().time() + self.deadline_for(priority, deadline_s)
        done = await self.complete(
            task,
            messages,
            model=model,
            max_tokens=answer_budget,
            priority=priority,
            deadline_at=deadline_at,
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
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        priority: int = BACKGROUND,
        deadline_s: float | None = None,
    ) -> str:
        result = await self.chat_result(
            task,
            messages,
            model=model,
            max_tokens=max_tokens,
            priority=priority,
            deadline_s=deadline_s,
        )
        return result.text + CUT_MARK if result.truncated else result.text

    async def chat_json(
        self,
        task: LLMTask,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        priority: int = BACKGROUND,
        deadline_s: float | None = None,
    ) -> Any:
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
        raise LLMError(f"invalid JSON from model: {last}")
