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

### Releasing

1. Bump `versionName`/`versionCode` of the `stutubot` flavor in `smarttubetv/build.gradle` and add a `CHANGELOG.md` section.
2. Tag and push: `git tag utubot-v0.2.2 && git push origin utubot-v0.2.1`. The workflow `.github/workflows/utubot-release.yml` builds the
   per-ABI APKs and creates the GitHub Release with `SHA256SUMS`. Secrets needed: `UTUBOT_KEYSTORE_B64` (`base64 -w0` of the keystore),
   `UTUBOT_KEYSTORE_PASSWORD`, `UTUBOT_KEY_ALIAS`, `UTUBOT_KEY_PASSWORD`. For a private repository change `runs-on` to your own runner label.
3. Publish to your server: `utubot app publish ...` ([server.md](server.md)).

The workflow checks out `SharedModules` and `MediaServiceCore` at the commits in its `env:`; update them when you merge the base app.

## Merging upstream

`master` mirrors Electric Eel; work lands on `feat/ai-layer`.

```sh
git fetch electriceel
git checkout master && git merge electriceel/master
git checkout feat/ai-layer && git merge master
```

Conflicts can only be in the files listed in [../ai/APP_INTEGRATION.md](../ai/APP_INTEGRATION.md): re-apply the small hooks (grep
`Utubot`). Inherited workflows are guarded with `if: github.repository == 'cygnusx-1-org/electriceel'` so they stay inert here.
After a merge, update the sibling checkouts and the pinned SHAs in the release workflow, run the unit tests, build both the
`stutubot` and an Electric Eel flavor, and note the change in `DEVLOG-utubot.md`.
