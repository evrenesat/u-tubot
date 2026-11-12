from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, Request


class MockOpenAI:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.audio_calls: list[dict[str, Any]] = []
        self.delay_s = 0.0
        self.bad_json_first = 0
        self.mode = "plain"
        self.fail_status: int | None = None
        self.busy_first = 0
        self.busy_status = 503
        self.retry_after: str | None = None
        self.busy_models: set[str] = set()
        self.empty_first = 0
        self.finish_reason = "stop"
        self.active = 0
        self.max_active = 0
        self.app = self._build()

    def _build(self) -> FastAPI:
        app = FastAPI()

        @app.post("/v1/chat/completions")
        async def chat(request: Request):
            body = await request.json()
            self.calls.append(body)
            self.requests.append(
                {"host": request.headers.get("host"), "auth": request.headers.get("authorization")}
            )
            from fastapi.responses import JSONResponse

            if body["model"] in self.busy_models or self.busy_first > 0:
                if self.busy_first > 0 and body["model"] not in self.busy_models:
                    self.busy_first -= 1
                headers = {"Retry-After": self.retry_after} if self.retry_after else {}
                return JSONResponse(
                    {"error": {"code": "engine_busy"}},
                    status_code=self.busy_status,
                    headers=headers,
                )
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                if self.delay_s:
                    await asyncio.sleep(self.delay_s)
            finally:
                self.active -= 1
            if self.fail_status:
                return JSONResponse({"error": "boom"}, status_code=self.fail_status)
            message: dict[str, Any] = {"role": "assistant", "content": self.respond(body)}
            if self.empty_first > 0:
                self.empty_first -= 1
                message = {"role": "assistant", "content": "", "reasoning_content": "thinking..."}
            return {
                "choices": [{"index": 0, "message": message, "finish_reason": self.finish_reason}]
            }

        @app.post("/v1/audio/transcriptions")
        async def transcriptions(request: Request):
            form = await request.form()
            self.audio_calls.append({k: v for k, v in form.items() if k != "file"})
            return {
                "language": "english",
                "duration": 4.0,
                "text": "Hello there. How are you doing today?",
                "segments": [
                    {"start": 0.0, "end": 4.0, "text": " Hello there. How are you doing today?"}
                ],
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 0.5},
                    {"word": "there.", "start": 0.5, "end": 1.2},
                    {"word": "How", "start": 2.0, "end": 2.3},
                    {"word": "are", "start": 2.3, "end": 2.5},
                    {"word": "you", "start": 2.5, "end": 2.8},
                    {"word": "doing", "start": 2.8, "end": 3.3},
                    {"word": "today?", "start": 3.3, "end": 4.0},
                ],
            }

        return app

    def respond(self, body: dict[str, Any]) -> str:
        system = body["messages"][0]["content"]
        user = body["messages"][-1]["content"]
        if "triage YouTube videos" in system:
            return self._wrap(self._triage(body["messages"][1]["content"]))
        if "analyse a YouTube video from its transcript" in system:
            return self._wrap(
                json.dumps(
                    {"answer_short": "Yes, since v3.", "answer_confidence": 0.8, "essential_s": 120}
                )
            )
        if "analyse a YouTube video for a TV viewer" in system:
            return self._wrap(
                json.dumps(
                    {
                        "title_question": "Does it work?",
                        "answer": "Yes.",
                        "answer_confidence": 0.7,
                        "summary": "A summary.",
                        "key_points": ["a", "b"],
                        "essential_s": 100,
                    }
                )
            )
        if "condense one part" in system:
            return "notes: " + user[:40]
        if "Translate each subtitle" in system:
            return json.dumps([f"T:{t}" for t in json.loads(user)])
        if "answer a viewer's question" in system:
            return "ANSWER: forty-two"
        return f"SUMMARY[{body['model']}] " + user[-60:].replace("\n", " ")

    def _wrap(self, text: str) -> str:
        if self.bad_json_first > 0:
            self.bad_json_first -= 1
            return "I think the answer is: not json at all"
        if self.mode == "think":
            return f"<think>let me reason {{not json}}</think>\n{text}"
        if self.mode == "fence":
            return f"Here you go:\n```json\n{text}\n```\nHope it helps."
        return text

    def _triage(self, user: str) -> str:
        videos = json.loads(user.split("Videos: ", 1)[1])
        results = []
        for v in videos:
            title = v["title"]
            results.append(
                {
                    "id": v["id"],
                    "clickbait": 0.95 if "SHOCKING" in title else (0.7 if "BIT" in title else 0.1),
                    "low_quality": 0.8 if "slop" in title else 0.0,
                    "topics": ["reaction videos"] if "reaction" in title.lower() else [],
                    "title_question": title if title.endswith("?") else None,
                }
            )
        return json.dumps({"results": results})
