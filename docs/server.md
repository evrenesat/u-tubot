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

Open `http://127.0.0.1:8790/`: paste the token to reach the web UI (health, policy, prompt sets, trying summaries, caption jobs,
and for admins pairing codes, devices and policies). Without a token the page shows the public Download section only.

The config file is `$UTUBOT_CONFIG` or `./config.toml`; `utubot --config PATH SUBCOMMAND` overrides it. Config changes need a
restart; `users.toml` changes are picked up live.

## CLI

```
utubot [--config PATH] serve [--host H] [--port P]
utubot user add NAME [--admin]      create a user, print a token once
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

**`[security]`**: `trusted_proxies` (peers whose `X-Forwarded-For` is believed; default `["127.0.0.1", "::1"]`),
`rate_per_token_per_min`, `rate_per_ip_per_min`, `rate_window_s`, pairing limits (`pair_code_digits`, `pair_code_ttl_s`,
`pair_attempts_per_ip_per_min`, `pair_lockout_failures`, `pair_lockout_s`, `pair_global_failures`, `pair_global_window_s`),
`max_body_bytes`, `max_device_name_chars`, `max_devices_per_user`.

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
`network_retry_s` (`60`), `max_background_queue` (`5`).

**`[transcripts]`**: `cache_ttl_s`, `no_captions_ttl_s` (default 3 days), `video_failure_ttl_s` (1 h), `empty_track_retry_s` (1 h), `fetch_timeout_s`, `default_language`, `cookies_file`
(only if YouTube blocks the host), `skip_if_longer_than_s`. (`max_concurrency` is gone: `[youtube] max_concurrent` replaces it;
an old entry is ignored.)

**`[summary]`**: `token_budget`, `chunk_tokens`, `chars_per_token`, `strategy` (`map_reduce` or `truncate`),
`default_wait_ms`, `wait_ms_cap`, `adhoc_ttl_s`, `max_summary_chars`, `max_import_bytes`, `import_timeout_s`,
`import_allow_hosts`, `import_max_redirects`, `panel_prompt` (prompt for the side panel's automatic summaries, default
`"builtin/glance"`; each user can choose their own), `auto_long` (default `false`: also generate the user's default long summary in
the background after a panel summary; a user's `auto_long` policy field overrides it), `auto_long_max_concurrent` (default `2`,
background long summaries in flight including the transcript fetch; further ones are skipped until one ends, `0` disables them). See [prompt-sets.md](prompt-sets.md).

**`[captions]`**: ASR and diarization, see [captions.md](captions.md). Also `asr_speed_factor` and `asr_overhead_s` (the estimate shown
before a background transcription), `transcribe_max_active_per_user` (default `5`), `job_max_attempts` (`3`), `media_orphan_age_s` (`3600`), `max_download_bytes` (400 MiB).

**`[setup]`, `[setup.defaults]`**: the public `/setup.json`: `name`, `pairing`, optional `prompt_set_urls`, and the switch values
the app applies on import (`assess`, `mark_only`, `answer_in_menu`, `summary_panel`, `auto_captions`).

**`[app]`**: `downloader_codes = { arm64-v8a = "12345", armeabi-v7a = "67890" }` shown on the landing page when non-empty.
Updates from GitHub ([Updates](#updates)): `github_repo`, `signing_cert_sha256`, `apksigner_path`, `github_token_env`,
`keep_versions`, `apksigner_timeout_s`, `sync_timeout_s`, `sync_releases_per_page`, `sync_max_apk_bytes`.

**`[default_policy]`** and **`[[users]]`**: see [policy.md](policy.md).

Environment: `UTUBOT_CONFIG`, the provider key variables you named, `UTUBOT_ASR_API_KEY`, `UTUBOT_HF_TOKEN`. Keys never go
in the config file.

## YouTube limits and the transcription fallback

One home address asking YouTube for dozens of caption files in a few minutes gets `HTTP 429 Too Many Requests`. The backend therefore
sends **every** request that reaches YouTube (yt-dlp metadata and caption lists, the caption text, audio downloads for transcription)
through one process-wide gate:

- **Pacing.** At most `[youtube] max_concurrent` requests (default 1) are in flight, and they start at least `min_interval_s`
  (3 s) plus a random `0..jitter_s` (1.5 s) apart. Interactive work (a summary someone is waiting for) goes before background work
  (tier-2 analysis, caption and transcript jobs); a user who starts waiting on a queued background fetch promotes it.
- **Circuit breaker.** Only signals about the server as a whole open it: a 429, the "Sign in to confirm you're not a bot" check, or a 403
  on the watch, player or metadata request. The cooldown is the `Retry-After` header when YouTube sends one, else `cooldown_base_s`
  (5 min) doubled for each consecutive block up to `cooldown_max_s` (60 min); no cooldown is longer than that. While it is open
  interactive requests are answered at once without touching YouTube, and background work (caption and transcript jobs, tier-2)
  **waits** (it is neither failed nor dropped) and resumes when the cooldown ends. The first request afterwards is a probe: any
  answer from YouTube (a transcript, "no captions", even "this video is private") closes the breaker and resets the escalation,
  another block doubles the cooldown. The state survives restarts. The log records each transition (`youtube gate open:
  reason=... cooldown_s=...`, `half-open`, `closed`); URLs never appear in it.
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
| 429, cooldown, bot check, network error, empty or incomplete YouTube answer, a caption file that parses to nothing | `status: "pending"`, `transcript_status: "delayed"`, a user-facing `error` ("YouTube is limiting transcript downloads; retrying in ~N min") and `retry_after_s`. Never cached as "no captions"; ask again after `retry_after_s` (a caption file that parses to nothing is held for `transcripts.empty_track_retry_s`, 1 h). |
| Private, members-only, age-gated or unavailable video, 403/410 on its caption or media URL, too long or live | `status: "failed"`, `transcript_status: "failed"`, `error`, `reason`, `can_transcribe`. |
| YouTube lists no captions (from a complete yt-dlp answer) | `status: "needs_transcript"`, `transcript_status: "none"`, `can_transcribe`, `message` and `estimate_s`. The TV offers "Transcribe in background?". |
| The user said yes | `POST /v1/videos/ID/transcribe` queues a job: audio through the gate, ffmpeg, your ASR backend ([captions.md](captions.md)), stored as the transcript with source `asr`. Meanwhile summaries answer `pending` with `transcript_status: "transcribing"` and `progress`; afterwards everything works as with YouTube captions. |

`GET /v1/videos/ID/transcript` shows the state (with `job_id` only for your own job) and `GET /v1/jobs` lists your caption and transcript
jobs (`waiting`, `processing`, `ready`, `failed`). Jobs wait while the breaker is open and run when it closes; a job that YouTube
keeps refusing is retried `captions.job_max_attempts` (3) times and then fails. Before spending effort on the audio a transcript job
asks YouTube once more for captions and uses them if they exist (ASR never replaces real captions). Videos that are live or longer than
`captions.max_duration_s` (3 h) cannot be transcribed (`can_transcribe: false`).

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

## Users, pairing, devices

A *user* is a person (own policy, own prompt sets). Create users with `utubot user add NAME` (token printed once, hash stored in
`users.toml`) or declare them in `[[users]]` with `admin = true` for admins. The user's own token is for the web UI.

TVs do not use that token. `utubot user pair NAME` (or *New pairing code* in the admin UI) prints a single-use 6-digit code,
valid 15 minutes. The TV posts it to `POST /v1/pair` and receives a separate per-device token, so each TV is revocable:

```sh
uv run utubot user devices          # ids
uv run utubot user revoke DEVICE_ID
```

Pairing is rate limited and locks an IP out after repeated wrong codes. At most `max_devices_per_user` devices per user.

## Reverse proxy and TLS

Keep the service on `127.0.0.1:8790` and terminate TLS in front of it. Set `server.public_base_url` to the public URL.

`security.trusted_proxies` must list the address your proxy connects from when it is not loopback; the client IP is then the
right-most `X-Forwarded-For` entry that is not itself trusted. Wrong values either let clients spoof their IP (too wide) or make
all clients look like the proxy and share rate limits (too narrow).

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

Back up `data_dir`: `utubot.sqlite` (caches, jobs, prompt sets, device token hashes, policy overrides) and `users.toml`; plus
`config.toml`, the env file and `app_dir`. Caches can be rebuilt; losing `users.toml` or the database means re-pairing.
