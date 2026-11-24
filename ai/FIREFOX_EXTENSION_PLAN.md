# u·tubot Firefox extension: implementation plan (issue #72)

Status: draft for owner approval. Nothing is implemented until Part 1's decisions are answered.
Scope: one extension for desktop Firefox and Firefox for Android that brings the u·tubot features of the TV app to
`www.youtube.com` and `m.youtube.com`, talking to the same backend over the same contract (`ai/CONTRACT.md`).

---

# Part 1: owner plan

## What the extension does

You install it in Firefox (computer or phone), type your server's address once (Import setup), enter a 6-digit pairing code, and
YouTube in the browser gains what the TV app has:

- **Marks and hiding** on video cards (clickbait, low quality, inflated, your topics), with the "mark only" switch.
- **Summaries**: the short glance summary for a card and the long Summary view with your prompt list.
- **AI answer** to the question a title asks.
- **HQ captions**: prepare them, see them appear while the video plays, kept on the device afterwards.
- **Director's cuts**: pick a preset or describe a cut, the skipped parts are jumped over while you watch.
- **Processed list**: the videos you recently processed, each saying what is ready; opening one plays it with its HQ captions.
- **Settings** in the same order as on the TV: Import setup, Pair with code, the switches, Prompts, Test connection, Advanced.

## What parity means

Every u·tubot feature of the TV app has a row in the parity matrix (Part 2, section 3) that says what the extension does on the
computer and on the phone. Same server, same account rules, same wording for server messages. Where the browser works differently
(mouse or touch instead of a remote), the action moves to the natural place, and the matrix says where.

## Out of scope

