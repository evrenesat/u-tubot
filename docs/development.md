# Development

## Layout

```
ai-backend/   Python backend (own README, AGENTS.md, tests)
ai/           CONTRACT.md (wire contract, setup file), APP_INTEGRATION.md (touched upstream files), FORK_SURVEY.md
common/       Android library; AI code in .../common/utubot/
smarttubetv/  Android app; panel code in .../tv/utubot/
docs/         user documentation
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

An end-to-end test (`UtubotBackendE2eTest`) runs against a real backend when `UTUBOT_E2E_URL` and `UTUBOT_E2E_CODE` are set.

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

Merging a change that touches the app to `main` releases it automatically: after the app tests pass, CI starts
`.github/workflows/utubot-release.yml` for that commit. "Touches the app" is decided against the newest `utubot-v*` tag, so an
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
- Secrets needed: `UTUBOT_KEYSTORE_B64` (`base64 -w0` of the keystore), `UTUBOT_KEYSTORE_PASSWORD`, `UTUBOT_KEY_ALIAS`,
  `UTUBOT_KEY_PASSWORD`. The automatic path is guarded to this repository (`github.repository` in the CI workflow); for a fork or a
  private repository change that guard and the `runs-on` label.
- Publish to your server with `utubot app sync-github` or by hand with `utubot app publish` ([server.md](server.md#updates)).

Everything in `main` that CI accepts is shipped, so protect `main` (pull requests, required `u-tubot CI` checks).

The workflows check out `SharedModules` and `MediaServiceCore` at the commits pinned in `.github/actions/android-env/action.yml`;
update them when you merge the base app.

## Merging upstream

`master` mirrors Electric Eel; work lands on `feat/ai-layer`.

```sh
git fetch electriceel
git checkout master && git merge electriceel/master
git checkout feat/ai-layer && git merge master
```

Conflicts can only be in the files listed in [../ai/APP_INTEGRATION.md](../ai/APP_INTEGRATION.md): re-apply the small hooks (grep
`Utubot`). Inherited workflows are guarded with `if: github.repository == 'cygnusx-1-org/electriceel'` so they stay inert here.
After a merge, update the sibling checkouts and the pinned SHAs in `.github/actions/android-env/action.yml`, run the unit tests, build both the
`stutubot` and an Electric Eel flavor, and note the change in `DEVLOG-utubot.md`.
