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
| `app/presenters/dialogs/AppUpdatePresenter.java` | `getUpdateUrls()`: stored setup URL (or the one derived from the backend) for the built-in flavor, none means no check; the update dialog opens for the built-in flavor (automatic and manual), with "Not now" and the dismissed version name and code stored so the automatic check stays silent for that build until a newer one; `startAutomatic()` asks the channel on every scheduled check regardless of the shared checker's short "recently checked" window; `UtubotUpdateChecker` instead of the shared checker; an update found while the player is open or the app is in the background is reported to `UtubotUpdates.onUpdateDeferred()` | self-update from the user's own backend, https-only downloads, no lost prompt |
| `app/presenters/dialogs/BootDialogPresenter.java` | `UtubotUpdates.start` instead of the one check at boot | check shortly after the start, then every 6 hours |
| `app/presenters/dialogs/BootDialogPresenter.java` (second line) | `UtubotSettingsSyncRunner.start` beside `UtubotUpdates.start` | the settings sync (`ai/WEB_SETTINGS_PLAN.md`): a round at start, then every 30 s while the app is in front, plus one open "anything new?" request (long poll, 20 s) so a web change arrives within seconds |
| `common/.../utubot/UtubotSecretOffer.java`, `UtubotSettingsSync` (secrets) | new: the one question before a token this TV holds is kept on the server; the server's Real-Debrid token and add-on address are written to the same `UtubotSettings` entries the films developer entry reads | decision D2 of `ai/WEB_SETTINGS_PLAN.md`: no silent upload, one set of storage |
| `tv/utubot/UtubotAppHooks.java` | `UtubotSettingsSyncRunner.requestNow` when a non-player screen resumes | the app came back to the front: look at the server now |
| `tv/ui/main/MainApplication.java` | `UtubotAppHooks.install` | busy badge on every screen but the player, which screen is up (video menu), the screen state of the cut-ready pop-up, and the cut watcher started |
| `smarttubetv/src/stutubot/res/` | app label; icon, alternative icon, banner and the three header logos, rendered from `assets/brand/*.svg` by `assets/brand/render.py` | own identity, not Electric Eel's |
| `smarttubetv/src/stutubot/AndroidManifest.xml` | literal `android:label="u·tubot"` on `<application>` (merged over main's `@string/app_name`; keep both the same) | the system installer's "App installed" screen read the label without resources and showed the class name |
| `smarttubetv/src/main/AndroidManifest.xml` | `uses-feature` `leanback`, `usb.host` and `bluetooth` with `required="false"` and `tools:node="replace"` (a library's required feature wins the merge otherwise) | the package installs on a tablet; `UtubotTabletManifestTest` |
| `common/src/stutubot/res/values/links.xml` | releases, sources, web site, feedback and About addresses of this repository, no donations, no Submit data server, the "Based on Electric Eel and SmartTube" credit | no upstream link is shown as ours |
| `common/src/stutubot/res/values/release_notes.xml` | release notes URL of this repository, tag prefix `utubot-v` | Settings, Updates, Release notes lists our releases only |
| `common/src/stutubot/res/values-da`, `values-fi` | the strings whose translation says "Electric Eel" | the app is called u·tubot |
| `leanbackassistant/src/stutubot/res/values/strings.xml`, `values-tr/strings.xml` | search label and description (main has a Turkish one that says Electric Eel) | Android TV search settings |
| `common/src/main/res/values/release_notes.xml` | `release_notes_tag_prefix`, empty | other flavors list every release |
| `common/src/main/res/values/about_links.xml` | addresses and credit of the short About, defaults are Electric Eel's | flavors override them |
| `misc/GitHubReleases.java` | `parse(json, tagPrefix)` keeps only the tags that start with the prefix; the changelog of the update channel (`update.json`) stands in when GitHub fails; `isInstalled` | one repository holds more than app releases; Settings, Updates, Release notes is the one place for them |
| `app/presenters/settings/AboutSimpleSettingsPresenter.java` | addresses from the resources above, no row without an address, Server row (built-in flavor), credit row | per-flavor About |
| `app/presenters/settings/UpdatesSettingsPresenter.java` | update check interval and development mode (moved from the u·tubot panel); a built-in switch "Check for u·tubot updates" (`update_checks`, synced as `updates.checks`; off stops the automatic check, the manual one stays); the release list marks the installed version; the update channel as fallback | release notes of the flavor only |
| `misc/AppDataSourceManager.java` | Settings, Debugging only with a Submit data server (`DataSubmitter.isConfigured`) | diagnostics must not go to Electric Eel's server |
| `app/presenters/settings/UtubotSettingsPresenter.java` | the "u·tubot web admin" entry, after "Pair with code", only in the built-in flavor: it asks the backend for a one-time sign-in link and opens it (`UtubotWebAdmin`); a QR sheet opens only when no browser is installed | open the web admin on the TV, signed in (issue #203) |
| `diagnostics/DataSubmitter.java` | `isConfigured`, `autoSubmit` does nothing without it | same |
| `.gitignore` | `utubot.properties`, `temp/` | local secrets and scratch |
| `app/models/data/Video.java` | `utubotMark` field (copied in `copy`) | label of the card mark |
| `app/models/data/VideoGroup.java` | `isHiddenByUtubot` in the add-filter chain | hides or marks a card from the cached verdict |
| `misc/HiddenVideoResolver.java` | `UtubotManager.resolve(...)` zipped into the existing resolve | one assess call per row emission, bounded by wait_ms and a hard timeout; failures show the videos unfiltered. It emits on the main thread: the rows are shown from what the resolver emits, so a background thread here changed the grids' adapters off the UI thread (empty Modern screen) |
| `app/presenters/SplashPresenter.java` | `UtubotPairing.promptIfNeeded` | first-launch pairing dialog when no token |
| `app/models/playback/controllers/VideoLoaderController.java` | `UtubotClientCaptions.onFormatInfo` after the censored-words hook | hands the original-language and the user-language caption tracks to the backend once per video per session, so it need not fetch them from YouTube |
| `app/presenters/dialogs/menu/VideoMenuPresenter.java` | `UtubotMenu.append` (two places) | AI answer, Summary panel toggle, Prepare HQ captions, Director's cut, Describe by voice… |
| `app/presenters/BrowsePresenter.java` | `UtubotBrowseCache`, gated by `UtubotSettings.isBuiltIn()`: on focus replay the last groups from memory or disk, refresh in the background when the "Browse refresh" minutes have passed, reuse the row ids so rows update in place (grid focus restored), save and append emitted groups, no progress bar or error page while cached content is shown; account and locale changes invalidate it, `refresh()` stays a manual network load. A section's layout type is stored with its groups, so a style change (Playlists style, History shorts, Channels old look) drops its cache instead of replaying the groups into another fragment. The channel-uploads multi-grid replays both cached columns without an uploads request (also when "auto load" is off) and restores the cached uploads column when their refresh fails; removed/hidden cards leave the cache at once, including cards removed while the refresh is still loading, and a cache dropped during that refresh isn't written back by its completion. | stale-while-revalidate for every browse section (u-tubot#65) |
| `app/presenters/BrowsePresenter.java` | `UtubotProcessedSection` mapping, gated by `UtubotSettings.isBuiltIn()`: the sidebar section past the other entries, its grid loaded from `UtubotManager.processedObserve(50)` (not YouTube), tiles in the backend's newest-first order, the processed line in the second title, the browse cache reused, the empty and failed states through `UtubotSectionError`; a tile click goes through `UtubotProcessedOpen` instead of `VideoActionPresenter`. A `UtubotSettings` connection listener drops that section's cache and cancels its in-flight cached refresh when the backend address or token changes, so another connection's user's tiles aren't replayed; without a backend it shows the setup hint. | the Processed section (u-tubot#66, steps 3-4) |
| `app/presenters/service/SidebarService.java` | the Processed default section, past the other entries and before Settings, only when `UtubotSettings.isBuiltIn()`; the saved sidebar keeps the ids of the default sections it knew, and a restore adds a current default missing from them once (a section the user turned off stays off), so existing installs get the section | the built-in flavor's sidebar, no change in the other flavors |
| `app/presenters/BrowsePresenter.java`, `app/presenters/service/SidebarService.java`, `tv/ui/modern/browse/ModernBrowseFragment.java` | the Films default section (`UtubotFilmsSection.ID` 28, past Inbox, before Settings), built-in flavor only: a one-button settings grid ("Open Films") and `openSectionApp`, which `ModernBrowseFragment.onSectionClicked` asks first so a rail click opens the films home (`UtubotFilmsSection.open`; with the developer entry off it says where to turn it on) | the Films entry of the main sidebar (#290) |
| `common/.../utubot/UtubotProcessedOpen.java` | new: `isProcessed` (the card's group carries the section, also on a cached replay), `open` requests the video's HQ captions and starts the normal playback path (`PlaybackPresenter.openVideo`); nothing carries or applies a cut | a Processed tile opens with its HQ captions; the #64 cut controller opens it with the chosen or last-used cut, else offers the ready ones, as at any video start (u-tubot#66, step 4) |
| `common/.../utubot/UtubotCaptionsOpen.java` | new: one video's selection request, taken by the player (`take`) with a short expiry | the tile's caption request reaches the playback without changing the automatic setting |
| `app/presenters/PlaybackPresenter.java` | `UtubotCutController` registered after `SponsorBlockController`, gated by `UtubotSettings.isBuiltIn()` | the director's cut of the video that plays and its double-press kept-part jump. The order is not changed: `VideoPlayerGlue` sends every key-down through the chain before the progress bar's seek handler, the sponsor watcher's `onVideoLoaded` starts the segment refresh the cut's skipper merges with, and the gesture is guarded (the controls overlay and a quick-skip direction keep their press) |
| `tv/ui/playback/other/VideoPlayerGlue.java` | `UtubotCutAction` put into the action map and added to the secondary row (`onCreateSecondaryActions`); `setButtonLabel` changes an action's label; `action_utubot_cut_skip` is in the map but only added to the secondary row on demand (`setCutSkipActive`: adds or removes it and `invalidateUi`s) | the Director's cut picker of the playing video from the player controls, and its "Cut: Half · 41:20" label while a cut is on |
| `app/models/playback/manager/PlayerUI.java`, `tv/ui/playback/PlaybackFragment.java`, `tv/ui/widgets/embedplayer/EmbedPlayerView.java` | `setButtonLabel(buttonId, label)` and `setCutSkipActive(active)` added to the player UI (the embed player has no controls and does nothing) | lets the cut controller show the applied cut on the player button, and the cut's skip toggle only while a cut is applied |
| `tv/ui/mod/leanback/misc/SeekBar.java` | a segment with `hatched` set is drawn with diagonal lines over its colour; a new segment list replaces the rectangles of the old one (a `null` or another list clears first) | the cut-out ranges of a director's cut are dimmed *and* hatched, not just another grey, and taking a cut off leaves no kept or cut-out rectangles underneath the sponsor colours |
| `app/models/playback/ui/SeekBarSegment.java` | `hatched` flag (additive, default false) | the seek bar gets the cut-out pattern without a second segment type |
| `smarttubetv/src/main/java/com/liskovsoft/smartyoutubetv2/tv/utubot/UtubotCutAction.java` | new: `Action` with the `action_utubot_cut` id, the u·tubot symbol and the label "Director's cut…"; `isAvailable` is the flavor and backend gate | the player's cut button |
| `smarttubetv/src/main/java/com/liskovsoft/smartyoutubetv2/tv/utubot/UtubotCutSkipAction.java` | new: `TwoStateAction` on the `action_utubot_cut_skip` id, the u·tubot symbol, `INDEX_ON`/`INDEX_OFF` labelled "Show cut-out parts" / "Skip cut-out parts" (the label is the action taken when clicked); `isAvailable` is the flavor and backend gate | the player's toggle of the applied cut's skipping: on while the cut skips its cut-out parts, off while they are watchable, the cut staying selected either way |
| `common/src/main/res/values/ids.xml` | `action_utubot_cut` and `action_utubot_cut_skip` ids | the player button, whose click reaches `UtubotCutController.onButtonClicked` |
| `app/models/playback/controllers/SponsorBlockController.java` | `onNewVideo` wipes through `UtubotCutSeekBar.wipe` and its own seek-bar segments go through `UtubotCutSeekBar.setSponsor`; `getActiveSegments()` exposes the segments of the video that plays | the cut's bright kept parts and dark hatched cut-outs stay on the seek bar (its reset for a new video keeps a cut of the same video, its own markers are laid next to the cut's), and the cut's jump goes past the sponsor segments that would jump after it: one jump, not two. Without a cut both writes behave exactly as before. Known for the real-device pass (u-tubot#1): chapter markers still write straight to the seek bar, so their order against `onMetadata` can hide the cut's colours on a chaptered video (recorded in the DEVLOG) |
| `app/models/playback/controllers/SponsorBlockController.java` | `skipSegment` returns early while a director's cut is applied to the video that plays (`UtubotCutController.isCutActive`), so the sponsor block is fully off (no skip, no prompt) over the same section and the two do not clash; it comes back the moment the cut is taken off or the video has no active cut | SponsorBlock and a director's cut fight an overlapping sponsor segment (u·tubot#145) |
| `common/.../utubot/UtubotCutController.java` | `isCutActive()` is public: true while a cut is applied to the video that plays; `getPlayingCut()` is the applied cut while its skipping is on (`null` with skipping off); `updateEndingTime()` asks the player to refresh the hourglass after a cut, skip or position change | the sponsor block reads `isCutActive()` to stay off over the same section (u·tubot#145); the player's hourglass follows the cut that plays (u·tubot#209) |
| `tv/ui/widgets/time/EndingTimeView.java` | while a cut plays (`UtubotCutController.getPlayingCut`) the hourglass adds the cut's remaining kept time and appends `✂`; otherwise it keeps the full-video end | the player's end time follows the director's cut, and goes back to the full video when the cut is off or the playback is past its last kept part (u·tubot#209) |
| `misc/AppDataSourceManager.java` | Settings entries "AI features" and "Backend", with its own tile icon `R.drawable.settings_utubot` | settings screen; Content filtering keeps `settings_aislist` |
| `common/src/main/res/drawable-nodpi/settings_utubot.png` | new: the symbol, white on transparent, 302x302 with the canvas and padding of `settings_about.png`; `assets/brand/render.py` draws it from `utubot-symbol-mono.svg` | tile of the u·tubot Settings entry |
| `utils/SimpleEditDialog.java` | `showNumber` | numeric pairing code dialog |
| `exoplayer/controller/ExoPlayerController.java` | `followCaptions` in `setVideo` (stopped in `release`), `attachUtubotCaptions` on source change (keeps the source it merged into), `onUtubotCaptionsReady` (opens the source again with a track that came while playing, toast), `selectUtubotCaptions` (after the tracks changed), `isSelected` (an HQ track and a YouTube track in one language are two picks); `setVideo` takes a `UtubotCaptionsOpen` request for the video and keeps it for the playback, so `attachUtubotCaptions` and `onUtubotCaptionsReady` select the HQ track whatever the automatic setting says | HQ caption tracks, live add, auto-select, the Processed tile's open (u-tubot#66, step 4) |
| `tv/ui/widgets/embedplayer/EmbedPlayerView.java` | `setUtubotCaptionsEnabled(false)` | the muted previews of the cards take no HQ captions and wait for no job |
| `exoplayer/selector/TrackSelectorUtil.java` | track name lookup | "u·tubot: label" in the subtitle picker |
| `exoplayer/selector/TrackSelectorManager.java` | `findUtubotCaptionTrack` first in `findBestMatch`, `invalidateSubtitles` | an HQ track is picked by its id, not by the language it shares with YouTube's track |
| `app/models/playback/controllers/VideoStateController.java` | `restoreSubtitleFormat` leaves the HQ track of the video selected | the saved subtitle choice (usually none) is applied twice per video, the second time after the HQ track was picked (#31) |
| `app/models/playback/controllers/PlayerUIController.java` | `onTrackSelected` refreshes the CC button; a key it consumes calls `UtubotCutController.resetJumpGesture` | the button follows a track the app picked, and OK, Back, a menu or a number key breaks the cut's double press even though it never reaches the cut controller |
| `common/.../utubot/UtubotRealDebridClient.java` | new: `streams(imdbId)` does `GET {addon}/stream/movie/{imdbId}.json` on a Stremio addon (Torrentio/Comet/MediaFusion), keeps entries with a direct http(s) `url` (torrent-only entries are dropped); `{token}` in the addon address is replaced by the Real-Debrid token entered on the TV; errors never quote the address (it may hold a key) | the spike's film list: a title is turned into playable streams, the key stays on the TV |
| `common/.../utubot/UtubotRealDebridSkips.java` | new: `parse(spec)` turns a hand-written `start,end` spec (seconds, `ms` suffix, comma/semicolon/newline separated, reversed ranges kept in time order) into `SponsorSegment`s of `CATEGORY="real-debrid"` with a skip action | the hand-written skip list fed through the sponsor block to prove cut-style playback, no director's cut built |
| `app/models/playback/controllers/ExoPlayerController.java` | `openProgressiveUrl(url)` next to `openUrlList`, builds a single progressive source and plays it | the spike plays one Real-Debrid stream through the same path as `urlList` |
| `exoplayer/ExoMediaSourceFactory.java` | `fromProgressiveUrl(url)` next to `fromUrlList` | the single-source media source for one stream |
| `app/models/playback/controllers/SponsorBlockController.java` | `applyHandWrittenSkips(List<SponsorSegment>)` (and `@Nullable` import): feeds the hand-written ranges to the sponsor block (`Observable.just(...).flatMap(this::startSponsorWatcher)`); the caller enables and skips the `real-debrid` category first | cut-style skips for a Real-Debrid stream, through the existing sponsor watcher |
| `common/.../utubot/UtubotFilmsDeveloperPresenter.java`, `UtubotSettings.java`, `UpdatesSettingsPresenter.java`, `smarttubetv/src/stutubot/.../films/FilmDetailsActivity.java` | new: Settings, Updates, switch "Films developer entry" (off by default, built-in flavor only; its address, token, IMDb id and skip list live in the private `UtubotSettings` prefs, never logged) shows "Films (developer)": address, token, IMDb id, skip list (no longer used: films play in the main player), "List streams" which opens the details screen of that IMDb id (stutubot flavor, not exported, closes itself when the switch is off) | the hidden developer entry of the spike; the codec checklist is `docs/films-codec-checklist.md` |
| `tv/presenter/VideoCardPresenter.java` | mark with own colour, `addMark` overload, card tag | mark rendering, panel reads the focused card |
| `tv/ui/modern/widgets/ModernVideoCard.java` | card tag | panel reads the focused card |
| `smarttubetv/src/main/res/layout/modern_video_card.xml` | `modern_card_utubot_summary` in the thumb frame, top-end, gone by default, own focus background and the `settings_utubot` symbol, clickable but not focusable | the card's visible touch entry to the Summary view on a tablet |
| `tv/ui/modern/widgets/ModernVideoCard.java` | `setupUtubotSummaryControl(Video)`: show the card's touch entry only while the screen is touch (`Helpers.isTouchSupported`), hide it otherwise; called at the end of `bind` | the entry is visible on a tablet, hidden on a D-pad screen |
| `tv/presenter/VideoCardPresenter.java` | `setupUtubotSummaryControl(ComplexImageCardView, Video, Context)`: show the classic card's touch entry only on a touch screen, programmatic, removed on unbind | the entry is visible on a tablet, hidden on a D-pad screen |
| `tv/ui/common/LeanbackActivity.java` | `UtubotPanelController` (key dispatch, resume, pause) | passive Summary panel and the Summary view (not in the player activity) |

## Behaviour

- Settings, two sections. "Backend" (`UtubotBackendSettingsPresenter`), in this order: Import setup, Pair with code (6 digits, `POST /v1/pair`, token stored,
  connection tested, then "Paired as <user>"), Test connection, u·tubot web admin, Advanced (backend URL and token by hand; a typed backend
  also sets `<backend>/app/update.json` when no update URL is stored). "AI features" (`UtubotSettingsPresenter.buildCategories`), in this order: assess switch,
  mark only, answer in menu, Summary panel, Summary delay, Reading pace (the self-scroll of the long answer and Summary text, 30, 45 or 60 px/s),
  auto-select HQ captions, apply ready cuts automatically, Cut jump, Prompts (list, choose default, Import from URL, Refresh all), Caption storage
  (size, videos and tracks; a warning past 200 MiB; delete older than 30, 90 or 365 days, or all, after a confirmation). Browse refresh is in System,
  General; update check interval and development mode are in Updates.
- Web admin on the TV (issue #203). In the "Backend" section the built-in flavor's "u·tubot web admin" (`UtubotWebAdmin`, only when
  `isBuiltIn()`): it asks the backend for a short-lived, single-use sign-in link (`POST /v1/web-login`, `UtubotClient.webLogin`, bearer
  token, rate-limited per IP), then opens it with an `ACTION_VIEW` intent (`https://<backend>/web-login/<token>`). The token is created for
  the device the backend knows (`client_of(request)`) and is single-use and ~60 s old; the backend redeems it, turns it into a session
  (`agent=device` — the TV is logged in) and redirects to `/#/home`. If no browser can handle the scheme, the entry falls back to a QR sheet
  (`UtubotCutQrView`) of the same link so a phone can open it. The entry is offered only while paired and connected (otherwise a "pair first"
  toast), and the link is requested once per open, so a re-open gets a fresh token.
- Import setup (`UtubotSetup`, `UtubotSetupFlow`): the user types a bare host or a URL, the app fetches `/setup.json`
  (`ai/CONTRACT.md`), stores backend URL, update URL and switch defaults, then opens the pairing dialog.
- Every launch without a backend offers Import setup (Not now / Don't ask again); pairing follows. With a backend but no
  token the pairing dialog is offered the same way. Import errors are mapped to a reason (`UtubotSetupFlow.describeError`);
  every step is logged with tag `Utubot`. `SimpleEditDialog` submits on OK and on the keyboard's Go/Done/Next/Send/Search
  action; Back with the keyboard up only hides it.
- Assess failures, timeouts and pending verdicts leave cards unfiltered. Marks use their own colour (`UtubotPolicy.MARK_COLOR`).
- A ready verdict or summary survives a restart of the app: `UtubotDiskCache` (`files/utubot_cache`) keeps only ready ones, scoped by the
  backend address, token and the backend's version (`GET /v1/health`), for 3 days, at most 2000 verdicts and 300 summaries; another
  backend, user or version starts empty and removes the old scope. Failures, pending jobs and transcript states are never stored. The
  user's Retry calls `POST /v1/videos/{id}/retry` first (the wait of a `delayed` answer does not), then asks again, even when that call
  fails; a prompt import, refresh or default change clears the stored summaries of every scope, even one not opened yet, and a
  request already in flight then is shown but not stored again.
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
   The long answer and Summary text (and the research results of the answer) crawl slowly and smoothly by themselves at the reading
   pace of the options page (30, 45 or 60 px/s, default 45) when they are taller than the view, and stop at the bottom: a page takes
   a few seconds to read. Any D-pad or keyboard key pauses it, and it resumes on its own a few seconds after the key; Up and Down still
   scroll one page at a time, and waiting long enough shows the whole text. The view turns it on when the state is Ready and off while
   it is opening or waiting (`UtubotSummaryOverlay`), which is the one view that renders both the Summary and the AI answer (`isAnswer`),
    so the answer scrolls the same way. A long press of the Back key closes the view and cancels the scroll (`UtubotPageScrollView`,
    `UtubotAutoScroll`).
- The cards' Summary entry on a touch screen (tablet): a tablet has no Info key, no Menu key and no D-pad, so the Summary view and the
  menu need a visible entry. Each card shows a small u·tubot symbol at the top-end of its thumb (`modern_card_utubot_summary`, the classic
  card gets the same control programmatic), visible only while the screen is touch (`Helpers.isTouchSupported`), hidden on a D-pad screen;
  it is clickable but not focusable, so it does not steal the D-pad. A tap on it opens the Summary view with `UtubotUiHost.request(UtubotOpenRequests.Kind.SUMMARY, video)` — the same call the Info key and the menu's "u·tubot summary" item make — the prompts on the left, the text
  on the right, Back closing it with the focus back on the card. The long press of a card still opens the u·tubot menu (`LongClickPresenter`), so the cut picker and the AI answer stay reachable by touch. `UtubotPanelControllerTest`.
- Transcript states (`UtubotPanelModel`, "Transcript status" of `ai/CONTRACT.md`): the words are the server's, the app's own strings are
  the fallback for an answer that has none (`UtubotStateText`, one place for the panel, the Summary view and the AI answer).
  - `needs_transcript`: the panel and the view show the server's `message` (the plain "No captions..." question, or "Captions are
    temporarily unavailable from YouTube; transcribe the audio instead (~N s)?" while YouTube limits the caption API); only without
    one the local "No captions — press Info to transcribe" / "This video has no captions..." is shown. The view offers
    `POST /v1/videos/{id}/transcribe` with the `estimate_s` in minutes on the button, then follows `GET /v1/videos/{id}/transcript`.
  - `pending` + `transcribing` (a job the server's auto policy started, or the user's): "Transcribing… N% (~M min)" (progress when known,
    `estimate_s` in whole minutes when given), nothing to press. It is followed every 4 s in the view and the answer and every 20 s in
    the panel (no faster than a pending summary's long poll) until the transcript is `ok`, then the summary or answer is asked for again.
  - `pending` + `delayed`: the server's `error` text and a "Retrying in 42 s" / "Retrying in 2:05" countdown from `retry_after_s`
    (1 s to 10 min), ticked once a second by `UtubotCountdown` while the card or view is shown; at zero the request is repeated.
  - `failed`: `error`; `reason` set means asking again changes nothing, otherwise Retry (and the transcribe action with `can_transcribe`).
  The manager keeps ready summaries only; these states are never cached. The AI answer (`UtubotAnswerModel`) waits like the view:
  it counts a delay down and follows a running transcription (its transcribe button still opens the Summary view of the video and
  starts there). Older backends simply never send any of this.
- Video metadata: every `insight`, `summary` and `transcribe` request carries `title`, `channel` and `duration_s` from the `Video`
  (`UtubotMeta`, `UtubotClient.addMeta`); the server's automatic transcription only starts for a video of known length. The length is the
  card's duration, else its media item's (a copy of a card keeps the item, not the field), else the clock in its badge.
- Working indicator: `UtubotWorkingIndicator` (three pulsing dots, redrawn about 12 times a second, only while active, attached and shown), in the panel, the
  view and the answer, and `UtubotBadgeController` (badge at the top right of every screen but the player, shown after 300 ms of work,
  kept for 700 ms) fed by `UtubotBusyTracker`, which counts every `UtubotClient` call in flight.
- Auto-update (`UtubotUpdates`, `UtubotUpdateSchedule`): 20 s after the app starts, then every interval of Settings, u·tubot, "Update check interval" (default 5 min; development mode, on by default, opens the dialog with Install selected when no video plays) (a check that can't happen now, e.g.
  the player is open, is tried again after 5 minutes), through `AppUpdatePresenter` (the checker of `SharedModules`, `appupdatechecker2`: version
  check, APK of the device's ABI, update dialog, installer). The scheduled check (`startAutomatic`) asks the channel on every run, whatever
  the shared checker's 60 second "recently checked" window says, and only while "Notify about updates" is on. On by default; Settings, Updates,
  "Notify about updates" is its switch. An automatic notification dismissed with Back or "Not now" stores that version name and
  code (`UtubotSettings.setDismissedUpdate`) and isn't offered again; a higher code, even under the same name, is.
  An update found while the player is open (or the app is in the background) is not dropped: `AppUpdatePresenter` tells
  `UtubotUpdates.onUpdateDeferred()`, the schedule checks again after 5 minutes, and `UtubotAppHooks` calls
  `UtubotUpdates.onScreenAvailable()` when a screen other than the player resumes, which brings that check forward to 5 seconds
  later. The dialog never opens during playback (`AppUpdatePresenter.canShowUpdateDialog`).
  `UtubotUpdateChecker` (a subclass of the shared `AppUpdateChecker`) decides whether the channel is newer by its `versionCode`
  (the backend publishes one per release; a version name can be shared while the code grew), falling back to the shared checker's
  version-name comparison when a manifest has no code, and filters the APK addresses of `update.json` before the shared
  downloader sees them: https, or http for a private host (`UtubotSetup.isPrivateHost`), judged as OkHttp reads the address; the
  shared checker only asks `URLUtil.isValidUrl`. With none left the check fails ("The update file offers no https download").
  A cached download whose version name matches but whose code does not is discarded, so the shared checker fetches the offered
  build instead of reusing the old file.
  Redirects are the downloader's own; the installer checks the package name and the signing key of whatever it gets.
  `UtubotSettings.getUpdateUrl()` returns the stored `update_url`, or `<backend>/app/update.json` when none was ever stored (a
  backend typed on 0.2.0); a setup that stored an empty address keeps none.
- HQ captions: fetched with the `Authorization` header (never `?token=`); the header is only sent to the backend: same scheme, host
  and port, path under the backend's (`UtubotClient.authorizationFor`).
- HQ captions, from start to storage (#31). `ExoPlayerController.setVideo` hands the video to `UtubotManager.followCaptions`
  (`UtubotCaptionsFollower`): one `GET /captions` at the start, then every 10 s while the answer is `queued` or `running` (at most 2 h,
  5 errors in a row). A ready answer is downloaded (`UtubotClient.captionFile`, header scoped to the backend) into
  `UtubotCaptionStore` (`files/utubot_captions/<video id>/<lang>.vtt`), then kept in memory and given to the player. The store is
  permanent: only WebVTT of at most 4 MiB, a track never replaced, and a track removed only when the user asks for it in Settings,
  u·tubot, Caption storage; not cleared by a change of backend or token (the memory caches are). That entry shows the size, videos and
  tracks, warns past 200 MiB, and deletes tracks older than 30, 90 or 365 days or all after a confirmation; it removes their labels and
  a video folder left without a track (`UtubotCaptionStore.usage`, `deleteOlderThan`, `deleteAll`). `UtubotCaptions.attach` merges the
  stored tracks (no backend needed) and, until a track is stored, the answer in memory (played from the backend). A video whose
  captions are stored makes no request.
  At the start the track is selected when "auto-select HQ captions" is on (default). Captions that come after the source was opened
  (a job finished while playing, or a late answer) open the source again with the track at the same position; the user-requested
  ones are selected whatever the setting says and announced ("u·tubot captions ready"). `VideoStateController.restoreSubtitleFormat`
  does not replace an HQ track of the playing video with the saved choice; the user's own pick in the subtitle menu always wins.
  Not for the merged live sources (`openMerged`).
- Processed section (u-tubot#66, step 4). A tile of the section opens through `UtubotProcessedOpen.open`: its card is recognized by
  the section of its group (`isProcessed`), the open requests the video's HQ captions (`UtubotCaptionsOpen.request`) and starts the
  normal playback path (`PlaybackPresenter.openVideo`). The player takes the request in `setVideo` and keeps it for that playback, so
  its stored or newly arrived HQ track is selected even with "auto-select HQ captions" off (`UtubotCaptions.shouldSelect` with the
  requested flag); the request expires if no player takes it, so it never carries to another open of the video. A ready cut is not
  carried by the tile: the open is the same playback path as #64, where `UtubotCutController` follows the video and applies the cut
  the viewer chose for it (or the preset used last when it has a ready cut here); with no such cut it offers every ready cut through
  its one-press Apply and applies none, also with "apply ready cuts automatically" on. A tile with no cut starts plainly.
- What the app keeps of the backend (`UtubotManager`: verdicts, summaries, captions, the prompt list, the session prompt) is dropped when
  `UtubotSettings.setUrl` or `setToken` changes a value (applySetup, Advanced, pairing all go through them), and the prompt list
  also when a prompt is made default, imported or refreshed. A request in flight during a switch is not stored
  (`UtubotManager.isCurrent`). Clearing the backend in Advanced also removes the stored update address.
- Director's cuts (checkpoint 2). The video menu gains "Director's cut…" (`UtubotMenu`): the picker lists the cut presets with their
  state for the video (`GET /v1/videos/{id}/cuts` — ready "12:40 of 18:05", building, waiting, needs transcript, failed, none), a ready
  row applies its cut (again = takes it off; in a picker opened from a list it starts the video through `PlaybackPresenter.openVideo`
  with the cut carried to the player, `UtubotCutController.applyOnOpen`), a `none` row asks for the build (`POST {preset}`, then the request is followed), and the
  last row "Describe on phone…" creates a waiting request (`POST {await_prompt:true}`) and shows `UtubotCutQrView`: a dimming sheet
  over the playing video with the request's short address (`<backend>/cuts/<id>`) as a QR code (made on the device, `QrCodeEncoder`)
  and in text. The video is not paused; Back (any key) takes the sheet away. Without a model on the backend the picker says so.
- Describe by voice (issue 176). The video menu gains "Describe by voice…" (`UtubotMenu`), which opens `UtubotCutSpeechView`: a dimming
  sheet over the playing video with a mic, the states IDLE → RECORDING → TRANSCRIPT → ERROR, an editable box for the transcript and "Use this"
  / "Record again". The video is not paused; Back (any key) takes the sheet away. The mic is driven by `UtubotSpeechInput`, which reports
  through a `Listener` (on a worker thread: the recording blocks and the upload is network; the view posts to the UI thread), asks for the
  RECORD_AUDIO permission through `MotherActivity.addOnPermissions` and forwards the speech recognizer result through `MotherActivity.OnResult`
  (an existing hook; the view re-registers it after each result, posted, since the activity is still iterating its callbacks). The capture is
  `AudioCapture`: `AudioRecord` on the voice-recognition source until the cap (`speech_max_s`, 50 s) or the Stop tap; a silent recording
  (`UtubotSpeechProbe.isUsable`) reports "no speech", and a recorder that cannot start (no microphone) falls back to the platform
  `SpeechRecognizer` (text only). The recorded 16 kHz mono 16-bit PCM is muxed to WAV on the device (`UtubotWav`) and uploaded
  (`UtubotClient.speech`, `POST /v1/speech`: multipart `audio` plus an optional `language` hint). The backend transcribes through modelgate
  and returns the text; an empty recording or an upload the backend rejects (`ai/CONTRACT.md`, Voice prompts) is reported back for a re-record.
  "Use this" builds the cut with the spoken text as the prompt (`POST {prompt}`), the same path as a typed description, and follows it like
  the others. Without a backend the menu row is not shown.
- Director's cuts, real length (issue 82): a ready preset's row in the picker is titled with the cut's real length
  ("Highlights in 5 min · 5:02", `UtubotCutController.presetTitle` from `kept_ms`). Only `UtubotMenu` changed, no upstream file.
- Director's cuts (checkpoint 4): a ready preset also appends a read-only "Kept parts" category under the preset row: the cut's
  summary and one line per kept part ("2:10 - 3:05  The demo", `UtubotCutController.formatPart`), so the owner judges the cut on
  the TV before applying it (the phone sheet's parts list is the same information). Saved presets and the Android Share target are
  phone-only in v1 (the saved presets become rows of this same picker).
- Director's cuts, Quick and Watched (`UtubotMenu.showCuts`): the picker's first row is the mode
  ("Mode: Quick (default)" or `modes[].label`, with the server's reason when unavailable); its choice holds
  for this picker session. Presets show `by_mode[selected]`, a ready row's title appends `· Watched`, and a
  failed Watched preset shows its reason plus "Use Quick" (`POST {"preset","mode":"quick"}`). Asking for a
  Watched build passes `"mode":"watched"` and toasts the `modes[].eta_s` ("Watched cut is being prepared,
  about 12 min. Keep watching."). The follower long-polls the watched request through `video` and `grids`
  and its ready announcement is unchanged. The device's personal default is read-only here (shown as the
  default); it is changed in the web UI Settings ("Cut mode"), whose setter is `PUT settings.cuts.cut_mode`.
- Director's cuts, while playing (`UtubotCutController`, a playback controller next to `SponsorBlockController`). The player's
  "Director's cut…" button (`UtubotCutAction`, next to the video stats button while the flavor is built in and a backend is set)
  opens the picker of the video that plays and reaches the controller's `onButtonClicked`. When a video opens it checks once where
  its cuts stand (`UtubotCutFollower`, like the captions follower): the backend's `selection` picks the cut the viewer chose for
  this video, else the preset they used last when it has a ready cut here (`GET /v1/videos/{id}/cuts`, `PUT .../cut-choice` records
  a pick). That cut is applied; with no selection the follower offers every ready cut and applies none, so the first one is never
  silently picked (even with "apply ready cuts automatically" on). The player button then says "Cut: No filler · 12:40". A cut
  picked in the player or carried from a list is remembered for the video, and picking the applied cut again turns it off and
  keeps "off" for that video. A waiting or building request for the video is long-polled (`GET /v1/cuts/{id}?wait_ms=10000`, at most 30 min, 5
  errors in a row) and applied from the current position when it becomes ready. A cut applies only to a video of its own length (±2 s,
  `cut.duration_ms` against the player's). While a cut is applied, the sponsor block is fully off over the video that plays (no skip, no
  prompt, u·tubot#145): the cut's own skip is the only one over these ranges, so the two do not fight an overlapping sponsor segment. While
  a cut is on, its dropped ranges are skipped with the sponsor-skip machinery:
  `UtubotCutSkipper` skips a drop when the playback crosses into it by itself (any flowing tick that lands inside it, however deep;
  a seek of the user wins and plays, backwards moves too), the jump goes past every sponsor segment set to skip that overlaps or touches the destination (`SponsorBlockController.
  getActiveSegments`, the same 3 s grouping the sponsor block uses itself), so there is one jump, not two. Each skip shows a
  transparent dialog "Skipped 1:20" with a Back that returns to the skipped part for 5 s; nothing extra while another dialog is up.
  The skipped parts are dimmed on the seek bar (`UtubotCutSeekBar`, see the SponsorBlockController row above). Picking the applied cut
  in the picker again turns it off; a video change or a finish clears it. The "different length" message is only for a real mismatch of the video
  that plays: a picker with no player of that video answers false and carries the cut to the video it opens, and a cut that counted
  as pending for another video is dropped at its open (no stale length claim). A video counts as playing only with its engine initialized, so a
  destroyed view the presenter still returns or a released engine carries no toggle and no length claim (`isLivePlayer`); the Apply offer closes
  at the next video and its press re-checks the cut's video (`applyReadyCut`), and a pending cut of another video is not tried (`tryApplyPending`).
  An engine release keeps the follower and the cut (only a finish ends the follower), and an engine re-init re-applies the cut of the same video; a
  same-video reload re-arms a cut that was still waiting for the length, and an engine release keeps such a pending one for its re-init. The skip rules live in `UtubotCutSkipper` (unit-tested); the emulator check (`CutsHarnessActivity`) plays a local MP4
  against the mock backend (docs/development.md, "Checking the director's cuts").
- Director's cuts, ready wherever the viewer is (issue 96). A cut this TV orders while it is still waiting or building is kept in
  `UtubotCutWaitlist` (the app may be closed before it is ready). `UtubotCutWatcher` follows every such request through
  `GET /v1/cuts/{id}` from `UtubotAppHooks` on any screen, not only the player; `UtubotCutNotices` asks one at a time
  "Director's cut ready: <video title> (<real length>). Play?". Yes carries the cut through the #64 path
  (`UtubotCutController.applyOnOpen`) and opens the video; No, or Back, only closes the question, so the screen and the playback
  position stay as they were. A ready cut found on the first check after a start (the app was closed when it finished) is not
  announced; a failed build shows its reason as a short message (at the next screen when there was none). A cut of the video that
  plays is not asked again only when the player's follower follows that same request (or the cut is already applied or queued);
  a request the follower never learned, such as one ordered from the cut sheet with no preset id, still asks. Network errors do not
  lose an order: it is retried (1 s, 2 s, 5 s, 10 s, then every 30 s) until it is ready, failed or older than 30 minutes. Ready,
  failed and dismissed requests leave the list, and a backend or token change clears it.
- Director's cuts, kept-part navigation and the outside-the-cut badge (issue 104): double-press Right/Left (or Up/Down, Settings,
  u·tubot, "Jump between kept parts"; Off turns it off) jumps to the start of the next/previous kept part (`UtubotCutNavigator`).
  The first press keeps its normal seek and the pair remembers the position it started from, so the jump is counted from there even
  when that seek lands in another part (`mLastJumpPositionMs`). A held key is not a double press; any other key breaks the pair,
  including the keys `PlayerUIController` consumes before the cut controller (they call `resetJumpGesture`). The next jump goes
  past the sponsor segments the destination touches like every cut jump. The gesture is guarded: while the controls or suggestions
  overlay owns the D-pad it never takes a press, and neither does it in a direction the player's quick skip would consume (that
  press loads another video), so it coexists with the existing seek, SponsorBlock and Leanback controls. A direction with no part
  left moves nowhere and the second press is consumed there instead of falling through to a seek. The controller keeps its place
  after `SponsorBlockController`: `VideoPlayerGlue` already sends every key-down through the chain before the progress bar's seek
  handler, the sponsor watcher's `onVideoLoaded` still starts the segment refresh the cut's skipper merges with first, and no reorder is
  needed. While the playback is inside a cut-out range a small, unfocused badge at the top left says "Outside the cut · ▶▶ next
  part in 2:10" (or that no kept part follows) and goes away in a kept part (`UtubotCutBadge`, fed by the existing 1 s cut tick).
  The seek bar draws the kept parts bright cyan and the cut-outs dark with a diagonal hatch (`UtubotCutSeekBar.segmentsFor`), the
  knob stays on top, a new segment list replaces the old rectangles, and the colours are explained once when a cut first applies.
  Unit tests: `UtubotCutNavigatorTest` (next/previous: start, middle, last part, none left; badge state), `UtubotCutSeekBarTest`
  (kept bright, cut-out dark and hatched) and `UtubotCutControllerTest` (the gesture's state machine, the overlay and quick-skip
  guards, none left consumed, a jump from inside a cut-out counted from the first press, a key consumed by the player UI breaking
  the pair), plus the TV's `SeekBarSegmentsTest` (a list replaces the rectangles).
- Director's cut, seek and skip toggle (issue 142): while a cut is on, a forward/rewind seek moves in cut time and never lands in a
   cut-out part. The seek lands in `UtubotCutController.onSeekEnd` (the UI's `PlaybackPresenter` reports the seek there), where the
   direction is taken from the position the seek started from (`mSeekFromPos`, tracked by the watcher and refreshed on every seek) and
   `UtubotCutSkipper.snapToKept` snaps a landing inside a dropped range to the range's edge — the end for a forward seek, the start for a
   backward one — so a seek within a kept part stays put and a longer press jumps between part boundaries. The player's skip toggle
   (`UtubotCutSkipAction`, the `action_utubot_cut_skip` button next to the cut button) flips `mSkipActive`: off, the cut's skipping stops
   and the seek no longer snaps, so the cut-out parts can be watched, but the cut stays selected and its skips stay dimmed on the seek bar;
   on, it resumes and jumps out of any drop the playback sits in. The button is shown only while a cut is applied (`setCutSkipActive`), and
   turning the cut off, a video change or a finish hide it. The rule lives in `UtubotCutSkipper` and is unit-tested with the controller.
- With the Summary view open the focus never rests on the screen under it: the first D-pad key, OK or Enter after the grid took
  the focus back restores the view's focus and is used (`UtubotKeys.actsOnFocus`).

## Web admin on the TV: WebView vs. system browser

Issue #203 asked to evaluate an embedded `WebView` for opening the web admin on the TV and tablet. The app
defaults to the system browser (an `ACTION_VIEW` intent); a `WebView` is not used. The evaluation:

- **Focus / D-pad.** A browser tab already has D-pad focus when the TV firmware forwards navigation keys; the
  web admin relies on that (`:focus-visible` outline on every control, 44px+ targets, `app.css`). A `WebView`
  does not get focus for free: with `WebSettings.setFocusableInTouchMode(true)` and `setFocusable(true)`, the
  firmware still has to deliver the arrow keys to it, and `onKeyDown`/`onKeyUp` must be wired by hand, arrow by
  arrow, to move focus between the same controls the browser moves automatically. That is a lot of code to
  re-implement what the browser gets out of the box.
- **Keyboard.** Signing in by hand needs a keyboard; the one-time link exists precisely so nothing is typed on
  the remote. A `WebView` needs a custom IME or `android:windowSoftInputMode` tuning to feel right on a big TV
  screen, and a system browser already has one.
- **Login cookies.** The one-time link is a plain URL with an opaque token in the path (`/web-login/<token>`).
  The system browser stores the session cookie the backend sets on redeem and sends it back on `/#/home`, so the
  admin stays signed in. A `WebView` must opt into cookies (`CookieManager.setCookie`, `setAcceptCookie`, the
  `CookieManager` sync with `AccountManager`), keep it across the app's lifetime, and clear it on logout — all the
  session handling a browser already does. It also re-surfaces the same-origin risk the CSP + `frame-ancestors
  'none'` guards were added to avoid.
- **Tablet.** Same story, bigger surface; the browser handles it and installs as a WebAPK (the raster icons in
  the manifest make the install reliable).

**Verdict.** System browser is the default and the only path today. A `WebView` would cost a hand-rolled focus
and keyboard layer, cookie/session plumbing, and more attack surface, for no gain the browser does not already
give. It is the fallback to add only if a future requirement makes a link-unopenable browser unavoidable.

## Web admin on the TV: remote-friendliness

The pages the admin opens on the TV (home, TVs, captions, login, account, settings) are already usable with a
D-pad: `:focus-visible` gives every control a visible outline, and `.btn`, `.nav-link`, `.segmented` label and
form controls clear a 44px+ target (`test_web_ui_is_remote_friendly` checks the CSS carries both). The one real
gap is a password on a TV remote — which the one-time link removes, because the admin lands on `/#/home` signed
in. Remaining gaps, accepted as "as far as reasonable": the removable-chip delete buttons (`.chip-x`, 36px) live
on the phone-oriented prompt editor, not a page the admin opens by default, and a TV remote scrolls the page
rather than clicking individual small links.

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
key by version-name comparison is the latest; the shared checker compares it with the installed version name, and the flavor then
decides by the channel's `versionCode` against the installed one (the names are a fallback when a manifest has no code). The
downloaded APK must carry the package `dev.utubot.tv` and the same signing key, otherwise Android refuses it. The backend writes the file with
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

## Checking the HQ captions without YouTube

No test or check of this layer may contact YouTube. Debug builds of the flavor carry `CaptionsHarnessActivity` (`smarttubetv/src/stutubotDebug`,
not in release builds): it plays a media file through the real `ExoPlayerController`, `TrackSelectorManager` and subtitle view, with the
video id of your choice, so the captions of the mock backend can be checked on an emulator. `docs/development.md` ("Checking the HQ
captions") has the recipe, including the network namespace that keeps the emulator away from the internet.

## Checking the director's cuts without YouTube

`CutsHarnessActivity` (same debug-only folder) plays a media file through the real engine AND the real playback controllers: the
`PlaybackPresenter`'s `UtubotCutController` (and `SponsorBlockController`) get the video events, a cut request is created the way the
menu does it (`--es request_preset`, or `--ez await_prompt true` for the QR sheet), and the mock backend's cuts routes stand in for the
server. The recipe, with the keyevents of a seek and the log lines a check reads: docs/development.md, "Checking the director's cuts".

## Checking the Real-Debrid streams spike without YouTube

The spike's entry is on the TV: Settings, Updates, "Films developer entry" (off by default; stutubot flavor only), then "Films (developer)". Enter
the stream addon address, the Real-Debrid token, an IMDb id and optionally a skip list ("30,90;600,720", seconds), then "List streams" and choose one.
The address may contain `{token}`, which is replaced by the token (Torrentio: `https://host/realdebrid={token}`). Address and token stay in the app's
private preferences and are never logged or shown. Films play in the main player (issue 294): the details screen opens `PlaybackPresenter.openVideo(Video.fromFilm(UtubotFilmPlay))`.
`VideoLoaderController.loadFilm` opens the stream as one progressive source (no YouTube format fetch); the hand-written skip list is not
applied any more. Hooks in upstream files, all guarded by `Video.isFilm()`: `VideoLoaderController` (load, no queue, no next/previous, end closes
the player), `VideoStateController` (position and watched mark go to `UtubotFilmsProgress`, no YouTube history), `SuggestionsController`,
`SponsorBlockController`, `RemoteController`, `ErrorFixerController` (a stream error shows a message), `ExoPlayerController` (no HQ captions, format
log), `ViewManager.startParentView` (Back finishes the player, the details screen is under it), `VideoPlayerGlue.setFilmMode` (hides like,
subscribe, channel, chat, queue, segment blocker, search, share, add to playlist and info; adds "Streams", handled by
`UtubotFilmStreamsController`). The cuts button stays; `UtubotFilmPlay` carries `sourceKind()` "film", `sourceKey()` `imdb:tt…[:S1E2]`,
`releaseKey()` and `releaseDurationMs()` for the follow-up. Unit tests run against a local fake addon (`TinyHttpServer`), never a real service and never YouTube. What the owner
tests on the TCL: `docs/films-codec-checklist.md`.

## End-to-end test without a device

`UtubotBackendE2eTest` (skipped unless `UTUBOT_E2E_URL` and `UTUBOT_E2E_CODE` are set) pairs with a running backend and
exercises me, assess, verdict mapping, prompts, summary and captions through the Java client. Run the real backend
(`utubot serve`) with a config whose LLM `base_url` points at a mock OpenAI server, and create the code with `utubot user pair owner`.
