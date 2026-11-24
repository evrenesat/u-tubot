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

Director's cuts work like the real ones (ai/CONTRACT.md "Director's cuts"): four presets, requests that build (ready after
`--cuts-delay` seconds, default 8) or wait for the phone, a cut document whose skips sit at 25-45% and 70-85% of the video:

    POST /v1/videos/ID/cuts                {"preset"} | {"prompt"} | {"await_prompt":true}
    GET  /v1/videos/ID/cuts                the presets and their states
    GET  /v1/cuts/REQUEST?wait_ms=N        the request, long-polled while waiting or building
    GET  /v1/cut-requests                  the queue; PUT/DELETE /v1/cut-requests/REQUEST fill and dismiss
    GET /__mock/cuts?video=ID&state=ready|none|failed[&preset=ID][&duration=MS][&stage=model]
                                           a ready cut without a request (the TV announces it when the video opens)
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
         "reason": None, "panel_status": None,
         "estimate": DEFAULT_ESTIMATE_S, "retry_after": DEFAULT_RETRY_AFTER_S, "start_progress": 0.0}
LOCK = threading.Lock()
CAPTIONS = {}
CAPTIONS_CONFIG = {"delay": 20.0, "lang": "tr", "label": "Turkish (u\u00b7tubot)", "vtt": Path("temp/captions.vtt"), "latency": 0.0}
CUT_PRESETS = [
    ("cut-no-filler", "No filler"),
    ("cut-answer", "Just the answer"),
    ("cut-demo", "Only the demo"),
    ("cut-highlights-5", "Highlights in 5 min"),
]
CUTS_CONFIG = {"delay": 8.0, "stage": "model"}
CUT_REQUESTS = {}
CUT_READY = {}
CUT_LOCK = threading.RLock()
REQUESTS = []
REQUEST_LOCK = threading.Lock()
HOLD = {"path": None, "until": 0.0}
HOLD_LOCK = threading.Lock()
ASSESS_CONFIG = {"verdicts": {}, "delay": 0.0, "fail": 0}
DEFAULT_PROMPT_KEY = "builtin/tldr"
IMPORTED_SETS = {}
PROCESSED_CONFIG = {"state": "items"}
PORT = None
SETUP_CONFIG = {"backend": None}
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
    sets = [{"id": "builtin", "name": "Built-in", "version": "1", "source_url": None, "prompts": prompts}]
    sets.extend(IMPORTED_SETS.values())
    return {
        "default": DEFAULT_PROMPT_KEY,
        "panel_default": "builtin/glance",
        "sets": sets,
    }


def all_prompt_keys():
    return {prompt["key"] for prompt in prompt_list()["sets"][0]["prompts"]} | {
        prompt["key"] for prompt_set in IMPORTED_SETS.values() for prompt in prompt_set["prompts"]
    }


def import_prompt_set(url):
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    set_id = parts[-1] if parts else "imported"
    prompt_set = {
        "id": set_id,
        "name": set_id,
        "version": "1",
        "source_url": url,
        "prompts": [{"id": "main", "key": f"{set_id}/main", "label": set_id, "default": False, "panel_default": False}],
    }
    IMPORTED_SETS[set_id] = prompt_set
    return prompt_set


def verdict(video):
    video_id = video["video_id"]
    custom = ASSESS_CONFIG["verdicts"].get(video_id)
    if custom is None:
        return {"video_id": video_id, "status": "ready", "action": "none", "mark_label": None, "flags": [],
                "title_question": None, "answer_short": None, "insight_ready": False, "captions_ready": False}
    return {"video_id": video_id, "status": custom.get("status", "ready"), "action": custom.get("action", "none"),
            "mark_label": custom.get("label") if custom.get("action") == "mark" else None, "flags": [],
            "title_question": None, "answer_short": custom.get("answer"), "insight_ready": False,
            "captions_ready": False}


