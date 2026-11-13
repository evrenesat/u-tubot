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

HQ captions have a state of their own, per video, so they can be tried while the video plays:

    GET /__mock/captions?video=ID&state=none|queued|running|ready|failed[&after=SECONDS][&latency=SECONDS]

`state` sets the answer of `GET /v1/videos/ID/captions` at once; with `after` the answer stays `running` for that many seconds and then
becomes `ready` (a job that finishes while the video plays); `latency` holds every captions answer back that many seconds (captions that
come after the player opened its source). `POST /v1/videos/ID/captions` queues a job that is ready after `--captions-delay`
seconds (default 20). A ready answer lists the track `tr` ("Turkish (u·tubot)", `--lang` and `--label` change it) whose
`GET /v1/videos/ID/captions/tr.vtt` serves the file of `--vtt` (default `temp/captions.vtt` in the working directory). `--media DIR` serves
the files of DIR under `/media/` with byte ranges: the local stream the debug build's captions harness plays (docs/development.md).
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
CAPTIONS = {}
CAPTIONS_CONFIG = {"delay": 20.0, "lang": "tr", "label": "Turkish (u\u00b7tubot)", "vtt": Path("temp/captions.vtt"), "latency": 0.0}
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


def captions_answer(video_id):
    with LOCK:
        job = CAPTIONS.get(video_id)
    if job is None:
        return {"status": "none", "progress": 0, "tracks": []}
    state = job["state"]
    if state in ("queued", "running") and job.get("ready_at") is not None and time.time() >= job["ready_at"]:
        state = "ready"
    if state == "ready":
        lang = CAPTIONS_CONFIG["lang"]
        return {"status": "ready", "progress": 1.0, "tracks": [
            {"lang": lang, "label": CAPTIONS_CONFIG["label"], "url": f"/v1/videos/{video_id}/captions/{lang}.vtt", "speakers": 0}]}
    return {"status": state, "progress": 0.4 if state == "running" else 0.0, "tracks": []}


def start_captions_job(video_id, state="queued", after=None):
    with LOCK:
        CAPTIONS[video_id] = {"state": state, "ready_at": time.time() + (CAPTIONS_CONFIG["delay"] if after is None else after)}


class Handler(BaseHTTPRequestHandler):
    server_version = "mock"
    protocol_version = "HTTP/1.1"
    static_dir = None
    media_dir = None
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
        m = re.match(r"/v1/videos/([A-Za-z0-9_-]{11})/captions$", url.path)
        if m:
            vid = m.group(1)
            if captions_answer(vid)["status"] != "ready":
                start_captions_job(vid)
            return self.send_json({"status": captions_answer(vid)["status"], "job_id": "cap1", "eta_s": None})
        m = re.match(r"/v1/videos/([A-Za-z0-9_-]{11})/transcribe$", url.path)
        if m:
            vid = m.group(1)
            with LOCK:
                STATE["transcribing"].add(vid)
                STATE["progress"][vid] = 0.0
            return self.send_json({"video_id": vid, "status": "queued", "job_id": "job1", "transcript_status": "transcribing",
                                   "progress": 0.0, "estimate_s": STATE["estimate"]})
        return self.send_json({"error": "not found"}, 404)

    def send_media(self, f):
        """A local media file with byte ranges, the stream the harness plays in place of a video of YouTube"""
        if not f.is_file():
            return self.send_json({"error": "not found"}, 404)
        size = f.stat().st_size
        start, end, code = 0, size - 1, 200
        m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range") or "")
        if m and (m.group(1) or m.group(2)):
            if m.group(1):
                start = int(m.group(1))
                end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            else:
                start = max(size - int(m.group(2)), 0)
            code = 206
        self.send_response(code)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with f.open("rb") as fh:
            fh.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = fh.read(min(65536, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

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
        if path == "/__mock/captions":
            if "latency" in q:
                CAPTIONS_CONFIG["latency"] = float(q["latency"][0])
            if "video" not in q:
                return self.send_json({"latency": CAPTIONS_CONFIG["latency"]})
            vid = q["video"][0]
            state = q.get("state", ["none"])[0]
            with LOCK:
                if state == "none":
                    CAPTIONS.pop(vid, None)
                else:
                    CAPTIONS[vid] = {"state": state, "ready_at": None}
            if "after" in q:
                start_captions_job(vid, "running", float(q["after"][0]))
            return self.send_json(captions_answer(vid))
        if path == "/v1/health":
            return self.send_json({"ok": True, "version": "mock"})
        if path.startswith("/media/") and self.media_dir:
            return self.send_media(Path(self.media_dir) / Path(path[len("/media/"):]).name)
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
        m = re.match(r"/v1/videos/([A-Za-z0-9_-]{11})/captions$", path)
        if m:
            time.sleep(CAPTIONS_CONFIG["latency"])
            return self.send_json(captions_answer(m.group(1)))
        m = re.match(r"/v1/videos/([A-Za-z0-9_-]{11})/captions/([A-Za-z-]+)\.vtt$", path)
        if m:
            vtt = CAPTIONS_CONFIG["vtt"]
            if captions_answer(m.group(1))["status"] != "ready" or not vtt.is_file():
                return self.send_json({"error": "not found"}, 404)
            body = vtt.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/vtt; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return self.send_json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--static", default=None)
    ap.add_argument("--base", default=None)
    ap.add_argument("--media", default=None, help="folder served under /media/ (with byte ranges), for the captions harness of the debug build")
    ap.add_argument("--vtt", default=str(CAPTIONS_CONFIG["vtt"]), help="WebVTT file served as the HQ captions track")
    ap.add_argument("--lang", default=CAPTIONS_CONFIG["lang"])
    ap.add_argument("--label", default=CAPTIONS_CONFIG["label"])
    ap.add_argument("--captions-delay", type=float, default=CAPTIONS_CONFIG["delay"],
                    help="seconds a captions job queued by POST /v1/videos/ID/captions takes")
    args = ap.parse_args()
    CAPTIONS_CONFIG.update(vtt=Path(args.vtt), lang=args.lang, label=args.label, delay=args.captions_delay)
    Handler.static_dir = args.static
    Handler.media_dir = args.media
    Handler.base_url = args.base or f"http://10.0.2.2:{args.port}"
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
