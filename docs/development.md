# Development

## Layout

```
ai-backend/   Python backend (own README, AGENTS.md, tests)
ai/           CONTRACT.md (wire contract, setup file), APP_INTEGRATION.md (touched upstream files), FORK_SURVEY.md
common/       Android library; AI code in .../common/utubot/
smarttubetv/  Android app; panel code in .../tv/utubot/
docs/         user documentation
assets/brand/ SVG sources of the symbol, banner and wordmark; render.py makes the PNGs
```

The rest is Electric Eel (a fork of SmartTube). Keep AI code in the `utubot` packages and hooks in upstream files small; every
hook is listed in [../ai/APP_INTEGRATION.md](../ai/APP_INTEGRATION.md).

## Backend

```sh
cd ai-backend
uv sync                              # --extra asr / --extra diarization are optional
uv run pytest -q && uv run ruff check && uv run ruff format --check
uv run utubot serve
```

Tests use an in-process mock OpenAI-compatible server (`tests/mock_openai.py`) and a fake transcript fetcher; no network. HQ caption
tests call `ffmpeg`. Rules for contributors are in `ai-backend/AGENTS.md` (tunables in `config.py` and `config.example.toml`,
contract changes together with `ai/CONTRACT.md`).

### Offline mode: a backend that never reaches YouTube

Tests, the emulator and E2E runs must not touch YouTube (owner rule, `AGENTS.md`). The real backend has an offline dev-proxy mode for
that: every request to YouTube is refused before it is made, and answers come from what the server has locally — cached transcripts
and metadata, and recorded fixtures ("cassettes", `ai-backend/fixtures/youtube/`).

```sh
cd ai-backend
UTUBOT_CONFIG=config.dev.toml uv run utubot serve      # config.dev.toml: [youtube] offline = true
```

A minimal dev config only needs its own data dir and the flag:

```toml
[server]
data_dir = "temp/dev-data"

[youtube]
offline = true
```

Recorded fixtures replay real YouTube answers (yt-dlp metadata, the caption track) without the network. `utubot_demo.json` is a
hand-written demo cassette; the owner records real ones — the one command that reaches YouTube, run by hand only:

```sh
uv run utubot youtube-record VIDEO_ID [--lang en] [--note "why this video"]
```

Cassettes carry no URLs at all (signed tokens can hide in URL paths too): the recorder replaces every URL with a `<url>` placeholder
before writing, and `test_youtube_fixtures.py` checks every committed cassette for URL, signature and cookie text. An offline miss is
not remembered as a failure: record the cassette (or turn offline off) and the video is fetched normally again. Point the emulator or
the E2E run at this backend instead of `scripts/emulator_mock_backend.py` when you want the real routes;
the mock script stays the lighter stand-in for panel checks.

The web UI (`ai-backend/src/utubot/web/`) is plain HTML, CSS and ES modules served as they are: edit, reload, no build. To look at it
without a real LLM or YouTube, run `uv run python tests/webui_demo.py temp/webui-demo` (mock LLM, canned data, owner password in
its first output line) and, for the screenshots in `docs/screenshots/webui/`,
`NODE_PATH=<dir with playwright> node docs/screenshots/webui/capture.cjs http://127.0.0.1:8791 docs/screenshots/webui`
(Playwright with Chromium; the script also fails on console errors and sideways scrolling at 360 px).

## Android app

Needs JDK 25, the Android SDK (platform 37, build-tools 30.0.3, NDK 30.0.16248370) and two sibling checkouts next to this repository:

```
parent/
  u-tubot/          this repository
  SharedModules/    https://github.com/cygnusx-1-org/SharedModules   (CI pins the commit)
  MediaServiceCore/ https://github.com/cygnusx-1-org/MediaServiceCore
```

```sh
export JAVA_HOME=/path/to/jdk-25 ANDROID_HOME=/path/to/android-sdk
./gradlew :common:testStutubotDebugUnitTest :smarttubetv:assembleStutubotDebug
```

