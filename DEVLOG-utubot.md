# u·tubot devlog

## 2026-11-12 (app round 1: passive panel, Summary view, transcripts, auto-update)

- Real-TV report (0.2.0, Modern skin): the screen dimmed, no grid, the panel over the top bar. Reproduced on an Android TV 14 emulator
  with the 0.2.2 release and then with this branch; evidence in `docs/screenshots/r1/` (`before-*`).
  - Dim: Electric Eel's own screensaver (`ScreensaverManager`: 60 s without a key press dims to 80%). The old panel consumed keys
    before `MotherActivity` could end the dimming (a Back that went back to the grid left the screen dark), and the focus inside its
    Spinner's popup window never reached the activity at all. Used keys now end the dimming (`UtubotPanelController.dispatchKeyEvent`).
  - Panel: a full-height strip over the top bar with a focusable Spinner and ScrollView, never hidden when the focus left the cards, so
    it stayed up over other sections and empty pages. Replaced by a passive corner card below the top bar that follows the focus.
  - Empty grid (the dump with `modern_browse_content` without children): not the panel. `UtubotManager.resolve`, zipped into
    `HiddenVideoResolver`, finished on the io thread of its last assess call, and `BrowsePresenter` showed the rows from there: the
    adapters of the grids were changed off the UI thread. With the main thread inside a layout this throws ("Cannot call this
    method while RecyclerView is computing a layout or scrolling", logged as `updateRowsHeader error`, with the stack of the io thread
    captured on the emulator) and cancels the load. The grid then has no visible rows: `ModernBrowseFragment` fades the first rows in
    (`setAlpha(0f)` and an animation) from that same thread, and `uiautomator` leaves out what isn't visible, which is how the dump
    showed `modern_browse_content` without children (the alpha itself was not measured). 3 of 12 cold starts of the Modern skin showed an
    empty screen and logged the error without the fix, 0 of 12 with it. The resolver now emits on the main thread
    (`UtubotAssessFlowTest` fails on the io thread).
- Panel timing: `FocusDebouncer` (every focus change or D-pad key starts the pause again, default 1.8 s, Settings 1/1.8/3/5 s),
  `PanelCoordinator` (when it is up: only for a card of the list, hidden for anything else, a card that goes away, pause, the view),
  `RequestGeneration` (answers for a card or prompt that was left are dropped). First Back hides the panel and keeps the focus.
- A bug found on the emulator: after Back closed the Summary view the focus went back to the card but the panel never returned:
  the framework refocused the card while the view closed, and the later `requestFocus` of the same card gave no focus event. The
  controller looks at the focus once the view is gone.
- Summary view (Info, or "u·tubot summary" in the menu; Menu stays the video menu): prompts left (400 ms rest, OK keeps the prompt),
  text right (page scrolling), title, source, indicator and Retry on top; the AI answer uses it too.
- Transcript states, coded against the backend branch `fix/youtube-pacing` and tolerant of its absence: `needs_transcript`,
  `delayed` (retry after `retry_after_s`, bounded 1 s to 10 min, only while the card or view is shown), `transcribing` (progress polls
  every 4 s). The manager caches only `ready` summaries (a test fails if a transient state is kept).
- Auto-update: `UtubotUpdateSchedule` (20 s after the start, then 6 h, 5 min retry when a check can't happen), the stored `update_url`
  or `<backend>/app/update.json` derived at read time for installs that typed their backend on 0.2.0. `UtubotUpdateManifestTest`
  parses the real manifest shape (`downloadUrlList_<abi>` wins over `downloadUrlList`). On the emulator the automatic check
  (30 s after the start) and "Check for updates" both opened the update dialog from the mock's `/app/update.json`; Install update
  reached the system installer.
- Verified on the emulator in the Classic and Modern skins: cold start, panel waiting/loading/ready, no panel on the sidebar,
  after a section switch and during the player, Back, Info view, transcript and delayed states, Settings. The mock backend is
  `scripts/emulator_mock_backend.py` (`docs/development.md`).

## 2026-11-12 (continuous delivery)

- CI: `utubot-ci.yml` (named apart from the inherited `CI.yml`, which differs only by case) tests the backend (ruff, pytest) and the
  app (`:common:testStutubotDebugUnitTest`, TV module compile) only when their files changed; one run with a conclusion per commit.
- Releases: a merge to `main` that touches the app (compared with the newest `utubot-v*` tag) starts `utubot-release.yml` after the
  app tests pass. Version `<utubot.version>.<next patch>`, `versionCode = major * 1000000 + minor * 1000 + patch` derived in
  `smarttubetv/build.gradle` (a run counter would differ between the automatic and the tag path). The release carries APKs,
  `SHA256SUMS`, `release.json` and notes from `## Unreleased` (new lines only) or the commit log. Manual `utubot-vX.Y.Z` tags still work.
- Backend: `utubot app sync-github` publishes the newest release into the update channel after SHA-256 and signing-certificate
  checks (`apksigner`, or a built-in v2/v3 reader when `apksigner_path` is unset) against `[app] signing_cert_sha256`; idempotent; optional `keep_versions`. Releases without `release.json` (0.2.x) are read
  from file names and `SHA256SUMS`. Scripts: `scripts/utubot_release.py`, tests in `ai-backend/tests`.

## 2026-11-12 (0.2.2: review fixes)

- Manual backend URLs go through `UtubotSetup.requireUrl`; the update URL is derived by URI resolution (origin + path + `/app/update.json`).
- `setUrlManually` clears the token and pairing flag when the origin changes. The import log omits the query. `applySetup` returns
  whether pairing is needed; re-importing on a paired device no longer opens the dialog. Version 0.2.2 (code 4).

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
