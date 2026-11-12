"""Serve the web UI on loopback with a mock LLM and canned data, for screenshots and manual poking.

    uv run python tests/webui_demo.py [DATA_DIR]      # DATA_DIR defaults to temp/webui-demo

Prints the address and the demo credentials, then serves until interrupted. Nothing here reaches the
network: models and summaries come from `tests/mock_openai.py`, transcripts from a fake fetcher and
GitHub releases from a canned list. `POST /demo/gate/open|close` (demo only) opens and closes the
YouTube circuit breaker so both states can be photographed.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.conftest import FakeFetcher  # noqa: E402
from tests.mock_openai import MockOpenAI  # noqa: E402
from utubot.app import create_app  # noqa: E402
from utubot.auth import hash_token  # noqa: E402
from utubot.config import Config, UserConfig, UserPolicy  # noqa: E402
from utubot.prompts import validate_prompt_set  # noqa: E402

APP_PORT, LLM_PORT = 8791, 8792
OWNER_TOKEN, PARTNER_TOKEN = "utb_demo_owner", "utb_demo_partner"
OWNER_PASSWORD = "demo-password-123"
GLANCE = (
    "→ Yes: firmware 4.2 schedules channels per device.\n"
    "Older phones still fall back to 2.4 GHz.\n"
    "Mesh nodes need the same update."
)
TLDR = (
    "- The new firmware schedules Wi-Fi channels per device instead of per router.\n"
    "- Phones and laptops get 5 GHz first; smart-home gear stays on 2.4 GHz.\n"
    "- Mesh nodes must be updated together or roaming gets worse.\n"
    "- Expect a 10 to 30 percent latency drop on busy evenings.\n"
    "- Rollback is possible from the admin page for 30 days."
)
RELEASES = [
    {
        "tag_name": "utubot-v0.3.4",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-11-10T09:30:00Z",
        "html_url": "https://github.com/example/u-tubot/releases/tag/utubot-v0.3.4",
    },
    {
        "tag_name": "utubot-v0.3.2",
        "draft": False,
        "prerelease": False,
        "published_at": "2026-11-02T18:05:00Z",
        "html_url": "https://github.com/example/u-tubot/releases/tag/utubot-v0.3.2",
    },
]


class DemoLLM(MockOpenAI):
    def respond(self, body):
        system = body["messages"][0]["content"]
        user = body["messages"][-1]["content"]
        if "glance card" in system:
            return GLANCE
        if "TL;DR" in user:
            return TLDR
        return super().respond(body)


def github(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=RELEASES)


def build(data: Path):
    mock = DemoLLM()
    mock.models = ["llama3.1:8b", "llama3.2:3b", "qwen3:14b", "mistral-small:24b", "gpt-oss:20b"]
    cfg = Config()
    cfg.server.data_dir = str(data)
    cfg.server.app_dir = str(data / "app")
    cfg.llm.providers["default"].base_url = f"http://127.0.0.1:{LLM_PORT}/v1"
    for task in (cfg.llm.summary, cfg.llm.answer, cfg.llm.analysis):
        task.model = "llama3.1:8b"
    cfg.llm.triage.model = "llama3.2:3b"
    cfg.security.scrypt_n = 2**12
    cfg.app.github_repo = "example/u-tubot"
    cfg.users = [
        UserConfig(
            name="owner",
            token_sha256=hash_token(OWNER_TOKEN),
            admin=True,
            policy=UserPolicy(
                hide_topics=["reaction videos", "AI-generated narration slop"],
                mark_topics=["celebrity gossip"],
            ),
        ),
        UserConfig(name="partner", token_sha256=hash_token(PARTNER_TOKEN)),
    ]
    fetcher = FakeFetcher()
    fetcher.meta_extra = {
        "title": "How the new router firmware changes Wi-Fi",
        "channel": "Tech Notes",
    }

    async def never_downloads(video_id, out_dir, started=None):
        await asyncio.sleep(3600)

    app = create_app(
        cfg,
        llm_transport=None,
        fetcher=fetcher,
        downloader=never_downloads,
        github_transport=httpx.MockTransport(github),
    )
    svc = app.state.svc

    @app.post("/demo/gate/{state}")
    async def gate(state: str):
        if state == "open":
            svc.gate.report_block("demo", 272)
        else:
            svc.gate._until, svc.gate._strikes = 0.0, 0
        return {"gate": svc.gate.state()}

    return mock, cfg, app


def seed(cfg: Config, app, mock: MockOpenAI) -> None:
    svc = app.state.svc
    db, now = svc.db, time.time()
    svc.webauth.set_password("owner", OWNER_PASSWORD)
    svc.webauth.set_password("partner", "partner-password-123")
    svc.webauth.create_user("guest", False, None)
    svc.prompts.save_set(
        "owner",
        validate_prompt_set(
            {
                "tubeai_prompt_set": 1,
                "id": "my-prompts",
                "name": "My prompts",
                "version": "2026-11-12",
                "prompts": [
                    {
                        "id": "bullets",
                        "label": "Three bullets",
                        "template": "{transcript}\n3 bullets.",
                        "max_tokens": 300,
                    },
                    {
                        "id": "eli12",
                        "label": "Explain to a 12 year old",
                        "template": "{transcript}\nExplain simply.",
                    },
                ],
            }
        ),
        source_url="https://example.com/my-prompts.json",
    )
    for name, used in (("Living room TV", now - 600), ("Bedroom Fire Stick", now - 3 * 86400)):
        db.execute(
            "INSERT INTO device_tokens(id,user,token_sha256,device,created_at,last_used) VALUES(?,?,?,?,?,?)",
            [uuid.uuid4().hex[:12], "owner", uuid.uuid4().hex, name, now - 20 * 86400, used],
        )
    jobs = [
        (
            "transcript",
            "aaaaaaaaa01",
            "Why the 2026 election model broke",
            "running",
            0.42,
            None,
            0,
        ),
        (
            "transcript",
            "aaaaaaaaa02",
            "I built a keyboard from scratch",
            "queued",
            0.0,
            None,
            now + 300,
        ),
        (
            "transcript",
            "aaaaaaaaa03",
            "Slow TV: eight hours of canal boats",
            "failed",
            0.0,
            "Transcription failed. Try again later.",
            0,
        ),
        ("captions", "aaaaaaaaa04", "Live lecture: category theory, part 3", "ready", 1.0, None, 0),
        (
            "transcript",
            "aaaaaaaaa05",
            "Unboxing the cheapest 4K TV",
            "cancelled",
            0.0,
            "Cancelled",
            0,
        ),
    ]
    for i, (kind, vid, title, status, progress, error, not_before) in enumerate(jobs):
        db.execute(
            "INSERT INTO jobs(id,user,video_id,lang,status,progress,error,created_at,updated_at,kind,title,"
            "finished_at,not_before) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                uuid.uuid4().hex[:12],
                "owner",
                vid,
                "auto",
                status,
                progress,
                error,
                now - 300 * (i + 1),
                now - 60,
                kind,
                title,
                None if status in ("running", "queued") else now - 120 * (i + 1),
                not_before or None,
            ],
        )
    for metric, n in (
        ("llm_calls", 184),
        ("llm_errors", 2),
        ("llm_prompt_tokens", 612_400),
        ("llm_completion_tokens", 48_900),
    ):
        db.execute(
            "INSERT OR REPLACE INTO usage_daily(day,metric,n) VALUES(date('now'),?,?)", [metric, n]
        )
    for i in range(12):
        db.execute(
            "INSERT OR REPLACE INTO transcripts(video_id,lang,source,text,fetched_at) VALUES(?,?,?,?,?)",
            [f"seedvideo{i:02d}", "en", "asr" if i == 0 else "youtube_captions", "x", now - i],
        )
    db.execute("INSERT OR REPLACE INTO tier2_usage(user,day,count) VALUES('owner',date('now'),7)")
    app_dir = Path(cfg.server.app_dir)
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "latest.json").write_text(
        json.dumps(
            {
                "version_name": "0.3.2",
                "version_code": 3002,
                "changelog": ["Prompt sets can be refreshed from the TV", "Faster side panel"],
                "files": {
                    "arm64-v8a": {"file": "u-tubot_0.3.2_arm64-v8a.apk", "size": 31_000_000},
                    "armeabi-v7a": {"file": "u-tubot_0.3.2_armeabi-v7a.apk", "size": 29_000_000},
                },
            }
        )
    )
    (app_dir / "sync.json").write_text(
        json.dumps(
            {
                "checked_at": now - 1800,
                "status": "up-to-date",
                "version_name": "0.3.2",
                "error": None,
            }
        )
    )
    base = f"http://127.0.0.1:{APP_PORT}"
    with httpx.Client(base_url=base, headers={"Authorization": f"Bearer {OWNER_TOKEN}"}) as client:
        client.get("/v1/models")
        mock.models += ["qwen3.5:35b", "gemma3:27b"]
        client.post("/v1/models/refresh")
        client.put(
            "/v1/me/settings",
            json={
                "settings": {"models": {"glance": "llama3.2:3b", "triage": "llama3.2:3b"}},
                "allow_unlisted_models": True,
            },
        )


def main() -> None:
    data = Path(sys.argv[1] if len(sys.argv) > 1 else "temp/webui-demo")
    mock, cfg, app = build(data)
    threading.Thread(
        target=lambda: uvicorn.run(mock.app, host="127.0.0.1", port=LLM_PORT, log_level="warning"),
        daemon=True,
    ).start()

    def seed_when_up() -> None:
        for _ in range(100):
            try:
                if httpx.get(f"http://127.0.0.1:{APP_PORT}/v1/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.1)
        seed(cfg, app, mock)
        print("demo data ready", flush=True)

    threading.Thread(target=seed_when_up, daemon=True).start()
    print(
        f"http://127.0.0.1:{APP_PORT}/  owner / {OWNER_PASSWORD}  (token {OWNER_TOKEN})", flush=True
    )
    uvicorn.run(app, host="127.0.0.1", port=APP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
