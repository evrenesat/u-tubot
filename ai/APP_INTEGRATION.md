# u·tubot app integration

u·tubot is an AI layer on the Electric Eel fork of SmartTube. It ships as the product flavor `stutubot`
(`applicationId dev.utubot.tv`, label "u·tubot", installs beside Electric Eel). Wire contract: `ai/CONTRACT.md`.

All new code lives in `common/.../common/utubot/` and `smarttubetv/.../tv/utubot/`. Upstream files only carry small hooks,
listed below. Every hook is gated by `UtubotSettings.isBuiltIn()` (`BuildConfig.UTUBOT_ENABLED`, true only in `stutubot`),
so the other flavors behave as before.

## Touched upstream files

| File | Change | Why |
|---|---|---|
| `common/build.gradle` | `stutubot` flavor, `UTUBOT_ENABLED/URL/TOKEN` BuildConfig fields (empty by default), `utubot.properties` reader | optional build-time defaults |
| `leanbackassistant/build.gradle` | `stutubot` flavor with `matchingFallbacks` | module variant matching |
| `smarttubetv/build.gradle` | `stutubot` flavor, applicationId, version, release signing from `UTUBOT_KEYSTORE*` or `keystore.properties`, APK name `u-tubot_<ver>_<abi>.apk` | side-by-side install, signed releases |
| `common/src/stutubot/res/values/update_urls.xml` | empty `update_urls` array | no built-in update source: the stored `update_url` of the imported setup is used |
| `app/presenters/dialogs/AppUpdatePresenter.java` | `getUpdateUrls()`: stored setup URL for the built-in flavor, none means no check | self-update from the user's own backend |
| `smarttubetv/src/stutubot/res/` | app label and icons | branding |
| `.gitignore` | `utubot.properties`, `temp/` | local secrets and scratch |
| `app/models/data/Video.java` | `utubotMark` field (copied in `copy`) | label of the card mark |
| `app/models/data/VideoGroup.java` | `isHiddenByUtubot` in the add-filter chain | hides or marks a card from the cached verdict |
| `misc/HiddenVideoResolver.java` | `UtubotManager.resolve(...)` zipped into the existing resolve | one assess call per row emission, bounded by wait_ms and a hard timeout; failures show the videos unfiltered |
| `app/presenters/SplashPresenter.java` | `UtubotPairing.promptIfNeeded` | first-launch pairing dialog when no token |
| `app/presenters/dialogs/menu/VideoMenuPresenter.java` | `UtubotMenu.append` (two places) | AI answer, Summary panel toggle, Prepare HQ captions |
| `misc/AppDataSourceManager.java` | Settings entry "u·tubot" | settings screen |
| `utils/SimpleEditDialog.java` | `showNumber` | numeric pairing code dialog |
| `exoplayer/controller/ExoPlayerController.java` | captions prefetch in `setVideo`, `attachUtubotCaptions` on source change, `selectUtubotCaptions` | HQ caption tracks, auto-select |
| `exoplayer/selector/TrackSelectorUtil.java` | track name lookup | "u·tubot: label" in the subtitle picker |
| `tv/presenter/VideoCardPresenter.java` | mark with own colour, `addMark` overload, card tag | mark rendering, panel reads the focused card |
| `tv/ui/modern/widgets/ModernVideoCard.java` | card tag | panel reads the focused card |
| `tv/ui/common/LeanbackActivity.java` | `UtubotPanelController` (key dispatch, resume) | Summary side panel (not in the player activity) |

## Behaviour

- Settings, always in this order: Import setup, Pair with code (6 digits, `POST /v1/pair`, token stored, connection tested,
  then "Paired as <user>"), assess switch, mark only, answer in menu, Summary panel, auto-select HQ captions, Prompts (list,
  choose default, Import from URL, Refresh all), Test connection, Advanced (backend URL and token by hand; a typed backend
  also sets `<backend>/app/update.json` when no update URL is stored). `UtubotSettingsPresenter.buildCategories` is the list.
