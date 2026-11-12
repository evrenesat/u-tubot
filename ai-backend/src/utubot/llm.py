from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from .config import Config, LLMTask

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
THINK_OPEN_RE = re.compile(r"^.*?</think>", re.DOTALL | re.IGNORECASE)
FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class LLMError(RuntimeError):
    pass


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
        self._sem = asyncio.Semaphore(cfg.llm.max_concurrency)
        self._http = httpx.AsyncClient(timeout=cfg.llm.timeout_s, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

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

    def _headers(self, provider: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        key = self.cfg.api_key(provider)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    async def chat(
        self,
        task: LLMTask,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        provider, model_name = self.resolve(task, model)
        body: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens or task.max_tokens,
            "temperature": task.temperature,
        }
        if task.reasoning_effort:
            body["reasoning_effort"] = task.reasoning_effort
        url = self.cfg.llm.providers[provider].base_url.rstrip("/") + "/chat/completions"
        async with self._sem:
            try:
                resp = await self._http.post(url, json=body, headers=self._headers(provider))
            except httpx.HTTPError as exc:
                raise LLMError(f"llm request failed: {exc}") from exc
        if resp.status_code >= 400:
            raise LLMError(f"llm http {resp.status_code}: {resp.text[:200]}")
        try:
            content = resp.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError("malformed llm response") from exc
        return strip_thinking(content)

    async def chat_json(
        self,
        task: LLMTask,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
    ) -> Any:
        attempts = 1 + self.cfg.llm.retries_on_bad_json
        convo = list(messages)
        last: Exception | None = None
        for _ in range(attempts):
            text = await self.chat(task, convo, model=model)
            try:
                return extract_json(text)
            except ValueError as exc:
                last = exc
                convo = [
                    *messages,
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": "Reply again with valid JSON only, no prose."},
                ]
        raise LLMError(f"invalid JSON from model: {last}")