Debug APKs: `smarttubetv/build/outputs/apk/stutubot/debug/u-tubot_<version>_<abi>.apk`. The flavor is `stutubot`, application id
`dev.utubot.tv`. Other flavors (`stbeta`, `ststable`) are Electric Eel's and must keep working.

An end-to-end test (`UtubotBackendE2eTest`) runs against a real backend when `UTUBOT_E2E_URL` and `UTUBOT_E2E_CODE` are set. Run that
backend in offline mode (above) so the E2E run cannot reach YouTube either; unknown videos then answer `offline` instead of a fetch.

### Checking the TV app on an emulator

The panel, the Summary view and the updates are checked on an Android TV emulator (`-no-window -no-audio -memory 2048 -cores 2`) with
`scripts/emulator_mock_backend.py`, which stands in for the backend (summaries in every state, transcripts, `/app/update.json`). Its
`/__mock/set` URL picks the state, including the server's own wording (`message`, `estimate`, `retry_after`) and `auto_transcribe`, the
automatic policy that starts a transcription itself (see the script's header).
Unit tests cover the logic (`UtubotPanelModelTest`, `PanelCoordinatorTest`, `UtubotPanelControllerTest`, ...); the emulator shows what
they can't: the real skins, focus and the framework's own refocusing.

```sh
python3 scripts/emulator_mock_backend.py --port 18790 --static temp/update &    # temp/ is ignored by git
adb -s emulator-5554 install -r smarttubetv/build/outputs/apk/stutubot/debug/u-tubot_<ver>_x86.apk
adb -s emulator-5554 shell run-as dev.utubot.tv sh -c 'cat > shared_prefs/utubot_settings.xml' < prefs.xml   # url, token, summary_panel
adb -s emulator-5554 shell input keyevent KEYCODE_INFO                                                      # D-pad and Info
adb -s emulator-5554 exec-out screencap -p > shot.png ; adb -s emulator-5554 shell uiautomator dump
```

`prefs.xml` is the `utubot_settings` preference file: `url` (`http://10.0.2.2:18790`), `token`, `summary_panel` true. Use `-s emulator-5554`
on every `adb` call. Skins: *Settings, User interface, Skins*; check Classic and Modern. `uiautomator dump` leaves out views that are
not visible to the user, which is how an invisible grid shows: `modern_browse_content` without children.
For an update, serve an `update.json` with a higher version (`downloadUrlList_x86` next to `downloadUrlList`) and an APK built with
`-PutubotVersionName=0.9.0`.

### Checking the HQ captions

No test or check may contact YouTube. The app's own screens play YouTube videos only, so debug builds of the `stutubot` flavor include
`CaptionsHarnessActivity` (`smarttubetv/src/stutubotDebug`): it plays a media file through the real player controller with the app's
subtitle view and lists the subtitle formats on screen (Up and Down pick the previous and the next one, like the subtitle menu). The mock
backend serves the files: `--media DIR` (a local stream, with byte ranges), `--vtt FILE` (the captions), and
`/__mock/captions?video=ID&state=none|queued|running|ready|failed[&after=SECONDS][&latency=SECONDS]` sets the state of a video's captions.

```sh
ffmpeg -f lavfi -i testsrc=size=640x360:rate=25 -f lavfi -i sine=frequency=440 -t 240 -c:v libx264 -pix_fmt yuv420p -c:a aac -movflags +faststart temp/media/test.mp4
# Keep the emulator away from the internet: one network namespace with only a loopback, its own adb server on another port
unshare -n sleep 14400 &  NS="nsenter -t $! -n"   # (pid of the sleep: pgrep -n -x sleep)
$NS ip link set lo up
$NS python3 scripts/emulator_mock_backend.py --port 18790 --vtt temp/captions.vtt --media temp/media &
$NS emulator -avd tv -port 5554 -no-window -no-audio -memory 2048 -cores 2 &
ADB="$NS adb -P 5038 -s emulator-5554"      # never the shared adb server on 5037
$ADB install -r smarttubetv/build/outputs/apk/stutubot/debug/u-tubot_<ver>_x86.apk       # prefs as above (url, token)
$NS curl "localhost:18790/__mock/captions?video=harnessCapA&state=running&after=25"        # a job that finishes while it plays
$ADB shell am start -n dev.utubot.tv/com.liskovsoft.smartyoutubetv2.tv.utubot.harness.CaptionsHarnessActivity \
    --es video_id harnessCapA --es url http://10.0.2.2:18790/media/test.mp4
```

After the first run the captions are in the app's storage (`files/utubot_captions`): stop the mock, copy the MP4 into the app's files
(`run-as dev.utubot.tv cp`) and start the harness with a `file:///data/data/dev.utubot.tv/files/test.mp4` url to see them offered
without a backend. Screenshots of such a run: `docs/screenshots/captions/`. The harness is not the app's screens: the saved subtitle
choice is applied by `VideoStateController`, which only the unit tests (`UtubotCaptionsRestoreTest`) run.

### Private builds with a baked backend

A build for your own devices may carry defaults: `-PutubotUrl=https://utubot.example.com -PutubotToken=...` or a gitignored
`utubot.properties` (`utubotUrl=`, `utubotToken=`). The published releases carry none.

### Release build and signing

```sh
export UTUBOT_KEYSTORE=/path/utubot-release.jks UTUBOT_KEYSTORE_PASSWORD=... UTUBOT_KEY_ALIAS=utubot UTUBOT_KEY_PASSWORD=...
./gradlew :smarttubetv:assembleStutubotRelease
```

or put `storeFile`, `storePassword`, `keyAlias`, `keyPassword` in a gitignored `keystore.properties` at the repo root. Without
them the release build stops with an explanation. Create a key once and keep it safe: apps signed with another key cannot
update the installed one.

```sh
keytool -genkeypair -keystore utubot-release.jks -storetype PKCS12 -alias utubot -keyalg RSA -keysize 4096 -validity 10950
```

Verify: `apksigner verify --print-certs u-tubot_0.2.0_arm64-v8a.apk` (compare the SHA-256 digest with the one in the release notes).

### Versions

`versionName` is `<major>.<minor>.<patch>`. `major.minor` (the series) is the only line in `utubot.version` at the repository root;
change it by hand to start a new series. `patch` is a counter: the release workflow takes the highest patch of the series among the
existing `utubot-v<series>.*` tags plus one (the first release of a series is `.0`) and refuses a series that would not be newer
than every existing release.

`versionCode` is derived from the name, so it grows with it and never depends on a run counter or on which path made the release:

```
versionCode = major * 1000000 + minor * 1000 + patch        (0.3.7 -> 3007; 0.2.2 shipped as 4, every later series is above it)
```

The `stutubot` flavor in `smarttubetv/build.gradle` reads `UTUBOT_VERSION_NAME` (or `-PutubotVersionName`) and derives the code;
`UTUBOT_VERSION_CODE` / `-PutubotVersionCode` override it. A local build without a name is `<series>.0-dev`. Patch stays below
1000 and minor below 1000 so the order holds.

### CI

`.github/workflows/utubot-ci.yml` runs on every pull request and every push to `main` and always ends with a conclusion (a
deployment can wait for the green commit). A first job lists the changed files through the GitHub API:

- the **backend** job (installs `ffmpeg`, then `uv sync --frozen`, `ruff check`, `ruff format --check`, `pytest -q`) runs when `ai-backend/`, `ai/`, `docs/`
  or `scripts/utubot_release.py` changed;
- the **app** job (`:common:testStutubotDebugUnitTest` and a compile of the TV module, with the pinned sibling checkouts, JDK 25
  and the Gradle cache) runs when anything outside the documentation, backend, scripts and `.github/` changed;
- skipped jobs count as passed.

The sibling commits are pinned in `.github/actions/android-env/action.yml`, shared by CI and the release workflow.

### Releasing

Merging a change that touches the app to `main` releases it automatically: after the app tests pass (and the backend
tests, when they ran, did not fail), CI starts `.github/workflows/utubot-release.yml` for that commit. "Touches the app" is decided against the newest `utubot-v*` tag, so an
earlier push whose release failed or was cancelled is picked up by the next push. Documentation, backend, `scripts/` and
`.github/` changes alone never release.

The release workflow resolves the next version, builds the signed per-ABI APKs, writes `release.json` and `SHA256SUMS`,
creates the tag `utubot-v<version>` on the commit and the GitHub Release. Only one release runs at a time.

- **Notes**: the lines of the `## Unreleased` section of `CHANGELOG.md` that the previous release's notes do not already contain;
  without any, the commit subjects since the previous tag (merge commits left out). Write user-facing bullets under `## Unreleased`
  in your pull request; rename the section to the version when you start a new series. Notes can never fail a release.
- **`release.json`**: `version_name`, `version_code`, `abis`, `files` (name, SHA-256, size per ABI), `changelog`,
  `signing_cert_sha256`. A backend reads it with `utubot app sync-github` ([server.md](server.md#updates)).
- **By hand**: push a tag `utubot-vX.Y.Z` (or run the workflow with the input `tag`) to build and publish exactly that version; the
  Gradle build gets the name from the tag, the unit tests run first, and the numbers must agree with the APKs or the release stops.
  The tag must be the newest `utubot-v*` tag, its release must not exist yet, its commit must be on `main` and CI must have finished green
  for it, so a hand release can neither go backwards nor skip the tests.
- **Guards, every path**: the commit is on `main` and its CI run is green (the app tests, and the backend tests when they ran: a red
  backend blocks the automatic release too, because the app and the backend are one contract and a red commit is never deployed).
- **Check on the server**: `utubot app sync-github` also reads each APK's own manifest and refuses a package other than `dev.utubot.tv`
  or a version that differs from `release.json`.
- Secrets needed: `UTUBOT_KEYSTORE_B64` (`base64 -w0` of the keystore), `UTUBOT_KEYSTORE_PASSWORD`, `UTUBOT_KEY_ALIAS`,
  `UTUBOT_KEY_PASSWORD`. The automatic path is guarded to this repository (`github.repository` in the CI workflow); for a fork or a
  private repository change that guard and the `runs-on` label.
- Publish to your server with `utubot app sync-github` or by hand with `utubot app publish` ([server.md](server.md#updates)).

Everything in `main` that CI accepts is shipped, so protect `main` (pull requests, required `u-tubot CI` checks).

The workflows check out `SharedModules` and `MediaServiceCore` at the commits pinned in `.github/actions/android-env/action.yml`;
update them when you merge the base app.

## Brand assets

The symbol (a play triangle holding a lowercase u, with the interpunct as a lime ball on its tip), the banner and the wordmark are SVGs in
`assets/brand/` with three flat colors (indigo `#4B3FE0`, white, lime `#C8F23A`; `#0F1124` behind the banner) and no fonts: the wordmark is
drawn with paths. `uv run assets/brand/render.py` renders them to the PNGs of the `stutubot` flavor (`smarttubetv/src/stutubot/res/mipmap-nodpi/`:
`app_icon`, `app_icon_alt`, `app_banner`, `app_logo`, `app_logo_semi_red`, `app_logo_semi_grey`) and to the previews in `assets/brand/png/`.
It also cuts the Settings tile icon `common/src/main/res/drawable-nodpi/settings_utubot.png` (white on transparent) from `utubot-symbol-mono.svg`
and fits it into the canvas and padding of `settings_about.png`.
It needs the cairo library (`apt install libcairo2`). Edit the SVGs, render, commit both.

## Merging upstream

`master` mirrors Electric Eel; `main` is the default branch and work lands on it through pull requests.

```sh
git fetch electriceel
git checkout master && git merge electriceel/master
git checkout -b feat/sync-electriceel origin/main && git merge master   # then open a PR
```

Conflicts can only be in the files listed in [../ai/APP_INTEGRATION.md](../ai/APP_INTEGRATION.md): re-apply the small hooks (grep
`Utubot`). Inherited workflows are guarded with `if: github.repository == 'cygnusx-1-org/electriceel'` so they stay inert here.
After a merge, update the sibling checkouts and the pinned SHAs in `.github/actions/android-env/action.yml`, run the unit tests, build both the
`stutubot` and an Electric Eel flavor, and note the change in `DEVLOG-utubot.md`.
