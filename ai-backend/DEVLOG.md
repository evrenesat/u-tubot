# DEVLOG

## 2026-11-12 (YouTube pacing, circuit breaker, no title-only summaries, ask-to-transcribe)

- Incident: one home IP, one user browsing the TV home screen: about 70 transcript fetches in 3 hours (26 interactive summaries, 41
  tier-2 analyses, insights, caption jobs) in bursts; YouTube answered `/api/timedtext` with 429. Every later fetch failed, the
  fetcher stored a `metadata_only` transcript (empty text, cached 30 days) and summaries were generated from the title (5 vague
  bullets, cached as ready).
- `youtube.py`: `YoutubeGate`, a process-wide pacer plus breaker for yt-dlp metadata, timedtext and audio download. At most
  `[youtube] max_concurrent` (1) in flight, `min_interval_s` (3 s) + random `jitter_s` between requests (measured from the end of the
  previous request), interactive before background, `promote(key)` lifts a queued background fetch when a user starts waiting on
  it. Breaker: 429, 403 or "Sign in to confirm you're not a bot" (also yt-dlp "rate-limited by YouTube") open it for `Retry-After`
  or `cooldown_base_s` * 2^(consecutive blocks - 1) up to `cooldown_max_s`; interactive callers get `YoutubeCooldown` immediately,
  background callers wait (paused, they hold no slot and no tier-2 semaphore) and the first request afterwards is the probe.
  State (`youtube_gate` row) survives restarts so a crash loop cannot hammer YouTube. Injectable `Clock` for tests.
- Failures are classified (`classify_failure`, `classify_status`) into `YoutubeBlocked` (opens the breaker), `YoutubeDelayed`
  (network, 5xx, empty caption body: transient, breaker untouched) or a sanitised `YoutubeError`; messages never carry URLs
  (`from None`, query strings stripped) and the `httpx`/`httpcore` loggers get a URL-redacting filter because httpx logs every
  request URL, signed caption tokens included, at INFO.
- `TranscriptService.get(video_id, priority)` is the only way to a transcript: cache, then "no captions" marker, then one shared
  in-flight fetch through the gate. `no_captions` table (3 day TTL, `[transcripts] no_captions_ttl_s`) replaces the empty
  `metadata_only` row. `Database` start-up deletes legacy `metadata_only` transcripts, summaries and insights.
- Metadata-only generation removed: `ContentService.source` no longer falls back to the title; `NO_TRANSCRIPT` prompt text gone.
  Summary/insight/ask answer `transcript_status` (`ok|delayed|none|transcribing|failed|null`): transient problem is
  `pending`+`delayed`+`error`+`retry_after_s` (not cached, not recorded as a task failure via the `expected` exception flag);
  no captions is `needs_transcript`+`none`+`can_transcribe`+`message`+`estimate_s` and makes no LLM call.
- `transcribe.py` (`Transcription`): state from the DB only (`ok`, active job -> `transcribing` with progress, recent failed job ->
  `failed`, marker -> `none`), `request()` for `POST /v1/videos/{id}/transcribe`, `status()` for `GET .../transcript` (adds
  `unknown`, not in the five values, for videos never looked at). Estimate = `asr_overhead_s` + duration / `asr_speed_factor`.
