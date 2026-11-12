#!/usr/bin/env python3
"""A stand-in for the u-tubot backend, for checking the TV app on an emulator without a server, an LLM or a real YouTube video.

    python3 scripts/emulator_mock_backend.py --port 18790 [--static DIR] [--base http://10.0.2.2:18790]

The emulator reaches the host as 10.0.2.2. Point the app at it with Import setup (`10.0.2.2:18790`) or write the stored settings
(see docs/development.md, "Checking the TV app on an emulator"). It serves `/setup.json`, `POST /v1/pair`, `/v1/me`, `/v1/assess`
(every video "none"), `/v1/prompts`, summaries, insights, transcripts, and `/app/update.json` plus the files of `--static` under `/app/`.

The state of the summaries is changed while it runs:

    GET /__mock/set?mode=ready|needs_transcript|delayed|failed|auto_transcribe&delay=SECONDS[&delayed=N][&message=TEXT]
                   [&estimate=SECONDS][&retry_after=SECONDS][&progress=0.4]

`delay` holds every summary back that many seconds (to see the working indicator), `delayed` is how many answers of mode `delayed`
come before a ready one. After `POST /v1/videos/ID/transcribe` the video reports `transcribing`, 25% more with each
`GET /v1/videos/ID/transcript`, and then its summaries are ready. A video id that ends in 0 gets a summary without a "→ " first line.
`message` is the text of a `needs_transcript` answer or the `error` of a `delayed` one (the caption-limited wording of the real server,
for example), `estimate` is the `estimate_s` of a transcription, `retry_after` the `retry_after_s` of a `delayed` answer. Mode
`auto_transcribe` is the server's automatic policy: the first summary or insight request of a video starts the transcription itself and
answers `pending` + `transcribing` (at `progress`), without the app asking.
"""
import argparse
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DEFAULT_MESSAGE = "No captions. Transcribe the audio in the background?"
DEFAULT_DELAYED_ERROR = "YouTube is slowing us down, trying again shortly"
DEFAULT_ESTIMATE_S = 240
DEFAULT_RETRY_AFTER_S = 4
STATE = {"mode": "ready", "delay": 1.0, "delayed_left": 2, "progress": {}, "transcribing": set(), "message": None,
         "estimate": DEFAULT_ESTIMATE_S, "retry_after": DEFAULT_RETRY_AFTER_S, "start_progress": 0.0}
LOCK = threading.Lock()
PROMPTS = [
    ("glance", "Glance", False, True),
    ("tldr", "TL;DR", True, False),
    ("answer-title", "Answer the title", False, False),
    ("takeaways", "Key takeaways", False, False),
    ("worth-it", "Worth watching?", False, False),
    ("eli-new", "Explain like I'm new", False, False),
]
LONG = "\n\n".join(
    f"Paragraph {i}: the video walks through a topic in detail, with examples, a short digression and a recap "
    "that a viewer on a couch can read without squinting. It keeps going so that the text needs scrolling."
    for i in range(1, 14)
)


def prompt_list():
    prompts = [
        {"id": pid, "key": "builtin/" + pid, "label": label, "default": dflt, "panel_default": pd}
        for pid, label, dflt, pd in PROMPTS
    ]
    return {
        "default": "builtin/tldr",
        "panel_default": "builtin/glance",
        "sets": [{"id": "builtin", "name": "Built-in", "version": "1", "source_url": None, "prompts": prompts}],
    }


def summary(video_id, prompt, hints):
    mode = STATE["mode"]
    base = {"video_id": video_id, "prompt": "builtin/glance" if prompt == "panel" else prompt, "source": "youtube_captions", "error": None, "text": None}
    if mode == "auto_transcribe" and video_id not in STATE["transcribing"]:
        with LOCK:
            STATE["transcribing"].add(video_id)
            STATE["progress"][video_id] = STATE["start_progress"]
    if mode == "needs_transcript" and video_id not in STATE["transcribing"]:
        return {**base, "status": "needs_transcript", "transcript_status": "none", "can_transcribe": True,
                "message": STATE["message"] or DEFAULT_MESSAGE, "estimate_s": STATE["estimate"]}
    if mode == "delayed":
        with LOCK:
            if STATE["delayed_left"] > 0:
                STATE["delayed_left"] -= 1
                return {**base, "status": "pending", "transcript_status": "delayed",
                        "error": STATE["message"] or DEFAULT_DELAYED_ERROR,
                        "retry_after_s": STATE["retry_after"]}
    if video_id in STATE["transcribing"]:
        p = STATE["progress"].get(video_id, 0.0)
        if p < 1.0:
            return {**base, "status": "pending", "transcript_status": "transcribing", "progress": round(p, 2), "estimate_s": STATE["estimate"]}
    if mode == "failed":
        return {**base, "status": "failed", "error": "the language model request failed, try again later"}
    if prompt in ("panel", "builtin/glance"):
        text = "→ Yes, but only since version 3.\nA short gist of the video in a few plain words.\nThe second detail line sits here."
        if video_id.endswith("0"):
            text = "A plain summary without a question lead.\nIt has a second line.\nAnd a third one."
    else:
        text = f"[{prompt}]\n\n" + LONG
    return {**base, "status": "ready", "transcript_status": "ok", "text": text}