- Import setup (`UtubotSetup`, `UtubotSetupFlow`): the user types a bare host or a URL, the app fetches `/setup.json`
  (`ai/CONTRACT.md`), stores backend URL, update URL and switch defaults, then opens the pairing dialog.
- Every launch without a backend offers Import setup (Not now / Don't ask again); pairing follows. With a backend but no
  token the pairing dialog is offered the same way. Import errors are mapped to a reason (`UtubotSetupFlow.describeError`);
  every step is logged with tag `Utubot`. `SimpleEditDialog` submits on OK and on the keyboard's Go/Done/Next/Send/Search
  action; Back with the keyboard up only hides it.
- Assess failures, timeouts and pending verdicts leave cards unfiltered. Marks use their own colour (`UtubotPolicy.MARK_COLOR`).
- Summary panel: right side, 35% width, 700 ms focus debounce, prompt selector, status line, polling while pending.
  RIGHT from the grid edge enters the panel, BACK or LEFT returns. It is hidden while the player is open.
- HQ captions: fetched with the `Authorization` header (never `?token=`); the header is only sent to the backend host.

## update.json (self-update)

The flavor has no update URL of its own: `AppUpdatePresenter` uses the `update_url` stored by Import setup
(`UtubotSettings.getUpdateUrl`), and checks nothing without one. The checker (`SharedModules` `appupdatechecker2`,
`AppVersionChecker`) reads the same shape as `updates/electriceel_stable.json`:

```json
{
  "package": {
    "downloadUrlList_arm64-v8a": ["https://utubot.example.com/app/u-tubot_0.2.0_arm64-v8a.apk"],
    "downloadUrlList_armeabi-v7a": ["https://utubot.example.com/app/u-tubot_0.2.0_armeabi-v7a.apk"],
    "downloadUrlList": ["https://utubot.example.com/app/u-tubot_0.2.0_universal.apk"]
  },
  "0.2.0": {"versionCode": 2, "changelog": ["First signed release"]}
}
```

`downloadUrlList_<abi>` (the device's primary ABI from `DeviceHelpers.getPrimaryAbi`) wins over `downloadUrlList`. The newest
key by version-name comparison is the latest; the app compares it with its own version name. The downloaded APK must carry the
package `dev.utubot.tv` and the same signing key, otherwise Android refuses it. The backend writes the file with
`utubot app publish APK... --version-name V --version-code N --changelog TEXT`. Bump `versionName`/`versionCode` in
`smarttubetv/build.gradle` before releasing.

## Merging upstream

1. Merge Electric Eel into `master`, then `master` into `feat/ai-app`.
2. Conflicts appear only in the files above. Re-apply the hooks, they are one to a few lines each (grep `Utubot`/`utubot`).
3. Run the unit tests and build both flavors: the layer must not change other flavors.

## Build

```
export JAVA_HOME=/path/to/jdk-25
./gradlew :smarttubetv:assembleStutubotDebug                       # universal and per-ABI debug APKs
./gradlew :common:testStutubotDebugUnitTest --tests '*utubot*'     # u-tubot unit tests
./gradlew :smarttubetv:assembleStutubotRelease                     # signed release APKs, needs the signing variables
```

A private build can bake an address with `-PutubotUrl=https://host -PutubotToken=utb_...` or the gitignored
`utubot.properties` at the repo root (`utubotUrl=`, `utubotToken=`). Both default to empty.

## End-to-end test without a device

`UtubotBackendE2eTest` (skipped unless `UTUBOT_E2E_URL` and `UTUBOT_E2E_CODE` are set) pairs with a running backend and
exercises me, assess, verdict mapping, prompts, summary and captions through the Java client. Run the real backend
(`utubot serve`) with a config whose LLM `base_url` points at a mock OpenAI server, and create the code with `utubot user pair owner`.
