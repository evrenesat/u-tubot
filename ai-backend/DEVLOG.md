# DEVLOG

## 2026-11-13 (media archive: keep every downloaded file, issue 34)

- Why: a job downloaded a video's audio, transcribed it and deleted everything; the next job downloaded the same audio again. Owner rule:
  never throw away downloaded media, never fetch the same thing twice. The report hooks were ready (`audio_download.source` =
  `downloaded|from_archive`, the report says "From the media archive"); now there is a real archive behind them.
- `utubot/media_archive.py` (new): content-addressed store. `lookup(video_id, kind)` → newest row for the video, original track first,
  verified on disk (a row whose file vanished is dropped, the video is fetched and stored again). `store(...)` copies the download into
  `files/<sha256[:2]>/<sha256>.<ext>` under `[archive] path` (empty: `<data dir>/archive`), fsync, `os.replace`, identical bytes stored
  once, the scratch original unlinked; the row carries format id, codec, bitrate, language, original flag, size, sha256, fetch time and the
  job id. `require_room` refuses a download at `quota_bytes` (0: no limit) with `MediaArchiveFull` — warn/stop, never silent deletion;
  `store` warns at `warn_frac` (0.9) and keeps a file that pushes usage over the quota. `remove(video_id)` is the one admin cleanup (a file
  another row still uses stays); `sweep_scratch` clears crash-left staging files at start, rows never.
- Pipeline: `_recognise` looks the video up in the archive first — a hit skips the gate and the download entirely (`audio_download` with
  `source=from_archive`), a miss checks the room, downloads as before and gains a `media_archive` stage (`bytes`, 12-char sha256 prefix)
  that keeps the file; the job then reads the audio from the archive. On a store failure (`MediaArchiveError`) the job fails and the scratch
  directory survives (`_keep_for_archive` checks the unwinding exception in the `finally`), so the download is not thrown away. Jobs map
  both errors to clear messages ("The media archive is full; an admin must free space…"). No magic numbers: `[archive]` in
  `config.py` + `config.example.toml`.
- Admin surface: `Services.archive`; `GET /v1/admin/archive?video_id=&limit=` (usage vs quota, state ok/warn/full, entries newest first,
  full sha256 — admin only), `DELETE /v1/admin/archive/{video_id}` (404 when nothing stored), `archive` in `GET /v1/admin/status`. Web UI:
  *Admin → Media archive* (`#/admin/archive`, usage card, one row per video with format/size/sha/age, Remove with confirm), linked from the
  users page; `jobtext.js` names the `media_archive` stage.
- Tests (`tests/test_media_archive.py`, no YouTube — the fake downloader and the env fixture): store/lookup round trip, content-addressed
  dedupe, original-first lookup, missing file pruned, quota stop before a download, warn state, job reuses the archive on the second run
  (downloader called once, `from_archive` in the event), job fails clear when full, admin API auth (401/403) and removal, scratch sweep
  leaves the archive alone. Suite 654 passed, ruff clean.

## 2026-11-13 (tests and dev servers never hit YouTube: fixtures and offline mode, GitHub #35)

- Why: the owner rule says tests, CI and agent verification runs never touch YouTube; the pytest guard (`block_youtube`) covered yt-dlp and
  httpx, but nothing replayed real YouTube answers and a running backend (emulator, E2E) had no way to work without the network.
- Fixtures: new `youtube_fixtures.py`. A cassette (`fixtures/youtube/<video id>.json`) keeps one video's recorded yt-dlp info dict and the
  caption track text, sanitized: every `url`/`fragment_base_url`/`http_headers` key is dropped and remaining strings have URL queries
  stripped (they carry signed tokens; `sanitize_info`, checked by tests). `utubot_demo.json` is a hand-written demo cassette; the owner
  records real ones with `utubot youtube-record VIDEO_ID` — the one command that reaches YouTube, guarded to refuse under pytest.