- Jobs: `jobs` table gained `kind` (`captions|transcript`), `title`, `finished_at` (ALTER on start). Transcript jobs reuse
  `CaptionPipeline._recognise` (gated download, ffmpeg, ASR), build cues, store the text as source `asr`. One active job per user
  and video; the same video never runs twice at once; `_claim` skips queued work while the breaker is open (state `waiting`); a
  job whose download is refused goes back to the queue. `GET /v1/jobs` (mine, any kind, `waiting|processing|ready|failed`) is the
  groundwork for the "check later" shelf (issue #16). `[captions] transcribe_max_active_per_user` caps queued jobs.
- Volume: tier-2 default cap 30/day; scheduled only for a title question or clickbait score >= threshold (unchanged rule) and now
  also only when the breaker is not open, the video is not known to lack captions and fewer than `[youtube] max_background_queue`
  background fetches wait. The fetch happens outside the assess `_bg` semaphore (a paused fetch no longer blocks triage).
  Audit: the only path to YouTube text is `TranscriptService.get`; summary prompts, insight, ask and tier-2 share one fetch per TTL.
  `[transcripts] max_concurrency` removed (superseded).
- Web UI: shows `needs_transcript` with a "Transcribe in background" button, stops polling on `delayed`, lists all jobs.
- Tests: `test_youtube_gate.py` (pacing, jitter, concurrency, priority, promotion, breaker open/close/exponential/Retry-After cap,
  paused-not-failed, persistence, log hygiene, classifiers), `test_youtube_fetch.py` (real `YoutubeFetcher` with a mock
  timedtext transport and injected extractor: 429+Retry-After, bot check, no captions + expiry, empty body, 5xx, once-per-TTL),
  `test_transcript_flow.py` (HTTP flow, ASR job end to end, `/v1/jobs`, tier-2 gating, legacy purge, column migration),
  `tests/fakes.py` (`FakeClock`).
- Known follow-ups: the TV app does not know `needs_transcript`/`delayed` yet (issue #16 shelf, "Transcribe in background?"
  action); diarization is not applied to transcript jobs; a job paused inside the gate while running shows as `processing`.

## 2026-11-12 (glance summaries, panel default, background long summaries)

- Owner request: the side-panel summary was too long for the screen and slow; titles that pose a question or tease a reveal
  should be answered first.
- New built-in prompt `builtin/glance` (<= ~280 chars, <= 3 short lines, plain text, `→ answer` line first when the title poses
  a question or is a curiosity gap, "Not answered in the video" otherwise, then 1-2 lines of gist; `max_tokens` 160). The
  triage `title_question` fills `{question}` (it already did; the glance and `answer-title` templates now use it, and both work
  when it is empty). `answer-title` rewritten with the same curiosity-first logic. Builtin set version 2.
- `Prompt.task` (`summary` default, `glance`): picks the `[llm.*]` table. `[llm.glance]` (optional; `reasoning_effort` "none"
  and `max_tokens` 160 by default) falls back to `[llm.summary]` with reasoning off. `content_hash` only includes `task` when
  it is not `summary`, so existing prompts keep their cached summaries; old prompt-set files validate unchanged.
- Defaults split: `GET /v1/prompts` returns `panel_default` next to `default` (and `panel_default` per prompt);
  `PUT /v1/prompts/panel-default {"key"}` (separate route chosen over a `panel_key` field on `/default`); stored in the new
  `user_panel_default` table (created by `CREATE TABLE IF NOT EXISTS`, no migration); resolution order user choice, then
  `[summary] panel_prompt`, then `builtin/glance`. `GET /v1/videos/{id}/summary?prompt=panel` resolves to it and returns the
  resolved key in `prompt`. Web UI got a "Use for the side panel" selector.
- `[summary] auto_long` (default false) and policy field `auto_long` (null = follow config): after a `prompt=panel` request ends
  ready, `ContentService.schedule_long` queues the user's `default` prompt at `BACKGROUND` priority through the existing
  per-provider limiter; skipped when cached, running, recently failed, or the same prompt as the panel one. Summary job
  creation was factored into `_start_summary` (shared by the interactive and background paths, same registry key, so joiners dedupe).
- Condense (map) step: system prompt asks for the passage that answers the title's question or reveals its tease first, on
  an `ANSWER:` line; the map user message now carries the video title and the triage question. Caveat: `condensed` rows made
  before this change are reused as they are (key is video + budget); `DELETE FROM condensed` rebuilds them.
- Review fix: background and interactive runs of one summary are separate registry tasks (`summary_task_key`: `summary` vs
  `summary-bg`), so a background failure never makes an interactive request `failed`, and an interactive request never
  joins a background task (it starts its own and cancels the background one; same result row, last write wins).
  `[summary] auto_long_max_concurrent` (2) caps background long jobs from task start (transcript fetch included); over the
  cap `schedule_long` skips and a later panel request retries.
- Known follow-ups: the Android panel still preselects `default` from `GET /v1/prompts` (needs `panel_default` or
  `prompt=panel`); no thumbnail text exists in the metadata the app sends, so only the title is used today.
- Tests: `tests/test_glance.py` (panel alias, `{question}` from triage, condense focus, `[llm.glance]` and its fallback,
  auto_long off/on/policy override/background priority/failure isolation/interactive takeover/concurrency cap, panel-default PUT and fallbacks, old prompt files and hashes).

## 2026-11-12 (sync-github)

- `utubot app sync-github --repo OWNER/NAME [--prerelease] [--dry-run]` (`appsync.py`): newest `utubot-vX.Y.Z` release from the
  GitHub API, `release.json` (version, versionCode, per-ABI SHA-256), download with a size cap, SHA-256 check, signature and
  signing-certificate check against `[app] signing_cert_sha256`, then `appchannel.publish`. Newer means higher versionCode; no-op
  otherwise. Exit 0 ok, 1 check failed or misconfigured, 75 GitHub unreachable or rate limited. A missing pin, or an
  `apksigner_path` that does not run, refuses loudly.
- Signature check: `apksigner_path` set runs `apksigner verify --print-certs`; unset uses `apksig.py`, a pure-Python reader of the
  APK Signing Block (v2, v3, v3.1) that verifies the RSA signatures (PKCS#1 v1.5, PSS), recomputes the chunked content digest and
  returns the signer certificates. ECDSA/DSA keys and v1-only APKs are refused with a pointer to apksigner. Tests use APKs signed by
  apksigner with a throwaway key (`tests/fixtures/*.apk.bin`) and OpenSSL signature vectors.
- Releases without `release.json`: ABIs from file names, hashes from `SHA256SUMS`, versionCode derived from the version.
- `[app]` gains `github_repo`, `github_token_env`, `signing_cert_sha256`, `apksigner_path`, `keep_versions` and sync limits.

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