- The inherited player features of the TV app (SponsorBlock, video quality, the browse cache: YouTube's own site handles loading).
- Chrome, Safari, the YouTube Android app, embedded players on other sites, YouTube Music.
- The phone web UI's own features (voice description, saved presets, admin pages): the extension links to the web UI for those.
- APK self-update: Firefox updates the extension itself.

## Decisions needed from you

| # | Decision | Recommended | Why |
|---|---|---|---|
| D1 | How people get the extension | **Signed file on this repository's releases first (not listed in the add-on store), store listing later** | Available the day it is built, no store review to wait for, and it stays low-profile while we learn how often YouTube's page changes break it. Cost: on the phone the install is a few extra taps through a hidden Firefox menu, and automatic updates on the phone are not confirmed yet (see Risks). Listing in the store later fixes both and is a separate, public step you confirm then. |
| D2 | Manifest version | **Manifest V3** (no service worker, Firefox's event page) | The issue asks for V3 where Firefox supports it. Firefox supports it on both platforms. Mozilla's Android guide still says V2 is the safer choice, so checkpoint 1 proves V3 on an Android emulator before anything else is built; the code avoids V3-only features so a fallback to V2 would be a small manifest change. |
| D3 | Oldest Firefox supported | **Firefox 140 on the computer, 142 on Android** | These are the first versions with Firefox's built-in "this extension sends data" consent screen, which new extensions must use. Older versions would need our own consent screen. |
| D4 | A Mozilla add-on developer account and its signing keys | **You create the account and add two repository secrets** | Signing is required even for a file we host ourselves. Only you can create the account; the keys live only in repository secrets, never in the tree. |
| D5 | The extension's permanent ID | **`extension@utubot.dev`** | It can never change after the first signed version (an update with another ID installs as a second extension). It matches the app's `dev.utubot.tv`. |
| D6 | Plain-http servers | **Allowed for private addresses only** (home network, VPN), as in the TV app | A home server without a certificate keeps working. A public address must be https. |
| D7 | Where the plan's standing rule lives | **`AGENTS.md`, the pull request checklist and the contract** (this pull request adds the `AGENTS.md` line) | From now on every AI feature is planned, built and tested for the TV app and the extension, or the contract says why one side cannot have it. |

## Risks

- **YouTube changes its page.** The extension reads YouTube's page structure, which changes without notice. Captions and cuts are
  built on the standard video element, so they survive most changes; marks, hiding and the card buttons are the fragile part. All
  page knowledge is in one file, a failure degrades to "nothing shown" (never a broken page), and the owner's real-device pass is
  the check after each YouTube change.
- **No automated test may open YouTube** (repository rule). Tests run against hand-written stand-in pages, so a real YouTube
  difference is only found in your own use. This is the same position as the TV app.
- **Ads** play in the same video element. The extension pauses captions and cut skipping while an ad plays; that detection is
  page knowledge and can break.
- **Phone install and updates with a self-hosted file** are clumsy (hidden menu) and the automatic update path on Android is
  unconfirmed. Mitigation: the store listing (D1, later).
- **Mozilla's V3 support on Android** has had gaps. Mitigation: checkpoint 1.
- **Store review** (if listed later) may ask how to test without a server; we point reviewers to the mock backend.

## How you try it

1. After checkpoint 1: load the build in desktop Firefox (`about:debugging`), import your setup, pair, see "Paired as …".
2. After each later checkpoint: the same build gains one feature group; the pull request says what to click.
3. After checkpoint 9: download the signed file from the release page on the computer and the phone and use YouTube normally.
   On the phone: Settings, About Firefox, tap the logo five times, then Settings, "Install extension from file".

---

# Part 2: agent plan

## 1. Facts checked

Repository (commit `58b421ec`, `main`):

| Fact | Where |
|---|---|
| Bearer-token calls are never origin- or CSRF-checked; only cookie sessions and `POST /v1/auth/login` are | `ai-backend/src/utubot/app.py` `authenticate`, `check_csrf`, `check_same_origin`; `webroutes.py` `login` |
| `POST /v1/pair` and `GET /setup.json` are public and have no origin check | `ai-backend/src/utubot/app.py` (`pair`), `ai/CONTRACT.md` Addendum |
| The backend sends no CORS headers (no CORS middleware; CSP `connect-src 'self'`, `frame-ancestors 'none'`) | `ai-backend/src/utubot/app.py` `CSP`, `SECURITY_HEADERS` |
| Caption files accept the header or `?token=`; the TV uses the header only, scoped to the backend's scheme, host, port and path | `ai/CONTRACT.md` (`captions/{lang}.vtt`), `UtubotClient.authorizationFor`, `captionFile` |
| Endpoints the TV client calls: `health`, `pair`, `setup.json`, `me`, `assess`, `insight`, `summary`, `transcribe`, `transcript`, `prompts`, `prompts/import`, `prompts/refresh`, `prompts/default`, `captions` (GET, POST), `captions/{lang}.vtt`, `videos/{id}/cuts` (GET, POST), `cuts/{request_id}`, `processed` | `common/.../utubot/UtubotClient.java` |
| The TV does not call `ask`, `feedback`, `jobs`, `speech`, `cut-presets`, `me/settings` | same file (no such call) |
| Settings list and order | `UtubotSettingsPresenter.buildCategories`; keys in `UtubotSettings` (`assess`, `mark_only`, `answer_in_menu`, `summary_panel`, `auto_captions`, `auto_cuts`, `wait_ms`, `panel_delay_ms`, `browse_refresh_minutes`) |
| Video menu items: AI answer, u·tubot summary, Summary panel on/off, Prepare HQ captions, Director's cut… | `UtubotMenu.append` |
| Timing constants: assess wait 1200 ms (cap 3000) + 500 ms slack, 50 videos per call; panel delay 1/1.8/3/5 s; summary and insight `wait_ms` 20000; transcript polls 4 s (view) and 20 s (panel); retry 1 s to 10 min; captions poll 10 s, 2 h, 5 errors; cut follow `wait_ms` 10000, 30 min, 5 errors; cut length tolerance 2 s; skip entry window 2 s; caption file cap 4 MiB; verdict cache 2000 | `UtubotSettings`, `UtubotManager`, `UtubotPanelModel`, `UtubotCaptionsFollower`, `UtubotCutFollower`, `UtubotCutSkipper`, `UtubotCaptionStore`, `VerdictCache` |
| The cut's `transcript_hash` is parsed but not compared by the TV; the length check is the guard | `UtubotParser`, `UtubotModels`, `UtubotCutController` |
| Private-host rule for http (loopback, RFC1918, link-local, CGNAT, `.local`, `.lan`, `.internal`, `.home.arpa`, `.ts.net`, single-label) | `UtubotSetup.isPrivateHost`, `resolveUrl` |
| The mock backend is one stdlib Python file with setup, pair, me, assess, prompts, summary, insight, transcript, captions, cuts and `/__mock/*` switches, and no CORS headers | `scripts/emulator_mock_backend.py` |
| CI treats every path not in `NON_APP` as an app change, which also triggers an automatic APK release | `.github/workflows/utubot-ci.yml` (`NON_APP`, `release`) |
| APK release tags are `utubot-vX.Y.Z` (anchored regex in the backend sync, prefix filter in the app and CI); a tag `utubot-ext-vX.Y.Z` matches none of them | `ai-backend/src/utubot/appsync.py` `TAG_RE`, `common/src/stutubot/res/values/release_notes.xml`, `utubot-ci.yml` |
| There is no pull request template yet | `.github/` |
| Tests, CI, emulators and agents never contact YouTube; only the deployed backend does | `AGENTS.md`, `ai-backend/AGENTS.md`, `docs/development.md` ("Offline mode") |

Firefox (read 2026-11-24):

| Fact | Source |
|---|---|
| Firefox does not support `background.service_worker`; Manifest V3 uses `background.scripts` (a non-persistent event page). Android: "Background service workers aren't supported on Firefox for Android. Instead, use event pages." | [MDN background](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/background), [Developing extensions for Firefox for Android](https://extensionworkshop.com/documentation/develop/developing-extensions-for-firefox-for-android/) |
| The same Android guide still says "it's recommended you use Manifest V2 for extensions targeting Firefox for Android" because of known gaps; V3 has been accepted on Android since Firefox 109 | same guide, [Mozilla Discourse](https://discourse.mozilla.org/t/what-version-of-android-firefox-added-support-for-mv3/137342) |
| From Firefox 127 users are asked to grant V3 host permissions at install; Firefox for Android 128 added a permissions UI | [Manifest V3 updates, May 2024](https://blog.mozilla.org/addons/2024/05/14/manifest-v3-updates/) |
| In V3 content-script `fetch` follows the page's CORS; host permissions work only in extension pages (background) | [MDN content scripts](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Content_scripts) |
| The V3 default CSP is `script-src 'self'; upgrade-insecure-requests;`; an extension that needs `http:` overrides `content_security_policy` without that directive | [MDN extension CSP](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Content_Security_Policy) |
| Android compatibility of a signed version comes from `browser_specific_settings.gecko_android` in the manifest; the `gecko` id applies to it | [Changes to Android extension signing](https://blog.mozilla.org/addons/2023/10/05/changes-to-android-extension-signing/) |
| New extensions must declare `browser_specific_settings.gecko.data_collection_permissions`; the built-in consent exists from desktop 140 and Android 142 | [Firefox built-in data consent](https://extensionworkshop.com/documentation/develop/firefox-builtin-data-consent/), [announcement](https://blog.mozilla.org/addons/2025/10/23/data-collection-consent-changes-for-new-firefox-extensions/) |
| A self-distributed file must be signed through the add-on store (listed or unlisted); with `update_url` in the manifest Firefox installs higher versions from there; a web download does not install on Android (the file is installed from the hidden "Install extension from file" setting) | [Self-distribution](https://extensionworkshop.com/documentation/publish/self-distribution/), [Installing self-distributed extensions](https://extensionworkshop.com/documentation/publish/install-self-distributed/) |
| `web-ext lint` reports Android-incompatible keys and APIs; `web-ext run --target=firefox-android` runs on a device or emulator over adb; `web-ext sign` takes the store's API key and secret and needs an id in a V3 manifest | [Android guide](https://extensionworkshop.com/documentation/develop/developing-extensions-for-firefox-for-android/), [web-ext](https://extensionworkshop.com/documentation/develop/getting-started-with-web-ext/) |

Not verifiable from here (each has a checkpoint that settles it, section 11).

## 2. Decisions (all made)

1. **Directory**: `extension/` at the repository root, with its own `AGENTS.md`, `README.md` and `DEVLOG.md`.
2. **Manifest V3**, `background: {"scripts": ["background.js"]}` (event page, no `service_worker` key, no `persistent`).
   Nothing in the code depends on a V3-only API: toolbar access goes through one wrapper (`action`), permissions through
   `optional_host_permissions`. If checkpoint 1's Android check fails, the fallback is a V2 manifest variant from the same build
   script (`browser_action`, `optional_permissions`), and the plan continues unchanged.
3. **Minimum versions**: `gecko.strict_min_version` `140.0`, `gecko_android.strict_min_version` `142.0`.
4. **Add-on id** `extension@utubot.dev`. **Name** "u·tubot". Icons rendered from `assets/brand/` by `assets/brand/render.py`.
5. **Language and tooling**: plain JavaScript ES modules, no framework, no TypeScript. One bundler, `esbuild`, unminified, to
   produce `background.js` and `content.js` (content scripts cannot be modules). Dev dependencies are `esbuild`, `web-ext` and
   `eslint` only, pinned in `package-lock.json`. Node 22 LTS. No runtime dependency.
6. **Network only in the background.** Content scripts and pages never hold the token and never call the backend; they send named
   messages (`assess`, `summary`, `insight`, `transcribe`, `transcript`, `prompts*`, `captions*`, `cuts*`, `processed`, `setup*`,
   `pair`, `me`, `health`) and the background performs the fixed request. There is no generic "fetch this URL" message. The
   background accepts messages only from its own id (`sender.id`) and, for content scripts, only from the two YouTube origins.
7. **Storage**: `storage.local` holds the backend URL, token, user name, switches, panel delay, the session prompt and the
   setup's pending prompt-set URLs. Never `storage.sync`. `storage.session` holds the verdict cache (2000 entries), ready
   summaries (100) and the one-shot captions-open request. IndexedDB (background) holds the caption files: WebVTT only, at most
   4 MiB each, keyed `<video id>/<lang>`, never replaced, not cleared by a backend or token change (as `UtubotCaptionStore`).
   A change of URL or token clears the `storage.session` caches (as `UtubotManager`).
8. **Auth**: `Authorization: Bearer <token>` added by one function that sends it only to the stored backend (same scheme, host,
   port, path under the backend's). `?token=` is never used. Caption files are fetched by the background and handed to the
   content script as text.
9. **Host permissions**: required `https://www.youtube.com/*`, `https://m.youtube.com/*`. Optional `https://*/*`, `http://*/*`;
   at Import setup (a click) the extension requests exactly the typed origin, fetches `/setup.json`, and requests the
   `backend_url` origin too when it differs. Removing the backend releases the permission (`permissions.remove`).
   No other permission than `storage`.
10. **http**: `content_security_policy.extension_pages` is `script-src 'self'; object-src 'self'` (no
    `upgrade-insecure-requests`), and the setup code refuses `http` for a non-private host with the rule ported from
    `UtubotSetup.isPrivateHost`.
11. **Data consent**: `data_collection_permissions.required` = `["browsingActivity", "websiteContent", "authenticationInfo"]`
    (video ids and card text go to the user's own server; the token authenticates there), no optional entries.
12. **Captions in the page**: the standard text-track API on YouTube's `<video>` element (`video.addTextTrack` once per language
    label, cues as `VTTCue`, cues swapped on navigation because a track cannot be removed). No overlay element, no hook into
    YouTube's own caption menu. Reason: it needs no page structure, and it works in fullscreen and picture-in-picture.
    Contingency with a fixed trigger: if the owner's device pass shows YouTube suppressing native cues, the renderer behind
    `captions.js`'s `show(cues)` / `clear()` is replaced by an overlay inside the fullscreen-capable player container; nothing
    else changes.
13. **Cuts in the page**: a port of `UtubotCutSkipper` driven by the video element's `timeupdate` plus a 250 ms timer while a cut
    is on; a `seeking` event from the user wins and plays; the jump is `video.currentTime = end`. The cut is applied only while
    `|cut.duration_ms - video.duration * 1000| <= 2000` and no ad is playing. The sponsor-segment merge of the TV is not ported
    (the browser has no built-in sponsor skip).
14. **UI**: one host element with a closed shadow root, attached to the document (moved into `document.fullscreenElement` while
    one exists). It contains the u·tubot button, the panel (Summary, Answer, Captions, Cut), the passive glance card, toasts. DOM
    is built with `textContent` only (no `innerHTML`; a test greps for it). On the phone the panel is a bottom sheet.
15. **Page knowledge in one file**, `content/site.js`: site kind (`www` or `m`), video id from the URL, navigation detection
    (URL change polled every 500 ms plus `popstate`; no YouTube event names are required), card discovery (anchors whose `href`
    is a watch or shorts link), the card container (closest of a fixed list of renderer tag names), ad detection. A card whose
    container is not recognised is marked but never hidden.
16. **Android differences are decided per row in the matrix**; code branches only on site kind and on
    `runtime.getPlatformInfo().os`, in `site.js` and `ui/layout.js`.
17. **Tests never contact YouTube.** Unit tests on Node (`node --test`). End-to-end tests drive real Firefox (Selenium,
    geckodriver, temporary add-on) against stand-in pages and the mock backend on loopback (section 7).
18. **Backend and contract**: no endpoint, field or behaviour changes (section 8).
19. **Distribution**: unlisted signing with `web-ext sign --channel=unlisted`, the signed file attached to a GitHub Release tagged
    `utubot-ext-vX.Y.Z`, `update_url` pointing at `updates.json` on the repository's `extension-updates` branch (raw file URL,
    written by the release workflow). A store-listed variant (no `update_url`) is built by the same script and submitted only
    after the owner confirms (D1).
20. **Versions**: `extension/version` holds `major.minor`; the release workflow appends the patch counter the way
    `scripts/utubot_release.py next-version` does for the app, with its own tag prefix.
21. **Pairing device name**: "Firefox (desktop)" or "Firefox (Android)"; it is what the backend's job log shows as the client.
22. **Not built**: `ask`, `feedback`, `jobs`, voice, saved presets, admin pages (the TV app has none of them); keyboard shortcuts
    (`commands` does not exist on Android); embedded players; YouTube Music.

## 3. Feature-parity matrix

"Panel" is the extension's own panel on a watch page; "chip" is the small u·tubot button the extension adds to a card.

| # | TV feature (code) | Contract | Desktop Firefox | Firefox for Android |
|---|---|---|---|---|
| 1 | Import setup: typed host or URL, `/setup.json`, stores backend, defaults, then pairing (`UtubotSetup`, `UtubotSetupFlow`) | `GET /setup.json` | Options page, first item; opens on install; host permission asked for the typed origin first. `update_url` is ignored (APK only) | Same; the options page opens in a tab |
| 2 | Pair with code (`UtubotPairing`) | `POST /v1/pair`, `GET /v1/me` | Options page: 6 digits, then "Paired as <user>"; pending prompt sets imported after it | Same |
| 3 | First-launch offers (setup, then pairing; "Don't ask again") | none | Options page opens once on install; the toolbar popup shows "Import setup" until configured | Same (popup is in the extensions menu) |
| 4 | Test connection, Advanced URL and token (`UtubotConnectionTest`) | `GET /v1/health`, `GET /v1/me` | Options page | Same |
| 5 | Assess: one call per row emission, hide or mark, unfiltered on error or timeout (`UtubotManager.resolve`, `VerdictCache`) | `POST /v1/assess` | Cards found on Home, Subscriptions, Search, Channel and the watch sidebar are batched (at most 50, one call per 300 ms batch, `wait_ms` 1200); `hide` hides the card container, `mark` adds a coloured label; pending verdicts are asked again when the cards are next scanned | Same on `m.youtube.com` |
| 6 | Mark only, never hide | none (local switch; setup default) | Options switch | Same |
| 7 | AI answer in the video menu, answer in the label (`UtubotMenu`, `UtubotAnswerModel`) | `GET /v1/videos/{id}/insight` | Chip menu on a card and "Answer" tab of the panel; the chip shows `answer_short` when known and the switch is on | Same; chip tap opens the sheet |
| 8 | Summary panel mode: passive preview after the focus delay (`PanelCoordinator`, `FocusDebouncer`, `UtubotPanelView`) | `GET /v1/videos/{id}/summary?prompt=panel`, fallback first prompt of `GET /v1/prompts` on 400/404 | Hovering a card for the panel delay shows the passive glance card (bottom right, never takes focus); moving away drops the request; Escape hides it | No hover on touch: with the mode on, each card's chip opens the glance sheet on tap (explicit, so it counts as passive only in wording: it still requests `prompt=panel`) |
| 9 | Summary view: prompt list, long summary, session prompt (`UtubotSummaryOverlay`) | `GET /v1/prompts`, `GET /v1/videos/{id}/summary?prompt=<key>` | "Summary" tab of the panel and "Summary options" on the glance card: prompt list left, text right, source line, Retry | Bottom sheet with the prompt list as a selector above the text |
| 10 | Transcript states with the server's words, countdown, Transcribe in background, follow-up polling (`UtubotPanelModel`, `UtubotStateText`, `UtubotCountdown`) | `transcript_status` fields, `POST /v1/videos/{id}/transcribe`, `GET /v1/videos/{id}/transcript` | Same states, same intervals (4 s view, 20 s glance), in the panel, the glance card and the answer | Same |
| 11 | Metadata on every insight, summary, transcribe call (`UtubotMeta`) | query `title`, `channel`, `duration_s` | From the card or the watch page; `duration_s` from the video element when playing | Same |
| 12 | Prompts: list, choose default, Import from URL, Refresh all (`UtubotSettingsPresenter.showPrompts`) | `GET /v1/prompts`, `PUT /v1/prompts/default`, `POST /v1/prompts/import`, `POST /v1/prompts/refresh` | Options page, Prompts section | Same |
| 13 | Prepare HQ captions (`UtubotMenu.prepareCaptions`) | `POST /v1/videos/{id}/captions` | Chip menu and "Captions" tab | Same |
| 14 | HQ captions while playing: check at start, poll while queued or running, add and select when ready, "captions ready" toast (`UtubotCaptionsFollower`, `ExoPlayerController` hooks) | `GET /v1/videos/{id}/captions`, `GET .../captions/{lang}.vtt` | Follower in the content script; ready track becomes a native text track on the video element, selected by the rule of row 15, toast for a job that finished while playing. Track on/off and language are in the "Captions" tab (YouTube's own caption menu is not touched) | Same |
| 15 | Auto-select HQ captions switch; a user-requested track is selected whatever the switch says | none (local switch; setup default) | Options switch; same rule | Same |
| 16 | Permanent caption store, works without the backend (`UtubotCaptionStore`) | none | IndexedDB in the background; a stored video makes no request | Same |
| 17 | Director's cut picker: presets with state, apply or take off, ask for a build, kept parts (`UtubotMenu.showCuts`) | `GET /v1/videos/{id}/cuts`, `POST /v1/videos/{id}/cuts {"preset"}` | "Cut" tab and chip menu; picking a ready cut from a card opens the video with the cut carried (one-shot request, as `applyOnOpen`) | Same |
| 18 | "Describe on phone…" with QR (`UtubotCutQrView`) | `POST .../cuts {"await_prompt":true}`, `GET /cuts/{id}` | A keyboard exists, so: "Describe here" (text box, `POST .../cuts {"prompt"}`), and "Open cut sheet" which creates the waiting request and opens `<backend>/cuts/<id>` in a new tab (voice and saved presets live there). No QR code | Same |
| 19 | Cut while playing: ready cut announced with one-press Apply, or applied automatically; waiting or building request followed; skips with "Skipped 1:20" and a 5 s Back (`UtubotCutController`, `UtubotCutFollower`, `UtubotCutSkipper`) | `GET /v1/videos/{id}/cuts`, `GET /v1/cuts/{id}?wait_ms=10000` | Same flow; the toast has "Back" (returns to the skipped part); length rule ±2 s; paused during ads | Same |
| 20 | Apply ready cuts automatically | none (local switch) | Options switch | Same |
| 21 | Dimmed skipped parts on the seek bar (`UtubotCutSeekBar`) | none | A slim timeline in the "Cut" tab shows kept and skipped parts; kept parts are a clickable list (seek). YouTube's seek bar is not modified | Same |
| 22 | Sponsor-segment merge of a cut jump | none | Not applicable: the browser has no built-in sponsor skip. Recorded in the contract note | Not applicable |
| 23 | Processed section and opening a tile with its HQ captions (`UtubotProcessedSection`, `UtubotProcessedOpen`) | `GET /v1/processed?limit=50` | Extension page "Processed" (from the popup and the panel): tiles with the processed line, empty and failed states; a tile opens the watch page with a one-shot captions-open request | Same, opened from the extensions menu |
| 24 | Working indicator and busy badge (`UtubotWorkingIndicator`, `UtubotBadgeController`, `UtubotBusyTracker`) | none | Three-dot indicator in the panel, glance card and answer; toolbar badge while calls are in flight (shown after 300 ms) | Indicator only (no toolbar badge) |
| 25 | Caches dropped on a backend or token change (`UtubotManager`) | none | `storage.session` caches cleared; caption store kept | Same |
| 26 | Browse cache, "Browse refresh" minutes, "Refresh section" (`UtubotBrowseCache`) | none | Not applicable: YouTube's site owns its loading. Recorded in the contract note | Not applicable |
| 27 | App self-update from the setup's `update_url` (`UtubotUpdates`) | `GET /app/update.json` | Not applicable: Firefox updates extensions (`update_url` of the manifest, or the store) | Not applicable |
| 28 | Own identity, About links, unofficial disclaimer | none | Name, icons, About section in the options page with this repository's links and the disclaimer | Same |

## 4. Architecture

```
extension/
  manifest.json            source manifest (release shape, no loopback match)
  version                  major.minor
  build.mjs                esbuild + manifest variants: unlisted, listed, test
  src/background/          main.js (message router), client.js, auth.js, setup.js, permissions.js,
                           cache.js (storage.session), captionstore.js (IndexedDB), busy.js
  src/shared/              models.js (parsers), statetext.js, panelmodel.js, countdown.js, cutskipper.js,
                           vtt.js, policy.js, meta.js, messages.js (message names), debounce.js
  src/content/             main.js, site.js, cards.js, player.js, captions.js, cuts.js, followers.js
  src/content/ui/          host.js (shadow root), panel.js, glance.js, sheet.js, toast.js, layout.js, styles.css
  src/pages/               options.html/js, processed.html/js, popup.html/js
  src/_locales/en/         messages.json (strings carried over from utubot_strings.xml)
  tests/unit/              node --test
  tests/fixtures/site/     www/*.html, m/*.html (hand-written stand-ins)
  tests/e2e/               pytest + selenium (uv project), conftest.py starts the mock backend and the fixture server
```

- **Background (event page)** is a stateless executor: one message in, one backend request, one answer. It may be unloaded when
  idle, so nothing lives only in its memory: caches are in `storage.session`, timers (followers, countdowns, hover delay) run in
  the content script of the tab that needs them, and a long poll never asks for more than 20 s (`wait_ms` cap, below Firefox's
  idle limit).
- **Content script** (`document_idle`, both YouTube origins, top frame only) starts `site.js` navigation watching, then per page:
  `cards.js` on browse pages (a `MutationObserver` batches new anchors), `player.js` on watch pages (waits for the `<video>`
  element, emits video id changes, ad state, duration), with `captions.js`, `cuts.js` and the panel bound to it.
- **Desktop page** (`www.youtube.com`) and **mobile page** (`m.youtube.com`) share every module. They differ in `site.js` (the
  list of card container names, the title lookup) and `layout.js` (panel docked right against bottom sheet, hover against chip).
  Both sites are single-page apps that reuse one video element: every per-video object is torn down on a video id change.
- **Captions hook**: `captions.js` owns one text track per language label on the video element; on a ready answer it parses the
  WebVTT (`vtt.js`: header, timings, cue text, `[S1]` prefixes kept as text) and adds cues; on a video change it removes the cues
  and sets the track to `disabled`; while an ad plays the track is `hidden`.
- **Cuts hook**: `cuts.js` owns the active cut, the skipper, the toast, the Apply offer, and the length and ad guards.
- **Messages**: names in `shared/messages.js`; the router rejects unknown names, senders that are not this extension, and video
  ids that do not match `^[A-Za-z0-9_-]{11}$`.
- **CORS and origin**: the backend needs no change because background requests with a granted host permission are not subject to
  CORS and bearer calls are not origin-checked (section 1). The e2e mock answers no `OPTIONS` and sends no CORS headers, so a
  regression that moves a call into a content script fails a test.
- **Errors**: a failed assess leaves cards untouched; a missing video element, an unknown page shape or a thrown error in
  `site.js` turns that feature off for the page and logs once under the `u-tubot` prefix. Nothing is ever removed from the page
  except by a `hide` verdict.

## 5. Privacy

`docs/privacy.md` gains a "Firefox extension" section: what leaves the browser (the same fields as the TV: card metadata for
assess, the video id with title, channel and duration, the pairing code and device name, the token only to the backend), that
YouTube cookies, account and history are never read or sent, that thumbnails of the Processed page load from YouTube's image
host, and that nothing goes to the authors. The store listing (if any) links to it.

## 6. Offline and YouTube-access rules

- No test, CI job, emulator run or agent check may load any YouTube or Google address. This includes thumbnails.
- Stand-in pages are hand-written from the structure `site.js` relies on (anchors with watch links inside the listed container
  names, one `<video>` element, a title element); they are not copies of YouTube pages and contain no YouTube script.
- A fixture video is generated at test time with `ffmpeg` (test pattern, 240 s, low resolution) and served from loopback.
- The **test variant** of the build (`build.mjs --variant test`) adds `http://127.0.0.1/*` to the content-script matches and
  host permissions and enables the `<meta name="utubot-fixture-site" content="www|m">` override. A unit test fails if the
  unlisted or listed variant contains a loopback match or the override.
- Firefox in e2e runs with a proxy that refuses and records everything except loopback, with Firefox's own background services
  off (updates, telemetry, safe browsing, remote settings, captive portal). The suite fails if the proxy saw any request.
  Where the host allows it the whole run is also placed in a network namespace with loopback only (as the emulator recipe in
  `docs/development.md`).
- The real-YouTube check is the owner's own use of a released build. Agents never do it.

## 7. Test approach

| Layer | Tool | Covers |
|---|---|---|
| Unit | `node --test`, no browser | client URLs and query fields, auth scoping, setup resolution and the private-host rule, parsers, state text, panel model and countdown (fake clock), cut skipper (the cases of `UtubotCutSkipperTest`), VTT parser, policy, verdict cache, manifest variants |
| Static | `eslint`, `web-ext lint` (with `gecko_android` set it reports Android-incompatible keys and APIs), a grep for `innerHTML` and for any host other than the placeholders | both platforms |
| End to end, desktop | pytest + Selenium + geckodriver, headless Firefox, test variant, `scripts/emulator_mock_backend.py`, fixture server | setup and pairing, marks and hiding, glance and Summary view with every transcript state, answer, captions while playing and from the store, cuts, Processed |
| End to end, mobile layout | same harness, `m` fixtures, 360 px viewport, touch events | the Android behaviours of the matrix in the mobile page shape |
| Android runtime | Android emulator in a no-route network namespace, Firefox for Android installed from Mozilla's APK, `web-ext run --target=firefox-android`, `adb reverse` to the mock and fixture servers | install, options page, permission prompt, storage, background messaging, captions and a cut on the fixture watch page. Run at checkpoints 1 and 8, by an agent, not in CI |
| Real YouTube | the owner, a released build | page-structure drift |

The mock backend gains only what the extension's tests need and the TV's do not have: `GET /v1/processed` (it has none today), and a
request log endpoint `GET /__mock/requests` (method, path, whether `Authorization` was present, never its value).

## 8. Backend and contract changes

- **Backend code: none.** No new endpoint, field, header or CORS rule.
- **`ai/CONTRACT.md`**: a new section "Clients" (text in section 10) listing the TV app and the Firefox extension, the rows that
  one side does not have and why (matrix rows 18, 22, 26, 27), and the sentence that a browser extension authenticates with the
  bearer token from its background context, never with the session cookie or `?token=`.
- **`scripts/emulator_mock_backend.py`**: the two additions of section 7.
- **`docs/`**: `docs/install.md` (Firefox section), `docs/privacy.md` (section 5), `docs/development.md` (build, tests, the
  no-YouTube harness), `README.md` (Features).

## 9. Build, signing, distribution

- `node build.mjs --variant unlisted|listed|test` writes `extension/dist/<variant>/`; `web-ext build` zips it.
- Signing: `web-ext sign --channel=unlisted` with `WEB_EXT_API_KEY` and `WEB_EXT_API_SECRET` from repository secrets
  (`AMO_JWT_ISSUER`, `AMO_JWT_SECRET`). The keys are never committed, printed or written to an artifact; `extension/.gitignore`
  lists `.amo-credentials`, `web-ext-artifacts/`, `dist/`.
- Release workflow `.github/workflows/utubot-extension-release.yml` (`ubuntu-24.04`, guarded to this repository like the APK
  release, started by CI on a push to `main` that changed `extension/` since the newest `utubot-ext-v*` tag, or by hand): resolve
  the version, build, lint, unit tests, sign, create the tag and the GitHub Release with `u-tubot-<version>.xpi` and
  `SHA256SUMS`, then commit `updates.json` (id, version, link to the release asset, `update_hash`, `strict_min_version`) to the
  `extension-updates` branch.
- The unlisted manifest's `update_url` is the raw URL of that file. The listed variant has none and is uploaded by hand by the
  owner (or with `web-ext sign --channel=listed`) after D1's second step is confirmed.
- Install instructions (`docs/install.md`): desktop, open the `.xpi` link or "Install Add-on From File"; Android, save the file,
  unlock the hidden menu, "Install extension from file".

## 10. The standing rule (exact texts)

`AGENTS.md` (added by this pull request):

> - Two clients, one feature set: every new or changed AI feature is specified, built and tested for the TV app (`stutubot`
>   flavor) and the Firefox extension (`extension/`, plan in `ai/FIREFOX_EXTENSION_PLAN.md`) in the same pull request or in two
>   linked ones. If one client cannot have it, `ai/CONTRACT.md` ("Clients") says which and why. A plan or pull request for an AI
>   feature that names only one client is incomplete.

`.github/pull_request_template.md` (new, checkpoint 0):

```
- [ ] AI feature parity: this change works in the TV app and the Firefox extension, or `ai/CONTRACT.md` ("Clients") says why
      one of them does not have it. (Not an AI feature: tick and write "n/a".)
- [ ] `ai/CONTRACT.md` changed together with the code that changes the wire.
- [ ] No test or check contacts YouTube; no host, token or key in the tree.
```

`ai/CONTRACT.md` (checkpoint 0), after "App behaviour summary":

> ## Clients
>
> Two clients speak this contract: the TV app and the Firefox extension (`extension/`). A feature of this contract is built for
> both. Exceptions, each with its reason: the QR sheet of "Describe on phone…" (TV only; the extension has a keyboard and opens
> the cut sheet in a tab), the sponsor-segment merge of a cut jump (TV only; the browser has no built-in sponsor skip), the
> browse cache (TV only; YouTube's site owns its loading), `GET /app/update.json` (TV only; Firefox updates extensions). The
> extension sends the bearer token from its background context only, never a session cookie and never `?token=`.

## 11. Checkpoints

Tiers follow the repository's model policy: **Fast** for straightforward implementation from this plan, **Heavy** for the
tricky parts. Every checkpoint ends with a clean-context review by the same tier that implemented it (a separate reviewer with
the plan, the diff and the evidence, never the implementer's own session), and its findings are fixed before the next one
starts. The plan itself and the final outcome are reviewed by the plan reviewer. One pull request per checkpoint, each updating
`extension/DEVLOG.md`.

| # | Scope | Main files | Done when (each is a test or a recorded check) | Tests | Tier |
|---|---|---|---|---|---|
| 0 | Skeleton and rules: `extension/` with manifest, build script, three variants, lint, empty background and content script; CI job; `NON_APP` gains `extension/`; PR template; contract "Clients" section; `extension/AGENTS.md` | `extension/*`, `.github/workflows/utubot-ci.yml`, `.github/pull_request_template.md`, `ai/CONTRACT.md` | `web-ext lint` has no errors for both platforms; a pull request touching only `extension/` runs the extension job and neither the app job nor an APK release; the release variants contain no loopback match | unit: manifest variants; CI run on the pull request | Fast |
| 1 | Connection: client, auth scoping, setup import with permission request, pairing, test connection, advanced, options page; the e2e harness with proxy guard; **Android proof of Manifest V3** | `src/background/{client,auth,setup,permissions,main}.js`, `src/pages/options.*`, `tests/e2e/conftest.py`, `scripts/emulator_mock_backend.py` | e2e: import `127.0.0.1:<port>`, pair with the mock's code, "Paired as owner" shown, `GET /v1/me` carried the header, `/setup.json` and `/v1/pair` did not; a request to an `http` public host is refused; the mock saw no `OPTIONS`; the proxy saw nothing. Recorded Android emulator run: install, permission prompt, pairing, and a 20 s held request answered after the background went idle. If the Android run fails on a V3 gap, the V2 variant is added here and the result written into this plan | unit: client, auth, setup, private hosts; e2e: setup and pairing; Android runtime check | Heavy |
| 2 | Site layer: site kind, navigation, video id, card discovery and containers, ad state, player lifecycle; fixtures for both sites | `src/content/{site,cards,player,main}.js`, `tests/fixtures/site/**` | e2e on `www` and `m` fixtures: cards added after load are found once, a simulated in-page navigation tears down and rebuilds, the video id and duration events fire, an unknown page shape logs once and changes nothing | unit: URL and id parsing; e2e: discovery, navigation | Heavy |
| 3 | Assess: batching, verdict cache, marks, hiding, mark only, answer in label, pending re-ask, caches dropped on connection change | `src/content/cards.js`, `src/shared/policy.js`, `src/background/cache.js` | e2e: a `hide` verdict hides its card and a `mark` shows its label on both fixtures; with mark only the hidden card is shown with a mark; a mock that answers after 5 s or with 500 leaves every card visible; one call carries at most 50 videos; an unrecognised container is never hidden | unit: policy, cache, batcher; e2e: the cases above | Fast |
| 4 | Summaries and answer: glance card (hover and chip), Summary view with prompts and session prompt, AI answer, every transcript state, countdown, transcribe and follow-up, working indicator, busy badge, prompts section of the options page | `src/shared/{panelmodel,statetext,countdown}.js`, `src/content/ui/*`, `src/pages/options.*` | e2e with the mock's modes: `ready`, `needs_transcript` (server `message` shown, Transcribe starts the job and the summary arrives), `delayed` (server `error`, countdown, retry not before `retry_after_s`), `failed` with and without `reason`, `auto_transcribe`; requests carry `title`, `channel`, `duration_s`; `prompt=panel` falls back on 404; hover shorter than the delay sends nothing; the `m` fixture opens the sheet from the chip | unit: panel model and state text (ported cases of `UtubotPanelModelTest`, `UtubotStateTextTest`); e2e as listed | Heavy |
| 5 | HQ captions: prepare, follower, VTT parser, native text track, auto-select rule, toast, caption store, ad pause | `src/content/{captions,followers}.js`, `src/shared/vtt.js`, `src/background/captionstore.js` | e2e on the fixture watch page with the generated video: a job that turns ready while playing adds a showing track whose active cue text matches the mock's file at a known time, with the toast; with auto-select off the track is listed and not showing; after a browser restart with the mock stopped the stored track still shows and no request is made; a file over 4 MiB or without the WEBVTT header is not stored; a video change clears the cues | unit: VTT parser, follower (ported cases of `UtubotCaptionsFollowerTest`), store rules; e2e as listed | Heavy |
| 6 | Director's cuts: picker, build request, "Describe here", "Open cut sheet", follower, ready offer and automatic apply, skipper, toast with Back, timeline and kept parts, carried cut from a card, guards | `src/content/cuts.js`, `src/shared/cutskipper.js`, `src/content/ui/panel.js` | e2e: with the mock's cut, playback crossing 60 s continues at 108 s and the toast shows "Skipped 0:48"; Back returns into the skipped part and it plays; a user seek into a skipped part plays; a cut built for 200 s on the 240 s video is refused with the message; a request that becomes ready while playing is applied from the current position; automatic apply applies without the offer; nothing is skipped while the ad flag is set | unit: skipper (ported cases of `UtubotCutSkipperTest`, without sponsor segments), follower; e2e as listed | Heavy |
| 7 | Processed page and its open, popup, About, first-run page | `src/pages/{processed,popup}.*` | e2e: tiles in the mock's order with the processed line; empty and failed states; a tile opens the fixture watch page and its HQ track is showing with auto-select off; the one-shot request does not carry to a second open; no image request leaves loopback in the test | unit: tile text (ported cases of `UtubotProcessedTilesTest`); e2e as listed | Fast |
| 8 | Android pass and mobile polish: sheet layout, touch targets, the full Android runtime check, parity audit of the matrix against the build | `src/content/ui/{layout,sheet}.js`, `extension/README.md` | every matrix row has a passing test or a recorded Android check named next to it in `extension/README.md`; the recorded emulator run covers install, setup, a mark, a summary, captions and a cut; no horizontal scroll at 360 px | e2e mobile layout; Android runtime check | Heavy |
| 9 | Release: version script, signing workflow, `updates.json` branch, install docs, privacy docs, README | `.github/workflows/utubot-extension-release.yml`, `scripts/`, `docs/install.md`, `docs/privacy.md`, `README.md` | a dry run of the workflow (signing step skipped without secrets) produces the unsigned package, checksums and a valid `updates.json`; with the owner's secrets one signed release exists, installs on desktop Firefox, and a second release updates the installed copy; the tree and the logs contain no key | unit: version and `updates.json`; workflow dry run; owner check of install and update | Fast |
| 10 | Owner's real-device pass and fixes; then, only on the owner's word, the store listing | `src/content/site.js`, fixtures | the owner used a released build on desktop and Android on real YouTube and each matrix row is ticked or has an issue; every fix adds the page shape that broke to the fixtures | regression fixtures | Heavy |

## 12. CI

- New job `extension` in `.github/workflows/utubot-ci.yml`, `runs-on: ubuntu-24.04` (this repository is public: hosted runners
  only, never self-hosted). It runs when `extension/`, `ai/CONTRACT.md`, `scripts/emulator_mock_backend.py` or the pipeline
  itself changed: Node 22, `npm ci`, `eslint`, unit tests, build of the three variants, `web-ext lint`, then `uv sync --frozen`
  in `extension/tests/e2e`, `ffmpeg`, Firefox and geckodriver, and the e2e suite headless. Actions are pinned by SHA like the
  existing ones.
- `changes` gains the output `extension`; `NON_APP` gains `extension/` so an extension change is not an app change and never
  starts an APK release; the `release` job's conditions are untouched.
- The extension release is its own workflow (section 9) and needs the extension job green on the commit.
- The Android runtime check is not in CI (it needs an emulator and a Firefox APK); its evidence is the recorded log of
  checkpoints 1 and 8.

## 13. Could not be verified from here

| Item | Why | Settled by |
|---|---|---|
| The exact element names of YouTube's desktop and mobile pages (card containers, ad marker) | agents never load YouTube | checkpoint 10 (owner), with the "never hide an unknown container" rule until then |
| YouTube leaving native text-track cues visible on its video element | same | checkpoint 10; contingency in decision 12 |
| Manifest V3 behaving on current Firefox for Android (Mozilla's guide still prefers V2) | no device here | checkpoint 1 |
| A pending message answer keeping the event page alive for a 20 s long poll | documented only in general terms | checkpoint 1 test |
| `http` requests to a private address from the background once `upgrade-insecure-requests` is removed | MDN states the opt-out; not tried | checkpoint 1 test against the loopback mock |
| Firefox for Android applying `update_url` updates to a file-installed extension, and accepting a raw file URL for `updates.json` | not documented for Android | checkpoint 9 (owner check); the store listing is the fallback |
| Whether sending card data to the user's own server needs the three consent categories or fewer | Mozilla's page does not cover self-hosted servers | the signing validator at checkpoint 9; declaring them is the safe side |
| `utubot.dev` as the id's domain part | an add-on id needs no real domain, but it is permanent | owner decision D5 |
