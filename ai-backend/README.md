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

Open `http://127.0.0.1:8790/` on any device and sign in with a username and password
(`uv run utubot user passwd owner`) or paste the token. The phone-first UI covers health and the YouTube gate, per-task
models from the live model list, prompts (sets, import, edit with validation, trying a prompt on a video), hide/mark
filtering, transcript policy and jobs, TV linking and devices, app updates, and (admins) users and their settings.
Plain HTML, CSS and ES modules under `src/utubot/web/`, no build step. See `../docs/server.md` (Web UI, Per-user settings).

## Configuration

One TOML file, `UTUBOT_CONFIG` (default `./config.toml`). `config.example.toml` lists every
option. Highlights:

- `[llm.providers.NAME]` any number of OpenAI-compatible providers; `[llm.triage|summary|glance|answer|analysis|captions]`
  pick provider and model per task (`glance` is the optional fast model for the side-panel summary). A prompt's `model` may be
  `alias` or `provider:model`.
- `[summary]` token budget and strategy, `panel_prompt` (side-panel prompt, `builtin/glance`), `auto_long` (also build the long
  summary in the background, off by default).
- `[security]` rate limits, pairing limits, request size cap, web sign-in (sessions, password hashing, lockout), `trusted_proxies` for
  `X-Forwarded-For` and `X-Forwarded-Proto` (loopback only by default); `[models]` the cached model list.
- `[default_policy]` and `[[users]] policy` hold the defaults of every per-user setting (filtering, models per task, transcript
  policy, TV settings); users override them in the web UI.
- `[assess]` batch size, wait cap, tier-2 daily cap per user (30).
- `[youtube]` pacing and circuit breakers (one per endpoint class: captions, metadata, media) for every request to YouTube
  (`max_concurrent`, `min_interval_s`, `jitter_s`, `cooldown_base_s`, `cooldown_max_s`, `captions_cooldown_max_s`), the JavaScript runtime for yt-dlp
  (`js_runtime_path`, `remote_components`); `[transcripts] no_captions_ttl_s`.
- `[archive]` the media archive (`path`, `quota_bytes`, `warn_frac`): every downloaded audio or video file is kept
  content-addressed by its sha256 and reused instead of being downloaded again; the quota only warns and stops, it never deletes
  (Admin → Media archive frees space).
- `[setup]`, `[app]` the public `/setup.json` (TVs import it by address), the landing page download codes and the GitHub
  update channel (`github_repo`, `signing_cert_sha256`, `apksigner_path`; `utubot app sync-github`, see `../docs/server.md`, Updates).
- `[captions]` the ASR engine chain (`[[captions.asr_engines]]`: `openai`-compatible servers and local `faster_whisper`, picked by health,
  language and priority, chunked and run in parallel; or the single `asr_*` keys), diarization (`none` or `pyannote`).
- Environment: `UTUBOT_CONFIG`, `UTUBOT_LLM_API_KEY`, `UTUBOT_ASR_API_KEY` (and any variable an ASR engine names), `UTUBOT_HF_TOKEN`.

## Auth and pairing

Everything except `GET /setup.json`, `GET /v1/health`, `POST /v1/pair`, the landing page and its static files (`/`, `/ui/*`), the
browser sign-in (`/v1/auth/login`, `/v1/auth/logout`) and `/app/*` (update.json, info.json, APKs)
needs `Authorization: Bearer <token>` or, for the web UI, the HttpOnly session cookie (writes then also need the `X-CSRF-Token`
header; caption `.vtt` accepts the bearer header, and `?token=` only for players that cannot set headers; URL tokens end up in logs and history, so avoid them).
`utubot user add NAME [--admin]` creates a user token; `utubot user passwd NAME` sets the web sign-in password; `utubot user pair NAME` prints a one-time
6-digit code that a device exchanges at `POST /v1/pair` for its own revocable token.

## CLI

```
utubot serve | user add|passwd|pair|devices|revoke | app publish APK... --version-name X --version-code N
utubot app sync-github [--repo OWNER/NAME] [--prerelease] [--dry-run]
utubot prompts validate FILE
```

## Prompt sets

`prompts/example-set.json` is a starting point. Each user has a `default` prompt (Summary view, `builtin/tldr`) and a
`panel_default` (side panel, `builtin/glance`); `GET /v1/videos/ID/summary?prompt=panel` uses the latter. Variables: `{title} {channel} {duration}
{description} {transcript} {language} {question}`. Validate with `utubot prompts validate FILE`,
host anywhere, import by URL (short links followed, 256 KiB cap).

## Captions

`POST /v1/videos/ID/captions` queues a persisted job: yt-dlp audio, ffmpeg 16 kHz mono, ASR,
optional diarization, segmentation (42 chars x 2 lines, 1-7 s), WebVTT with `[S1]` prefixes.
Jobs survive restarts. Needs `ffmpeg` on PATH.

Every job has a detail report (web UI: *Captions*, tap a job; `GET /v1/jobs/ID`): what was asked, each stage with its time, the result with
downloads, and which client fetched it (`../docs/server.md`, Job details).

## No transcript, no summary

Everything that reaches YouTube goes through `youtube.py` (`YoutubeGate`: pacing plus a 429/403/bot-check circuit breaker).
Summaries, insights and answers are never made from the title alone: a transient YouTube problem answers `pending` with
`transcript_status: "delayed"` and `retry_after_s` (but when only the caption API is limited and a speech engine is available the audio is
transcribed instead, like a video without captions), a video without captions answers `needs_transcript` and the user can start
`POST /v1/videos/ID/transcribe` (audio, chunked ASR, stored with source `asr`); with the default policy (`auto_transcribe = "on_open"`,
videos up to 30 minutes) the request that finds no captions starts it by itself and answers `pending` + `transcribing`. `GET /v1/videos/ID/transcript` and `GET /v1/jobs` show
progress. See `../docs/server.md` and `../ai/CONTRACT.md`.

## Tests

```sh
uv run pytest -q && uv run ruff check && uv run ruff format --check
```

Tests use an in-process mock OpenAI-compatible server (`tests/mock_openai.py`); no network.

## Deploy

See `deploy/README.md` (systemd unit, pairing, app publishing) and `../docs/server.md` (reverse proxy, config reference).
