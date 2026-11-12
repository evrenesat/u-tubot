# u·tubot backend

Python service behind the forked Android TV YouTube client. It owns model calls, transcripts,
per-user policy, summaries and high-quality captions. Wire contract: `../ai/CONTRACT.md`.

FastAPI + httpx + SQLite. LLMs are any OpenAI-compatible chat-completions endpoints
(local or cloud; set `[llm.providers.*]`, no default host). Python 3.12, managed with `uv`.

## Setup

```sh
cd ai-backend
uv sync                        # core
uv sync --extra asr            # + local faster-whisper (CPU, no torch)
uv sync --extra diarization    # + pyannote.audio 4.x (pulls torch; large, optional)
cp config.example.toml config.toml
export UTUBOT_LLM_API_KEY=...  # only if your provider needs a key; never put keys in config.toml
uv run utubot user add owner --admin   # prints the token once
uv run utubot serve            # 127.0.0.1:8790
```

Open `http://127.0.0.1:8790/`, paste the token. The UI covers health, policy, prompt set
import/edit/default, trying summaries (saved or ad-hoc prompt text), caption jobs, and (admins)
pairing codes, devices and policy edits.

## Configuration

One TOML file, `UTUBOT_CONFIG` (default `./config.toml`). `config.example.toml` lists every
option. Highlights:

- `[llm.providers.NAME]` any number of OpenAI-compatible providers; `[llm.triage|summary|answer|analysis|captions]`
  pick provider and model per task. A prompt's `model` may be `alias` or `provider:model`.
- `[security]` rate limits, pairing limits, request size cap, `trusted_proxies` for
  `X-Forwarded-For` (loopback only by default).
- `[assess]` batch size, wait cap, tier-2 daily cap per user.
- `[setup]`, `[app]` the public `/setup.json` (TVs import it by address) and the landing page download codes.
- `[captions]` ASR backend (`openai` or `faster_whisper`), diarization (`none` or `pyannote`).
- Environment: `UTUBOT_CONFIG`, `UTUBOT_LLM_API_KEY`, `UTUBOT_ASR_API_KEY`, `UTUBOT_HF_TOKEN`.

## Auth and pairing

Everything except `GET /setup.json`, `GET /v1/health`, `POST /v1/pair`, the landing page and `/app/*` (update.json, info.json, APKs)
needs `Authorization: Bearer <token>` (caption `.vtt` accepts the same header, and `?token=` only for players that cannot set headers; URL tokens end up in logs and history, so avoid them).
`utubot user add NAME [--admin]` creates a user token; `utubot user pair NAME` prints a one-time
6-digit code that a device exchanges at `POST /v1/pair` for its own revocable token.

## CLI

```
utubot serve | user add|pair|devices|revoke | app publish APK... --version-name X --version-code N
utubot prompts validate FILE
```

## Prompt sets

`prompts/example-set.json` is a starting point. Variables: `{title} {channel} {duration}
{description} {transcript} {language} {question}`. Validate with `utubot prompts validate FILE`,
host anywhere, import by URL (short links followed, 256 KiB cap).

## Captions

`POST /v1/videos/ID/captions` queues a persisted job: yt-dlp audio, ffmpeg 16 kHz mono, ASR,
optional diarization, segmentation (42 chars x 2 lines, 1-7 s), WebVTT with `[S1]` prefixes.
Jobs survive restarts. Needs `ffmpeg` on PATH.

## Tests

```sh
uv run pytest -q && uv run ruff check && uv run ruff format --check
```

Tests use an in-process mock OpenAI-compatible server (`tests/mock_openai.py`); no network.

## Deploy

See `deploy/README.md` (systemd unit, pairing, app publishing) and `../docs/server.md` (reverse proxy, config reference).
