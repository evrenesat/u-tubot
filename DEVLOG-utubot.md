# u·tubot devlog

## 2026-11-12 (0.2.1: setup import and pairing UI)

- Real-device report on 0.2.0: Import setup did nothing, Settings showed no Import setup / Pair with code. Reproduced on an
  Android TV 14 (x86) emulator. Root cause of the silent import: `UtubotClient.fetchSetup` used `BufferedSource.readUtf8(64 KiB)`,
  which throws `EOFException` (null message) unless the body is at least that long, so every import failed and the toast read
  "failed: null". Now a bounded stream read; errors are mapped to a reason (DNS, TLS, timeout, connect, HTTP status, bad file).
- The 0.2.0 list did contain Import setup, but Pair with code sat below the switches (off-screen on a TV); the list is now built
  by `UtubotSettingsPresenter.buildCategories` in the fixed order and covered by a test.
- `SimpleEditDialog`: the URI field makes keyboards send Go (not Done), which was ignored; every submit action is handled, the
  field declares Done, Back with the keyboard up is consumed, an empty value says so.
- First-launch prompt is a choice (Import / Not now / Don't ask again) shown on every launch until configured; pairing ends with
  an automatic connection test and "Paired as <user>". A typed backend derives `<backend>/app/update.json`. Version 0.2.1 (code 3).

## 2026-11-12 (release preparation)

- Setup import: the backend serves `/setup.json`; the app's Settings, u·tubot, Import setup fetches it (bare host to
  `https://host/setup.json`, full URL as typed, http only for private addresses), stores backend and update URLs and the
  switch defaults, then opens the pairing dialog. First launch without a backend offers it.
- No baked backend: `UTUBOT_URL` defaults to empty and the `stutubot` flavor has no update URL of its own. The update checker
  reads the stored `update_url`; without one nothing is checked.
- Release signing: `stutubot` release APKs are signed from `UTUBOT_KEYSTORE*` environment variables or `keystore.properties`; the
  build fails with a message when they are missing. Version 0.2.0 (code 2). 0.1.0 was a debug build signed with a debug key: it has
  to be uninstalled once before 0.2.0 installs.
- APK names `u-tubot_<version>_<abi>.apk` (arm64-v8a, armeabi-v7a, x86, universal). `utubot app publish` takes several APKs, writes
  `downloadUrlList_<abi>` keys, `latest.json` and stable `/app/latest/<abi>.apk` redirects; the landing page shows the downloads.
- CI: `utubot-release.yml` builds and publishes release APKs on `utubot-v*` tags; inherited Electric Eel workflows are guarded to
  run only in their own repository.
- Removed deployment-specific hosts, paths and gateway scripts from the tree; user documentation added under `docs/`.

## 2026-11-12 (integration and first deployment)

- Merged the app and backend branches into `feat/ai-layer`.
- Backend deployed behind a hardened systemd unit; verified health, auth, prompt sets and a real HQ caption job (yt-dlp,
  faster-whisper small int8, VTT served). Published APK 0.1.0 (debug-signed) with `/app/update.json` in Electric Eel's format.

## 2026-11-12 (completion pass)

- Verified the flavor, settings, pairing, assess hook, menu, panel and captions against the requirements.
- Captions are fetched with the `Authorization` header (host-scoped) instead of `?token=`; `UtubotClient.captionUrl` is token-free,
  new `authorizationFor`.
- Added `UtubotBackendE2eTest` and ran it against the real backend with a mock LLM; unit tests green.
- `ai/CONTRACT.md` now carries the pairing, `/app` and admin addendum; wrote `ai/APP_INTEGRATION.md`.

## 2026-11-12 (first implementation)

- Wire contract v1, the `stutubot` product flavor with BuildConfig defaults, client, settings, assess hook (HiddenVideoResolver and
  VideoGroup), context menu items.
- Renamed the layer to u-tubot, added pairing (6-digit dialog, first-launch prompt).
- Summary side panel and HQ captions in the player.
