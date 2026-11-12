# DEVLOG

## 2026-11-12 (review fixes, backpressure PR)

- summary/ask jobs now return their result (text, source) so deduped joiners read it; truncated
  summaries/answers sit in a short-TTL cache (`adhoc_ttl_s`) readable by all callers and the summary lookup also
  checks the ad-hoc row. Truncated map-step notes are never persisted in `condensed`.
- `llm.py`: one absolute deadline per logical call shared by truncation/bad-JSON retries; HTTP timeout clamped to the
  remaining deadline; a failed truncation retry returns the first (truncated) answer; HTTP error messages carry status
  and `error.code` only, never the response body.

## 2026-11-12 (truncated summaries)

- Bug: summaries cut mid-sentence were cached as ready. Per-prompt `max_tokens` overrode the task budget and reasoning
  models spent it on thinking (finish_reason=length). `max_tokens` is now the answer budget; `[llm] reasoning_headroom_tokens`
  (2048, per-task override, 0 allowed) is added to each request. `chat_result` retries once with double budget on length; if
  still cut the text gets " …", is logged kind=truncated and summaries are stored under the ad-hoc key (ad-hoc TTL).
- Built-in prompt budgets raised: tldr 700, answer-title 400, takeaways 900, worth-it 600, eli-new 700.

## 2026-11-12 (LLM backpressure)

- Production: the TV triggers /v1/assess per row, background triage saturated a fail-fast
  endpoint (503 engine_busy at its concurrency cap) and an interactive summary failed. Some
  triage calls failed with `no JSON found` (reasoning model, content empty or cut at max_tokens).
- `llm.py`: per-provider `PriorityLimiter` (`max_concurrent`, default 2; interactive before
  background; `reserved_interactive` slots background cannot take). Replaces the global
  `llm.max_concurrency`. Retries on 429/502/503/504 and connection errors with exponential
  backoff + jitter and Retry-After (seconds or date), bounded by a per-task deadline
  (`deadline_interactive_s`, `deadline_background_s`); never on other 4xx. Per-task
  `fallback = ["provider:model"]` after the prompt's own model; not used after a 4xx.
- JSON: `json_mode` per provider sends `response_format`; empty content with reasoning is a
  failure (reasoning is never parsed), retried once with `json_retry_max_tokens` and a
  "JSON only" nudge; failure kind logged (empty, truncated, no-json) without content. Plain
  `chat` also raises on empty output instead of caching an empty summary.
- `assess.py`: `coalesce_ms` window merges uncached videos from concurrent requests into shared
  batches (full batch flushes at once, in-flight dedupe unchanged).
- `errors.py`: busy failures surface as "the language model is busy, try again in a moment".
- Tests: `tests/test_backpressure.py` plus mock server knobs (busy, Retry-After, empty content).
  Docs: `docs/llm-providers.md` section "Fail-fast endpoints and backpressure".

## 2026-11-12 (overnight build)

- Built the backend: config, SQLite, OpenAI-compatible client (think-block and fence tolerant,
  one JSON retry), yt-dlp transcripts, batched triage plus tier-2 deep analysis, prompt sets,
  summaries/insight/ask with map-reduce, HQ caption pipeline with persisted job queue, web UI.
- Verified against real YouTube (metadata + captions for `jNQXAC9IVRw`) and real
  faster-whisper `small` int8 on CPU (19 s clip transcribed in about 7 s after model load).
  Needed `av<16`: PyAV 17+ breaks faster-whisper 1.2.1 (`metadata_errors`).
- Renamed project to u·tubot (package `utubot`, env `UTUBOT_*`).
- Hardening for public exposure: all routes token-gated except health/pair/app update,
  per-token and per-IP rate limits, body cap, strict 11-char video ids, constant-time compare,
  trusted-proxy X-Forwarded-For, docs endpoints disabled.
- Pairing: one-time 6-digit codes (hashed, 15 min), lockout per IP and globally, per-device
  revocable tokens, admin routes and UI.
- App update channel and `utubot app publish`.
- Multiple named LLM providers, per-task selection, `provider:model` prompt overrides.
- Pyannote diarization (community-1, token from `UTUBOT_HF_TOKEN`) implemented and tested with a
  stub only; not installed (torch) and no token tonight.

## 2026-11-12 (review fixes)

- SSRF: prompt-set import now goes through `urlguard.py`: every hop (manual redirect loop, max 5)
  needs http/https, default port, and only public resolved addresses (loopback, RFC1918,
  link-local, CGNAT, ULA, multicast, reserved, unspecified, mapped/6to4/NAT64/Teredo). The
  connection is pinned to the validated IP (Host header + SNI of the original name), so DNS
  rebinding between check and connect is closed. `summary.import_allow_hosts` bypasses it.
  The only other outbound fetch of a URL is the yt-dlp caption URL (from YouTube, not the caller).
- Error leakage: background/content/job failures return generic messages; details are logged
  server-side. Fetch/JSON errors no longer echo exception text.
- config.example.toml now holds working defaults (faster_whisper small int8, 4 threads,
  tier-2 cap 100, /var/lib/utubot paths).
- VTT accepts the Authorization header (already did via bearer; now tested and documented);
  `?token=` documented as discouraged.
- deploy: the service unit runs the venv binary with hardening and cache dirs under
  /var/lib/utubot/cache; README updated.

## 2026-11-12 (release preparation)

- `GET /setup.json` (public, rate limited) with `[setup]` config: name, backend and update URLs,
  pairing flag, app switch defaults and optional prompt set URLs, so a TV can configure itself
  from a short address. Documented in `ai/CONTRACT.md`.
- `utubot app publish` accepts several APKs, one per ABI (detected from `..._<abi>.apk`, or
  `--abi` for one file). It writes `downloadUrlList_<abi>` and `downloadUrlList` in update.json,
  plus `latest.json` (file names, sizes, sha256). `/app/latest/<abi>.apk` redirects (302) to the
  versioned file, so Downloader codes never change. `/app/info.json` and a public Download
  section on `/` (shown without a token) list the latest version, links and `[app]
  downloader_codes`.
- `security.trusted_proxies` now defaults to loopback only; add a reverse proxy address
  explicitly (docs/server.md).
- Version 0.2.0.