class Handler(BaseHTTPRequestHandler):
    server_version = "mock"
    protocol_version = "HTTP/1.1"
    static_dir = None
    base_url = ""

    def log_message(self, fmt, *args):
        print(time.strftime("%H:%M:%S"), self.command, self.path, flush=True)

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if url.path == "/v1/pair":
            return self.send_json({"token": "utb_emulator", "user": "emu"})
        if url.path == "/v1/assess":
            vids = json.loads(body or b"{}").get("videos", [])
            return self.send_json({"results": [
                {"video_id": v["video_id"], "status": "ready", "action": "none", "mark_label": None, "flags": [],
                 "title_question": None, "answer_short": None, "insight_ready": False, "captions_ready": False} for v in vids]})
        m = re.match(r"/v1/videos/([A-Za-z0-9_-]{11})/transcribe$", url.path)
        if m:
            vid = m.group(1)
            with LOCK:
                STATE["transcribing"].add(vid)
                STATE["progress"][vid] = 0.0
            return self.send_json({"video_id": vid, "status": "queued", "job_id": "job1", "transcript_status": "transcribing",
                                   "progress": 0.0, "estimate_s": STATE["estimate"]})
        return self.send_json({"error": "not found"}, 404)

    def do_PUT(self):
        return self.send_json({"ok": True})

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        path = url.path
        if path == "/__mock/set":
            with LOCK:
                if "mode" in q:
                    STATE["mode"] = q["mode"][0]
                    STATE["delayed_left"] = int(q.get("delayed", ["2"])[0])
                    STATE["transcribing"].clear()
                    STATE["progress"].clear()
                if "delay" in q:
                    STATE["delay"] = float(q["delay"][0])
                STATE["message"] = q["message"][0] if "message" in q else None
                STATE["estimate"] = int(q["estimate"][0]) if "estimate" in q else DEFAULT_ESTIMATE_S
                STATE["retry_after"] = int(q["retry_after"][0]) if "retry_after" in q else DEFAULT_RETRY_AFTER_S
                STATE["start_progress"] = float(q["progress"][0]) if "progress" in q else 0.0
            return self.send_json({k: (list(v) if isinstance(v, set) else v) for k, v in STATE.items()})
        if path == "/v1/health":
            return self.send_json({"ok": True, "version": "mock"})
        if path == "/setup.json":
            return self.send_json({"utubot_setup": 1, "name": "Emulator mock", "backend_url": self.base_url,
                                   "update_url": self.base_url + "/app/update.json", "pairing": True,
                                   "defaults": {"assess": True, "summary_panel": True}})
        if path == "/app/update.json":
            f = Path(self.static_dir or "/nonexistent") / "update.json"
            if self.static_dir and f.exists():
                body = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            return self.send_json({"error": "no update"}, 404)
        if path.startswith("/app/") and self.static_dir:
            f = Path(self.static_dir) / path[len("/app/"):]
            if f.is_file():
                size = f.stat().st_size
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.android.package-archive")
                self.send_header("Content-Length", str(size))
                self.end_headers()
                with f.open("rb") as fh:
                    while chunk := fh.read(65536):
                        self.wfile.write(chunk)
                return
            return self.send_json({"error": "not found"}, 404)
        if path == "/v1/me":
            return self.send_json({"user": "emu", "policy": {}, "features": {"assess": True, "insight": True, "captions": True}, "admin": False})
        if path == "/v1/prompts":
            return self.send_json(prompt_list())
        m = re.match(r"/v1/videos/([A-Za-z0-9_-]{11})/summary$", path)
        if m:
            time.sleep(STATE["delay"])
            return self.send_json(summary(m.group(1), (q.get("prompt") or ["builtin/tldr"])[0], q))
        m = re.match(r"/v1/videos/([A-Za-z0-9_-]{11})/transcript$", path)
        if m:
            vid = m.group(1)
            with LOCK:
                if vid in STATE["transcribing"]:
                    STATE["progress"][vid] = min(1.0, STATE["progress"].get(vid, 0.0) + 0.25)
                    p = STATE["progress"][vid]
                else:
                    p = None
            if p is None:
                return self.send_json({"video_id": vid, "transcript_status": "unknown", "source": None})
            if p >= 1.0:
                return self.send_json({"video_id": vid, "transcript_status": "ok", "source": "asr"})
            return self.send_json({"video_id": vid, "transcript_status": "transcribing", "progress": p, "estimate_s": STATE["estimate"]})
        m = re.match(r"/v1/videos/([A-Za-z0-9_-]{11})/insight$", path)
        if m:
            time.sleep(STATE["delay"])
            state = summary(m.group(1), "builtin/tldr", q)
            if state["status"] != "ready":
                return self.send_json({k: v for k, v in state.items() if k not in ("prompt", "text")})
            return self.send_json({"video_id": m.group(1), "status": "ready", "transcript_status": "ok", "answer": "Yes.", "summary": LONG,
                                   "key_points": ["a", "b"], "source": "youtube_captions"})
        if path.endswith("/captions"):
            return self.send_json({"status": "none", "progress": 0, "tracks": []})
        return self.send_json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--static", default=None)
    ap.add_argument("--base", default=None)
    args = ap.parse_args()
    Handler.static_dir = args.static
    Handler.base_url = args.base or f"http://10.0.2.2:{args.port}"
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
