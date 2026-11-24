from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, Request

DESCRIBE_MARK = "You describe one moment of a video"


def _describe_system(body: dict[str, Any]) -> bool:
    system = body.get("messages", [{}])[0].get("content", "")
    return isinstance(system, str) and DESCRIBE_MARK in system


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(
        part.get("text", "")
        for part in content
        if isinstance(part, dict) and part.get("type") == "text"
    )


class MockOpenAI:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.requests: list[dict[str, Any]] = []
        self.audio_calls: list[dict[str, Any]] = []
        self.audio_filenames: list[str] = []
        self.audio_status: int | None = None
        self.audio_text: str = "Hello there. How are you doing today?"
        # How the transcription endpoint hands out word times: "top" (a top-level `words` list, the
        # OpenAI shape), "flag_nested" (words nested in each segment, and only when the form carries
        # `word_timestamps=true`, as the production mlx-audio server does) or "none".
        self.audio_words = "top"
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
        self.length_first = 0
        self.active = 0
        self.max_active = 0
        self.models = ["fast", "worker", "smart", "llama3.1:8b"]
        self.models_status = 200
        self.model_requests: list[dict[str, Any]] = []
        # Cut answers: `cut_answers` entries are popped per cut call (a dict, or a callable that
        # receives (system, user) and returns the parsed answer object); `cut_answer` is the default.
        self.cut_answer: Any = None
        self.cut_answers: list[Any] = []
        self.cut_calls: list[str] = []
        # Watched describe answers: one per grid in order; a callable gets (user text, images).
        self.describe_answer: Any = None
        self.describe_answers: list[Any] = []
        self.describe_calls: list[dict[str, Any]] = []
        self.describe_bad_json_first = 0
        self.describe_400_first = 0
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

            if self.describe_400_first > 0 and _describe_system(body):
                self.describe_400_first -= 1
                return JSONResponse({"error": "context too long"}, status_code=400)
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
            finish = self.finish_reason
            if self.length_first > 0:
                self.length_first -= 1
                finish = "length"
            return {"choices": [{"index": 0, "message": message, "finish_reason": finish}]}

        @app.get("/v1/models")
        async def models(request: Request):
            from fastapi.responses import JSONResponse

            self.model_requests.append({"auth": request.headers.get("authorization")})
            if self.models_status != 200:
                return JSONResponse({"error": "nope"}, status_code=self.models_status)
            return {
                "object": "list",
                "data": [{"id": m, "object": "model", "owned_by": "mock"} for m in self.models],
            }

        @app.post("/v1/audio/transcriptions")
        async def transcriptions(request: Request):
            form = await request.form()
            self.audio_calls.append({k: v for k, v in form.items() if k != "file"})
            file_part = form.get("file")
            self.audio_filenames.append(getattr(file_part, "filename", "") or "")
            if self.audio_status is not None:
                from fastapi.responses import JSONResponse

                return JSONResponse({"error": "boom"}, status_code=self.audio_status)
            words = [
                {"word": "Hello", "start": 0.0, "end": 0.5},
                {"word": "there.", "start": 0.5, "end": 1.2},
                {"word": "How", "start": 2.0, "end": 2.3},
                {"word": "are", "start": 2.3, "end": 2.5},
                {"word": "you", "start": 2.5, "end": 2.8},
                {"word": "doing", "start": 2.8, "end": 3.3},
                {"word": "today?", "start": 3.3, "end": 4.0},
            ]
            segments = [
                {"start": 0.0, "end": 4.0, "text": " Hello there. How are you doing today?"}
            ]
            body: dict[str, Any] = {
                "language": "english",
                "duration": 4.0,
                "text": self.audio_text,
                "segments": segments,
            }
            if self.audio_words == "top":
                body["words"] = words
            elif self.audio_words == "flag_nested" and form.get("word_timestamps") == "true":
                segments[0]["words"] = words
            return body

        return app

    def respond(self, body: dict[str, Any]) -> str:
        system = body["messages"][0]["content"]
        user = _text_of(body["messages"][-1]["content"])
        if _describe_system(body):
            return self._describe_respond(body)
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
        if "director's cut" in system:
            return self._wrap(json.dumps(self.cut_respond(system, user)))
        return f"SUMMARY[{body['model']}] " + user[-60:].replace("\n", " ")

    def _describe_respond(self, body: dict[str, Any]) -> str:
        content = body["messages"][-1]["content"]
        text = _text_of(content)
        images = (
            [
                part["image_url"]["url"]
                for part in content
                if isinstance(part, dict) and part.get("type") == "image_url"
            ]
            if isinstance(content, list)
            else []
        )
        self.describe_calls.append({"text": text, "images": images, "model": body["model"]})
        if self.describe_bad_json_first > 0:
            self.describe_bad_json_first -= 1
            return "not a json answer at all"
        if self.describe_answers:
            answer = self.describe_answers.pop(0)
        else:
            answer = self.describe_answer
        if callable(answer):
            answer = answer(text, images)
        if answer is not None:
            value = answer
        else:
            value = {
                "visual_summary": "A desk with a terminal; a build runs and stops.",
                "kind": "screen",
                "on_screen_text": "error: linker failed",
                "same_as_previous": False,
            }
        return json.dumps(value)

    def cut_respond(self, system: str, user: str) -> Any:
        self.cut_calls.append(user)
        if self.cut_answers:
            answer = self.cut_answers.pop(0)
        else:
            answer = self.cut_answer
        if callable(answer):
            return answer(system, user)
        if answer is not None:
            return answer
        return {
            "parts": [{"from": 1, "to": 1, "label": "Part 1"}],
            "summary": "Mock cut.",
            "kept_s": 10,
        }

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