def processed_items():
    thumbnail = f"http://127.0.0.1:{PORT}/__mock/thumb/{{}}.png"
    first = {
        "video_id": "dQw4w9WgXcQ", "title": "A processed video", "thumbnail": thumbnail.format("dQw4w9WgXcQ"),
        "updated_at": 1763900000.0, "summary": True,
        "captions": [{"job_id": "capA", "lang": "tr", "translate_to": "en", "state": "ready", "progress": 1.0,
                      "error": None, "created_at": 1763899900.0, "updated_at": 1763900000.0}],
        "cuts": [{"request_id": "cutA", "state": "ready", "preset_id": "cut-demo", "preset_label": "Only the demo",
                  "prompt": None, "error": None, "created_at": 1763899800.0, "updated_at": 1763899900.0}],
    }
    second = {
        "video_id": "9bZkp7q19f0", "title": "Another processed video", "thumbnail": thumbnail.format("9bZkp7q19f0"),
        "updated_at": 1763890000.0, "summary": False,
        "captions": [{"job_id": "capB", "lang": "en", "translate_to": "en", "state": "processing", "progress": 0.4,
                      "error": None, "created_at": 1763889900.0, "updated_at": 1763890000.0}],
        "cuts": [],
    }
    return {"videos": [first, second]}


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
        answer = {**base, "status": "failed", "error": "the language model request failed, try again later"}
        if STATE["reason"] is not None:
            answer["reason"] = STATE["reason"]
        return answer
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


# ---- director's cuts -----------------------------------------------------------------------


def cut_state_now(request):
    """The state of a request at this moment: a build that is past its delay is ready"""
    state = request["state"]
    if state in ("waiting", "building") and request.get("ready_at") is not None and time.time() >= request["ready_at"]:
        return "ready"
    return state


