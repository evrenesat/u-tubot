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

from tests.conftest import FakeFetcher, block_youtube  # noqa: E402
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
            for name, breaker in svc.gate._breakers.items():
                breaker.until, breaker.strikes = 0.0, 0
                svc.gate._save(name)
        return {"gate": svc.gate.state()}

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
