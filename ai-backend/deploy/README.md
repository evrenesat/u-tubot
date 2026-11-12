# Deploying u·tubot

Nothing here is installed automatically. Target layout:

- checkout: `/opt/utubot/ai-backend` (any path; edit `utubot.service` to match)
- config: `/etc/utubot/config.toml` (copy `config.example.toml`, set `data_dir = "/var/lib/utubot"`)
- secrets: `/etc/utubot/env`, mode 0600, one `NAME=value` per line: the provider keys named by `api_key_env`
  (for example `UTUBOT_LLM_API_KEY=...`), optionally `UTUBOT_HF_TOKEN=...` (pyannote read token).
- service binds `127.0.0.1:8790` only.

## Install

```sh
cd /opt/utubot/ai-backend
uv sync --frozen --extra asr        # builds .venv; add --extra diarization for pyannote (torch, large)
install -d -m 0750 /etc/utubot /var/lib/utubot /var/lib/utubot/app
cp config.example.toml /etc/utubot/config.toml    # then edit
install -m 0600 /dev/null /etc/utubot/env         # then fill in
cp deploy/utubot.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now utubot
```

The unit starts `.venv/bin/utubot` directly (no `uv run`, so nothing syncs or downloads at
start; rerun `uv sync --frozen --extra asr` and restart after updating the checkout). It is
hardened (`ProtectSystem=strict`, `ReadWritePaths=/var/lib/utubot`, read-only home) and keeps
Hugging Face, torch and yt-dlp caches under `/var/lib/utubot/cache` via `HF_HOME`, `TORCH_HOME`
and `XDG_CACHE_HOME`. ffmpeg must be installed on the host (`/usr/bin/ffmpeg`). The first admin:

```sh
UTUBOT_CONFIG=/etc/utubot/config.toml .venv/bin/utubot user add owner --admin
```

## Public-input safety

Prompt-set import (`POST /v1/prompts/import`, refresh) fetches user-supplied URLs. Every hop,
redirects included (max 5), must be http/https on the default port and resolve only to public
addresses (loopback, RFC1918, link-local, CGNAT/tailnet, ULA, multicast, reserved and
mapped/6to4 forms are refused), and the connection is pinned to the validated IP, which closes
DNS rebinding between check and connect. `summary.import_allow_hosts` lists exact hostnames that
bypass the check; keep it empty unless needed. API errors never include upstream bodies or
internal URLs; details go to `journalctl -u utubot`.

## Reverse proxy and exposure

The service binds loopback. Put a TLS reverse proxy (nginx, Caddy) or Tailscale Serve in front of it and set
`server.public_base_url` to the public URL. `security.trusted_proxies` lists the peers whose `X-Forwarded-For` is
believed (default loopback only); add the address your proxy connects from if it is not loopback. The client IP is the
right-most entry that is not a trusted proxy, and drives rate limits and the pairing lockout. Examples for nginx, Caddy and
Tailscale Serve are in `docs/server.md`.

## Pairing a TV

```sh
uv run utubot user pair NAME        # prints a 6-digit code, valid 15 minutes, single use
```

The app posts it to `POST /v1/pair` and receives a per-device token. List and revoke with
`utubot user devices` / `utubot user revoke ID` or in the admin section of the web UI.

## Publishing an app update

```sh
uv run utubot app publish u-tubot_0.2.0_arm64-v8a.apk u-tubot_0.2.0_armeabi-v7a.apk u-tubot_0.2.0_universal.apk \
  --version-name 0.2.0 --version-code 2 --changelog "line one
line two"
```

One APK per ABI; the ABI comes from the `_<abi>.apk` file name (`--abi` for a single file named otherwise). The APKs are
copied into `app_dir`, `update.json` (Electric Eel format, with `downloadUrlList_<abi>` keys) and `latest.json` are rewritten.
All are served without auth: `/app/update.json`, `/app/<file>.apk`, the stable `/app/latest/<abi>.apk` redirect and
`/app/info.json` for the landing page.

## Ops

- logs: `journalctl -u utubot`
- data: `/var/lib/utubot/utubot.sqlite` (cache, jobs, prompt sets, device token hashes)
- storage hygiene: transcripts and captions are small; media is deleted after each caption job
  unless `keep_media = true`.