def cut_document(duration_ms, video_id, label="No filler", preset_id="cut-no-filler"):
    """A cut of a video of duration_ms: keeps 0-25%, 45-70% and 85-100%, skips the rest"""
    part = [
        (0, round(duration_ms * 0.25), "Start"),
        (round(duration_ms * 0.45), round(duration_ms * 0.70), "Middle"),
        (round(duration_ms * 0.85), duration_ms, "End"),
    ]
    skip = [[round(duration_ms * 0.25), round(duration_ms * 0.45)], [round(duration_ms * 0.70), round(duration_ms * 0.85)]]
    return {
        "version": 1,
        "video_id": video_id,
        "transcript_hash": "mock",
        "duration_ms": duration_ms,
        "label": label,
        "summary": "A cut of the emulator's test video.",
        "parts": [{"label": l, "start_ms": s, "end_ms": e} for s, e, l in part],
        "skip_ranges_ms": skip,
        "kept_ms": duration_ms - sum(t - f for f, t in skip),
        "source": "youtube_captions",
        "preset_id": preset_id,
        "model": "cutmodel",
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def cut_request_doc(request, wait=False):
    """The request document; with wait=True the answer is held while the request waits or builds (the long poll)"""
    deadline = time.time() + wait / 1000.0 if wait else 0.0
    while True:
        with CUT_LOCK:
            state = cut_state_now(request)
            doc = {
                "id": request["id"],
                "video_id": request["video_id"],
                "state": state,
                "source": request["source"],
                "preset_id": request.get("preset_id"),
                "prompt": request.get("prompt"),
                "error": request.get("error"),
                "created_at": request["created_at"],
                "updated_at": request.get("updated_at", request["created_at"]),
            }
            if request.get("title"):
                doc["title"] = request["title"]
            if request.get("channel"):
                doc["channel"] = request["channel"]
            if request.get("duration_s"):
                doc["duration_s"] = request["duration_s"]
            if state in ("waiting", "building"):
                doc["stage"] = CUTS_CONFIG["stage"] if state == "building" else "transcript"
            if state == "ready":
                doc["cut"] = cut_document(request.get("duration_ms", 240000), request["video_id"],
                                          label=cut_label(request), preset_id=request.get("preset_id"))
            if state == "failed":
                doc["error"] = request.get("error") or "the cut could not be built"
        if state in ("waiting", "building") and time.time() < deadline:
            time.sleep(0.05)
            continue
        return doc


def cut_label(request):
    for pid, label in CUT_PRESETS:
        if pid == request.get("preset_id"):
            return label
    return "Your cut"


def preset_state(video_id, preset_id):
    """The state of a preset for a video: its request's, else the ready cut the __mock control set"""
    with CUT_LOCK:
        for request in CUT_REQUESTS.values():
            if request["video_id"] == video_id and request.get("preset_id") == preset_id:
                return cut_state_now(request)
        ready = CUT_READY.get(video_id)
        if ready and (ready["preset_id"] is None or ready["preset_id"] == preset_id):
            return "ready"
    return "none"


def record_request(handler):
    url = urlparse(handler.path)
    if url.path.startswith("/__mock/"):
        return
    with REQUEST_LOCK:
        REQUESTS.append({
            "method": handler.command,
            "path": url.path,
            "query": url.query,
            "authorization": bool(handler.headers.get("Authorization")),
            "cookie": bool(handler.headers.get("Cookie")),
            "origin": bool(handler.headers.get("Origin")),
        })


def hold_request(path):
    with HOLD_LOCK:
        prefix = HOLD["path"]
        until = HOLD["until"]
    while prefix and path.startswith(prefix) and time.time() < until:
        time.sleep(0.02)


class Handler(BaseHTTPRequestHandler):
    server_version = "mock"
    protocol_version = "HTTP/1.1"
    static_dir = None
    media_dir = None
    base_url = ""
    user_name = "emu"

    def log_message(self, fmt, *args):
        print(time.strftime("%H:%M:%S"), self.command, self.path, flush=True)

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        url = urlparse(self.path)
        record_request(self)
        return self.send_json({"error": "method not allowed"}, 405)

    def do_POST(self):
        url = urlparse(self.path)
        record_request(self)
        hold_request(url.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if url.path == "/v1/pair":
            return self.send_json({"token": "utb_emulator", "user": self.user_name})
        if url.path == "/v1/assess":
            time.sleep(ASSESS_CONFIG["delay"])
            if ASSESS_CONFIG["fail"]:
                return self.send_json({"error": "the assess request failed"}, ASSESS_CONFIG["fail"])
            vids = json.loads(body or b"{}").get("videos", [])
            return self.send_json({"results": [verdict(v) for v in vids]})
        if url.path == "/v1/prompts/import":
            return self.send_json(import_prompt_set(json.loads(body or b"{}").get("url", "")))
        if url.path == "/v1/prompts/refresh":
            return self.send_json({"ok": True})
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
        m = re.match(r"/v1/videos/([A-Za-z0-9_-]{11})/cuts$", url.path)
        if m:
            return self.post_cut(m.group(1), parse_qs(url.query), json.loads(body or b"{}"))
        return self.send_json({"error": "not found"}, 404)

    def post_cut(self, vid, q, body):
        await_prompt = bool(body.get("await_prompt"))
        preset = body.get("preset")
        prompt = body.get("prompt")
        with CUT_LOCK:
            for request in CUT_REQUESTS.values():
                if request["video_id"] != vid or cut_state_now(request) in ("ready", "failed", "dismissed"):
                    continue
                same = (request.get("await_prompt") and await_prompt) or (not await_prompt and (
                        (preset and request.get("preset_id") == preset) or (prompt and request.get("prompt") == prompt)))
                if same:
                    return self.send_json({"request_id": request["id"], "state": cut_state_now(request)})
            rid = "cut%d" % (len(CUT_REQUESTS) + 1)
            request = {
                "id": rid, "video_id": vid, "state": "waiting" if await_prompt else "building",
                "source": "TV", "preset_id": preset, "prompt": prompt, "await_prompt": await_prompt,
                "title": (q.get("title") or [None])[0], "channel": (q.get("channel") or [None])[0],
                "duration_s": float((q.get("duration_s") or [0])[0] or 0) or None,
                "duration_ms": int(float((q.get("duration_s") or [0])[0] or 240) * 1000),
                "ready_at": None if await_prompt else time.time() + CUTS_CONFIG["delay"],
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            CUT_REQUESTS[rid] = request
        return self.send_json({"request_id": rid, "state": request["state"]})

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
        url = urlparse(self.path)
        record_request(self)
        hold_request(url.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if url.path == "/v1/prompts/default":
            key = (body.get("key") or "").strip()
            if key not in all_prompt_keys():
                return self.send_json({"error": "unknown prompt"}, 404)
            global DEFAULT_PROMPT_KEY
            DEFAULT_PROMPT_KEY = key
            return self.send_json({"default": key})
        m = re.match(r"/v1/cut-requests/([a-z0-9]+)$", url.path)
        if m:
            with CUT_LOCK:
                request = CUT_REQUESTS.get(m.group(1))
                if request is None:
                    return self.send_json({"error": "not found"}, 404)
                if request["state"] != "waiting" or cut_state_now(request) != "waiting":
                    return self.send_json({"error": "the request is not waiting any more"}, 409)
                prompt = (body.get("prompt") or "").strip()
                if not prompt:
                    return self.send_json({"error": "the prompt is empty"}, 400)
                request["prompt"] = prompt
                request["state"] = "building"
                request["ready_at"] = time.time() + CUTS_CONFIG["delay"]
            return self.send_json(cut_request_doc(request))
        return self.send_json({"ok": True})

    def do_DELETE(self):
        url = urlparse(self.path)
        if url.path == "/v1/prompts/default":
            key = (body.get("key") or "").strip()
            if key not in all_prompt_keys():
                return self.send_json({"error": "unknown prompt"}, 404)
            global DEFAULT_PROMPT_KEY
            DEFAULT_PROMPT_KEY = key
            return self.send_json({"default": key})
        m = re.match(r"/v1/cut-requests/([a-z0-9]+)$", url.path)
        if m:
            with CUT_LOCK:
                request = CUT_REQUESTS.get(m.group(1))
                if request is None:
                    return self.send_json({"error": "not found"}, 404)
                request["state"] = "dismissed"
                request["ready_at"] = None
            return self.send_json(cut_request_doc(request))
        return self.send_json({"error": "not found"}, 404)

    def do_GET(self):
        url = urlparse(self.path)
        record_request(self)
        hold_request(url.path)
        q = parse_qs(url.query)
        path = url.path
        if path == "/__mock/requests":
            if q.get("clear", ["0"])[0] == "1":
                with REQUEST_LOCK:
                    REQUESTS.clear()
                return self.send_json({"requests": []})
            with REQUEST_LOCK:
                return self.send_json({"requests": list(REQUESTS)})
        if path == "/__mock/hold":
            prefix = q.get("path", [""])[0]
            seconds = float(q.get("seconds", ["0"])[0] or 0)
            with HOLD_LOCK:
                HOLD["path"] = prefix or None
                HOLD["until"] = time.time() + seconds if (prefix and seconds > 0) else 0.0
            return self.send_json({"path": HOLD["path"], "seconds": seconds})
        if path == "/__mock/assess":
            with REQUEST_LOCK:
                if "delay" in q:
                    ASSESS_CONFIG["delay"] = float(q["delay"][0])
                if "fail" in q:
                    ASSESS_CONFIG["fail"] = int(q["fail"][0])
                if "video" in q:
                    video = q["video"][0]
                    action = q.get("action", ["none"])[0]
                    ASSESS_CONFIG["verdicts"][video] = {
                        "action": action,
                        "status": q.get("status", ["ready"])[0],
                        "label": q.get("label", [None])[0],
                        "answer": q.get("answer", [None])[0],
                    }
                return self.send_json({"delay": ASSESS_CONFIG["delay"], "fail": ASSESS_CONFIG["fail"],
                                       "verdicts": dict(ASSESS_CONFIG["verdicts"])})
        if path == "/__mock/setup":
            setup_q = parse_qs(url.query, keep_blank_values=True)
            if "backend" in setup_q:
                SETUP_CONFIG["backend"] = setup_q["backend"][0] or None
            return self.send_json({"backend": SETUP_CONFIG["backend"] or self.base_url})
        if path == "/__mock/processed":
            PROCESSED_CONFIG["state"] = q.get("state", ["items"])[0]
            return self.send_json(PROCESSED_CONFIG)
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
                STATE["reason"] = q["reason"][0] if "reason" in q else None
                STATE["estimate"] = int(q["estimate"][0]) if "estimate" in q else DEFAULT_ESTIMATE_S
                STATE["retry_after"] = int(q["retry_after"][0]) if "retry_after" in q else DEFAULT_RETRY_AFTER_S
                STATE["start_progress"] = float(q["progress"][0]) if "progress" in q else 0.0
                if "panel" in q:
                    STATE["panel_status"] = None if q["panel"][0] == "ok" else int(q["panel"][0])
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
        if path == "/__mock/cuts":
            if "video" not in q:
                with CUT_LOCK:
                    return self.send_json({"delay": CUTS_CONFIG["delay"], "stage": CUTS_CONFIG["stage"],
                                           "requests": len(CUT_REQUESTS)})
            vid = q["video"][0]
            state = q.get("state", ["none"])[0]
            with CUT_LOCK:
                if state == "none":
                    CUT_READY.pop(vid, None)
                    for rid in [r for r, req in CUT_REQUESTS.items() if req["video_id"] == vid]:
                        del CUT_REQUESTS[rid]
                elif state == "ready":
                    CUT_READY[vid] = {"preset_id": (q.get("preset") or [None])[0],
                                      "duration_ms": int(q.get("duration", ["240000"])[0])}
                elif state == "failed":
                    CUT_READY[vid] = {"preset_id": (q.get("preset") or [None])[0], "failed": True}
            return self.send_json({"video": vid, "state": state})
        if path == "/v1/health":
            return self.send_json({"ok": True, "version": "mock"})
        if path.startswith("/media/") and self.media_dir:
            return self.send_media(Path(self.media_dir) / Path(path[len("/media/"):]).name)
        if path == "/setup.json":
            return self.send_json({"utubot_setup": 1, "name": "Emulator mock",
                                   "backend_url": SETUP_CONFIG["backend"] or self.base_url,
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
            return self.send_json({"user": self.user_name, "policy": {}, "features": {"assess": True, "insight": True, "captions": True,
                                                                            "cuts": True}, "admin": False})
        if path == "/v1/prompts":
            return self.send_json(prompt_list())
        if path == "/v1/processed":
            limit = int(q.get("limit", ["50"])[0] or 50)
            if limit < 1 or limit > 200:
                return self.send_json({"error": "limit must be 1 to 200"}, 400)
            if PROCESSED_CONFIG["state"] == "fail":
                return self.send_json({"error": "the processed request failed"}, 500)
            if PROCESSED_CONFIG["state"] == "empty":
                return self.send_json({"videos": []})
            return self.send_json(processed_items())
        if path == "/v1/cut-requests":
            with CUT_LOCK:
                docs = [cut_request_doc(r) for r in reversed(list(CUT_REQUESTS.values()))]
            return self.send_json({"requests": docs[:100]})
        m = re.match(r"/v1/cuts/([a-z0-9]+)$", path)
        if m:
            with CUT_LOCK:
                request = CUT_REQUESTS.get(m.group(1))
            if request is None:
                return self.send_json({"error": "not found"}, 404)
            wait_ms = int((q.get("wait_ms") or ["0"])[0] or 0)
            return self.send_json(cut_request_doc(request, wait=wait_ms))
        m = re.match(r"/v1/videos/([A-Za-z0-9_-]{11})/cuts$", path)
        if m:
            vid = m.group(1)
            with CUT_LOCK:
                presets = []
                for pid, label in CUT_PRESETS:
                    state = preset_state(vid, pid)
                    preset = {"id": pid, "label": label, "state": state}
                    ready = CUT_READY.get(vid)
                    if state == "ready":
                        if ready is not None and ready.get("failed"):
                            preset["state"] = "failed"
                            preset["error"] = "the cut could not be built"
                        else:
                            preset["cut"] = cut_document(ready["duration_ms"] if ready else 240000, vid, label=label, preset_id=pid)
                    presets.append(preset)
            return self.send_json({"configured": True, "presets": presets})
        m = re.match(r"/v1/videos/([A-Za-z0-9_-]{11})/summary$", path)
        if m:
            prompt = (q.get("prompt") or ["builtin/tldr"])[0]
            if prompt == "panel" and STATE["panel_status"]:
                return self.send_json({"error": "the panel prompt is refused"}, STATE["panel_status"])
            time.sleep(STATE["delay"])
            return self.send_json(summary(m.group(1), prompt, q))
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
    ap.add_argument("--host", action="append", help="listen address, repeatable (default 0.0.0.0)")
    ap.add_argument("--user", default="emu", help="the pairing user name (default emu)")
    ap.add_argument("--static", default=None)
    ap.add_argument("--base", default=None)
    ap.add_argument("--media", default=None, help="folder served under /media/ (with byte ranges), for the captions harness of the debug build")
    ap.add_argument("--vtt", default=str(CAPTIONS_CONFIG["vtt"]), help="WebVTT file served as the HQ captions track")
    ap.add_argument("--lang", default=CAPTIONS_CONFIG["lang"])
    ap.add_argument("--label", default=CAPTIONS_CONFIG["label"])
    ap.add_argument("--captions-delay", type=float, default=CAPTIONS_CONFIG["delay"],
                    help="seconds a captions job queued by POST /v1/videos/ID/captions takes")
    ap.add_argument("--cuts-delay", type=float, default=CUTS_CONFIG["delay"],
                    help="seconds a director's cut build takes (default 8)")
    args = ap.parse_args()
    CAPTIONS_CONFIG.update(vtt=Path(args.vtt), lang=args.lang, label=args.label, delay=args.captions_delay)
    CUTS_CONFIG["delay"] = args.cuts_delay
    Handler.static_dir = args.static
    Handler.media_dir = args.media
    Handler.base_url = args.base or f"http://10.0.2.2:{args.port}"
    Handler.user_name = args.user
    global PORT
    PORT = args.port
    servers = [ThreadingHTTPServer((host, args.port), Handler) for host in (args.host or ["0.0.0.0"])]
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


if __name__ == "__main__":
    main()
