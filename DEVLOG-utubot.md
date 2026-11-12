# u·tubot devlog

## 2026-11-12 (audio when captions are limited)

- Backend only: when YouTube limits the caption API the audio is transcribed instead of answering "delayed" (policy permitting), the
  caption class is probed by one background request after a cooldown, plus review follow-ups of the engine chain and the yt-dlp runtime
  option. Details in `ai-backend/DEVLOG.md`, `docs/server.md`, `docs/captions.md`, `ai/CONTRACT.md`.

## 2026-11-12 (app review follow-ups)

Findings of the review of PR 20 (app round 1), each with a unit test.

- Caches: `UtubotManager` kept the prompt list for the session (`mPrompts`) and the summaries, verdicts and captions of the backend it
  was loaded from. `UtubotSettings` now notifies a connection listener when `setUrl` or `setToken` really changes a value, which
  covers `applySetup`, `setUrlManually` and the pairing at one place; the manager drops everything, the session prompt included
  (a key of another backend's list). Choose default, Import and Refresh drop the prompt list themselves (also when they fail: the
  backend may have changed before the error), which covers the pending prompt sets of `UtubotSetupFlow.importPendingPromptSets` too.
  A summary, verdict, prompt list or caption list that arrives after a switch is not stored (`isCurrent` compares the client's
  backend and token with the settings'): `UtubotConnectionCacheTest` holds a request open across a token change.
- Security: `authorizationFor` compared `startsWith(baseUrl)`; `https://u.example.com.evil.net/x` got the token. It parses both with
  OkHttp `HttpUrl` and compares scheme, host and port, and requires the path to be under the backend's path by whole segments (a dot
  segment can't climb out).
- Updates: an update found while the player was open was dropped by `showUpdateDialog` and the schedule had counted the check as
  done (6 hours). `AppUpdatePresenter` now reports it (`UtubotUpdates.onUpdateDeferred`), the schedule retries in 5 minutes and
  `UtubotAppHooks` brings the retry forward to 5 seconds after a non-player screen resumes. `check()` still refuses to start
  during playback or over a dialog, so nothing is prompted while playing and a long film causes no repeated downloads.
- `SharedModules` `appupdatechecker2` (read at the pinned checkout): `AppVersionChecker` reads `downloadUrl*` as plain `Uri`s,
  `AppDownloader` only tests `URLUtil.isValidUrl` (accepts http, file, content, ...) and fetches with OkHttp; neither looks at the
  scheme or host. `UtubotUpdateChecker` overrides `onChangelogReceived` and passes on only https or private-host http addresses
  (judged by OkHttp's own parse of the string, so a parser difference can't let a different host through).
- Settings: `setUrlManually("")` removed the token but left `update_url`, so the old server kept being checked.
- Panel: with the Summary view open, `UtubotPanelController.handleKey` restored the view's focus only for the D-pad; OK/Enter went
  to the card under the view whenever the grid had the focus (the restore is posted, so a key can land first). Select keys
  (`UtubotKeys.isSelectKey`) are used there as well, and the rest of that press is swallowed.
- Installer label (owner's TV: "App installed" showed `com.liskovsoft.smartyoutubetv2.tv.ui.main.MainAp…` and the generic icon during a
  self-update). The manifest was not missing anything: `<application>` has `label`, `icon`, `banner` and `logo` in main and `aapt2 dump
  badging` of every published APK (0.2.0 to 0.3.0) and of this branch's debug APK shows `application-label:'u·tubot'` and
  `application-icon-*`. That class name is `ApplicationInfo.loadLabel`'s last fallback, taken when the label resource can't be resolved,
  i.e. an installer reading the package file without its resources. The label is now a literal in `src/stutubot/AndroidManifest.xml`
  (the first thing `loadLabel` returns, no resources needed). The icon is always a resource, so the generic icon in such an
  installer is not something the app can change. Not verified on the TV (no device here); to check it: update from a build
  without the literal and look at `adb shell dumpsys package dev.utubot.tv | grep -iE "labelRes|nonLocalizedLabel|icon="` and the
  installer's log for "Failure retrieving text".
- `UtubotBadgeController` (the value of a `WeakHashMap<Activity, ...>` in `UtubotAppHooks`) held its activity and its badge view
  (which holds the activity as its context) strongly; both are weak references now. `mReturnFocus` was already a weak reference and
  is cleared in `closeOverlay`.


## 2026-11-12 (fast transcripts)

- Backend only (no app change): videos without captions are transcribed automatically under the per-user policy (`auto_transcribe`),
  by an engine chain with chunked parallel ASR, the original-language audio track and per-class YouTube breakers (issue #19). Details in
  `ai-backend/DEVLOG.md`, `docs/captions.md`, `docs/server.md`, `ai/CONTRACT.md`.

## 2026-11-12 (R4: phone web UI)

- Backend only (no app change, so no automatic release): the web UI at `/` was rebuilt as a phone-first control page with
  password sign-in, per-user settings (`/v1/me/settings`), a live model list, status, jobs control and user admin. Details in
  `ai-backend/DEVLOG.md`, usage in `docs/server.md` (Web UI, Per-user settings), wire in `ai/CONTRACT.md`. Screenshots under
  `docs/screenshots/webui/`. The TV will read the pushed settings in a later release; R5 adds the enrollment link and QR.

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
