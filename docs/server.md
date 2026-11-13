# Running the u·tubot backend

The backend is a small Python service (FastAPI, SQLite) in `ai-backend/`. It does all model work: LLM calls through any
OpenAI-compatible endpoint, yt-dlp downloads, speech recognition, per-user policy and caching. The TV app only sends video
metadata and shows results. Wire details: [../ai/CONTRACT.md](../ai/CONTRACT.md).

## Requirements

- Linux (or macOS) with Python 3.12 and [uv](https://docs.astral.sh/uv/).
- `ffmpeg` on `PATH` (HQ captions).
- An OpenAI-compatible chat-completions endpoint: [llm-providers.md](llm-providers.md).
- Optional: `faster-whisper` for local speech recognition (CPU, `--extra asr`), `pyannote.audio` for speaker labels
  (`--extra diarization`, pulls torch).
- A TLS name reachable from the TVs for use outside your LAN (below).

## Install and first run

```sh
git clone https://github.com/evrenesat/u-tubot.git
cd u-tubot/ai-backend
uv sync                          # core; add --extra asr and/or --extra diarization
cp config.example.toml config.toml
$EDITOR config.toml              # providers, models, public_base_url
export UTUBOT_LLM_API_KEY=...    # only if your provider needs a key (the env var named by api_key_env)
uv run utubot user add owner --admin   # prints the token once; only its hash is stored
uv run utubot serve              # 127.0.0.1:8790
```

Open `http://127.0.0.1:8790/`: sign in with a username and password (`uv run utubot user passwd owner` sets one) or paste the
token. The phone-first [web UI](#web-ui) steers everything: models, prompts, filtering, transcripts, TVs, updates, users. Without a
session the page shows the sign-in form and the public Download section only.

The config file is `$UTUBOT_CONFIG` or `./config.toml`; `utubot --config PATH SUBCOMMAND` overrides it. Config changes need a
restart; `users.toml` changes are picked up live.

## CLI

```
utubot [--config PATH] serve [--host H] [--port P]
utubot user add NAME [--admin]      create a user, print a token once
utubot user passwd NAME [--stdin]   set the web sign-in password (prompts twice; --stdin reads one line)
utubot user pair NAME               one-time 6-digit code (15 minutes) for a TV
utubot user devices [NAME]          list paired devices (id, user, name)
utubot user revoke DEVICE_ID        revoke one device token
utubot app publish APK... --version-name V --version-code N [--changelog TEXT] [--abi ABI]
utubot app sync-github [--repo OWNER/NAME] [--prerelease] [--dry-run]
                                    publish the newest GitHub Release of the app (see Updates)
utubot prompts validate FILE        check a prompt set file
```

## Configuration reference

`config.example.toml` lists every option with its default. All sections:

**`[server]`**: `host`, `port` (bind; keep loopback behind a proxy), `data_dir` (SQLite database `utubot.sqlite`, `users.toml`,
media scratch), `app_dir` (APKs and `update.json`, served without auth under `/app/`), `public_base_url` (the URL TVs use;
published in `/setup.json` and in APK download links), `users_file` (default `data_dir/users.toml`).

**`[security]`**: `trusted_proxies` (peers whose `X-Forwarded-For` is believed; default `["127.0.0.1", "::1"]`), `client_ip_header` and
`client_ip_header_secret_env` (name the real client through a second proxy hop, see [Reverse proxy and TLS](#reverse-proxy-and-tls)),
`rate_per_token_per_min`, `rate_per_ip_per_min`, `rate_window_s`, pairing limits (`pair_code_digits`, `pair_code_ttl_s`,
`pair_attempts_per_ip_per_min`, `pair_lockout_failures`, `pair_lockout_s`, `pair_global_failures`, `pair_global_window_s`),
`max_body_bytes`, `max_device_name_chars`, `max_devices_per_user`; web sign-in: `session_cookie`, `session_ttl_s` (30 days),
`session_refresh_s`, `max_sessions_per_user`, `password_min_chars` (10), `password_max_chars`, `scrypt_n` (2^17)/`scrypt_r`/`scrypt_p`/`scrypt_max_concurrent`,
`login_attempts_per_ip_per_min`, `login_lockout_failures` (5), `login_lockout_s` (15 min), `login_user_lockout_failures` (10),
`login_global_failures`, `login_global_window_s` (see [Web UI](#web-ui)).

**`[models]`**: the live model list behind the web UI: `cache_ttl_s` (300), `error_ttl_s` (30), `refresh_min_interval_s` (10),
`timeout_s`, `new_for_s` (3 days), `max_models_per_provider`.

**`[llm]`**: `default_provider`, `timeout_s`, `retries_on_bad_json`, `json_retry_max_tokens`, `reasoning_headroom_tokens`, `retry_max_attempts`, `retry_base_s`, `retry_max_s`,
`deadline_interactive_s`, `deadline_background_s`; `[llm.providers.NAME]` with `base_url`, `api_key_env`, `max_concurrent`,
`reserved_interactive`, `json_mode`; per-task tables `[llm.triage]`, `[llm.summary]`, `[llm.glance]` (optional), `[llm.answer]`, `[llm.analysis]`, `[llm.captions]`, each with
`model`, optional `provider`, `fallback`, `reasoning_effort`, `max_tokens`, `temperature`. `[llm.glance]` runs the short side-panel
summary; when absent the glance uses `[llm.summary]` with `reasoning_effort = "none"`, and when present `reasoning_effort` defaults
to `"none"` and `max_tokens` to 160. See [llm-providers.md](llm-providers.md).

**`[assess]`**: `batch_size` (titles per triage call), `coalesce_ms`, `max_videos_per_request`, `wait_ms_cap`, `default_wait_ms`,
`background_concurrency`, `tier2_daily_cap_per_user` (transcript-based deep analyses per user per UTC day, default `30`),
`tier2_clickbait_threshold`, `triage_cache_ttl_s`, `title_max_chars`, `description_max_chars`.

**`[youtube]`**: pacing and circuit breaker for everything that reaches YouTube, see [YouTube limits](#youtube-limits-and-the-transcription-fallback).
`max_concurrent` (default `1`), `min_interval_s` (`3.0`), `jitter_s` (`1.5`), `cooldown_base_s` (`300`), `cooldown_max_s` (`3600`),
`captions_cooldown_max_s` (`1800`, the lower ceiling of the caption class), `captions_probe_retry_s` (`10`), `network_retry_s` (`60`),
`max_background_queue` (`5`), and the yt-dlp JavaScript runtime (`js_runtime`, `js_runtime_path`, `remote_components`).

**`[archive]`**: the media archive, see [Media archive](#media-archive): `path` (empty: `<data dir>/archive`), `quota_bytes`
(`0`: no limit) and `warn_frac` (`0.9`).

**`[transcripts]`**: `cache_ttl_s`, `no_captions_ttl_s` (default 3 days), `video_failure_ttl_s` (1 h), `empty_track_retry_s` (1 h), `fetch_timeout_s`, `default_language`, `cookies_file`
(only if YouTube blocks the host), `skip_if_longer_than_s`. (`max_concurrency` is gone: `[youtube] max_concurrent` replaces it;
an old entry is ignored.)

**`[summary]`**: `token_budget`, `chunk_tokens`, `chars_per_token`, `strategy` (`map_reduce` or `truncate`),
`default_wait_ms`, `wait_ms_cap`, `adhoc_ttl_s`, `max_summary_chars`, `max_import_bytes`, `import_timeout_s`,
`import_allow_hosts`, `import_max_redirects`, `panel_prompt` (prompt for the side panel's automatic summaries, default
`"builtin/glance"`; each user can choose their own), `auto_long` (default `false`: also generate the user's default long summary in
the background after a panel summary; a user's `auto_long` policy field overrides it), `auto_long_max_concurrent` (default `2`,
background long summaries in flight including the transcript fetch; further ones are skipped until one ends, `0` disables them). See [prompt-sets.md](prompt-sets.md).

**`[captions]`**: the ASR engine chain (`[[captions.asr_engines]]`, or the single `asr_*` keys), chunking, diarization and the estimate
inputs, see [captions.md](captions.md). Also `asr_unhealthy_s` (`300`), `asr_failure_window_s` (`600`), `asr_chunk_overlap_s` (`2`), `download_overhead_s` and
`download_speed_factor` (the estimate shown before a transcription), `transcribe_max_active_per_user` (default `5`), `job_max_attempts`
(`3`), `media_orphan_age_s` (`3600`), `max_download_bytes` (400 MiB), `audio_format` (yt-dlp's fallback selector).

**`[setup]`, `[setup.defaults]`**: the public `/setup.json`: `name`, `pairing`, optional `prompt_set_urls`, and the switch values
the app applies on import (`assess`, `mark_only`, `answer_in_menu`, `summary_panel`, `auto_captions`).

**`[app]`**: `downloader_codes = { arm64-v8a = "12345", armeabi-v7a = "67890" }` shown on the landing page when non-empty.
Updates from GitHub ([Updates](#updates)): `github_repo`, `signing_cert_sha256`, `apksigner_path`, `github_token_env`,
`keep_versions`, `apksigner_timeout_s`, `sync_timeout_s`, `sync_releases_per_page`, `sync_max_apk_bytes`; for the web UI's update
page `release_check_ttl_s` (600), `release_check_error_ttl_s` (60), `release_check_min_interval_s` (30).

**`[default_policy]`** and **`[[users]]`**: see [policy.md](policy.md). They also carry the defaults of the [per-user
settings](#per-user-settings): `models`, `auto_transcribe`, `auto_transcribe_max_minutes`, `summary_delay_ms`, `update_checks`,
`mark_only`, `summary_panel`, `auto_captions`, `auto_long`.

Environment: `UTUBOT_CONFIG`, the provider key variables you named, `UTUBOT_ASR_API_KEY` and every other variable named by an
ASR engine's `api_key_env`, `UTUBOT_HF_TOKEN`. Keys never go
in the config file.

## YouTube limits and the transcription fallback

One home address asking YouTube for dozens of caption files in a few minutes gets `HTTP 429 Too Many Requests`. The backend therefore
sends **every** request that reaches YouTube (yt-dlp metadata and caption lists, the caption text, audio downloads for transcription)
through one process-wide gate. Requests belong to one of three **endpoint classes**, each with its own circuit breaker:
`captions` (the timedtext caption API), `metadata` (the watch and player pages that yt-dlp reads for the format and caption lists) and
`media` (audio downloads). YouTube limits them independently: a 429 from the caption API used to pause audio downloads that
still worked, now it only pauses caption fetches.

- **Pacing.** The pacer is shared by all classes, so the overall request rate is what you configured. At most `[youtube] max_concurrent` requests (default 1) are in flight, and they start at least `min_interval_s`
  (3 s) plus a random `0..jitter_s` (1.5 s) apart. Interactive work (a summary someone is waiting for) goes before background work
  (tier-2 analysis, caption and transcript jobs); a user who starts waiting on a queued background fetch promotes it.
- **Circuit breakers (one per class).** Only signals about the server as a whole open one: a 429, the "Sign in to confirm you're not a
  bot" check, or a 403 on the watch, player or metadata request. It opens the class that received it; the bot check comes from yt-dlp's
  player request, so it opens both yt-dlp classes (`metadata` and `media`) but not `captions`. A transcript fetch needs `metadata` and
  `captions`, a transcript job's download needs `media`. The cooldown is the `Retry-After` header when YouTube sends one, else `cooldown_base_s`
  (5 min) doubled for each consecutive block up to `cooldown_max_s` (60 min), and for the caption class up to
  `captions_cooldown_max_s` (30 min); no cooldown is longer than its ceiling, `Retry-After` included. While it is open
  interactive requests are answered at once without touching YouTube, and background work (caption and transcript jobs, tier-2)
  **waits** (it is neither failed nor dropped) and resumes when the cooldown ends. The first request afterwards is a probe: any
  answer from YouTube (a transcript, "no captions", even "this video is private") closes the breaker and resets the escalation,
  another block doubles that class's cooldown. For the **caption class the probe is never an interactive request**: once its cooldown is
  over, exactly one *background* request goes out (the first background fetch in the queue, or one the backend starts itself for the
  video somebody just asked about) while the other background fetches wait behind it, and interactive requests keep being answered
  without touching YouTube (`captions_probe_retry_s` is the retry hint if nothing else can answer) until that probe has been answered. A
  probe that finds a video with no caption track at all (a complete yt-dlp answer) counts as an answer for the caption class too and
  closes it, so back-to-back probes do not follow. The state of each class survives restarts (a state saved by the older single breaker is
  adopted by all three once). The log records each transition (`youtube gate open: class=... reason=... cooldown_s=...`,
  `half-open`, `closed`); URLs never appear in it. `GET /v1/status` shows each class (`youtube.classes`: `state`,
  `cooldown_remaining_s`, `strikes`) next to the combined `youtube.state`, and the engine chain (`asr.engines`: health, no URLs).
- **Audio instead of waiting.** While the caption class cools down or waits for its probe, or a caption fetch has just been refused
  (429, 403), the audio is usually still reachable (`media` is a separate class) and a speech engine can transcribe a 30 minute video in
  well under a minute. The request is then treated like "no captions" instead of "delayed", under the user's policy: with
  `auto_transcribe` allowing it and the video within `auto_transcribe_max_minutes` the transcription starts at once (`pending` +
  `transcribing`, `progress`, `estimate_s`); otherwise it answers `needs_transcript` with `can_transcribe`, `estimate_s` and a message
  such as "Captions are temporarily unavailable from YouTube; transcribe the audio instead (~N s)?". This is never remembered (no
  "no captions" entry). "Delayed" stays for the cases where the audio cannot help: no engine serves the video, the video is live or too
  long, the `media` class cools too (a bot check blocks metadata and media together) or the problem is a network error rather than a
  limit. A transcript stored from the audio is kept: captions fetched later, even by a probe that was already in flight, never replace it,
  and a video with an `asr` transcript is not asked for captions again. In the other direction, stored captions that are still fresh
  (`transcripts.cache_ttl_s`) are kept and an expired captions row is replaced by the audio transcript; a transcription job whose
  result could not be stored fails (recorded, `failed`) instead of ending silently.
- **Problems of one video stay with that video.** A 403 or 410 on a caption or media URL and members-only, age-gated, private or
  unavailable videos are failures of that video (`transcript_status: "failed"` with a `reason`), remembered for
  `transcripts.video_failure_ttl_s` (1 h) so they are not re-fetched; they never touch the breaker.
- **Long downloads do not hold the gate.** Audio downloads take the gate only to start (a paced slot, released when the first bytes
  arrive), so a 20 minute download never stalls an interactive metadata or caption fetch. A video that yt-dlp reports as live or
  longer than `captions.max_duration_s` (3 h) is refused from the real info before anything is downloaded, and audio larger than
  `captions.max_download_bytes` is skipped.
- **Fewer fetches.** A transcript is fetched at most once per `transcripts.cache_ttl_s` (30 days), concurrent requests share one fetch,
  and "this video has no captions" is remembered for `transcripts.no_captions_ttl_s` (3 days, then checked again). The second tier
  (inflation and answer analysis) runs only for videos with a title question or a clickbait score above
  `assess.tier2_clickbait_threshold`, at most `assess.tier2_daily_cap_per_user` (30) per user per day, only while the breaker is
  closed or probing, not for videos known to have no captions, and not while `max_background_queue` (5) background fetches are
  already waiting.

**A summary, insight or answer is never made from the title alone.** When no transcript can be had the API says why instead
(`transcript_status`, see the [contract](../ai/CONTRACT.md)):

| Situation | Response |
|---|---|
| 429, cooldown, bot check, network error, empty or incomplete YouTube answer, a caption file that parses to nothing, when the audio cannot stand in (below) | `status: "pending"`, `transcript_status: "delayed"`, a user-facing `error` ("YouTube is limiting transcript downloads; retrying in ~N min") and `retry_after_s`. Never cached as "no captions"; ask again after `retry_after_s` (a caption file that parses to nothing is held for `transcripts.empty_track_retry_s`, 1 h). |
| The caption API is limited (cooldown, probe out, 429/403 just now) and a speech engine can take the video while `media` is healthy | like "no captions" below, with the message "Captions are temporarily unavailable from YouTube; transcribe the audio instead (~N s)?": started by the policy (`pending` + `transcribing`) or offered (`needs_transcript`). Never `delayed`, never remembered. |
| Private, members-only, age-gated or unavailable video, 403/410 on its caption or media URL, too long or live | `status: "failed"`, `transcript_status: "failed"`, `error`, `reason`, `can_transcribe`. |
| YouTube lists no captions (from a complete yt-dlp answer) | `status: "needs_transcript"`, `transcript_status: "none"`, `can_transcribe`, `message` and `estimate_s`. The TV offers "Transcribe in background?". |
| No captions and the user's policy allows it (`auto_transcribe` `on_open`/`on_dwell`, video up to `auto_transcribe_max_minutes`, default 30) | the transcription is queued by the request itself and it answers `status: "pending"`, `transcript_status: "transcribing"`, `progress`, `estimate_s`. No question is asked. The side panel (`prompt=panel`) only does this for `on_dwell`. |
| The user said yes (or the policy did) | `POST /v1/videos/ID/transcribe` queues a job: audio through the gate (the original-language track at the lowest bitrate), ffmpeg, your ASR engines in chunks ([captions.md](captions.md)), stored as the transcript with source `asr`. Meanwhile summaries answer `pending` with `transcript_status: "transcribing"` and `progress`; afterwards everything works as with YouTube captions. |

`GET /v1/videos/ID/transcript` shows the state (with `job_id` only for your own job) and `GET /v1/jobs` lists your caption and transcript
jobs (`waiting`, `processing`, `ready`, `failed`). Jobs wait while the `media` breaker is open and run when it closes (a caption or metadata limit does not hold them back); a job that YouTube
keeps refusing is retried `captions.job_max_attempts` (3) times and then fails. Before spending effort on the audio a transcript job
asks YouTube once more for captions and uses them if they exist (ASR never replaces captions stored first, and captions fetched later never replace ASR). Videos that are live or longer than
`captions.max_duration_s` (3 h) cannot be transcribed (`can_transcribe: false`).

A systemd service often lacks `deno` on its `PATH`: set `[youtube] js_runtime_path` (and `remote_components = ["ejs:github"]`) so yt-dlp
can solve YouTube's JavaScript challenge, see [captions.md](captions.md#youtubes-javascript-challenge).

If YouTube keeps blocking the host even at the default pace, raise `min_interval_s`, lower `tier2_daily_cap_per_user`, or set
`transcripts.cookies_file` (a credential: keep it private). Scratch directories under `data_dir/media` that a crash left behind are
removed at start when older than `captions.media_orphan_age_s` (1 h). Summaries created from the title alone by earlier versions are deleted
when the new version first starts.

Suggested production values for a home connection that was rate limited:

```toml
[youtube]
max_concurrent = 1
min_interval_s = 4.0
jitter_s = 2.0
[assess]
tier2_daily_cap_per_user = 30
```

## Media archive

Nothing downloaded from YouTube is thrown away, and nothing is downloaded twice. Every file a pipeline fetches (today: the
original-language audio of a transcription; later: low-res video for frame features) is kept in the **media archive**:
content-addressed by its sha256 under `[archive] path` (default `<data dir>/archive`, put it on a large disk), described by a
`media_archive` row per video — format id, codec, bitrate, language, original-track flag, size, sha256, fetch time. Identical
bytes are stored once; the scratch copy under `data_dir/media` is removed when the job is done, as before.

Pipelines read from the archive first: a job whose video is already archived never contacts YouTube for its audio (no gate wait,
the report shows "From the media archive"), and only a miss leads to a download, which the job then stores. Removing entries is
an explicit admin act — *Admin → Media archive* in the web UI (usage against the quota, one row per video with format, size,
sha256 and age, a *Remove* button) or `DELETE /v1/admin/archive/{video_id}` (`GET /v1/admin/archive` lists it). Nothing in the
archive is ever deleted automatically, and the scratch sweep of `data_dir/media` never touches it.

The quota (`[archive] quota_bytes`, `0`: no limit) never frees space by itself. At `warn_frac` (`0.9`) of the quota a warning is
logged; at the quota new downloads are refused — the job fails with "The media archive is full; an admin must free space in it
(nothing is deleted automatically)" — while archived media keeps serving every pipeline. A download whose storage fails (the
archive disk is out of space or gone) fails the job and keeps the file in its scratch directory instead of deleting it.

## Users, pairing, devices

A *user* is a person (own settings, own prompt sets). Create users with `utubot user add NAME` (token printed once, hash stored in
`users.toml`), with *Admin, Add a user* in the web UI (a user without a token that signs in with a password; `users.toml` gets a
block with an empty `token_sha256`), or declare them in `[[users]]` with `admin = true` for admins. A person signs in to the web UI
with a password (`utubot user passwd NAME`, or the web UI) or with their token. Users declared in `config.toml` keep their admin flag
there; the web UI changes it only for users that live in `users.toml`.

TVs do not use that token. `utubot user pair NAME` (or *New pairing code* in the admin UI) prints a single-use 6-digit code,
valid 15 minutes. The TV posts it to `POST /v1/pair` and receives a separate per-device token, so each TV is revocable:

```sh
uv run utubot user devices          # ids
uv run utubot user revoke DEVICE_ID
```

Pairing is rate limited and locks an IP out after repeated wrong codes. At most `max_devices_per_user` devices per user. Each user
makes their own codes and revokes their own TVs under *TVs* in the web UI.

## Web UI

`GET /` serves a static, phone-first control page (plain HTML, CSS and ES modules under `ai-backend/src/utubot/web/`, no build step,
no external requests). Everything it shows comes from authenticated JSON endpoints; the shell itself carries no data.

| Section | What it does |
|---|---|
| Home | version, health, the YouTube gate (healthy, cooling down with the time left, probing), today's model calls and tokens, transcripts, deep-analysis quota, your jobs |
| Models | the model for each task (glance, summary, answer, triage, analysis), picked from the live model list; "Other model name" for anything unlisted |
| Prompts | defaults (side panel, long summary, language, background long summary), prompt sets (import from URL, refresh, edit JSON with validation messages), try a prompt on a video link or id |
| Filters | hide and mark topics as chips, thresholds as sliders, mark-only |
| Captions | the automatic-transcription policy, "transcribe this video" from a link, the job list with cancel and retry; every job links to its [detail report](#job-details) |
| TVs | *Link a TV* (a big one-time code and the steps), linked devices with revoke, the TV settings kept on the server |
| Updates | the app version this server publishes, the newest GitHub release, the last `sync-github` run |
| Admin | users (add, set a password, admin flag, pairing code), each user's settings and TVs, the [media archive](#media-archive) (usage, per-video entries, manual cleanup) |

Screenshots (390 x 844 at 2x): [home](screenshots/webui/02-home.png), [models](screenshots/webui/04-models.png),
[prompts](screenshots/webui/06-prompts.png), [try a prompt](screenshots/webui/09-prompts-try.png),
[filters](screenshots/webui/11-filters-thresholds.png), [captions](screenshots/webui/13-captions-jobs.png),
[link a TV](screenshots/webui/14-tv-link.png), [updates](screenshots/webui/16-updates.png), [admin](screenshots/webui/17-admin.png),
[light theme](screenshots/webui/20-home-light.png), [job report](screenshots/webui/22-job-detail.png),
[its stage timeline](screenshots/webui/23-job-timeline.png), [a failed job](screenshots/webui/24-job-failed.png). `ai-backend/tests/webui_demo.py` serves the same canned data locally (mock LLM,
no network) and `docs/screenshots/webui/capture.cjs` takes them with Playwright.

### Job details

Every job in the *Captions* list (and `GET /v1/jobs`, via `detail_url`) opens a report: what was requested, what was done, what
happened and whether anything fetched the result. The page is `/#/jobs/ID`, the data `GET /v1/jobs/ID` (the owner of the job and admins
only; anybody else gets `404`). It shows

- **What was requested**: the video (id, title, channel, length, spoken language), the kind of job, who asked and from which client (a
  paired TV by the name it was linked under, "Web UI", or "API token"), the endpoint, why it was queued (asked for explicitly, or started by
  the automatic-transcription policy: `on_open` / `on_dwell`, side panel or not, the minutes limit), its priority.
- **What it produced**: the transcript (source, language, engine, model, size, the first 10 lines, a download of the whole text) or the
  captions track(s) (label, language, speakers, cue count, size, the first 10 cues, `.vtt` and text downloads).
- **Delivery**: which client fetched the result, how (the `.vtt`, the captions list, the transcript status, a summary, the panel summary,
  an answer, the downloaded text), how often and when last. A job that is `ready` but was never fetched says so, in the job list too
  ("Not fetched by any client yet"), which is how to tell that a TV never asked for its captions.
- **What happened**: a timeline of the stages with their duration and a status icon (done, running, skipped, warning, failed), refreshed
  every few seconds while the job runs and every 15 s afterwards.
- **Errors**, with the stage that failed, the cause and a scrubbed technical line; *Retry* (failed or cancelled) and *Cancel* (waiting),
  for the owner only.

The log is the `job_events` table: one row per event (`job_id`, `ts`, `stage`, `status`, `detail` JSON), written as the stage happens, so a
running job shows its progress and a crashed one shows where it stopped. Stages: `queued`, `promoted`, `started` (attempt and time
waited), `gate_wait` (the YouTube class and how long the gate held the job), `caption_recheck` (found, none, delayed or skipped and why),
`audio_download` (format id, original/dubbed/unmarked track, language, bytes, length, seconds, and `source`: `downloaded` or `from_archive`),
`media_archive` (bytes and the sha256 prefix of what was kept; skipped when the audio came from the archive), `ffmpeg`, `chunking` (chunks and their sizes), `asr` and `asr_chunk` (engine, model, seconds, characters, detected language per chunk),
`asr_fallback` (an engine gave up on a chunk, and why: `http_503`, `transport_timeout`, `unhealthy`, `language_mismatch` ...), `stitching`
(seams, segments cut at overlaps, repeated words dropped), `diarization` (ran, or skipped and why: off, no Hugging Face token, package
missing), `cues` (count, longest line), `text`, `translate`, `stored` (what was saved and how big), `retry`, `finished`, `failed` (cause
class, human message, stage) and `delivered`. A `delivered` row is added by the routes clients use (`GET /v1/videos/ID/captions`, the
`.vtt`, `GET /v1/videos/ID/transcript`, summary, insight and ask built from a transcript the audio made); the same client fetching the
same way again within `[captions] delivery_coalesce_s` (300) raises the `count` of one row instead of adding rows. At most
`[captions] job_events_max` (400) stage events are kept per job; queued, finished, failed and retry rows are always kept, and at most
`[captions] delivery_events_max` (50) delivered rows (past that, new deliveries are counted into the newest row: `count` and `merged` go up).

Nothing secret or signed is stored: details pass through `captions/events.py clean`, which drops keys that name a token, secret, cookie,
header or URL and replaces URLs, `key=value` secrets, bearer tokens and long random strings in any text with `[url]` / `[redacted]`.
Failure text is the scrubbed exception, never a raw yt-dlp message. Jobs from before the log existed get one synthetic event
("finished (no detailed log, created before event logging)") at the first start, so their page works.

### Sign-in and sessions

- **Password.** `utubot user passwd NAME` (or *Admin* / *Account* in the page) stores a scrypt hash (`[security] scrypt_n` 2^17, r 8, p 1: about 128 MiB and a few tenths of a second per
  hash, at most `scrypt_max_concurrent` at once). The parameters are part of each hash, so old hashes keep verifying and are hashed again with the
  current cost at the user's next successful sign-in. At least `password_min_chars` (10) characters.
- **Token.** The old way still works: paste the user token on the sign-in form. It is exchanged for a session; the page never keeps
  the token. Device tokens (TVs) and `Authorization: Bearer` keep working for every endpoint, unchanged.
- **Session cookie.** `utubot_session`, `HttpOnly`, `SameSite=Lax`, `Secure` whenever the browser reached the service over HTTPS: the
  request itself is HTTPS, or the peer is in `[security] trusted_proxies` and sent `X-Forwarded-Proto: https`. The server stores only the
  SHA-256 of the session id. A session lasts 30 days from the last use (the cookie is re-issued at most hourly) and at most
  `max_sessions_per_user` (20) exist per user. Changing a password signs the user out everywhere else.
- **CSRF.** A write (`POST`, `PUT`, `DELETE`) authenticated by the cookie must carry the `X-CSRF-Token` header (a per-session value the
  page gets from sign-in or `GET /v1/auth/session`) and, when the browser sends `Origin`, the origin must be this server (the `Host`
  header or `server.public_base_url`). Requests with a bearer token need neither, since a browser never adds that header by itself.
- **Lockout.** Failed sign-ins are counted per IP address (`login_lockout_failures`, 5 in `login_lockout_s`, 15 minutes), per account
  (`login_user_lockout_failures`, 10) and globally (`login_global_failures`); a locked address, account or server answers `429` with
  `Retry-After`, even for the right password. An unknown user and a wrong password look the same (same message, same timing).
- **Behind a proxy** pass `Host` and `X-Forwarded-Proto` (the nginx example below does) and list the proxy in `trusted_proxies`, or the
  cookie is not marked `Secure` and every client shares one IP for rate limits and lockout.

### What the page can and cannot do

Every response carries a strict `Content-Security-Policy` (`default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'`,
no inline script or style), `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`; `/v1/*`
answers are `Cache-Control: no-store`. The page builds its DOM with `textContent` only, so titles, prompt text and server messages
are never interpreted as markup. Provider API keys never leave the server: `GET /v1/models` reports `key: configured | missing |
not needed` and nothing else about them (admins also see the provider's base URL, without credentials).

## Per-user settings

`GET /v1/me/settings` returns one versioned document with the user's effective settings, only the values they changed (`overrides`)
and what applies when nothing is set (`defaults`). `PUT /v1/me/settings` changes some of them; admins use
`GET/PUT /v1/users/NAME/settings`. A write from a browser session must say which `version` it was made from (`428` otherwise) so two
open pages cannot overwrite each other; scripts using a bearer token may leave it out and merge their partial change. The wire format is in the [contract](../ai/CONTRACT.md#per-user-settings). The sections:

| Section | Settings |
|---|---|
| `models` | `glance`, `summary`, `answer`, `triage`, `analysis`: a model name or `provider:model` |
| `prompts` | `default` (Summary view), `panel_default` (side panel) |
| `filtering` | `hide_topics`, `mark_topics`, the five thresholds, `inflated_min_duration_s`, `answer_in_label`, `mark_only` |
| `summaries` | `language`, `auto_long` |
| `transcripts` | `auto_transcribe` (`off`, `on_dwell`, `on_open`, default `on_open`), `auto_transcribe_max_minutes` (default 30) |
| `tv` | `summary_delay_ms`, `summary_panel`, `auto_captions`, `update_checks` |

**Precedence**, for each setting, highest first:

1. the user's own choice (web UI or `PUT /v1/me/settings`, also `PUT /v1/me/policy` and the prompt-default calls), kept as a sparse
   override of only what they changed; `null` removes it again;
2. the user's `[users.policy]` entry (`config.toml` or `users.toml`);
3. `[default_policy]`;
4. the built-in default.

A setting still unset at that point follows the server setting it mirrors, so there is one place to change it for everyone:
`auto_long` follows `[summary] auto_long`; `mark_only`, `summary_panel` and `auto_captions` follow `[setup.defaults]` (the values a
TV applies when it imports `/setup.json`); a task without a model follows its `[llm.<task>]` table (`glance` follows `[llm.glance]`,
else `[llm.summary]`); the prompt defaults follow `builtin/tldr` and `[summary] panel_prompt`. When a model is actually used a prompt's
own `model` (in the prompt set) wins over the user's model for that task, which wins over `[llm.<task>]`.

**One source of truth.** The policy fields (everything except the prompt defaults) live in the user's single override row of
`policy_overrides`, which `PUT /v1/me/policy`, the admin policy route and the settings route all write; the prompt defaults live
in `user_default` and `user_panel_default`, which `PUT /v1/prompts/default` and `panel-default` write. The settings document is a
view over them. Any change through any of these routes bumps `version`; a `PUT` that sends the `version` it read gets `409` when
someone changed the settings meanwhile.

**Models** are checked against the live list (`GET /v1/models`: every provider's `/models`, cached for 5 minutes, refreshable by
hand, models that appeared since the last list marked `new` for 3 days). A model that is not listed is refused unless an admin sends `"allow_unlisted_models": true` (the page offers "Use it anyway" to admins
only; anyone else gets `403`); the same goes for a provider whose list cannot be fetched. `PUT /v1/me/policy` refuses a `models` field
from a non-admin for the same reason.
Summaries made with a user's model are cached apart from other models (the model is part of the prompt's content hash); the shared
triage, insight and analysis caches are keyed without the model, so the first user to compute a video decides which model made it.
Batches of the title triage are shared only between users with the same topics and the same triage model.

**Transcript policy and TV settings** are stored and served now. The server acts on `auto_transcribe` and
`auto_transcribe_max_minutes` itself (a request that finds no captions starts the transcription, see
[captions.md](captions.md#transcripts-for-videos-without-captions)); the TV reads the other settings (and `settings_version` from
`GET /v1/me`) in a later app release.

## Reverse proxy and TLS

Keep the service on `127.0.0.1:8790` and terminate TLS in front of it. Set `server.public_base_url` to the public URL.

`security.trusted_proxies` must list the address your proxy connects from when it is not loopback; the client IP is then the
right-most `X-Forwarded-For` entry that is not itself trusted. Wrong values either let clients spoof their IP (too wide) or make
all clients look like the proxy and share rate limits (too narrow).

### Two proxies in a row

When a second hop sits between your edge proxy and the service (a tunnel, Tailscale Serve, another reverse proxy), it may replace
`X-Forwarded-For` with its own address. Every client then looks like that hop and shares one bucket of the per-IP rate limit and of the
sign-in lockout. Have the **edge** proxy name the client in a header of its own and prove it with a shared secret, which the inner hop
passes through untouched:

```nginx
proxy_set_header X-Utubot-Client-IP    $remote_addr;
proxy_set_header X-Utubot-Proxy-Secret "<a long random string>";
```

```toml
[security]
trusted_proxies = ["127.0.0.1", "::1"]          # the peer the service sees: the inner hop
client_ip_header = "X-Utubot-Client-IP"
client_ip_header_secret_env = "UTUBOT_PROXY_SECRET"   # the same random string goes in this environment variable
```

The header is believed only when the peer is a trusted proxy **and** `X-Utubot-Proxy-Secret` equals the configured secret
(constant-time comparison) **and** the header holds exactly one IP address; otherwise the `X-Forwarded-For` rules above apply, so a
client that sends the header itself changes nothing. With no secret in the environment the feature is off. Keep the secret out of
the config file (it goes into the service's environment file like the provider keys) and make the edge proxy overwrite both headers,
never forward the client's own.

### Caddy (same host)

```
utubot.example.com {
    reverse_proxy 127.0.0.1:8790
}
```

Caddy gets the certificate itself. The proxy connects from loopback, so the default `trusted_proxies` works.

### nginx (same host)

```nginx
server {
    listen 443 ssl http2;
    server_name utubot.example.com;
    ssl_certificate     /etc/letsencrypt/live/utubot.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/utubot.example.com/privkey.pem;
    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:8790;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;   # lets the web UI's session cookie be marked Secure
        proxy_read_timeout 90s;     # summaries can long-poll up to the wait_ms caps
    }
}
```

### Proxy on another machine

If nginx or Caddy runs on a different host and forwards to the service over a private network, bind the service to that
interface (`--host`) or keep a tunnel, and add the proxy's address as seen by the service:

```toml
[security]
trusted_proxies = ["127.0.0.1", "::1", "10.0.0.2"]   # example proxy address
```

### Tailnet only (no public exposure)

With Tailscale, `tailscale serve --bg --https=443 http://127.0.0.1:8790` gives `https://HOST.TAILNET.ts.net` inside your
tailnet; set `public_base_url` to it. Tailscale Serve connects from loopback. TVs must be on the tailnet; the app accepts `http`
only for private addresses and `https` otherwise.

### Same LAN, no TLS

`http://10.0.0.5:8790` works for a server on your network (the app allows plain http for private addresses). Bind with
`utubot serve --host 0.0.0.0` only on a network you trust.

## systemd

`ai-backend/deploy/utubot.service` is a hardened unit. Adjust the checkout path, then:

```sh
cd /opt/utubot/ai-backend
uv sync --frozen --extra asr
install -d -m 0750 /etc/utubot /var/lib/utubot /var/lib/utubot/app
cp config.example.toml /etc/utubot/config.toml        # edit; set data_dir = "/var/lib/utubot"
install -m 0600 /dev/null /etc/utubot/env             # NAME=value lines: provider keys, UTUBOT_HF_TOKEN
cp deploy/utubot.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now utubot
UTUBOT_CONFIG=/etc/utubot/config.toml .venv/bin/utubot user add owner --admin
```

The unit runs the venv binary (nothing downloads at start), keeps model caches under `/var/lib/utubot/cache`, and needs
`ffmpeg` in `/usr/bin`. Logs: `journalctl -u utubot`. After updating the checkout run `uv sync --frozen --extra asr` and restart.

## Updates

TVs poll `/app/update.json` on your server, so the update channel is whatever is published in `app_dir`. Two ways to fill it.

### From GitHub Releases (automatic)

The project's release workflow publishes a GitHub Release for every app change merged to `main` (tag `utubot-v<major>.<minor>.<patch>`):
signed APKs per ABI, `SHA256SUMS` and `release.json` (version, versionCode, ABIs, SHA-256 per file). One command pulls the newest
release into your channel:

```sh
utubot app sync-github --repo OWNER/NAME          # or set [app] github_repo and omit --repo
utubot app sync-github --dry-run                  # say what would happen; no APK is downloaded, nothing is written
```

```toml
[app]
github_repo = "owner/u-tubot"
signing_cert_sha256 = "<64 hex digits>"           # SHA-256 of your release signing certificate
# apksigner_path = "/path/to/android-sdk/build-tools/<version>/apksigner"   # optional; unset uses the built-in verifier
# keep_versions = 3                               # keep the APK files of the newest 3 versions; the default 0 keeps all
```

What a run does:

1. Lists the repository's releases through the GitHub API (no login needed for a public repository; set `UTUBOT_GITHUB_TOKEN`,
   or the variable named by `github_token_env`, only to raise the rate limit) and takes the highest `utubot-vX.Y.Z` that is not a
   draft (prereleases only with `--prerelease`).
2. Reads its `release.json` and compares `version_code` with the channel's (`latest.json`). Equal or older: nothing to do, so the
   command is safe to run every few minutes.
3. Downloads each APK, checks its SHA-256 against `release.json`, then verifies its signature and requires every signer
   certificate to equal `signing_cert_sha256`. Nothing is published unless all APKs pass. The signature is checked by `apksigner`
   when `apksigner_path` is set (Android build-tools, needs a JRE), otherwise by a built-in pure-Python reader of the APK Signing
   Block (schemes v2, v3 and v3.1): it verifies each signature, recomputes the APK's content digest and compares it with the
   signed one, so an APK changed after signing is refused. It supports RSA keys (PKCS#1 v1.5 and PSS); for an ECDSA key set
   `apksigner_path`.
4. Publishes them like `utubot app publish` (APKs first, `update.json` last) and, with `keep_versions`, deletes the APK files of
   older versions (only files named `u-tubot_<version>_<abi>.apk`).

Get the digest with `apksigner verify --print-certs u-tubot_<version>_<abi>.apk` (`Signer #1 certificate SHA-256 digest`); each
release's notes carry it too. Without `signing_cert_sha256`, or when `apksigner_path` is set but is not an executable file (the
check is never silently weakened), a real run refuses to publish and says so; `--dry-run` only warns and names the check it would use.

A release made before `release.json` existed is read from its file names and `SHA256SUMS`; its versionCode is derived from the
version (`major * 1000000 + minor * 1000 + patch`) and the channel compares version names instead.

Exit codes: `0` published or nothing to do, `1` a check failed or the configuration is wrong, `75` GitHub could not be reached or is
rate limiting (retry later). Run it from cron or a systemd timer, for example every five minutes:

```ini
# /etc/systemd/system/utubot-sync.service
[Service]
Type=oneshot
Environment=UTUBOT_CONFIG=/etc/utubot/config.toml
ExecStart=/opt/utubot/ai-backend/.venv/bin/utubot app sync-github
SuccessExitStatus=75
```

### By hand

Build or download the release APKs (`u-tubot_<version>_<abi>.apk`), then:

```sh
uv run utubot app publish u-tubot_0.2.0_arm64-v8a.apk u-tubot_0.2.0_armeabi-v7a.apk u-tubot_0.2.0_universal.apk \
  --version-name 0.2.0 --version-code 2 --changelog "First signed release"
```

The ABI comes from the file name. The command copies the files into `app_dir`, rewrites `update.json` (what TVs poll, with
`downloadUrlList_<abi>` entries) and `latest.json`. Public, unauthenticated URLs:

- `/app/update.json`, `/app/<file>.apk`
- `/app/latest/<abi>.apk`: stable redirect to the newest file, for Downloader codes
- `/app/info.json` and the Download section of `/`: version, links, checksums and your `[app] downloader_codes`

Publish APKs signed with the same key as the installed app. TVs only learn about a version greater than their own `versionName`.

## Backups

Back up `data_dir`: `utubot.sqlite` (caches, jobs, prompt sets, device token hashes, password hashes, web sessions, per-user settings) and `users.toml`; plus
`config.toml`, the env file and `app_dir`. Caches can be rebuilt; losing `users.toml` or the database means re-pairing.
