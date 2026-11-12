# DEVLOG

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
