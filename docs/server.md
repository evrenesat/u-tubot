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
utubot user prime NAME on|off       put a user in the prime class or back to normal
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

**`[auth]`**: `tailscale_identity` (off by default; sign in from the `Tailscale-User-Login` header of a loopback peer, see
[Tailnet only](#tailnet-only-no-public-exposure)) and `tailscale_users` (tailnet login to local user name; matching ignores
case).

**`[models]`**: the live model list behind the web UI: `cache_ttl_s` (300), `error_ttl_s` (30), `refresh_min_interval_s` (10),
`timeout_s`, `new_for_s` (3 days), `max_models_per_provider`.

**`[usage]`**: per-feature cost/time telemetry behind the admin *Features* page: `price_usd_per_million` (a map from alias to
dollars per 1M prompt+completion tokens; cost is estimated since this server has no modelgate, and is unknown for an alias with no
price), `window_days` (7: the look-back for calls, tokens, cost and median/p90 time), `keep_days` (30: how long per-call rows are
kept). The same section also carries the per-user limits: `user_budget_usd` (a daily UTC cost ceiling for each user's own upstream;
`0` = unlimited) and `user_requests_per_min` (a per-user request cap; `0` = follow the global limit).

**`[llm]`**: `default_provider`, `timeout_s`, `retries_on_bad_json`, `json_retry_max_tokens`, `reasoning_headroom_tokens`, `retry_max_attempts`, `retry_base_s`, `retry_max_s`,
`deadline_interactive_s`, `deadline_background_s`; `[llm.providers.NAME]` with `base_url`, `api_key_env`, `max_concurrent`,
`reserved_interactive`, `json_mode`; per-task tables `[llm.triage]`, `[llm.summary]`, `[llm.glance]` (optional), `[llm.answer]`, `[llm.analysis]`, `[llm.captions]`, each with
`model`, optional `provider`, `fallback`, `reasoning_effort`, `max_tokens`, `temperature`. `[llm.glance]` runs the short side-panel
summary; when absent the glance uses `[llm.summary]` with `reasoning_effort = "none"`, and when present `reasoning_effort` defaults
to `"none"` and `max_tokens` to 160. `[llm.captions]` also defaults to `reasoning_effort = "none"`: proofreading and
translation are JSON over many short strings. `[llm.cuts]` (optional) is the model that builds director's cuts — an explicit alias, no
default; without the table every cuts route reports "not configured". `[llm.cuts_vision]` (optional) is the vision model for
Watched mode; without it Watched is unavailable, Quick still works, and every fallback in this table must name the same provider
because the grids never go elsewhere. Pick the cuts model with the offline test set (`uv run python scripts/cut_bench.py`,
[Director's cuts](#directors-cuts)). See [llm-providers.md](llm-providers.md).

**`[cuts]`**: the director's-cut engine. `default_mode` (`quick` or `watched`), the unit/keep rules (`unit_max_pause_s`, `unit_max_s`, `merge_gap_s`, `min_part_s`, `pad_before_s`,
`pad_after_s`, `min_keep_frac`, `max_keep_frac`, `max_input_tokens`), the queue (`max_active_per_user`,
`default_wait_ms`, `wait_ms_cap`, `transcript_wait_s`, `poll_s`, `max_report_chars`) and `release_duration_tolerance_ms`. Watched adds
`[cuts.watched]`: `enabled`, `max_video_minutes` (90), video size/format and free-space floors, the ffmpeg scene/analysis/chunk
thresholds, `max_grids` (240) with its cap, the vision context (`recent_window_count`, `carry_forward_scenes`, `describe_context_chars`,
`max_input_tokens`, `max_unseen_frac`), `describe_concurrency`/`max_concurrent`, the timeouts and the ETA/progress weights. Every
key and its default is in `config.example.toml`.

**`[assess]`**: `batch_size` (titles per triage call), `coalesce_ms`, `max_videos_per_request`, `wait_ms_cap`, `default_wait_ms`,
`background_concurrency`, `tier2_daily_cap_per_user` (transcript-based deep analyses per user per UTC day, default `30`),
`tier2_clickbait_threshold`, `triage_cache_ttl_s`, `title_max_chars`, `description_max_chars`,
`channel_description_max_chars` (channel description sent to the triage prompt), `reassess_max_per_run`
(clickbait verdicts on subscribed channels re-triaged per user by `utubot assess-fixup`).

**`[youtube]`**: pacing and circuit breaker for everything that reaches YouTube, see [YouTube limits](#youtube-limits-and-the-transcription-fallback).
`max_concurrent` (default `1`), `min_interval_s` (`3.0`), `jitter_s` (`1.5`), `cooldown_base_s` (`300`), `cooldown_max_s` (`3600`),
`captions_cooldown_max_s` (`1800`, the lower ceiling of the caption class), `captions_probe_retry_s` (`10`), `network_retry_s` (`60`),
`max_background_queue` (`5`), and the yt-dlp JavaScript runtime (`js_runtime`, `js_runtime_path`, `remote_components`).

**`[archive]`**: the media archive, see [Media archive](#media-archive): `path` (empty: `<data dir>/archive`), `quota_bytes`
(`0`: no limit), `warn_frac` (`0.9`), `eviction` (`never`, the default, or `lru`, see [Media archive](#media-archive)) and
`evict_protect_s` (`3600`).

**`[transcripts]`**: `cache_ttl_s`, `no_captions_ttl_s` (default 3 days), `video_failure_ttl_s` (15 min), `empty_track_retry_s` (15 min), `meta_retry_s` (10 min), `client_max_tracks` (10), `client_max_track_bytes` (2 MiB; caption tracks a client uploads), `fetch_timeout_s`, `default_language`, `cookies_file`
(only if YouTube blocks the host), `skip_if_longer_than_s`. (`max_concurrency` is gone: `[youtube] max_concurrent` replaces it;
an old entry is ignored.)

**`[summary]`**: `token_budget`, `chunk_tokens`, `chars_per_token`, `strategy` (`map_reduce` or `truncate`),
`default_wait_ms`, `wait_ms_cap`, `adhoc_ttl_s`, `max_summary_chars`, `failure_cooldown_s` (`120`: how long a non-busy model
failure of a summary, insight, answer or background analysis is remembered before asking again), `max_import_bytes`, `import_timeout_s`,
`import_allow_hosts`, `import_max_redirects`, `panel_prompt` (prompt for the side panel's automatic summaries, default
`"builtin/glance"`; each user can choose their own), `auto_long` (default `false`: also generate the user's default long summary in
the background after a panel summary; a user's `auto_long` policy field overrides it), `auto_long_max_concurrent` (default `2`,
background long summaries in flight including the transcript fetch; further ones are skipped until one ends, `0` disables them). See [prompt-sets.md](prompt-sets.md).

**`[captions]`**: the ASR engine chain (`[[captions.asr_engines]]`, or the single `asr_*` keys), chunking, diarization and the estimate
inputs, see [captions.md](captions.md). Also `asr_unhealthy_s` (`300`), `asr_failure_window_s` (`600`), `asr_warmup_wait_s` (`90`), `asr_warmup_retry_s` (`3`), `asr_warmup_max_step_s` (`20`), `asr_chunk_overlap_s` (`2`), `download_overhead_s` and
`download_speed_factor` (the estimate shown before a transcription), `transcribe_max_active_per_user` (default `5`), `job_max_attempts`
(`3`), `media_orphan_age_s` (`3600`), `max_download_bytes` (400 MiB), `audio_format` (yt-dlp's fallback selector), and the
`gate_*` thresholds of the offline `captions-gate` ([captions.md](captions.md)).

**`[setup]`, `[setup.defaults]`**: the public `/setup.json`: `name`, `pairing`, optional `prompt_set_urls`, and the switch values
the app applies on import (`assess`, `mark_only`, `answer_in_menu`, `summary_panel`, `auto_captions`).

**`[app]`**: `downloader_codes = { arm64-v8a = "12345", armeabi-v7a = "67890" }` shown on the landing page when non-empty.
Updates from GitHub ([Updates](#updates)): `github_repo`, `signing_cert_sha256`, `apksigner_path`, `github_token_env`,
`keep_versions`, `apksigner_timeout_s`, `sync_timeout_s`, `sync_releases_per_page`, `sync_max_apk_bytes`; for the web UI's update
page `release_check_ttl_s` (600), `release_check_error_ttl_s` (60), `release_check_min_interval_s` (30).

**`[default_policy]`** and **`[[users]]`**: see [policy.md](policy.md). They also carry the defaults of the [per-user
settings](#per-user-settings): `models`, `auto_transcribe`, `auto_transcribe_max_minutes`, `cut_mode`, `summary_delay_ms`, `update_checks`,
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
  `transcribing`, `progress`, `estimate_s`; a length the client did not send is learned first with one paced `metadata` request,
  only while that class is healthy and not again for `transcripts.meta_retry_s`); otherwise it answers `needs_transcript` with `can_transcribe`, `estimate_s` and a message
  such as "Captions are temporarily unavailable from YouTube; transcribe the audio instead (~N s)?". This is never remembered (no
  "no captions" entry). "Delayed" stays for the cases where the audio cannot help: no engine serves the video, the video is live or too
  long, the `media` class cools too (a bot check blocks metadata and media together) or the problem is a network error rather than a
  limit. A transcript stored from the audio is kept: captions fetched later, even by a probe that was already in flight, never replace it,
  and a video with an `asr` transcript is not asked for captions again. In the other direction, stored captions that are still fresh
  (`transcripts.cache_ttl_s`) are kept and an expired captions row is replaced by the audio transcript; a transcription job whose
  result could not be stored fails (recorded, `failed`) instead of ending silently.
- **Problems of one video stay with that video.** A 403 or 410 on a caption or media URL and members-only, age-gated, private or
  unavailable videos are failures of that video (`transcript_status: "failed"` with a `reason`), remembered for
  `transcripts.video_failure_ttl_s` (15 min) so they are not re-fetched; they never touch the breaker.
- **Long downloads do not hold the gate.** Audio downloads take the gate only to start (a paced slot, released when the first bytes
  arrive), so a 20 minute download never stalls an interactive metadata or caption fetch. A video that yt-dlp reports as live or
  longer than `captions.max_duration_s` (3 h) is refused from the real info before anything is downloaded, and audio larger than
  `captions.max_download_bytes` is skipped.
- **Fewer fetches.** Clients upload the caption tracks they already hold (`POST /v1/videos/{id}/captions/client`, stored like a fetch with `origin = client`), so a watched video usually needs no yt-dlp request. A transcript is fetched at most once per `transcripts.cache_ttl_s` (30 days), concurrent requests share one fetch,
  and "this video has no captions" is remembered for `transcripts.no_captions_ttl_s` (3 days, then checked again). The second tier
  (inflation and answer analysis) runs only for videos with a title question or a clickbait score above
  `assess.tier2_clickbait_threshold`, at most `assess.tier2_daily_cap_per_user` (30) per user per day, only while the breaker is
  closed or probing, not for videos known to have no captions, and not while `max_background_queue` (5) background fetches are
  already waiting.

**A summary, insight or answer is never made from the title alone.** When no transcript can be had the API says why instead
(`transcript_status`, see the [contract](../ai/CONTRACT.md)):

| Situation | Response |
|---|---|
| 429, cooldown, bot check, network error, empty or incomplete YouTube answer, a caption file that parses to nothing, when the audio cannot stand in (below) | `status: "pending"`, `transcript_status: "delayed"`, a user-facing `error` ("YouTube is limiting transcript downloads; retrying in ~N min") and `retry_after_s`. Never cached as "no captions"; ask again after `retry_after_s` (a caption file that parses to nothing is held for `transcripts.empty_track_retry_s`, 15 min). |
| The caption API is limited (cooldown, probe out, 429/403 just now) and a speech engine can take the video while `media` is healthy | like "no captions" below, with the message "Captions are temporarily unavailable from YouTube; transcribe the audio instead (~N s)?": started by the policy (`pending` + `transcribing`) or offered (`needs_transcript`). Never `delayed`, never remembered. |
| Private, members-only, age-gated or unavailable video, 403/410 on its caption or media URL, too long or live | `status: "failed"`, `transcript_status: "failed"`, `error`, `reason`, `can_transcribe`. |
| YouTube lists no captions (from a complete yt-dlp answer) | `status: "needs_transcript"`, `transcript_status: "none"`, `can_transcribe`, `message` and `estimate_s`. The TV offers "Transcribe in background?". |
| No captions and the user's policy allows it (`auto_transcribe` `on_open`/`on_dwell`, video up to `auto_transcribe_max_minutes`, default 30) | the transcription is queued by the request itself and it answers `status: "pending"`, `transcript_status: "transcribing"`, `progress`, `estimate_s`. No question is asked. The side panel (`prompt=panel`) only does this for `on_dwell`. |
| The user said yes (or the policy did) | `POST /v1/videos/ID/transcribe` queues a job: audio through the gate (the original-language track at the lowest bitrate), ffmpeg, your ASR engines in chunks ([captions.md](captions.md)), stored as the transcript with source `asr`. Meanwhile summaries answer `pending` with `transcript_status: "transcribing"` and `progress`; afterwards everything works as with YouTube captions. |

`GET /v1/videos/ID/transcript` shows the state (with `job_id` only for your own job) and `GET /v1/jobs` lists your caption and transcript
jobs (`waiting`, `processing`, `ready`, `failed`). Jobs wait while the `media` breaker is open and run when it closes (a caption or metadata limit does not hold them back); a job that YouTube
keeps refusing is retried `captions.job_max_attempts` (3) times and then fails. Before spending effort on the audio a transcript job
asks YouTube once more for captions and uses them if they exist (ASR never replaces captions stored first, and captions fetched later never replace ASR). Videos that are live or longer than
`captions.max_duration_s` (3 h) cannot be transcribed (`can_transcribe: false`). With `force` (`POST /v1/videos/ID/transcribe?force=true`,
or `"force": true` for `POST /v1/videos/ID/captions`) the backend skips that caption check and builds from the audio even when captions exist;
a stored caption transcript is replaced, an existing ASR transcript is still `ready`. While a forced transcript job runs,
`GET /v1/videos/ID/transcript` answers `transcribing` even though the old captions are still stored.

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
the report shows "From the media archive"), and only a miss leads to a download, which the job then stores. Watched cuts read or
store a `kind=video` entry; `utubot media import <video_id> <file> [--kind video|audio]` adds an already-downloaded file without
network (the default kind is `video`, which is what the grid tests and offline benches use). Removing entries is
an explicit admin act — *Admin → Media archive* in the web UI (usage against the quota, one row per video with format, size,
sha256 and age, a *Remove* button) or `DELETE /v1/admin/archive/{video_id}` (`GET /v1/admin/archive` lists it). Unless the
opt-in eviction below is on, nothing in the archive is deleted automatically, and the scratch sweep of `data_dir/media` never touches
it.

Optional LRU eviction (`[archive] eviction = "lru"`, default `never`): a download that would start at or past the quota first frees the
least recently used entries (a `lookup` hit stamps `last_used_at`; an entry never read counts from its fetch time) until the usage is
below it, and a download stored while the usage is over the quota frees the least recently used entries it can (never itself) with
the same rule. Entries used within `evict_protect_s` (1 h; a job may be reading one) and the file just stored are never evicted; when
that is not enough the download is refused as without eviction. Turning it on is the owner's decision: the default keeps the "nothing
is deleted by itself" rule.

## Cache and failures

Everything generated or downloaded for a video is kept per video and reused: metadata, transcripts (captions or audio), HQ captions and
their pipeline stages, triage and deep analysis, summaries (key: video, prompt key, prompt content hash, language; the model is part of
the content hash), condensed text, insights, verdicts, and the media archive. Successes are never re-made while their key matches.

Failures are the opposite, short-lived and always bypassable:

| What | Remembered for | Config |
|---|---|---|
| Language model busy (429/503, connection refused) | never | - |
| Other model failure of a summary, insight or answer | 2 min | `[summary] failure_cooldown_s` |
| Video that cannot be read (private, members-only, too long, ...) | 15 min | `[transcripts] video_failure_ttl_s` |
| Caption file that parses to nothing | 15 min | `[transcripts] empty_track_retry_s` |
| "No captions" (a complete answer, not an error) | 3 days | `[transcripts] no_captions_ttl_s` |

`POST /v1/videos/{id}/retry` (any signed-in user; the TV app's Retry action) drops every one of these memories for the video at once,
including "no captions", and keeps the stored successes.

Admin: `GET /v1/admin/videos/{id}/artifacts` lists what is stored for a video (per kind: rows, bytes, newest write) and
`DELETE /v1/admin/videos/{id}/artifacts[?kind=summary&kind=...]` removes the named kinds (all but the media archive when none is named;
`kind=archive` removes the archived media, as `DELETE /v1/admin/archive/{id}` does). Kinds: `metadata`, `transcript`, `captions`,
`triage`, `analysis`, `summary`, `condensed`, `insight`, `pipeline`, `verdict`, `archive`.

Without `eviction = "lru"`, the quota (`[archive] quota_bytes`, `0`: no limit) never frees space by itself. At `warn_frac` (`0.9`) of
the quota a warning is logged; at the quota new downloads are refused — the job fails with "The media archive is full; an admin must
free space in it (nothing is deleted automatically)" — while archived media keeps serving every pipeline. With `"lru"` the check first
evicts what it can, and a file stored over the quota is kept with a warning (it is never evicted right after its own store); the
job only fails when the protection window leaves too little to free. A download whose storage fails (the archive disk is out of
space or gone) fails the job and keeps the file in its scratch directory instead of deleting it.

## Users, pairing, devices

A *user* is a person (own settings, own prompt sets). Create users with `utubot user add NAME` (token printed once, hash stored in
`users.toml`), with *Admin, Add a user* in the web UI (a user without a token that signs in with a password; `users.toml` gets a
block with an empty `token_sha256`), or declare them in `[[users]]` with `admin = true` for admins and `prime = true` for the prime
class (`utubot user prime NAME on|off` or the web UI for `users.toml` users). A person signs in to the web UI
with a password (`utubot user passwd NAME`, or the web UI) or with their token. Users declared in `config.toml` keep their admin and
prime flags there; the web UI changes them only for users that live in `users.toml`.

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
| Updates | the app version this server publishes, the newest GitHub release, the last `sync-github` run, and two histories: app versions (release time, notes) and backend deploys (time, real version, changes since the previous deploy) |
| Admin | users (add, set a password, admin flag, pairing code), each user's settings and TVs, the [media archive](#media-archive) (usage, per-video entries, manual cleanup), the alias each feature runs on (last 7 days calls, tokens, estimated cost and median/p90 time, switched from the live model list; the choice overrides the config default for everyone and applies on the next call) |

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
  the automatic-transcription policy: `on_open` / `on_dwell`, side panel or not, the minutes limit), its priority and class
  (`normal` or `prime`).
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
running job shows its progress and a crashed one shows where it stopped. A director's-cuts job adds `video`, `grids`, `describing`
and `in_line` to the stages below if it runs Watched. Stages: `queued`, `promoted`, `started` (attempt and time
waited, and the class), `in_line` (a normal caption or transcript job waiting for prime work: `reason`, `progress` and a message), `gate_wait` (the YouTube class and how long the gate held the job), `caption_recheck` (found, none, delayed or skipped and why; `found` also says how many YouTube word times (`words`) and which `caption_kind` (`manual|auto`) the stored captions have),
`audio_download` (format id, original/dubbed/unmarked track, language, bytes, length, seconds, and `source`: `downloaded` or `from_archive`),
`media_archive` (bytes and the sha256 prefix of what was kept; skipped when the audio came from the archive), `ffmpeg` (`audio_s`, `sample_rate`, and `start_offset_s` when the container placed the first audio sample away from time 0), `chunking` (chunks and their sizes), `asr` and `asr_chunk` (engine, model, seconds, characters, detected language per chunk),
`asr_wait` (an engine was still starting and was waited for: `engine`, `waited_s`, `attempts`, `outcome` = `ready|gave_up`; one per wait, shared by all chunks), `asr_fallback` (an engine gave up on a chunk, and why: `http_503`, `transport_timeout`, `unhealthy`, `engine_unavailable`, `language_mismatch`, `no_word_times` ...; `asr_chunk` also carries `word_timing`, `words` and `word_mode`), `asr_recheck` (a chunk heard in the wrong language, mostly made-up text or far sparser than the rest was listened to again: one event per attempt with `reason`, `action` `forced_language|smaller_window|next_engine`, `detected`, `expected`, `outcome` `replaced|kept|failed`, `flagged_share_before`/`after`; one with `action` `dropped` and `dropped_segments`, `dropped_s` when text that is not speech was removed; `skipped` = `budget|requests` when a re-listen was not done; `detected_after`; `asr` also carries `rechecked_chunks`, `unresolved_chunks`, `skipped_chunks`, `recheck_requests`, `hallucination_drops`, `dropped_s`, and `cache` = `not_stored_unresolved`), `stitching`
(seams, segments cut at overlaps, repeated words dropped), `separation` (the optional vocal separation before ASR, or skipped and why),
`word_timing` (after `asr`: whether the engine's word times were real, with the counts of words repaired — stretched, zero-length,
squeezed, out of order — and the number of silences used; `warn` when the engine returned no word times and the cue times are estimates),
`ref_check` (after `word_timing`, captions jobs only: the engine's word starts against YouTube's own word starts (or, without them, its caption rows' first words): `reference_words`, `anchors`, `anchor_share`, `median_s` (the engine's start minus YouTube's, so YouTube's lead is positive), `p10_s`, `p90_s`, `within_s` (share within `ref_agree_s` of the median), `source` = `words|rows`, `regions` = `[start_s, end_s, median_s]` stretches where the engine differs from the global median by more than `ref_region_off_s`; `ok`, `warn` when there are regions, `skipped` with `reason` = `no_reference|too_few_anchors|other_script`; it changes no times; the stored `captions.timing` keeps `ref_check` with `anchors`, `median_s`, `within_s` and the number of `regions`), `diarization` (only when `[captions] diarization` is enabled; ran, or skipped and why: no Hugging Face token, package missing), `cues`
(count, longest line), `align` (`mode` `silence`: boundaries moved to silences; `words`: cues built from word times, with the speech and
fill cue counts, `fill_from_words` (fill cues built from YouTube's word times) and `merged_short` (cues under `min_cue_s` joined to a neighbour); `captions_timing`: skipped, the caption cues kept as they are (no words, or estimated word times); `merge`: the legacy rule),
`sync_score` (after `align`: `speech_overlap`, `starts_in_silence`, `silence_share` of the finished cues against the audio, and `char_timed_cues`: cues whose times were shared over their text by character count, not taken from words), `proofread` (corrected
cues and how overflowing text was split: `split_exact`, `split_at_pause`, `split_by_chars` (no word times, so the time is by character count), `overlong`; or skipped: off, no LLM, or `translated` when the source pass is skipped because the translated text is proofread instead; per-batch warnings hang under it as `proofread_batch`; a translated track is proofread after translation, so the English output is proofread too), `text`, `translate` (the source and target language, `batches`, `retried`, `split`, `untranslated` (a batch with the wrong number of strings is retried once, then split in halves; a cue that still fails keeps its source text and the stage is `warn`; the job fails only above `translate_max_untranslated_share`), and the same split counts for translated text that does not fit a cue; skipped when the track
already is in the target language), `stored` (what was saved and
how big), `retry`, `finished`, `failed` (cause class, human message, stage) and `delivered`. A `delivered` row is added by the routes clients use (`GET /v1/videos/ID/captions`, the
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
- **Tailscale identity.** With `[auth] tailscale_identity = true`, a safe request (`GET`, `HEAD`, `OPTIONS`) from a loopback peer
  that carries `Tailscale-User-Login` signs in as the local user that login maps to in `tailscale_users`, and the page gets a normal
  session cookie. The header is ignored from any other peer, unmapped logins and unknown local users are refused, and writes still
  need the session's CSRF token. Enable it only on a tailnet-only listener; the public page keeps password and token sign-in.
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
| `transcripts` | `auto_transcribe` (`off`, `on_dwell`, `on_open`, default `on_open`), `auto_transcribe_max_minutes` (default 30), `captions_translate_to` (subtitle language: a code such as `en`, or `off` to keep the spoken language; unset follows `[captions] translate_to`) |
| `cuts` | `cut_mode` (`quick` default or `watched`): the viewer's default director's-cut mode; a request can still choose the other mode |
| `tv` | `summary_delay_ms`, `summary_panel`, `auto_captions`, `update_checks` |

**Precedence**, for each setting, highest first:

1. the user's own choice (web UI or `PUT /v1/me/settings`, also `PUT /v1/me/policy` and the prompt-default calls), kept as a sparse
   override of only what they changed; `null` removes it again;
2. the user's `[users.policy]` entry (`config.toml` or `users.toml`);
3. `[default_policy]`;
4. the built-in default.

A setting still unset at that point follows the server setting it mirrors, so there is one place to change it for everyone:
`cut_mode` follows `[cuts] default_mode`; `auto_long` follows `[summary] auto_long`; `mark_only`, `summary_panel` and `auto_captions` follow `[setup.defaults]` (the values a
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

## Per-user upstream

A user can bring their own OpenAI-compatible upstream for their cuts and answers, so those calls run on
their key and budget instead of this server's. They store it with `PUT /v1/me/provider`
(`{"base_url": "https://host/v1", "api_key": "..."}`), read what is stored with `GET /v1/me/provider`
(host and a short key fingerprint, never the key, or `{"configured": false}`), and clear it with
`DELETE /v1/me/provider` (back to the server default). The key is needed to make the call, so it is
stored on the server, never returned in a response or a log line, exactly like the `[llm.providers]`
env-var keys. A base url that is not `http(s)://host` or an empty key is refused with `400`. The database file is owner-only (0600); keep backups of it equally private.

Their calls still run under their own limits: `user_budget_usd` (`[usage]`, a daily UTC cost ceiling,
`0` = unlimited) is checked before each send and a `UserBudgetError` surfaces as `429` with a
`Retry-After`; `user_requests_per_min` (`[usage]`) caps their requests and also returns `429`. The
router sends their calls to their upstream (the model is requested as before, any `provider:` prefix
dropped since the endpoint is fixed) and falls back on the server default when they have none.

The admin page shows each user's own upstream and their cost/calls for the day; both `GET /v1/users`
and `GET /v1/admin/users` include a `provider` (host + key fingerprint, or `{"configured": false}`) and
a `usage` (`{cost, calls, day}`) per user.

## Director's cuts

A director's cut is a model-picked list of the parts of a video worth keeping; the TV app skips
the rest with its sponsor-skip engine, and the phone can judge a cut from its parts list before
the TV plays it. Requests start on the TV ("Director's cut…" in the video menu, or "Describe on
phone…" which shows a QR code) or on the phone (the Cuts tab, paste a link, pick a preset chip
or describe the cut). Wire details: [../ai/CONTRACT.md](../ai/CONTRACT.md#directors-cuts-addendum-2026-11-20).

A cut's mode resolves in order: its own explicit `mode`, the owner's stored default for the
video's channel, the `cuts.cut_mode` setting, then `[cuts] default_mode`; the answer says which
rule decided (`request`, `channel`, `user` or `server`). A default `watched` that is unavailable
runs `quick` and still reports its rule.

The owner can store a default per channel from the TV cut sheet or the Cuts tab: the web UI lists
every channel seen in their cut requests, with its current override and a `quick` / `watched` /
"follow the user" choice. Clearing it falls back to the user's choice, then the server default.
Channel overrides belong to one user and need the video's `channel_id` (the clients send it with
the video facts). `GET|PUT|DELETE /v1/cut-channels` edit them.

- Requests are rows in `cut_requests` (`waiting` → `building`/`needs_transcript` → `ready`/
  `failed`, or `dismissed`); the phone queue is `GET /v1/cut-requests`, the TV long-polls
  `GET /v1/cuts/{id}`. The QR target `GET /cuts/{id}` redirects into the web UI's cut sheet.
- The viewer's choice is kept per `(user, video)` in `cut_choices` (a preset, a typed request, or
  `off`); the preset used last is kept per user in `cut_last_presets`. A video opens with the
  choice, else with the last-used preset when it has a ready cut here; otherwise
  `GET /v1/videos/{id}/cuts` returns no `selection` and the TV offers the ready cuts. A cut
  request created or filled remembers its preset/request as the choice; the TV records a cut
  applied from its player or picker with `PUT /v1/videos/{id}/cut-choice`.
- Builds are their own async tasks (never the caption worker's queue) with a per-user cap
  (`[cuts] max_active_per_user`). A missing timed transcript queues a transcript job and the
  build shows `needs_transcript` until it lands (10 min, then it fails with a plain reason).
- The engine merges caption fragments into numbered sentence-like units (`[cuts]`
  `unit_max_pause_s`/`unit_max_s`; rolling auto-caption repeats are dropped), sends them with
  title, chapters and duration to the `[llm.cuts]` model, and validates its kept unit ranges:
  one repair round, then gap merging (`merge_gap_s`) and short-part dropping (`min_part_s`) on
  the model's own boundaries clamped to the video, padding (`pad_before_s`/`pad_after_s`), and
  the keep guards: `min_keep_frac` ("would remove almost everything") refuses except for a cut
  with a target length and the `short_presets` (a targeted answer or demo may be short), and
  `max_keep_frac` ("nothing to cut") refuses only a typed prompt without a target: a named
  preset is a removal instruction, so keeping nearly all of the video is a valid result. A removal preset puts the
  result in the cut's `summary` ("Removed 1:12 of filler, 2 % of the video"); when nothing is
  removed the summary says so ("No filler found") and the request is still `ready`. A failed
  request never blocks a new one: asking for the same preset again builds a fresh request and
  keeps the failure in the history (the picker shows it with a Retry). One finished cut is
  shared per (video, preset or prompt, model, transcript) cache key, so a second identical request is
  instant; a changed transcript invalidates it.
- Long videos: a transcript that fits `[cuts] max_input_tokens` goes in one request. Set that
  value to about 80% of the context of the `[llm.cuts]` alias (the default 80000 suits a
  100k-token alias; a small local model needs a lower one). A longer transcript is cut by
  map/reduce: excerpts of at most `map_chunk_tokens` (starting on chapter boundaries where
  there are chapters, `map_overlap_units` shared with the previous excerpt) are asked in parallel
  (`map_parallel`, further capped by the provider's limiter) to apply the task to their own text,
  with their share of the target length; one final call over the candidates (id, time range,
  label, rank, `reduce_excerpt_chars` of text) picks the cut with the usual rank selection.
  Candidates that do not fit one call are narrowed in rounds (`max_reduce_rounds`). A failed
  excerpt is retried once, then the cut fails naming the part. Typed prompts keep their meaning:
  the map collects candidates for the prompt, the reduce applies it. A preset with no target
  length (`cut-demo`, a saved preset with no length) would otherwise let every excerpt stand for
  all of itself, so each excerpt is limited to its share of `map_max_keep_frac` (default 0.90) and
  the final choice is trimmed to that maximum, keeping the highest-ranked parts; the model still
  chooses what to keep. Each excerpt's decision is logged (kept and removed seconds, part count),
  and the final `reduce` event carries the kept seconds and the target or cap.
- Old near-full long cuts are repaired once: on start (unless `[cuts] repair_on_start` is false)
  and with `utubot cuts repair [--dry-run]`, a cut built by an older cut algorithm
  (`algo_version`) that kept over `repair_near_full_frac` (default 0.90) on the map/reduce path
  with no target length is superseded — its request leaves the queue and its cut row is deleted —
  and the same user, video and preset (or typed prompt) is queued again. Rebuilt cuts carry the
  current algorithm version, so a repaired cut that legitimately keeps a high share is never
  queued again. The command prints each old kept share and the new request id.
- **Watched** is opt-in picture analysis, chosen with mode `watched` (Quick is the default). It
  stores a small video copy (`bestvideo` at most 360p, up to 90 minutes/1 GiB) in the media
  archive, samples 2x2 grids with `ffmpeg`, and describes each grid with `[llm.cuts_vision]`
  (`[cuts.watched]` holds every threshold). Descriptions are cached per video and video
  description; a later preset for the same video reuses them, but each preset's editor prompt is
  built again. A silent stretch over 4 s becomes a `(no speech)` unit, so a silent demo can be
  kept by id. Boundaries may move outward up to 1 s to a real shot cut, never across a speech
  unit. One Watched build runs at a time per server; a second request shows `in_line` and waits.
  A grid/video cache is invalidated by a new video file or a transcript change, not by a preset.
  The watched editor reuses the target-length rank selection of Quick (the model is asked for a
  target and the server drops the lowest-ranked parts until it fits).
- **Watched failures offer Quick.** Over 20 % unseen scenes, a busy/absent vision endpoint, an
  over-limit video, low disk, a too-slow estimate (over `describe_s_per_grid_max` per grid) or
  the 1-hour build deadline fail the request with a plain reason; the request carries
  `fallback` = the same preset's Quick state, so the app can build Quick in one press. Quick
  itself never carries a fallback. The app can choose the mode per picker session; the viewer's
  default is `cut_mode` in Settings (web UI), following `[cuts] default_mode`.
- The stages of a build are in its job report (kind `cuts`): `transcript` → `model` →
  `checking` (long videos: `transcript` → `map` → `reduce` → `checking`; `map` events carry
  `done`/`of`, and the request document's `progress` mirrors them); Watched runs `transcript` →
  `video` → `grids` → `describing` → `model` → `checking` (cached stages report `skipped`), and a
  queued watched request shows `in_line` while another build holds the one slot, and any normal build shows `in_line` (`reason` `priority`) while it waits for prime work. The job page
  shows `progress`/`eta_s` and the new stages, with the model's raw answer trimmed into the row.
  Cut jobs never appear in the caption worker's cancel/retry paths — a cut is retried or
  dismissed from its cut sheet. Admins can read the newest TDT with
  `GET /v1/admin/videos/{id}/tdt`; removing the archive entry drops its watched caches too.
- A description typed on the cut sheet can be saved as the owner's own preset (phone only in
  v1): `POST /v1/cut-presets` stores it in the user's `cut-presets` prompt set, so it becomes a
  chip on later sheets and a row of the TV picker; `GET` lists them and `DELETE` removes one.
  The same name and description replace the earlier copy; at most 20; built-ins cannot be
  deleted here. The set stays out of the summary prompt pickers.
- The web UI is installable (manifest `/manifest.webmanifest`, icons `/ui/icon-192.png` and
  `/ui/icon-512.png` rendered from `/ui/icon.svg`) and takes Android's YouTube Share button:
  the manifest's `share_target` is `/shared`, and `/sw.js` keeps the shared link in the Cache
  API before redirecting to the Cuts tab, which turns it into a waiting request. The server
  never receives the shared POST; manifest and worker are public static files. The Share target
  needs **HTTPS** and an **installed** app: Chrome builds a WebAPK only from an installed PWA,
  and a home-screen shortcut is not enough. If the menu says "Install app" but YouTube's Share
  sheet still lacks u·tubot, check Chrome's install prompt and the PNG icon sizes on the phone.
- The Cuts tab loads its queue even when the service worker does not register: taking a shared
  link waits at most 1.5 s and the queue and its poller start before that. Chrome with site data
  blocked, Firefox private windows or a proxy that does not pass `/sw.js` must not leave the
  tab blank.

**Choosing the model**: `[llm.cuts]` has no default on purpose — quality matters and the
feature stays off until an alias is named. Score the available aliases offline against the
test set (6 hand-marked transcripts and 19 requests, must-keep/must-skip spans, no network):

    cd ai-backend && uv run python scripts/cut_bench.py --list --base-url http://gateway:8787/v1
    uv run python scripts/cut_bench.py --model <alias> --base-url ... --api-key-env KEY_ENV
    uv run python scripts/cut_bench.py                           # every alias the endpoint serves

The key is read from the named environment variable and never logged. Past measurements live in
`ai-backend/fixtures/cuts/` (the 2026-11-20 pick: `fast`, with `fast-instruct` as fallback).

## Processed videos

The TV's *Processed* section lists what the owner has recently processed, so the server keeps a
read-only view over rows it already has rather than a new history table. Wire details:
[../ai/CONTRACT.md](../ai/CONTRACT.md#processed-videos-addendum-2026-11-23).

- `GET /v1/processed?limit=50` (default 50, at most 200) answers `{"videos":[...]}`, one item per
  video, newest last change first. The limit counts videos, not the caption or cut entries under
  them.
- A video comes from the caller's caption jobs (`jobs`, kind `captions`) and their cut requests
  (`cut_requests`). Another user's jobs and cuts are never combined into this view; a dismissed
  cut request is not listed, and a video with only dismissed requests is absent.
- `captions` lists each caption job in the client-facing states `waiting`/`processing`/`ready`/
  `failed`/`cancelled` with language, translation target, progress and error. `cuts` lists each
  request with its state, `preset_id`, the built-in or saved preset label (null for a typed
  prompt, which rides in `prompt`) and error.
- `summary` is true when any stored summary exists for the video; summaries are shared per video.
- `updated_at` is the newest change among the item's caption jobs and cut requests. The title
  comes from cached video metadata, else the newest caption job's title. The thumbnail is the
  cached metadata URL, else YouTube's standard `mqdefault` image for the id. Nothing is stored
  for this endpoint.

On the TV, a tile's second title says what is ready there ("HQ captions: ready • Cut ready: Only
the demo • Summary ready") or where unfinished work stands. Opening a tile plays the video through
the usual playback path, selects its HQ captions even when *Select HQ captions automatically* is
off, and opens with the cut the viewer chose for that video (or the preset used last when it has a
ready cut here); with no such cut it offers every ready director's cut with one Apply each (the
player's cut controller, as at any video start).

## Voice prompts

The phone records a spoken cut description and posts it to `POST /v1/speech`; this backend sends
the audio on to modelgate's `POST /v1/audio/transcriptions` with `[speech] alias` (the route from
EVR-464) and returns only the text. Nothing is stored locally, and the log keeps the client, alias,
bytes and duration, never the audio or the words. Wire details:
[../ai/CONTRACT.md](../ai/CONTRACT.md#voice-prompts-addendum-2026-11-21).

- `[speech] alias` names modelgate's transcription alias; without it the sheet's mic says
  "Speech is not configured on this server; type the cut instead." and `GET /v1/me` features
  carries `"speech": false`.
- The upload has its own cap (`[speech] max_upload_bytes`, 4 MiB default) because the global
  `security.max_body_bytes` (256 KiB) covers JSON bodies only; oversize answers `413`
  `"request too large"` before the form is read.
- A per-user rate limit (`[speech] per_user_per_min`, 10 default) stops a retry loop. Upstream
  busy (`429`/`503`/`504`), timeouts and transport failures (modelgate unreachable) answer `503
  "Speech service is busy, try again or type it."`; other refusals answer `502 "Speech could not
  be transcribed, try again or type it."`. The forwarded file part gets an extension from its
  content type when the client sent a bare filename (STT servers often pick the decoder by it).
- The text lands in the description box and stays editable; the phone never sends it itself.
  `[speech] max_record_s` (50 default) is the recording limit the sheet reads from `GET /v1/me`.
  The modelgate route's oMLX whisper refuses a chunk over about 55 s (upstream `500 "Engine not
  started"`, tracked in EVR-524), so one recording stops below that; a longer description is
  spoken in several taps and the answers append to the same box. The phone sends the whole
  recording as one file, so keep the configured limit under 55 s.
- The page's `Permissions-Policy` allows the microphone for its own origin (`microphone=(self)`);
  camera and geolocation stay off. The microphone is requested only when the owner taps Speak.
- ffmpeg is needed on the modelgate host when the phone's webm/opus cannot be passed through
  (EVR-464 documents the format matrix).

## Voice control

Plan: `ai/VOICE_CONTROL_PLAN.md`. Checkpoint 1 is the backend half only: consent per device, the command history, retention and the
addresses clients read. It is off by default (`[voice] enabled = false`): the voice routes answer `404`, `GET /v1/me` has
`features.voice = false` and nothing else new, `/setup.json` has no `realtime_url`, and the web UI shows no Voice page. Rolling back is
that switch or reverting the revision: the three new tables (`device_voice`, `user_voice`, `voice_commands`) are `CREATE IF NOT EXISTS`
and nothing reads them while voice is off, so no database step is needed either way.

- Config: `[voice] enabled`, `realtime_path` (`/rt`; `/setup.json` gets `realtime_url` = `public_base_url` + this), `retention_days`
  (30), `max_text_chars`, `max_args_bytes`, `history_page_max`, `commands_per_min` (see `config.example.toml`).
- A device is off until its owner switches it on in the web UI (TVs page, Voice control) after reading the consent text the server
  serves (`consent.version` must be sent back). The all-off button switches every device off and the next switch-on asks again.
- The history is text only (what was said, the tool, its arguments, the outcome, timing marks), kept `retention_days` (the user may
  choose 0 to keep nothing) and read and deleted on the Voice page. No audio is stored by this backend or, by design, by anything else.
- The live server that carries audio is a later checkpoint; until it exists the switches and the history are all that does anything.

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

Tailscale Serve also names the signed-in tailnet user in `Tailscale-User-Login`. Map logins to local users to sign in to the web UI
without a password:

```toml
[auth]
tailscale_identity = true
tailscale_users = { "person@example.com" = "owner" }
```

The app trusts that header only when the peer is loopback (Tailscale Serve's own connection), so enable this only on a listener
that is not publicly exposed. `X-Forwarded-For` does not affect this check. Each tailnet login maps to one local user; remove the
mapping or turn the option off to go back to password sign-in. The first page load creates a session like any other sign-in, and
signing out at *Account* clears it until the next load.

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

### Updating and rolling back

Database changes are additive only: `utubot.sqlite` is created and extended at start (`CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ...
ADD COLUMN` with a default or a nullable column), and nothing is dropped or rewritten except the cleanup of rows that must not
exist. Going back to an older revision therefore needs no database step: the older code ignores the newer tables and columns, and
the next upgrade finds them already there. A test (`tests/test_db_migrations.py`) keeps new columns that way, and a change that cannot
be additive (a rename, a type change, a dropped column) must ship as a new column or table plus a copy, with the old one left in place for
at least one release. A rollback does not undo data that the newer revision wrote, and it does not restore files; to be able to
undo even that, copy `data_dir` first (`sqlite3 utubot.sqlite ".backup utubot.before-update.sqlite"` is safe while the service runs).

## Updates

The backend version (`/v1/health`, `/v1/me`, the web UI) is `0.<series>.<commit time>+<short sha>` read from the git checkout the
server runs from; the series is the minor of `utubot.version`, the commit time the HEAD commit's date in UTC as `YYYYMMDDHHMM`
(not the commit count, which a shallow clone undercounts). Without git (an installed package) it is the package version. At every
start the server compares the running commit with the last recorded deploy and, when they differ, stores a deploy entry (time, version,
commit, the merged changes since the previous one) in the database, so a restart never adds one. `utubot app sync-github` stores the
notes and release time of the app releases it sees in the same table. `GET /v1/changelog?kind=app|backend` serves both (`ai/CONTRACT.md`).

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

1. Lists the repository's releases through the GitHub API (no login needed for a public repository; a token in the environment
   variable named by `github_token_env`, `UTUBOT_GITHUB_TOKEN` by default, is the preferred setup because it raises the rate limit)
   and takes the highest `utubot-vX.Y.Z` that is not a draft (prereleases only with `--prerelease`). The request carries the last
   ETag (`If-None-Match`), so an unchanged list answers `304` and does not count against the rate limit. The ETag, the last list and
   GitHub's `X-RateLimit-Reset` are kept in `app_dir/sync-state.json`; while a reset is in the future the command exits `75`
   without asking GitHub and prints one warning when the limit is first hit, not on every run.
2. Reads its `release.json` and compares `version_code` with the channel's (`latest.json`). Equal or older: nothing to do, so the
   command is safe to run every few minutes.
3. Downloads each APK, checks its SHA-256 against `release.json`, then verifies its signature and requires every signer
   certificate to equal `signing_cert_sha256`. Nothing is published unless all APKs pass. The signature is checked by `apksigner`
   when `apksigner_path` is set (Android build-tools, needs a JRE), otherwise by a built-in pure-Python reader of the APK Signing
   Block (schemes v2, v3 and v3.1): it verifies each signature, recomputes the APK's content digest and compares it with the
   signed one, so an APK changed after signing is refused. It supports RSA keys (PKCS#1 v1.5 and PSS); for an ECDSA key set
   `apksigner_path`.
   Then it reads the APK's own `AndroidManifest.xml` and requires the package `dev.utubot.tv`, the `versionName` of the release and,
   when `release.json` gives one, its `versionCode`, so wrong metadata cannot publish an APK under another version (no `aapt2`
   needed).
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

Publish APKs signed with the same key as the installed app. TVs compare the manifest's `versionCode` with their own (the
`versionName` decides only when the manifest has no code).

## Backups

Back up `data_dir`: `utubot.sqlite` (caches, jobs, prompt sets, device token hashes, password hashes, web sessions, per-user settings) and `users.toml`; plus
`config.toml`, the env file and `app_dir`. Caches can be rebuilt; losing `users.toml` or the database means re-pairing.
