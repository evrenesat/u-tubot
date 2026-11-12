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
`background_concurrency`, `tier2_daily_cap_per_user` (transcript-based deep analyses per user per UTC day),
`tier2_clickbait_threshold`, `triage_cache_ttl_s`, `title_max_chars`, `description_max_chars`.

**`[transcripts]`**: `cache_ttl_s`, `max_concurrency`, `fetch_timeout_s`, `default_language`, `cookies_file` (only if YouTube
blocks the host), `skip_if_longer_than_s`.

**`[summary]`**: `token_budget`, `chunk_tokens`, `chars_per_token`, `strategy` (`map_reduce` or `truncate`),
`default_wait_ms`, `wait_ms_cap`, `adhoc_ttl_s`, `max_summary_chars`, `max_import_bytes`, `import_timeout_s`,
`import_allow_hosts`, `import_max_redirects`, `panel_prompt` (prompt for the side panel's automatic summaries, default
`"builtin/glance"`; each user can choose their own), `auto_long` (default `false`: also generate the user's default long summary in
the background after a panel summary; a user's `auto_long` policy field overrides it), `auto_long_max_concurrent` (default `2`,
background long summaries in flight including the transcript fetch; further ones are skipped until one ends, `0` disables them). See [prompt-sets.md](prompt-sets.md).

**`[captions]`**: ASR and diarization, see [captions.md](captions.md).

**`[setup]`, `[setup.defaults]`**: the public `/setup.json`: `name`, `pairing`, optional `prompt_set_urls`, and the switch values
the app applies on import (`assess`, `mark_only`, `answer_in_menu`, `summary_panel`, `auto_captions`).

**`[app]`**: `downloader_codes = { arm64-v8a = "12345", armeabi-v7a = "67890" }` shown on the landing page when non-empty.

**`[default_policy]`** and **`[[users]]`**: see [policy.md](policy.md).

Environment: `UTUBOT_CONFIG`, the provider key variables you named, `UTUBOT_ASR_API_KEY`, `UTUBOT_HF_TOKEN`. Keys never go
in the config file.

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

## Publishing APKs

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
