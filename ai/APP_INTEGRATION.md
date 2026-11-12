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
| `app/presenters/dialogs/AppUpdatePresenter.java` | `getUpdateUrls()`: stored setup URL (or the one derived from the backend) for the built-in flavor, none means no check; the update dialog always opens for the built-in flavor; `UtubotUpdateChecker` instead of the shared checker; an update found while the player is open or the app is in the background is reported to `UtubotUpdates.onUpdateDeferred()` | self-update from the user's own backend, https-only downloads, no lost prompt |
| `app/presenters/dialogs/BootDialogPresenter.java` | `UtubotUpdates.start` instead of the one check at boot | check shortly after the start, then every 6 hours |
| `tv/ui/main/MainApplication.java` | `UtubotAppHooks.install` | busy badge on every screen but the player, which screen is up (video menu) |
| `smarttubetv/src/stutubot/res/` | app label; icon, alternative icon, banner and the three header logos, rendered from `assets/brand/*.svg` by `assets/brand/render.py` | own identity, not Electric Eel's |
| `smarttubetv/src/stutubot/AndroidManifest.xml` | literal `android:label="u·tubot"` on `<application>` (merged over main's `@string/app_name`; keep both the same) | the system installer's "App installed" screen read the label without resources and showed the class name |
| `common/src/stutubot/res/values/links.xml` | releases, sources, web site, feedback and About addresses of this repository, no donations, no Submit data server, the "Based on Electric Eel and SmartTube" credit | no upstream link is shown as ours |
| `common/src/stutubot/res/values/release_notes.xml` | release notes URL of this repository, tag prefix `utubot-v` | Settings, Updates, Release notes lists our releases only |
| `common/src/stutubot/res/values-da`, `values-fi` | the strings whose translation says "Electric Eel" | the app is called u·tubot |
| `leanbackassistant/src/stutubot/res/values/strings.xml`, `values-tr/strings.xml` | search label and description (main has a Turkish one that says Electric Eel) | Android TV search settings |
| `common/src/main/res/values/release_notes.xml` | `release_notes_tag_prefix`, empty | other flavors list every release |
| `common/src/main/res/values/about_links.xml` | addresses and credit of the short About, defaults are Electric Eel's | flavors override them |
| `misc/GitHubReleases.java` | `parse(json, tagPrefix)` keeps only the tags that start with the prefix; the changelog of the update channel (`update.json`) stands in when GitHub fails; `isInstalled` | one repository holds more than app releases; Settings, Updates, Release notes is the one place for them |
| `app/presenters/settings/AboutSimpleSettingsPresenter.java` | addresses from the resources above, no row without an address, Server row (built-in flavor), credit row | per-flavor About |
| `app/presenters/settings/UpdatesSettingsPresenter.java` | the release list marks the installed version; the update channel as fallback | release notes of the flavor only |
| `misc/AppDataSourceManager.java` | Settings, Debugging only with a Submit data server (`DataSubmitter.isConfigured`) | diagnostics must not go to Electric Eel's server |
| `diagnostics/DataSubmitter.java` | `isConfigured`, `autoSubmit` does nothing without it | same |
| `.gitignore` | `utubot.properties`, `temp/` | local secrets and scratch |
| `app/models/data/Video.java` | `utubotMark` field (copied in `copy`) | label of the card mark |
| `app/models/data/VideoGroup.java` | `isHiddenByUtubot` in the add-filter chain | hides or marks a card from the cached verdict |
| `misc/HiddenVideoResolver.java` | `UtubotManager.resolve(...)` zipped into the existing resolve | one assess call per row emission, bounded by wait_ms and a hard timeout; failures show the videos unfiltered. It emits on the main thread: the rows are shown from what the resolver emits, so a background thread here changed the grids' adapters off the UI thread (empty Modern screen) |
| `app/presenters/SplashPresenter.java` | `UtubotPairing.promptIfNeeded` | first-launch pairing dialog when no token |
| `app/presenters/dialogs/menu/VideoMenuPresenter.java` | `UtubotMenu.append` (two places) | AI answer, Summary panel toggle, Prepare HQ captions |
| `misc/AppDataSourceManager.java` | Settings entry "u·tubot" | settings screen |
| `utils/SimpleEditDialog.java` | `showNumber` | numeric pairing code dialog |
| `exoplayer/controller/ExoPlayerController.java` | captions prefetch in `setVideo`, `attachUtubotCaptions` on source change, `selectUtubotCaptions` | HQ caption tracks, auto-select |
| `exoplayer/selector/TrackSelectorUtil.java` | track name lookup | "u·tubot: label" in the subtitle picker |
| `tv/presenter/VideoCardPresenter.java` | mark with own colour, `addMark` overload, card tag | mark rendering, panel reads the focused card |
| `tv/ui/modern/widgets/ModernVideoCard.java` | card tag | panel reads the focused card |
| `tv/ui/common/LeanbackActivity.java` | `UtubotPanelController` (key dispatch, resume, pause) | passive Summary panel and the Summary view (not in the player activity) |

## Behaviour

- Settings, always in this order: Import setup, Pair with code (6 digits, `POST /v1/pair`, token stored, connection tested,
  then "Paired as <user>"), assess switch, mark only, answer in menu, Summary panel, Summary delay, auto-select HQ captions, Prompts (list,
  choose default, Import from URL, Refresh all), Test connection, Advanced (backend URL and token by hand; a typed backend
  also sets `<backend>/app/update.json` when no update URL is stored). `UtubotSettingsPresenter.buildCategories` is the list.
- Import setup (`UtubotSetup`, `UtubotSetupFlow`): the user types a bare host or a URL, the app fetches `/setup.json`
  (`ai/CONTRACT.md`), stores backend URL, update URL and switch defaults, then opens the pairing dialog.
- Every launch without a backend offers Import setup (Not now / Don't ask again); pairing follows. With a backend but no
  token the pairing dialog is offered the same way. Import errors are mapped to a reason (`UtubotSetupFlow.describeError`);
  every step is logged with tag `Utubot`. `SimpleEditDialog` submits on OK and on the keyboard's Go/Done/Next/Send/Search
  action; Back with the keyboard up only hides it.
- Assess failures, timeouts and pending verdicts leave cards unfiltered. Marks use their own colour (`UtubotPolicy.MARK_COLOR`).
- Summary panel (`UtubotPanelController`, `UtubotPanelView`, `PanelCoordinator`): a passive preview. One view added to the activity's
  content (no dialog, no window, no dimming); it never takes the focus and never handles a D-pad key. It is the bottom of the right
  strip (35% of the width), below the screen's top bar (`modern_browse_top_bar`, the classic title group), and nothing of the
  screen is detached, hidden or moved. A global focus listener finds the card (`R.id.utubot_card_video` tag set by
  `VideoCardPresenter` and `ModernVideoCard`); `PanelCoordinator` decides: focus on a card shows the title and "Waiting…" at once, the
  request starts after the card kept the focus for the delay of the settings (1, 1.8, 3 or 5 s) and any focus change or D-pad key
  starts the pause again (`FocusDebouncer`); focus on anything else, a card that is detached, the activity pausing (the player
  opens), the mode turned off or the Summary view opening hides the panel and drops its request (`RequestGeneration` ignores the
  late answers). The first Back with the panel up hides it and leaves the focus on the card (`UtubotKeys`); the next one is the app's.
  Header: the label of the panel prompt, the hint "Long-press OK or press Info for summary options" and the working indicator.
- The panel requests `prompt=panel`; on 400 or 404 (an older backend) it uses the first prompt of `GET /v1/prompts` and remembers it.
  The header label is the label of `panel_default`. The text is about three lines; a first line that starts with "→ " is bold.
- Summary view (`UtubotSummaryOverlay`): opened with the Info key on a card while the panel mode is on, or "u·tubot summary" in the
  video menu (`UtubotUiHost`: the menu closes its dialog, the screen underneath takes the request). A focused card over the
  screen, in the same window: prompts on the left (Up and Down reload after 400 ms, OK keeps the prompt for the session), the text
  on the right (Right enters, Up and Down page, Left goes back), the title, the source line, the indicator and Retry (or
  "Transcribe in background") on top. It uses the `default` prompt (or the kept one). Back closes it; the focus returns to the card.
  Menu keeps the video menu (Electric Eel's `KeyHelpers.isMenuKey`), so Info is the key.
- Transcript states (`UtubotPanelModel`, "Transcript status" of `ai/CONTRACT.md`): a summary can answer `needs_transcript` (message,
  `can_transcribe`, `estimate_s`: the view offers `POST /v1/videos/{id}/transcribe`, then follows `GET /v1/videos/{id}/transcript`),
  `pending` with `transcript_status` `delayed` (message in `error`, asked again after `retry_after_s`, 1 s to 10 min, while the card or
  view is shown), `transcribing` (progress, followed every 4 s in the view and every 20 s in the panel, which must not poll faster
  than a pending summary) or `failed` (`error`, `reason`: the transcribe action returns with `can_transcribe`, Retry goes with a
  `reason`). The manager keeps ready summaries only; these states are never cached. An insight (the AI answer) can say the same
  (`UtubotAnswerModel`): it shows the state, and its transcribe button opens the Summary view of the video and starts there.
  Older backends simply never send them.
- Working indicator: `UtubotWorkingIndicator` (three pulsing dots, redrawn about 12 times a second, only while active, attached and shown), in the panel, the
  view and the answer, and `UtubotBadgeController` (badge at the top right of every screen but the player, shown after 300 ms of work,
  kept for 700 ms) fed by `UtubotBusyTracker`, which counts every `UtubotClient` call in flight.
- Auto-update (`UtubotUpdates`, `UtubotUpdateSchedule`): 20 s after the app starts, then every 6 hours (a check that can't happen now, e.g.
  the player is open, is tried again after 5 minutes), through `AppUpdatePresenter` (the checker of `SharedModules`, `appupdatechecker2`: version
  check, APK of the device's ABI, update dialog, installer). On by default; Settings, Updates, "Notify about updates" is its switch.
  An update found while the player is open (or the app is in the background) is not dropped: `AppUpdatePresenter` tells
  `UtubotUpdates.onUpdateDeferred()`, the schedule checks again after 5 minutes, and `UtubotAppHooks` calls
  `UtubotUpdates.onScreenAvailable()` when a screen other than the player resumes, which brings that check forward to 5 seconds
  later. The dialog never opens during playback (`AppUpdatePresenter.canShowUpdateDialog`).
  `UtubotUpdateChecker` (a subclass of the shared `AppUpdateChecker`) filters the APK addresses of `update.json` before the shared
  downloader sees them: https, or http for a private host (`UtubotSetup.isPrivateHost`), judged as OkHttp reads the address; the
  shared checker only asks `URLUtil.isValidUrl`. With none left the check fails ("The update file offers no https download").
  Redirects are the downloader's own; the installer checks the package name and the signing key of whatever it gets.
  `UtubotSettings.getUpdateUrl()` returns the stored `update_url`, or `<backend>/app/update.json` when none was ever stored (a
  backend typed on 0.2.0); a setup that stored an empty address keeps none.
- HQ captions: fetched with the `Authorization` header (never `?token=`); the header is only sent to the backend: same scheme, host
  and port, path under the backend's (`UtubotClient.authorizationFor`).
- What the app keeps of the backend (`UtubotManager`: verdicts, summaries, captions, the prompt list, the session prompt) is dropped when
  `UtubotSettings.setUrl` or `setToken` changes a value (applySetup, Advanced, pairing all go through them), and the prompt list
  also when a prompt is made default, imported or refreshed. A request in flight during a switch is not stored
  (`UtubotManager.isCurrent`). Clearing the backend in Advanced also removes the stored update address.
- With the Summary view open the focus never rests on the screen under it: the first D-pad key, OK or Enter after the grid took
  the focus back restores the view's focus and is used (`UtubotKeys.actsOnFocus`).

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
`utubot app publish APK... --version-name V --version-code N --changelog TEXT`, or pulls the newest GitHub Release with
`utubot app sync-github`. Versions are automatic (`utubot.version`, `docs/development.md`, "Versions").

## Merging upstream

1. Merge Electric Eel into `master`, then `master` into a branch cut from `main` and open a PR.
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
