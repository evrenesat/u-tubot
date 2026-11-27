"""Serve the web UI on loopback with a mock LLM and canned data, for screenshots and manual poking.

    uv run python tests/webui_demo.py [DATA_DIR] [PORT]   # defaults temp/webui-demo and 8791

Prints the address and the demo credentials, then serves until interrupted. Nothing here reaches the
network: models and summaries come from `tests/mock_openai.py`, transcripts from a fake fetcher and
GitHub releases from a canned list. `POST /demo/gate/open|close` (demo only) opens and closes the
YouTube circuit breaker so both states can be photographed.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.conftest import FakeFetcher, block_youtube  # noqa: E402
from tests.mock_openai import MockOpenAI  # noqa: E402
from utubot.app import create_app  # noqa: E402
from utubot.auth import hash_token  # noqa: E402
from utubot.config import Config, LLMTask, UserConfig, UserPolicy  # noqa: E402
from utubot.prompts import validate_prompt_set  # noqa: E402
from utubot.secretstore import new_master_key  # noqa: E402

APP_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8791
LLM_PORT = APP_PORT + 1
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
    def __init__(self):
        super().__init__()
        self.hold_cuts = False
        self.cut_answer_mode = "good"

    def respond(self, body):
        system = body["messages"][0]["content"]
        user = body["messages"][-1]["content"]
        if "director's cut" in system:
            if self.hold_cuts:
                time.sleep(
                    3
                )  # demo knob (POST /demo/cut/hold|release) so the check can see the building state
            if self.cut_answer_mode == "bad":
                # demo knob (POST /demo/cut/answer/bad): ids that never exist, so the cut fails
                # after its repair round and the phone can show a plain failure.
                return json.dumps({"parts": [{"from": 900, "to": 999}]})
            return json.dumps(
                {
                    "parts": [
                        {"from": 2, "to": 3, "label": "The change"},
                        {"from": 5, "to": 6, "label": "What to expect"},
                    ],
                    "summary": "The per-device channel scheduling and its effects.",
                    "kept_s": 92,
                }
            )
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
    cfg.llm.cuts = LLMTask(model="llama3.1:8b")
    cfg.speech.alias = "stt"
    cfg.speech.max_record_s = 50
    cfg.speech.per_user_per_min = 20
    cfg.voice.enabled = True
    cfg.settings_sync.enabled = True
    os.environ.setdefault(
        cfg.security.secrets_key_env, new_master_key()
    )  # demo only: a throwaway key
    cfg.security.scrypt_n = 2**12
    # The seeded "running" job parks its worker on the never-downloading fake; a second worker
    # keeps the queue alive for the cut builds the pages show live.
    cfg.captions.job_concurrency = 2
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
    fetcher.segments = [
        (i * 20.0, i * 20.0 + 18, line[8:]) for i, line in enumerate(TRANSCRIPT_LINES)
    ]
    # The demo's fresh videos report the length of that short transcript, so a cut's keep
    # guard measures against the real thing (a 900 s meta with a 2 min transcript would
    # refuse every cut as "removes almost everything").
    fetcher.meta_extra = {"duration_s": 120}

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
            for name, breaker in svc.gate._breakers.items():
                breaker.until, breaker.strikes = 0.0, 0
                svc.gate._save(name)
        return {"gate": svc.gate.state()}

    @app.post("/demo/cut/{state}")
    async def cut_hold(state: str):
        if state in ("hold", "release"):
            mock.hold_cuts = state == "hold"
        elif state in ("good", "bad"):
            mock.cut_answer_mode = state
        return {"hold_cuts": mock.hold_cuts, "cut_answer_mode": mock.cut_answer_mode}

    return mock, cfg, app


TURKISH_CUES = [
    (1.2, "Merhaba arkadaşlar, bugün enflasyonun neden düşmediğini konuşacağız."),
    (5.0, "Önce son açıklanan rakamlara bakalım."),
    (8.4, "Yıllık enflasyon beklentilerin üzerinde geldi."),
    (12.9, "Bunun üç temel nedeni var."),
    (16.0, "Birincisi, kira ve hizmet fiyatlarındaki katılık."),
    (20.3, "İkincisi, döviz kurundaki dalgalanmalar."),
    (24.1, "Üçüncüsü ise beklentilerin bozulması."),
    (28.6, "Şimdi bunların her birine sırayla bakacağız."),
    (32.2, "Kiralar, bir yıl önceki sözleşmelerin yenilenmesiyle artıyor."),
    (37.0, "Bu da hizmet enflasyonunu yukarı çekiyor."),
]
TRANSCRIPT_LINES = [
    "[00:00] Welcome back. Today we look at what the new router firmware changes.",
    "[00:20] The big change is that channels are now scheduled per device, not per router.",
    "[00:41] Phones and laptops get the 5 GHz band first; smart-home gear stays on 2.4.",
    "[01:02] Mesh nodes must be updated together, or roaming gets worse.",
    "[01:24] On busy evenings you can expect a latency drop of ten to thirty percent.",
    "[01:47] Rollback is possible from the admin page for thirty days.",
]


TURKISH_CUE_COUNT = 612
TURKISH_CUE_SPACING_S = 2.85


def vtt_of(cues) -> str:
    def stamp(sec: float) -> str:
        return f"00:{int(sec // 60):02d}:{sec % 60:06.3f}"

    blocks = ["WEBVTT", ""]
    for i, (start, text) in enumerate(cues, 1):
        blocks += [str(i), f"{stamp(start)} --> {stamp(start + 3.5)}", text, ""]
    return "\n".join(blocks)


def seed_voice(db, now: float) -> None:
    """One device with voice on and a few spoken commands, so the Devices and Voice pages have content."""
    tv = db.one("SELECT id FROM device_tokens WHERE device='Living room TV'")["id"]
    db.execute(
        "INSERT INTO device_voice(device_id,user,enabled,listen_mode,speak,consent_version,consented_at,"
        "updated_at) VALUES(?,?,1,'push',1,1,?,?)",
        [tv, "owner", now - 2 * 86400, now - 2 * 86400],
    )
    rows = [
        (
            90,
            "make a cut that keeps only the benchmarks",
            "cut_custom",
            {"prompt": "only the benchmarks"},
            "ok",
            {"stt_ms": 412, "intent_ms": 230, "total_ms": 1480},
        ),
        (400, "pause", "pause", {}, "ok", {"stt_ms": 380, "total_ms": 610}),
        (
            3600,
            "back thirty seconds",
            "seek",
            {"delta_s": -30},
            "ok",
            {"stt_ms": 360, "total_ms": 590},
        ),
        (
            7200,
            "summarise the whole thing in Turkish please and read it out loud",
            "summary",
            {"language": "tr"},
            "clarify",
            {"stt_ms": 905, "intent_ms": 840},
        ),
        (86400, "next part", "next_part", {}, "refused", {"stt_ms": 350}),
    ]
    for age, text, tool, args, outcome, marks in rows:
        db.execute(
            "INSERT INTO voice_commands(user,device_id,at,text,tool,args,outcome,marks) VALUES(?,?,?,?,?,?,?,?)",
            ["owner", tv, now - age, text, tool, json.dumps(args), outcome, json.dumps(marks)],
        )


def seed_settings(svc, now: float) -> None:
    """Two TVs on the Settings page: one in step with the server (an app of schema 2, with its own
    update interval and cut keys) and one that has been off for days on an app of schema 1, with its
    own values, waiting changes and a history of ten rows."""
    sync = svc.device_settings
    ids = {
        r["device"]: r["id"]
        for r in svc.db.all("SELECT id, device FROM device_tokens WHERE user='owner'")
    }
    living, bedroom = ids["Living room TV"], ids["Bedroom Fire Stick"]

    def change(key, value, base=0):
        return {"key": key, "value": value, "base_rev": base}

    first = {
        "schema_version": 2,
        "app_version": "0.9.14",
        "initial": True,
        "changes": [
            change("ai.mark_only", True),
            change("ai.panel_delay_ms", 3000),
            change("updates.interval_minutes", 60),
            change("ai.cut_jump", "up_down"),
        ],
    }
    sync.push("owner", living, first)
    sync.push(
        "owner",
        bedroom,
        {
            "schema_version": 1,
            "app_version": "0.9.12",
            "initial": True,
            "changes": [change("ai.wait_ms", 800)],
        },
    )
    steps = [
        {"ai.summary_panel": True},
        {"ai.auto_cuts": True},
        {"ai.assess": False},
        {"ai.assess": True},
        {"ai.wait_ms": 1500},
        {"ai.answer_in_menu": False},
        {"ai.auto_captions": False},
        {"ai.auto_captions": True},
    ]
    for step in steps:
        asyncio.run(svc.settings.update("owner", {"settings": step}, by="owner"))
    doc = sync.pull("owner", living, None, 2)
    sync.pull("owner", living, doc["version"], 2)
    asyncio.run(svc.settings.update("owner", {"settings": {"ai.panel_delay_ms": 2400}}, by="owner"))
    sync.pull("owner", living, None, 2)
    sync.pull("owner", living, svc.auth.settings_version("owner")[0], 2)
    svc.db.execute(
        "UPDATE device_settings_state SET last_sync_at=?, applied_at=? WHERE device_id=?",
        [now - 3 * 86400 + 60, now - 3 * 86400, bedroom],
    )
    svc.db.execute(
        "UPDATE device_settings_state SET applied_version=4 WHERE device_id=?", [bedroom]
    )
    svc.secrets.set(
        "owner", "films_rd_token", "rd-demo-token-not-a-real-key-ab12", via="web", by="owner"
    )
    svc.secrets.deliver("owner", living, ["films_rd_token"])
    rows = svc.db.all("SELECT id FROM settings_audit ORDER BY id")
    for i, row in enumerate(rows):
        svc.db.execute(
            "UPDATE settings_audit SET at=? WHERE id=?", [now - (len(rows) - i) * 5400, row["id"]]
        )


def seed_job_reports(svc, now: float) -> None:
    """Event logs for the demo jobs: a captions job that two TVs fetched, a transcript nobody fetched, failures."""
    db, events = svc.db, svc.jobs.events

    def log(job_id: str, t0: float, rows) -> None:
        for offset, stage, status, detail in sorted(rows, key=lambda row: row[0]):
            events.record(job_id, stage, status, detail, ts=t0 + offset)

    def queued(who: str, client: str, endpoint: str, trigger: dict, priority: str, **extra) -> dict:
        return {
            "user": who,
            "client": client,
            "endpoint": endpoint,
            "trigger": trigger,
            "priority": priority,
            **extra,
        }

    explicit = {"kind": "explicit"}
    auto = {"kind": "auto", "mode": "on_open", "passive": False, "max_minutes": 30}
    # A Turkish captions job: one engine failed a chunk, the next took it; ready, fetched by the living room TV.
    turkish, t0 = "demojob0005", now - 2400
    turkish_vtt = vtt_of(
        [
            (1.2 + TURKISH_CUE_SPACING_S * i, TURKISH_CUES[i % len(TURKISH_CUES)][1])
            for i in range(TURKISH_CUE_COUNT)
        ]
    )
    db.execute(
        "INSERT INTO jobs(id,user,video_id,lang,status,progress,created_at,updated_at,kind,title,"
        "finished_at,priority) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            turkish,
            "owner",
            "aaaaaaaaa06",
            "auto",
            "ready",
            1.0,
            t0,
            t0 + 53,
            "captions",
            "Türkiye'de enflasyon neden düşmüyor?",
            t0 + 53,
            1,
        ],
    )
    db.execute(
        "INSERT OR REPLACE INTO video_meta(video_id,json,fetched_at) VALUES(?,?,?)",
        [
            "aaaaaaaaa06",
            json.dumps(
                {
                    "title": "Türkiye'de enflasyon neden düşmüyor?",
                    "channel": "Ekonomi Notları",
                    "duration_s": 1740,
                    "language": "tr",
                }
            ),
            t0,
        ],
    )
    db.execute(
        "INSERT OR REPLACE INTO captions(video_id,lang,label,speakers,vtt,created_at,job_id)"
        " VALUES(?,?,?,?,?,?,?)",
        [
            "aaaaaaaaa06",
            "tr",
            "Turkish (u·tubot)",
            1,
            turkish_vtt,
            t0 + 52,
            turkish,
        ],
    )
    log(
        turkish,
        t0,
        [
            (
                0,
                "queued",
                "ok",
                queued(
                    "owner",
                    "Living room TV",
                    "POST /v1/videos/{video_id}/captions",
                    explicit,
                    "background",
                    kind="captions",
                    lang="auto",
                ),
            ),
            (2.1, "started", "ok", {"attempt": 1, "waited_s": 2.1, "priority": "background"}),
            (
                2.2,
                "gate_wait",
                "ok",
                {"klass": "media", "waited_s": 3.4, "priority": "background"},
            ),
            (5.6, "audio_download", "running", {}),
            (
                9.4,
                "audio_download",
                "ok",
                {
                    "seconds": 3.8,
                    "bytes": 6414220,
                    "source": "downloaded",
                    "format_id": "251",
                    "track": "original",
                    "original": True,
                    "language": "tr",
                    "codec": "opus",
                    "duration_s": 1740,
                },
            ),
            (9.5, "ffmpeg", "running", {}),
            (13.4, "ffmpeg", "ok", {"seconds": 3.9, "audio_s": 1740.0, "bytes": 55680044}),
            (
                13.5,
                "chunking",
                "ok",
                {
                    "chunks": 3,
                    "sizes_s": [600.0, 600.0, 544.0],
                    "engines": ["mac", "box"],
                    "audio_s": 1740.0,
                },
            ),
            (13.6, "asr", "running", {"requested_language": "tr"}),
            (
                19.8,
                "asr_chunk",
                "ok",
                {
                    "engine": "mac",
                    "model": "whisper-large-v3-turbo",
                    "start_s": 0,
                    "end_s": 600,
                    "seconds": 6.2,
                    "chars": 8210,
                    "language": "tr",
                },
            ),
            (
                14.2,
                "asr_chunk",
                "failed",
                {
                    "engine": "mac",
                    "model": "whisper-large-v3-turbo",
                    "start_s": 598,
                    "end_s": 1198,
                    "seconds": 0.6,
                    "error_class": "http_503",
                },
            ),
            (
                14.3,
                "asr_fallback",
                "warn",
                {
                    "engine": "mac",
                    "reason": "http_503",
                    "next": "box",
                    "start_s": 598,
                    "end_s": 1198,
                },
            ),
            (
                36.0,
                "asr_chunk",
                "ok",
                {
                    "engine": "box",
                    "model": "whisper-small",
                    "start_s": 598,
                    "end_s": 1198,
                    "seconds": 21.7,
                    "chars": 7954,
                    "language": "tr",
                },
            ),
            (
                21.0,
                "asr_chunk",
                "ok",
                {
                    "engine": "mac",
                    "model": "whisper-large-v3-turbo",
                    "start_s": 1196,
                    "end_s": 1740,
                    "seconds": 7.4,
                    "chars": 7421,
                    "language": "tr",
                },
            ),
            (
                36.1,
                "asr",
                "ok",
                {
                    "seconds": 22.5,
                    "engine": "mac+box",
                    "model": "whisper-large-v3-turbo+whisper-small",
                    "language": "tr",
                    "chars": 23585,
                    "segments": 412,
                    "words": 3920,
                },
            ),
            (
                36.2,
                "stitching",
                "ok",
                {"chunks": 3, "seams": 2, "cut_segments": 41, "repeated_words": 3},
            ),
            (36.3, "diarization", "running", {}),
            (
                36.4,
                "diarization",
                "skipped",
                {
                    "seconds": 0.0,
                    "reason": "no_hf_token",
                    "message": "No Hugging Face token was set (UTUBOT_HF_TOKEN is empty).",
                },
            ),
            (
                37.1,
                "cues",
                "ok",
                {
                    "cues": TURKISH_CUE_COUNT,
                    "words": 3920,
                    "max_line_chars": 42,
                    "max_lines": 2,
                    "limit_line_chars": 42,
                },
            ),
            (
                37.2,
                "stored",
                "ok",
                {
                    "kind": "captions",
                    "lang": "tr",
                    "label": "Turkish (u·tubot)",
                    "speakers": 0,
                    "cues": TURKISH_CUE_COUNT,
                    "bytes": len(turkish_vtt.encode()),
                },
            ),
            (37.3, "finished", "ok", {"seconds": 35.2}),
        ],
    )
    for ago, via, count in ((1900, "captions_status", 4), (1850, "vtt", 2)):
        events.record(
            turkish,
            "delivered",
            "ok",
            {
                "via": via,
                "client": "Living room TV",
                "user": "owner",
                "count": count,
                "first_ts": now - ago,
                "lang": "tr",
            },
            ts=now - ago + 120,
        )
    # A transcript the policy started when the Fire Stick opened the video; nobody fetched it since.
    plain, t1 = "demojob0006", now - 900
    db.execute(
        "INSERT INTO jobs(id,user,video_id,lang,status,progress,created_at,updated_at,kind,title,"
        "finished_at,priority) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            plain,
            "owner",
            "aaaaaaaaa07",
            "auto",
            "ready",
            1.0,
            t1,
            t1 + 41,
            "transcript",
            "How the new router firmware changes Wi-Fi",
            t1 + 41,
            0,
        ],
    )
    db.execute(
        "INSERT OR REPLACE INTO video_meta(video_id,json,fetched_at) VALUES(?,?,?)",
        [
            "aaaaaaaaa07",
            json.dumps(
                {
                    "title": "How the new router firmware changes Wi-Fi",
                    "channel": "Tech Notes",
                    "duration_s": 600,
                    "language": "en",
                }
            ),
            t1,
        ],
    )
    svc.transcripts.store_asr(
        "aaaaaaaaa07",
        "\n".join(TRANSCRIPT_LINES),
        "en",
        engine="mac",
        model="whisper-large-v3-turbo",
        segments=[(i * 20.0, i * 20.0 + 18, line[8:]) for i, line in enumerate(TRANSCRIPT_LINES)],
        job_id=plain,
    )
    log(
        plain,
        t1,
        [
            (
                0,
                "queued",
                "ok",
                queued(
                    "owner",
                    "Bedroom Fire Stick",
                    "GET /v1/videos/{video_id}/summary",
                    auto,
                    "interactive",
                    kind="transcript",
                    lang="auto",
                ),
            ),
            (0.4, "started", "ok", {"attempt": 1, "waited_s": 0.4, "priority": "interactive"}),
            (
                0.5,
                "caption_recheck",
                "ok",
                {"result": "no_captions", "seconds": 1.6},
            ),
            (
                2.2,
                "gate_wait",
                "ok",
                {"klass": "media", "waited_s": 3.0, "priority": "interactive"},
            ),
            (
                5.4,
                "audio_download",
                "ok",
                {
                    "seconds": 2.1,
                    "bytes": 2210000,
                    "source": "downloaded",
                    "format_id": "249",
                    "track": "unmarked",
                    "original": False,
                    "language": "en",
                    "codec": "opus",
                    "duration_s": 600,
                },
            ),
            (8.0, "ffmpeg", "ok", {"seconds": 2.4, "audio_s": 600.0, "bytes": 19200044}),
            (
                8.1,
                "chunking",
                "ok",
                {"chunks": 1, "sizes_s": [600.0], "engines": ["mac"], "audio_s": 600.0},
            ),
            (
                16.0,
                "asr_chunk",
                "ok",
                {
                    "engine": "mac",
                    "model": "whisper-large-v3-turbo",
                    "start_s": 0,
                    "end_s": 600,
                    "seconds": 7.9,
                    "chars": 4830,
                    "language": "en",
                },
            ),
            (
                16.1,
                "asr",
                "ok",
                {
                    "seconds": 8.0,
                    "engine": "mac",
                    "model": "whisper-large-v3-turbo",
                    "language": "en",
                    "chars": 4830,
                    "segments": 6,
                },
            ),
            (16.2, "stitching", "skipped", {"reason": "single_chunk", "chunks": 1}),
            (16.3, "text", "ok", {"segments": 6, "lines": 6, "chars": 4830}),
            (
                16.4,
                "stored",
                "ok",
                {
                    "kind": "transcript",
                    "source": "asr",
                    "stored": True,
                    "lang": "en",
                    "engine": "mac",
                    "model": "whisper-large-v3-turbo",
                    "chars": 4830,
                    "segments": 6,
                },
            ),
            (16.5, "finished", "ok", {"seconds": 16.1}),
        ],
    )
    # The running job (first in the list): three chunks, the first one done.
    running = "demojob0000"
    t2 = now - 300
    log(
        running,
        t2,
        [
            (
                0,
                "queued",
                "ok",
                queued(
                    "owner",
                    "Web UI",
                    "POST /v1/videos/{video_id}/transcribe",
                    explicit,
                    "interactive",
                    kind="transcript",
                    lang="auto",
                ),
            ),
            (1.0, "started", "ok", {"attempt": 1, "waited_s": 1.0, "priority": "interactive"}),
            (
                1.2,
                "caption_recheck",
                "ok",
                {"result": "no_captions", "seconds": 1.8},
            ),
            (
                4.0,
                "gate_wait",
                "ok",
                {"klass": "media", "waited_s": 2.8, "priority": "interactive"},
            ),
            (
                10.0,
                "audio_download",
                "ok",
                {
                    "seconds": 5.9,
                    "bytes": 9400000,
                    "source": "downloaded",
                    "format_id": "251",
                    "track": "original",
                    "original": True,
                    "language": "en",
                    "codec": "opus",
                    "duration_s": 2520,
                },
            ),
            (14.2, "ffmpeg", "ok", {"seconds": 4.2, "audio_s": 2520.0, "bytes": 80640044}),
            (
                14.3,
                "chunking",
                "ok",
                {
                    "chunks": 5,
                    "sizes_s": [600.0, 600.0, 600.0, 600.0, 520.0],
                    "engines": ["mac"],
                    "audio_s": 2520.0,
                },
            ),
            (14.4, "asr", "running", {"requested_language": None}),
            (
                27.0,
                "asr_chunk",
                "ok",
                {
                    "engine": "mac",
                    "model": "whisper-large-v3-turbo",
                    "start_s": 0,
                    "end_s": 600,
                    "seconds": 12.6,
                    "chars": 9120,
                    "language": "en",
                },
            ),
        ],
    )
    # The failed one: the audio download stopped it.
    failed = "demojob0002"
    t3 = now - 900
    log(
        failed,
        t3,
        [
            (
                0,
                "queued",
                "ok",
                queued(
                    "owner",
                    "Bedroom Fire Stick",
                    "GET /v1/videos/{video_id}/insight",
                    auto,
                    "interactive",
                    kind="transcript",
                    lang="auto",
                ),
            ),
            (0.8, "started", "ok", {"attempt": 1, "waited_s": 0.8, "priority": "interactive"}),
            (1.0, "caption_recheck", "ok", {"result": "no_captions", "seconds": 1.4}),
            (
                4.0,
                "gate_wait",
                "ok",
                {"klass": "media", "waited_s": 2.6, "priority": "interactive"},
            ),
            (4.1, "audio_download", "running", {}),
            (
                6.3,
                "audio_download",
                "failed",
                {"seconds": 2.2, "error_class": "too_long", "technical": "too_long"},
            ),
            (
                6.4,
                "failed",
                "failed",
                {
                    "message": "Transcription failed. Try again later.",
                    "stage": "audio_download",
                    "error_class": "too_long",
                    "technical": "too_long",
                    "attempts": 1,
                },
            ),
        ],
    )
    # Waiting: YouTube held it back once.
    waiting = "demojob0001"
    t4 = now - 600
    log(
        waiting,
        t4,
        [
            (
                0,
                "queued",
                "ok",
                queued(
                    "owner",
                    "Web UI",
                    "POST /v1/videos/{video_id}/transcribe",
                    explicit,
                    "background",
                    kind="transcript",
                    lang="auto",
                ),
            ),
            (1.0, "started", "ok", {"attempt": 1, "waited_s": 1.0, "priority": "background"}),
            (
                3.0,
                "retry",
                "warn",
                {
                    "reason": "rate_limited",
                    "attempt": 1,
                    "max_attempts": 3,
                    "retry_after_s": 300,
                    "message": "YouTube held the job back; it goes back into the queue.",
                },
            ),
        ],
    )
    events.backfill()


def seed_cuts(svc, client: httpx.Client, now: float) -> None:
    """One cut built for real through the mock, plus canned waiting/building/failed requests."""
    db = svc.db
    # The ready cut: a real build against the demo model over the seeded ASR transcript.
    r = client.post("/v1/videos/aaaaaaaaa07/cuts", json={"preset": "cut-no-filler"})
    if r.status_code != 200:
        raise RuntimeError("demo cut build failed: " + r.text)
    rid = r.json()["request_id"]
    for _ in range(100):
        doc = client.get(f"/v1/cuts/{rid}").json()
        if doc["state"] in ("ready", "failed"):
            break
        time.sleep(0.05)
    if doc["state"] != "ready":
        raise RuntimeError("demo cut did not go ready: " + json.dumps(doc))
    db.execute(
        "UPDATE cut_requests SET source='Living room TV', created_at=?, updated_at=? WHERE id=?",
        [now - 2400, now - 2330, rid],
    )
    # The request the TV created and is waiting on (the QR opens its sheet).
    db.execute(
        "INSERT INTO video_meta(video_id,json,fetched_at) VALUES(?,?,?)",
        [
            "aaaaaaaaa08",
            json.dumps(
                {
                    "title": "I tried the cheapest 4K projector so you don't have to",
                    "channel": "Tech Notes",
                    "duration_s": 1120,
                }
            ),
            now - 300,
        ],
    )
    db.execute(
        "INSERT INTO jobs(id,user,video_id,lang,status,progress,created_at,updated_at,kind,priority)"
        " VALUES('democut0009','owner','aaaaaaaaa08','','queued',0,?,?, 'cuts',0)",
        [now - 280, now - 280],
    )
    db.execute(
        "INSERT INTO cut_requests(id,user,video_id,source,state,job_id,created_at,updated_at)"
        " VALUES('democut0008','owner','aaaaaaaaa08','Living room TV','waiting','democut0009',?,?)",
        [now - 280, now - 280],
    )
    svc.jobs.events.record(
        "democut0009",
        "queued",
        "ok",
        {
            "kind": "cuts",
            "user": "owner",
            "client": "Living room TV",
            "endpoint": "POST /v1/videos/{video_id}/cuts",
            "video_id": "aaaaaaaaa08",
            "await_prompt": True,
        },
        ts=now - 280,
    )
    # One building (the model is choosing), one failed with a plain reason.
    db.execute(
        "INSERT INTO video_meta(video_id,json,fetched_at) VALUES(?,?,?)",
        [
            "aaaaaaaaa09",
            json.dumps(
                {
                    "title": "Category theory in 20 minutes",
                    "channel": "Chalkboard Maths",
                    "duration_s": 1290,
                }
            ),
            now - 200,
        ],
    )
    db.execute(
        "INSERT INTO jobs(id,user,video_id,lang,status,progress,created_at,updated_at,kind,priority)"
        " VALUES('democut0011','owner','aaaaaaaaa09','','running',0.4,?,?, 'cuts',0)",
        [now - 180, now - 120],
    )
    db.execute(
        "INSERT INTO cut_requests(id,user,video_id,source,preset_id,state,job_id,created_at,updated_at)"
        " VALUES('democut0010','owner','aaaaaaaaa09','Web UI','cut-highlights-5','building','democut0011',?,?)",
        [now - 180, now - 120],
    )
    for offset, stage, status, detail in (
        (
            0,
            "queued",
            "ok",
            {
                "kind": "cuts",
                "user": "owner",
                "client": "Web UI",
                "video_id": "aaaaaaaaa09",
                "preset": "cut-highlights-5",
            },
        ),
        (2.0, "started", "ok", {"kind": "cuts", "video_id": "aaaaaaaaa09"}),
        (2.1, "transcript", "running", {"video_id": "aaaaaaaaa09"}),
        (
            3.4,
            "transcript",
            "ok",
            {"source": "youtube_captions", "lang": "en", "units": 71, "chars": 9800},
        ),
        (3.5, "model", "running", {"model": "llama3.1:8b", "units": 71}),
    ):
        svc.jobs.events.record("democut0011", stage, status, detail, ts=now - 180 + offset)
    db.execute(
        "INSERT INTO video_meta(video_id,json,fetched_at) VALUES(?,?,?)",
        [
            "aaaaaaaaa10",
            json.dumps(
                {
                    "title": "A day at the canal, unhurried",
                    "channel": "Slow TV",
                    "duration_s": 8 * 3600,
                }
            ),
            now - 800,
        ],
    )
    db.execute(
        "INSERT INTO jobs(id,user,video_id,lang,status,error,created_at,updated_at,kind,finished_at,priority)"
        " VALUES('democut0013','owner','aaaaaaaaa10','','failed','Part 2 of 5 of this long video could not be analysed (the model service did not answer), so no cut was built. Try again.',?,?, 'cuts',?,0)",
        [now - 700, now - 660, now - 660],
    )
    db.execute(
        "INSERT INTO cut_requests(id,user,video_id,source,prompt,state,error,job_id,created_at,updated_at,finished_at)"
        " VALUES('democut0012','owner','aaaaaaaaa10','Living room TV','Only the part with the lock operation','failed','Part 2 of 5 of this long video could not be analysed (the model service did not answer), so no cut was built. Try again.','democut0013',?,?,?)",
        [now - 700, now - 660, now - 660],
    )
    for offset, stage, status, detail in (
        (
            0,
            "queued",
            "ok",
            {
                "kind": "cuts",
                "user": "owner",
                "client": "Living room TV",
                "video_id": "aaaaaaaaa10",
                "prompt": "Only the part with the lock operation",
            },
        ),
        (1.0, "started", "ok", {"kind": "cuts", "video_id": "aaaaaaaaa10"}),
        (1.1, "transcript", "ok", {"source": "asr", "lang": "en", "units": 912, "chars": 121000}),
        (
            1.2,
            "transcript",
            "failed",
            {
                "seconds": 0.1,
                "error_class": "CutRefused",
                "technical": "Part 2 of 5 of this long video could not be analysed (the model service did not answer), so no cut was built. Try again.",
            },
        ),
        (
            1.3,
            "failed",
            "failed",
            {
                "message": "Part 2 of 5 of this long video could not be analysed (the model service did not answer), so no cut was built. Try again."
            },
        ),
    ):
        svc.jobs.events.record("democut0013", stage, status, detail, ts=now - 700 + offset)


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
    seed_voice(db, now)
    seed_settings(svc, now)
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
                f"demojob{i:04d}",
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
    seed_job_reports(svc, now)
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
    # Feature-model overrides for the admin Features page: analysis on the "smart" alias, a recent
    # call history so the cost/time tiles are populated.
    db.execute(
        "INSERT INTO feature_models(feature,alias,changed_at,changed_by) VALUES(?,?,?,?)",
        ["analysis", "smart", now, "owner"],
    )
    db.execute(
        "INSERT INTO feature_models(feature,alias,changed_at,changed_by) VALUES(?,?,?,?)",
        ["cuts", "worker", now, "owner"],
    )
    db.execute(
        "INSERT INTO feature_audit(feature,from_alias,to_alias,changed_by,at) VALUES(?,?,?,?,?)",
        ["analysis", "llama3.1:8b", "smart", "owner", now - 3600],
    )
    for i, (feature, alias, toks) in enumerate(
        (
            ("summary", "worker", (1200, 180)),
            ("answer", "smart", (900, 220)),
            ("analysis", "smart", (3400, 510)),
            ("cuts", "worker", (2100, 300)),
        )
    ):
        for day in range(6):
            t0 = now - 86400 * day - i * 3600
            prompt, completion = toks
            cost = (prompt + completion) * (0.002 if alias == "worker" else 0.006) / 1e6
            db.execute(
                "INSERT INTO feature_calls(feature,alias,ts,elapsed_ms,prompt_tokens,"
                "completion_tokens,cost) VALUES(?,?,?,?,?,?,?)",
                [feature, alias, t0, 18000 + i * 1200, prompt, completion, round(cost, 6)],
            )
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
        seed_cuts(svc, client, now)


def main() -> None:
    block_youtube()
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