- Offline dev-proxy mode: `[youtube] offline = true` (`fixtures_dir` moves the cassette dir). `YoutubeFetcher` refuses before yt-dlp, the
  gate refuses every media-class transfer (`YoutubeOffline`, a video error with reason `offline`, so no audio fallback is offered), and
  `build_services` wires `OfflineYoutubeFetcher`: cassettes answer through the same parsers as the real fetcher, unknown videos answer
  `offline` and are remembered as failed. Status (`/v1/... home`, admin status route data) shows `offline: true`. Cached transcripts and
  metadata keep working, so the emulator and `UtubotBackendE2eTest` can run against the real backend with no route out.
- Guard: `block_youtube()` also patches `socket.getaddrinfo`/`gethostbyname` — DNS-level refusal for anything the library patches miss
  (urllib, raw sockets). New `test_network_guard.py`, `test_youtube_fixtures.py`, `test_youtube_offline.py` (the real app serves the demo
  cassette's summary with the mock LLM, offline).

## 2026-11-13 (job report: event log, delivery, detail page)

- Why: the jobs list only showed kind/state/progress; a "ready" captions job for a Turkish video did not say what it produced or whether the TV
  fetched it. Every job now keeps a log and has a report page.
- Log: new `job_events(id, job_id, ts, stage, status, detail JSON)` table (index on job_id) and `job_id` columns on `captions` and
  `transcripts` (migrated; `store_asr(..., job_id=)`). `captions/events.py`: `JobEvents` (record, list, `deliver`, `backfill`), `JobTrace` bound
  per running job in a `ContextVar` (`events.bind`/`unbind`), module helpers `emit`, `stage(...)` (a running event, then ok/failed/skipped with
  `seconds`), `note` / `take_notes` (facts learnt deep inside a stage, for example the yt-dlp format), and `set_origin` (who is behind the HTTP request).
  A ContextVar instead of parameters because `pipeline.transcribe`, `ASRBackend.transcribe` and the downloaders have many stubs in tests and
  threads (`to_thread`, `gather`) inherit the context. Without a bound trace every helper is a no-op.
- Instrumented: `JobQueue` (queued with user, client, endpoint, trigger and priority; promoted; started; retry; restart; cancelled;
  caption recheck; stored; finished; failed with cause class, message and stage), `CaptionPipeline` (gate wait, audio download with
  format id / track kind / language / bytes / `source`, ffmpeg, ASR totals, text, diarization, cues, translate, stored), `AsrRouter` (chunking,
  one event per chunk with engine, model, seconds, characters and language, `asr_fallback` with `EngineError.code`, stitching via
  `chunking.StitchStats`), the diarizers (`events.note(skip=...)`). `audio_download.source` is `downloaded` or `from_archive`; the media archive
  (GitHub #34) sets it with `events.note(source=events.AUDIO_FROM_ARCHIVE)`.
- Privacy: `events.clean` filters every detail before it is stored (keys naming token/secret/cookie/header/url dropped; URLs, `key=value`
  secrets, bearer tokens, hex digests, `utb_`/`sk-` keys and mixed-case 32+ character runs replaced; text cut to 240 characters; depth and list
  limits). Failure text is `events.technical(exc)`, never `str(exc)` raw. A model name such as `whisper-large-v3-turbo+whisper-small` must
  survive, which is why the random-run rule needs upper case, lower case and a digit.
- Delivery: `JobQueue.record_captions_delivery` / `record_transcript_delivery` credit the job that made the stored track (`captions.job_id`) or
  transcript (`transcripts.job_id`, ASR only; older rows fall back to the video's newest ready job). Called from `GET .../captions` (with
  tracks), `.vtt`, `GET .../transcript` (ok, asr), ready summary / panel summary / ask, `GET /v1/jobs/ID/transcript.txt`. Client name:
  `client_of(request)` = device name, "Web UI" or "API token". `deliver` coalesces the same client and way within `delivery_coalesce_s` into
  one row with a `count`. `[captions] job_events_max` caps stage events per job (milestones always kept).
- API: `GET /v1/jobs/{id}` (`captions/report.py`, `JobReports`; owner or admin, else 404 like cancel/retry), `GET /v1/jobs/{id}/transcript.txt`,
  `detail_url` / `api_url` / `stage` / `delivered` / `delivered_at` on `GET /v1/jobs`. Routes that can queue a job call `mark_origin(request, user)`
  first (cancel and retry too). `Transcription.request(..., trigger=)` carries the policy that fired for automatic starts.
- Backfill: `JobQueue.__init__` writes one synthetic event (`finished`, or `queued` for waiting jobs) for every job without events; the report
  also synthesises one on the fly for jobs inserted by other means.
- UI: `pages/job.js` (route `#/jobs/ID`, hidden from the bar, Captions stays lit), `jobtext.js` (labels, one-line summaries, `collapse` folds a
  running event into the one that ends it; pure, checked with node in the tests), `transcripts.js` rows link to the report and show
  fetched / not fetched. Auto refresh every 3 s while the job is waiting or running, 15 s afterwards; the page redraws only when the data changed.
  Screenshots 22 to 24 and a new 13; `capture.cjs` also checks the job pages for sideways scroll and console (CSP) errors at 360 px.
- Owner rule (no YouTube in tests): `tests/conftest.py` `block_youtube()` makes yt-dlp `extract_info`/`download`/`urlopen` raise and the real
  httpx transports refuse YouTube hosts, in an autouse fixture and in `webui_demo.py`; tests stand in for `yt_dlp.YoutubeDL` or the fetcher and
  downloader. `webui_demo.py`: the gate close endpoint now resets the per-class breakers (it still set the old single-breaker fields), demo job
  reports with event logs (a Turkish captions job fetched by a TV, an unfetched transcript, a failed and a waiting job).
- Review fixes: `events.clean` now handles quoted keys and values, `Authorization`/`Proxy-Authorization` with Bearer/Basic/Digest values,
  bare `Bearer ...`, cookie values to the end of the line (also `Set-Cookie`), compound names (`hf_token`, `client_secret`, `x-api-key`) and
  `token abcdefgh1234` without a separator (only a value of 8+ characters with a digit), and scans at most 2000 characters; plain words such as
  "Keyboard: the build" or "token provided" stay. `delivered` rows are capped per job (`[captions] delivery_events_max`, 50): past it a
  delivery is counted into the newest row. `Database` sets `PRAGMA synchronous=NORMAL` with WAL: no corruption risk, but a power loss may drop
  the last few commits (a delivery count, a just-written session) instead of none.
- Tests: `test_job_report.py` (stage order for transcript and captions jobs, who asked and the policy, cancel/retry/restart/transient retries,
  caps, mocked yt-dlp format notes, mocked engine fallbacks and stitching, secrets/URLs, auth, delivery by client kind, backfill, the UI assets
  under the CSP and the report text through node).

## 2026-11-12 (audio when captions are limited)

- Why: production showed "YouTube is limiting transcript downloads, retrying in 34 minutes". Only the caption class (timedtext) was 429;
  audio downloads worked and the fast engine transcribes 30 minutes in about 30 s. The caption breaker also kept escalating because each
  probe after a cooldown was an interactive request that hit 429 again.
- Fallback: `Transcription.state()` (cheap, also behind `GET /transcript`), `blocked()` and `problem()` ask `captions_limited()` (the
  breaker is open or the probe is out: `YoutubeGate.interactive_ok(*FETCH_CLASSES)` is false) or get a fetch ended by a back-off reason
  (`rate_limited`, `forbidden`, `bot_check`, `cooldown`) and call `audio_fallback()`: `media` healthy and `can_transcribe` (not live, within
  `max_duration_s`, an engine serves the language) give the "no captions" fields (`transcript_status: none`, `can_transcribe`, `estimate_s`,
  message "Captions are temporarily unavailable from YouTube; transcribe the audio instead (~N s)?"; no `(~N s)` when the length is
  unknown), which `auto()` turns into a started job under the user's policy (`on_open` explicit, `on_dwell` also the panel, up to
  `auto_transcribe_max_minutes`). Nothing is remembered. A network error, no engine, a live or too long video, or a cooling `media`
  class (a bot check opens metadata and media) keep `delayed`. Existing delayed tests now cool `media` (`audio_unreachable`).
- Probing: `PROBE_CLASSES = (captions,)` are probe-only once half-open. `_acquire` refuses an interactive request for such a class
  (`YoutubeCooldown`, hint `captions_probe_retry_s`), lets exactly one background request through (`_Breaker.probing`, released in
  `_release`) and holds the other background waiters behind it; `promote` skips probe-bound waiters. `TranscriptService.probe_captions`
  starts that background fetch for the video of the first content request that finds the class half-open (never from `GET /transcript`,
  skipped for cached, held and no-captions videos). A complete yt-dlp answer without a caption track (`ANSWERED_NO_CAPTIONS`)
  counts as answered for the caption class too, so a probe on such a video closes it instead of leaving it half-open. An
  interactive transcript job skips its caption recheck while the probe is out; a background job may be the probe.
- Caps: `[youtube] captions_cooldown_max_s` (1800) is the ceiling of the caption class, `Retry-After` included, never above
  `cooldown_max_s`. Old tests that probed with an interactive request now probe with `BACKGROUND`.
- Stored transcripts: `_fetch` upserts captions with `WHERE source != 'asr'` (and clears engine/model/segments for caption rows), so a late
  or in-flight caption fetch returns the stored ASR transcript instead of replacing it; `cached()` already returned ASR first, so there is
  no refetch.
- Engines (PR #22 review): `_chunk_on` re-checks health after `limiter.acquire` and `_span_on` before each sub-chunk
  (`_passed_over`: unhealthy and a healthy engine later in the chain, `EngineError(penalize=False)`); unknown language sorts engines
  without `languages` first and `_span` redoes a chunk an allow-listed engine took when the detected language is outside its list (the
  result is kept as a last resort); `EngineError.isolated` (5xx, unreadable or oddly shaped answer, a non-connect/timeout transport error)
  marks the engine only after two different files failed with no success between (`_record_failure`, keyed by the wav path); connect and
  timeout failures, 429 and 401/403/404 still mark at once.
- yt-dlp: `ytdlp_runtime_options` always passes `js_runtimes={js_runtime: {path}|{}}` (yt-dlp looks the runtime up on PATH without a path);
  `pyproject.toml` requires `yt-dlp>=2025.11.12`, the first release with `remote_components` (checked in the 2025.10.22 and 2025.11.12
  wheels; the lock holds 2026.10.26 and its specifier is updated).
- Review fixes (PR #24): `store_asr` replaces captions older than `cache_ttl_s` (they are unusable: `cached()` ignores them), so an
  expired captions row no longer makes state() offer the fallback, run ASR and store nothing in a loop; a transcript job that ends with
  no usable transcript (`cached()` is None after `store_asr`) now fails with the recorded message instead of finishing silently.
  `[captions] asr_failure_window_s` (600): two isolated engine failures only count together when at most that far apart.
- Tests: `test_gate_probe.py`, `test_audio_fallback.py` (policy, panel, 429 now, probe flow, escalation cap, late captions, jobs), engine
  and media additions.

## 2026-11-12 (fast transcripts, issue #19)

- Gate: `YoutubeGate` keeps one shared pacer and one breaker per endpoint class (`captions` = timedtext, `metadata` = watch/player/yt-dlp
  extract, `media` = audio download; state in `youtube_gate_class`, the old single row is adopted by all three once). Why: the TV
  home screen's timedtext fetches got 429 while googlevideo audio downloads still worked, and the single breaker paused those too. Errors
  carry `klass` (`classify_failure`/`classify_status` take it), `run(..., classes=)` names what an operation needs, a block opens the class
  that got it (a bot check opens both yt-dlp classes), a success closes the classes it `answered` (`FetchResult.answered`). Pacing stays
  shared on purpose (the owner's request rate is one number); `healthy()/state()/cooldown_remaining()` without arguments mean "all
  classes", `snapshot()` feeds `GET /v1/status` (`youtube.classes`, `asr.engines`). Jobs are claimed while `media` is healthy; a transcript
  job skips its "did captions appear?" recheck when `metadata`/`captions` cool or answer delayed and goes straight to the audio.
- Audio: `captions/formats.py` picks the lowest-bitrate audio of the original track from yt-dlp's format list (a yt-dlp `format`
  callable; fallback chain in the module doc and `docs/captions.md`; `audio_format` is only the last resort). Real multi-track videos
  (checked on a 29 minute lecture with 20 languages) mark only the original (`... original (default)`), other tracks are plain language
  names, so "marked original wins" is the operative rule; dubbed/descriptive notes are excluded when no marker exists.
- JS runtime: `[youtube] js_runtime`, `js_runtime_path`, `remote_components` go to yt-dlp (`js_runtimes`, `remote_components`) for the
  metadata fetch and the download. Verified live without deno on PATH: no option = "No supported JavaScript runtime"; path only =
  "n challenge solving failed" (the solver script is missing); path + `remote_components = ["ejs:github"]` = clean and one more format.
- ASR: `captions/engines.py` (`AsrRouter`, `OpenAIEngine`, `FasterWhisperEngine`) replaced `OpenAIASR`/`FasterWhisperASR`.
  `[[captions.asr_engines]]` (name, kind, url, model, api_key_env, languages, max_chunk_s, max_parallel, timeout_s, priority,
  background_only, speed_factor, overhead_s); the old `asr_*` keys become one engine `default` (key optional). Selection: enabled (key
  env set, package present) -> serves a known language -> not background-only for interactive jobs -> healthy first -> priority (lower
  first). Failures fall through per chunk, the next engine re-cuts to its own limit; 5xx/429/transport/401/403/404 mark the engine
  unhealthy for `asr_unhealthy_s`, input rejections (400/413/415/422) do not; all unhealthy = try anyway. Per-engine `PriorityLimiter`
  (`max_parallel`) is shared by all jobs. Unknown video language lets restricted engines through (documented caveat).
- Chunking (`captions/chunking.py`): `plan_chunks` with 2 s overlap and a tail fold, WAV slicing in a thread, `stitch_*` cut at each
  overlap midpoint then drop a repeated seam (>= 2 words, only when the next chunk starts inside the overlap). Progress = done chunks /
  chunks. Transcripts keep `segments` (JSON), `engine`, `model` (new `transcripts` columns, migrated); `GET .../transcript` shows them.
- Policy: `Transcription.auto` acts on `auto_transcribe` / `auto_transcribe_max_minutes` (fields from the web UI branch's
  `UserPolicy`): explicit requests (summary view, insight, ask, ad-hoc) start on `on_open`/`on_dwell`, `prompt=panel` only on
  `on_dwell`; known length <= limit, `can_transcribe`, queue not full, else `needs_transcript` as before. Jobs have a `priority`
  (explicit = interactive, panel = background, promoted when the user opens the video); claim order is priority then age.
- Estimates: `download_overhead_s + duration / download_speed_factor + engine.overhead_s + duration / (speed_factor x min(max_parallel,
  chunks))` for the engine the selection would pick now.
- Real check (public videos, stub caption fetch, real yt-dlp and ASR endpoint): 5.6 min video: 3.9 s download (2.0 MB), 4.7 s ASR, 17.6 s
  whole job (about 4 s of that is the gate's mandatory gap between the caption check and the download); 29.5 min lecture: 2.5 s download
  (10.7 MB), 3.4 s ffmpeg, 16.4 s ASR (3 chunks in parallel, ~108x real time), 30.7 s whole job. Seams at 598 s and 1196 s were clean.
- Tests: `test_gate_classes.py`, `test_audio_formats.py`, `test_chunking.py`, `test_asr_engines.py` (stub engines, mock HTTP, the documented
  chain), `test_auto_transcribe.py` (policy, priorities, estimates, migration, end to end with ffmpeg), plus media/flow updates. The
  ask-first flow tests opt the owner out with `auto_transcribe = "off"`.

## 2026-11-12 (R4: phone web UI, per-user settings, web sign-in; issue #9)

- UI: `web/index.html` is now a static shell; `web/ui/app.css` and `web/ui/js/**` (ES modules, no build, no npm, no external requests)
  render Home, Models, Prompts, Filters, Captions, TVs, Updates, Account and Admin. DOM only through `h()`/`textContent` (a test greps
  for `innerHTML` and friends), CSP `default-src 'none'; script-src 'self'; style-src 'self'` on every response, no inline code. Phone
  first (bottom bar at 360 px, left sidebar from 900 px), dark and light (system, with a switch), no sideways scroll at 360 px
  (`docs/screenshots/webui/capture.cjs` checks it). `tests/webui_demo.py` serves canned data for screenshots.
- Sign-in (`webauth.py`, `passwords.py`): scrypt passwords (`utubot user passwd`, web UI), token sign-in kept but exchanged for a
  session, HttpOnly `SameSite=Lax` cookie (Secure through `security.is_https`: direct HTTPS or `X-Forwarded-Proto` from a trusted
  proxy), 30-day sliding sessions stored as SHA-256, CSRF = per-session `X-CSRF-Token` (derived from the session id) plus an `Origin`
  check, lockout per IP, per account and global in `login_failures` (a wrong password and an unknown user look the same, dummy
  verify). Bearer tokens (TVs, scripts) are untouched and need no CSRF.
- Settings: `UserPolicy` grew `models`, `mark_only`, `auto_transcribe`, `auto_transcribe_max_minutes`, `summary_delay_ms`,
  `summary_panel`, `auto_captions`, `update_checks` (validated ranges; thresholds <= 1.01, topics trimmed and deduplicated). They ride
  the existing override row (`policy_overrides`, now with `version` and `updated_at`), so `[default_policy]` -> `[users.policy]` ->
  override is the precedence and `None` fields follow `[summary]`/`[setup.defaults]`; `settings.py` is a view with PUT
  (partial, `null` resets, optional `version` -> 409) over that row and the prompt-default tables. `resolve_users` replaced the reload
  in `Auth._refresh` (users.toml edits no longer reload config.toml, `declared_users` keeps the file's users).
- Models in use: summaries use `with_user_model` (user model when the prompt has none; part of the content hash, so cached apart),
  insight/analysis/ask pass `model=`, title triage batches are keyed by (topics hash, model). The shared triage, insight and deep caches
  stay keyed without the model (documented). `modelcatalog.py` caches each provider's `/models` (5 min, error ttl, forced refresh
  rate-limited), remembers `model_seen` so a restart does not mark everything new, never returns keys.
- Status: `/v1/status` (gate, LLM and transcript counters from `usage_daily`, which `LLMClient` fills per call), `/v1/updates` (channel,
  cached GitHub release lookup, `sync.json` written by `utubot app sync-github`). Jobs: `cancel` (waiting only) and `retry`
  (failed/cancelled), state `cancelled`. Small additions: `/v1/me/devices|pair`, `/v1/videos/resolve`, `/v1/prompts/validate`,
  `/v1/users*` (create with password and no token, admin flag only for users.toml users).
- Tests: `test_websession.py` (login, cookie flags, CSRF, Origin, sliding expiry, lockout, password change, CLI), `test_settings.py`
  (document, validation, versions, precedence incl. config files, models applied to calls, admin routes, migration),
  `test_modelcatalog.py` (cache, refresh, new marks, errors, no secrets), `test_webui.py` (static assets and CSP, module graph, every
  route needs auth, admin-only routes, users, devices, jobs, status, updates, resolve).
- Review fixes: (1) a password change used to sign the browser out: the edge middleware re-issued the old, revoked session cookie after
  the handler had set the new one; the handler now owns the cookie (`fresh_session`, also for an admin setting their own password) and
  the middleware skips a response that already sets it. (2) Client IP behind two proxies: `[security] client_ip_header` (+
  `client_ip_header_secret_env`, `X-Utubot-Proxy-Secret`) names the client for a trusted peer that proves the secret (constant-time),
  ignored otherwise, XFF logic as before. (3) `SettingsService.update` re-reads the version after the model check and writes with a
  compare-and-set (`Auth.write_override(expected=)`); browser sessions must send `version` (428), bearer callers may omit it.
  (4) `allow_unlisted_models` is admin-only, and `PUT /v1/me/policy` refuses `models` from non-admins (it skipped the list check).
  (5) scrypt N=2^17 (`scrypt_max_concurrent` bounds the memory), old hashes verify (parameters are bounded when read) and are
  re-hashed on the next successful sign-in with a compare-and-set on the old hash.
- Left for R5: the enrollment link and QR for "Link a TV" (placeholder in the TVs page), first-run admin creation and the
  provider/key wizard in the UI, the TV reading `GET /v1/me/settings`, acting on `auto_transcribe` (server or TV).

## 2026-11-12 (review fixes for the YouTube gate)

- Breaker scope: only a 429, the bot check or a 403 on the watch/player/metadata request open it. A 403/410 on a caption or media
  URL and private, members-only, age-gated or unavailable videos raise `YoutubeVideoError` (`transcript_status: "failed"` + `reason`),
  recorded in `video_holds` (`[transcripts] video_failure_ttl_s`, 1 h) so they are not re-fetched; any such answer closes a half-open
  breaker and resets the escalation. `RATE_LIMIT_RE` no longer matches a bare "try again later".
- Jobs: `YoutubeDelayed` (including blocked) re-queues with `attempts` and `not_before` (gate clock), capped by
  `[captions] job_max_attempts` (3), then fails; a per-video error fails the job at once. Orphan `media/<id>` directories older
  than `media_orphan_age_s` are removed at start.
- Media lane: `YoutubeGate.run_started` holds the paced slot only until the download signals its first bytes (yt-dlp progress
  hook), then releases it; a 429 after the start still opens the breaker. yt-dlp gets a `match_filter` (live, duration) and
  `max_filesize`; the converted WAV is re-checked against `max_duration_s` before ASR.
- Soft-degraded answers: "no captions" is cached only from a complete yt-dlp answer (formats present, no caption language listed
  without formats); otherwise `delayed`. A caption file that parses to nothing is `delayed` with a `video_holds` entry
  (`empty_track_retry_s`, 1 h), never "no captions".
- ASR vs captions: a transcript job first re-checks YouTube (`get(recheck=True)`, ignores the no-captions memory) and uses captions
  if they exist; `store_asr` never replaces a `youtube_captions` row (a fresh complete "no captions" answer deletes a stale one).
- Tier-2 refunds the daily slot when the fetch ends delayed. `GET .../transcript` shows `job_id` only for the caller's own job;
  `state()` and the summary/insight/ask responses never carry one. `delayed` can appear on that endpoint (empty-track hold).
- Tests: scoped classification, per-video failures end to end, retry cap (network and blocked), media start gating, filters,
  sweep, soft-degraded answers, recheck, refunds, job-id scoping (`test_youtube_gate.py`, `test_youtube_fetch.py`, `test_media.py`,
  `test_transcript_flow.py`).

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
