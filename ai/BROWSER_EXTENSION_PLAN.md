# u·tubot browser extension: implementation plan (issue #72)

Status: plan review approved at revision `129048d0`; this revision adds the owner's later directions (other browsers,
lessons from existing extensions, an early MVP, the web UI companion) and waits for the owner's decisions (Part 1) and a
re-check. History: section 14.
Scope: one extension, Firefox first (desktop and Android), Chromium browsers on desktop after it, that brings the u·tubot
features of the TV app to `www.youtube.com` and `m.youtube.com`, talking to the same backend over the same contract
(`ai/CONTRACT.md`).

---

# Part 1: owner plan

## What the extension does

You install it in the browser, type your server's address once (Import setup), enter a 6-digit pairing code, and YouTube in
the browser gains what the TV app has:

- **Marks and hiding** on video cards (clickbait, low quality, inflated, your topics), with the "mark only" switch.
- **Summaries**: the short glance summary for a card and the long Summary view with your prompt list.
- **AI answer** to the question a title asks.
- **HQ captions**: prepare them, see them appear while the video plays, kept on the device afterwards.
- **Director's cuts**: pick a preset or describe a cut, the skipped parts are jumped over while you watch.
- **Processed list**: the videos you recently processed, each saying what is ready; opening one plays it with its HQ captions.
- **Settings** in the same order as on the TV: Import setup, Pair with code, the switches, Prompts, Test connection, Advanced.

## First: an MVP you can use

The first checkpoints (0 to 9b) give a signed build for **desktop Firefox** with the smallest useful set:

- Import setup and pairing.
- On a video's page: the summary of that video (the short one and the long Summary view with your prompts).
- HQ captions on the playing video (ready ones shown, a running job followed, kept afterwards).
- A ready director's cut offered and its skipped parts jumped over.

Estimated at about 85 local-agent hours, roughly one and a half to two weeks of calendar time with reviews (section 17; an
estimate, not a measurement). You look at it on real YouTube twice on the way (after checkpoints 5 and 7, a few minutes
each), and it needs your Mozilla account and signing keys (D4) by checkpoint 9. Marks on cards, the AI
answer, the cut picker, the Processed list, the phone and the other browsers follow after it.

## What parity means

Every u·tubot feature of the TV app has a row in the parity matrix (Part 2, section 3) that says what the extension does on the
computer and on the phone. Same server, same account rules, same wording for server messages. Where the browser works differently
(mouse or touch instead of a remote), the action moves to the natural place, and the matrix says where.

## Other browsers

- **Firefox on the computer and on Android**: the main target. The phone target is Firefox for Android.
- **Chrome, Edge, Brave on the computer**: the same code with a small per-browser layer, built and tested after the MVP
  (checkpoints 19 and 20). Nothing in the Firefox work waits for it.
- **Chromium browsers on phones**: not planned. Chrome for Android runs no extensions, Kiwi was shut down in 2025, and Edge for
  Android only has experimental support.

## Later: companion of the web UI

Mid-term the extension becomes the companion of the server's phone web page: pair the extension from the web page instead of
typing a code, jump from a YouTube video to its page on your server and back, share settings and prompts. Nothing of it is in
the MVP; the plan only makes sure the first version does not block it (Part 2, section 18). No decision is needed from you now.

## Out of scope

- The inherited player features of the TV app (SponsorBlock, video quality, the browse cache: YouTube's own site handles loading).
- Safari, the YouTube Android app, embedded players on other sites, YouTube Music.
- The phone web UI's own features (voice description, saved presets, admin pages): the extension links to the web UI for those.
- APK self-update: the browser updates the extension itself.

## Decisions needed from you

"Changed" marks what differs from the version the review approved.

| # | Decision | Recommended | Why |
|---|---|---|---|
| D1 (changed) | How people get the Firefox build | **A signed file kept in this repository (its own branch, not the Releases page, not the add-on store), first published at the end of the MVP (checkpoint 9); a new version only when we raise the version number; store listing later** | Available the day the MVP works, no store review to wait for, low-profile while we learn how often YouTube's page changes break it. It stays off the Releases page on purpose: the TV app and the server read that page to find APK updates. Cost: on the phone the install is a few extra taps through a hidden Firefox menu, and automatic updates on the phone are not confirmed yet. Listing in the store later fixes both and is a separate, public step you confirm then. |
| D2 (changed) | Manifest version | **Manifest V3 on every browser** (Firefox's event page, Chromium's service worker) | The issue asks for V3, and one V3 codebase is what makes Chrome cheap to add. Caution: the mature YouTube extensions we read still ship V2 on Firefox, and Mozilla's Android guide prefers V2. So the Android proof (checkpoint 10, right after the MVP) can switch the Firefox build to V2 with a manifest change; the MVP on desktop Firefox does not depend on it. |
| D3 | Oldest Firefox supported | **Firefox 140 on the computer, 142 on Android** | The first versions with Firefox's built-in "this extension sends data" consent screen, which new extensions must use. |
| D4 (changed) | A Mozilla add-on developer account and its signing keys | **Needed by checkpoint 9 (the MVP release), not at the end.** You create the account, add two repository secrets, make the parity check a required check for `main`, and switch releases on with one repository variable | Signing is required even for a file we host ourselves. Only you can create the account; the keys live only in repository secrets. Until you switch it on, nothing tries to release, and the MVP can still be loaded by hand for testing. |
| D5 | The extension's permanent Firefox ID | **`extension@utubot.dev`** | It can never change after the first signed version. It matches the app's `dev.utubot.tv`. |
| D6 | Plain-http servers | **Allowed for private addresses only** (home network, VPN), as in the TV app | A home server without a certificate keeps working. A public address must be https. |
| D7 (changed) | The standing rule | **In force now, with a transition**, worded for the "browser extension" (in `AGENTS.md`, the pull request checklist and the contract) | Every AI feature is planned, built and tested for the TV app and the extension, or the contract says why one side cannot have it. Until the extension has caught up (checkpoint 18), a new AI feature only has to add its row to this plan's matrix. |
| D8 (new) | How people get the Chrome/Edge/Brave build | **A zip in the same repository branch, installed with "Load unpacked", first; the Chrome Web Store (unlisted) later, on your word** | Chrome does not install an extension file from outside its store on Windows and macOS, so the only store-free way is developer mode's "Load unpacked": fine for you, no automatic updates. The store needs a developer account with a one-time fee and a review; it is the real way to distribute and a public step, so it waits for your word. Needed at checkpoint 20, not before. |

Already decided by you, recorded in the plan: the extension stays MIT. Other extensions' GPL code is read to learn how they
handle YouTube and is never copied; only permissively licensed code may be copied, with attribution.

## Risks

- **YouTube changes its page.** The extension reads YouTube's page structure, which changes without notice. Captions and cuts are
  built on the standard video element, so they survive most changes; marks, hiding and the card buttons are the fragile part. All
  page knowledge is in one file, a failure degrades to "nothing shown" (never a broken page), and your own use is the check
  after each YouTube change. What other extensions do about it is in Part 2, section 15.
- **No automated test may open YouTube** (repository rule). Tests run against hand-written stand-in pages, so a real YouTube
  difference is only found in your own use: two short looks during the MVP (after checkpoints 5 and 7), then the MVP itself. This is the same position as the TV app.
- **Our captions use a browser feature no extension we read uses on YouTube** (the video element's own subtitle tracks). If
  YouTube hides them, the fallback is drawing them ourselves. That is why captions are in the MVP: you see it early.
- **YouTube's own scripts can see what the extension puts in the page**: mark labels, which cards are hidden, and the caption
  text. Your server address, token and user name are never put in the page.
- **Ads** play in the same video element. The extension pauses captions and cut skipping while an ad plays. Ads stitched into
  the video itself shift the clock: a cut is then held back (the lengths differ), captions can run shifted. The extension
  does not correct the shift in this version.
- **Phone install and updates with a self-hosted file** are clumsy (hidden menu) and the automatic update path on Android is
  unconfirmed. Mitigation: the store listing (D1, later).
- **Manifest V3 on Firefox for Android** has had gaps, and on the phone Firefox does not show that an extension is waiting for
  permission to run on a site. Mitigation: the Android proof (checkpoint 10), and an "Allow on YouTube" button in the extension.
- **Store reviews** (if listed later) may ask how to test without a server; we point reviewers to the mock backend.

## How you try it

Only you ever open real YouTube with it; no agent or test does.

1. After checkpoint 4: load the build in desktop Firefox (`about:debugging`), import your setup, pair, see "Paired as …".
2. After checkpoint 5, **first look at real YouTube** (unsigned build, loaded the same way): open a video, then another one
   from the suggestions, and open the extension's popup. It shows what the extension found on the page (player, video, ad,
   which navigation signal fired). You send us that text or a screenshot; nothing else works yet. This is where a wrong
   assumption about YouTube's page is cheap to fix.
3. After checkpoint 6 the summary shows on a video page. After checkpoint 7, **second look**: prepare captions for a video
   and watch it; the popup also says whether the caption track is on and visible. After checkpoint 8 a ready cut skips.
4. After checkpoint 9 the release machinery exists. The whole MVP is then reviewed once more as one piece; after that you
   switch releases on (D4) and the first signed file is published.
5. Checkpoint 9b, the MVP in use: download the signed file (the link is in `docs/install.md`), Add-ons, the cog, "Install
   Add-on From File", and use YouTube normally for a few days. What you report is fixed in this checkpoint or moved to a named
   later one; it closes when your list is empty.
6. After checkpoint 18: the same on the phone. Settings, About Firefox, tap the logo five times, then Settings, "Install
   extension from file".
7. After checkpoint 20: Chrome, Edge or Brave with "Load unpacked".

---

# Part 2: agent plan

## 1. Facts checked

Repository (commit `58b421ec`, `main`):

| Fact | Where |
|---|---|
| Bearer-token calls are never origin- or CSRF-checked; only cookie sessions and `POST /v1/auth/login` are | `ai-backend/src/utubot/app.py` `authenticate`, `check_csrf`, `check_same_origin`; `webroutes.py` `login` |
| Without a bearer token `authenticate` falls back to the web UI's session cookie (safe methods skip CSRF) | `ai-backend/src/utubot/app.py` `authenticate` |
| `POST /v1/pair` and `GET /setup.json` are public and have no origin check | `ai-backend/src/utubot/app.py` (`pair`), `ai/CONTRACT.md` Addendum |
| The backend sends no CORS headers (no CORS middleware; CSP `connect-src 'self'`, `frame-ancestors 'none'`) | `ai-backend/src/utubot/app.py` `CSP`, `SECURITY_HEADERS` |
| Caption files accept the header or `?token=`; the TV uses the header only, scoped to the backend's scheme, host, port and path | `ai/CONTRACT.md` (`captions/{lang}.vtt`), `UtubotClient.authorizationFor`, `captionFile` |
| Endpoints the TV client calls: `health`, `pair`, `setup.json`, `me`, `assess`, `insight`, `summary`, `transcribe`, `transcript`, `prompts`, `prompts/import`, `prompts/refresh`, `prompts/default`, `captions` (GET, POST), `captions/{lang}.vtt`, `videos/{id}/cuts` (GET, POST), `cuts/{request_id}`, `processed` | `common/.../utubot/UtubotClient.java` |
| Client caption upload (`POST /v1/videos/{id}/captions/client`): the TV sends the original-language and user-language tracks its player got, once per video per session; the extension does not read YouTube's own caption tracks yet, so it sends none until it does (then the same body, `format` as the page's timed text gives it) | `ai/CONTRACT.md`, `UtubotClientCaptions` |
| The TV does not call `ask`, `feedback`, `jobs`, `speech`, `cut-presets`, `me/settings` | same file (no such call) |
| Settings list and order | `UtubotSettingsPresenter.buildCategories`; keys in `UtubotSettings` (`assess`, `mark_only`, `answer_in_menu`, `summary_panel`, `auto_captions`, `auto_cuts`, `cut_jump`, `wait_ms`, `panel_delay_ms`, `browse_refresh_minutes`) |
| Video menu items: AI answer, u·tubot summary, Summary panel on/off, Prepare HQ captions, Director's cut… | `UtubotMenu.append` |
| Assessed sections: Home `home`; Subscriptions and channel groups `subscriptions`; Search `search`; a channel page `channel`; Suggestions `other`; History, playlists, Watch later and channel lists are not assessed | `UtubotPolicy.sectionName` |
| `VideoMeta` fields the TV fills: `video_id`, `title`, `channel`, `channel_id`, `duration_s`, `is_short`, `is_live`, `description`, `views`, `published` | `UtubotMeta` |
| Cut requests also carry `is_live` in the query | `UtubotClient.cutUrl` |
| Timing and size constants: assess wait 1200 ms (cap 3000) + 500 ms slack, 50 videos per call; panel delay 1/1.8/3/5 s; summary and insight `wait_ms` 20000, at most 6 long polls per request while `pending` (`MAX_POLLS`); transcript polls 4 s (view) and 20 s (panel); retry 1 s to 10 min; captions poll 10 s, 2 h, 5 errors; cut follow `wait_ms` 10000, 30 min, 5 errors; cut length tolerance 2 s; a flowing tick landing anywhere inside a drop skips it (a seek is a backwards move or one over 5 s x speed); caption file cap 4 MiB; caches: verdicts 2000, ready summaries 100, captions answers 30 | `UtubotSettings`, `UtubotManager`, `UtubotPanelModel`, `UtubotCaptionsFollower`, `UtubotCutFollower`, `UtubotCutSkipper`, `UtubotCaptionStore`, `VerdictCache` |
| Timing and size constants: assess wait 1200 ms (cap 3000) + 500 ms slack, 50 videos per call; panel delay 1/1.8/3/5 s; summary and insight `wait_ms` 20000, at most 6 long polls per request while `pending` (`MAX_POLLS`); transcript polls 4 s (view) and 20 s (panel); retry 1 s to 10 min; captions poll 10 s, 2 h, 5 errors; cut follow `wait_ms` 10000, until ready/failed/30 min, retry 1 s to 30 s (the player follower stops after 5 errors); cut length tolerance 2 s; skip entry window 2 s; caption file cap 4 MiB; caches: verdicts 2000, ready summaries 100, captions answers 30 | `UtubotSettings`, `UtubotManager`, `UtubotPanelModel`, `UtubotCaptionsFollower`, `UtubotCutFollower`, `UtubotCutSkipper`, `UtubotCaptionStore`, `VerdictCache` |
| The cut's `transcript_hash` is parsed but not compared by the TV; the length check is the guard (the contract sentence that said otherwise is corrected in this pull request) | `UtubotParser`, `UtubotModels`, `UtubotCutController` |
| Private-host rule for http (loopback, RFC1918, link-local, CGNAT, `.local`, `.lan`, `.internal`, `.home.arpa`, `.ts.net`, single-label) | `UtubotSetup.isPrivateHost`, `resolveUrl` |
| The mock backend is one stdlib Python file. It pairs as user `emu` with token `utb_emulator`, serves a setup whose `backend_url` is its own base, answers every `assess` with `action: "none"`, has summary, insight, transcript, captions and cuts with `/__mock/*` switches, and has no prompts import, refresh or default, no `processed`, no request log, no CORS headers | `scripts/emulator_mock_backend.py` |
| CI treats every path not in `NON_APP` as an app change, which also triggers an automatic APK release; a change to `utubot-ci.yml` itself runs every job | `.github/workflows/utubot-ci.yml` (`NON_APP`, `PIPELINE`, `release`) |
| The APK readers list GitHub Releases by count before filtering by tag: the TV's release notes read the newest 10, the backend's app sync and status the newest 20 (`sync_releases_per_page`). Tags alone are not listed by either | `common/src/stutubot/res/values/release_notes.xml`, `ai-backend/src/utubot/appsync.py`, `status.py`, `config.py` |
| There was no pull request template (this pull request adds one) | `.github/` |
| Tests, CI, emulators and agents never contact YouTube; only the deployed backend does | `AGENTS.md`, `ai-backend/AGENTS.md`, `docs/development.md` ("Offline mode") |

Browsers (read 2026-11-24):

| Fact | Source |
|---|---|
| Firefox does not support `background.service_worker`; Manifest V3 uses `background.scripts` (a non-persistent event page). Android: "Background service workers aren't supported on Firefox for Android. Instead, use event pages." | [MDN background](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/manifest.json/background), [Developing extensions for Firefox for Android](https://extensionworkshop.com/documentation/develop/developing-extensions-for-firefox-for-android/) |
| The same Android guide still says "it's recommended you use Manifest V2 for extensions targeting Firefox for Android" because of known gaps; V3 has been accepted on Android since Firefox 109 | same guide, [Mozilla Discourse](https://discourse.mozilla.org/t/what-version-of-android-firefox-added-support-for-mv3/137342) |
| From Firefox 127 users are asked to grant V3 host permissions at install, and they can revoke them; Firefox for Android 128 added a permissions UI. The Android guide still lists: no visual sign of a pending host-permission request, and no editing of host permission grants in the Add-ons Manager | [Manifest V3 updates, May 2024](https://blog.mozilla.org/addons/2024/05/14/manifest-v3-updates/), Android guide |
| `permissions.request` only works inside a user-action handler | [MDN permissions.request](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/API/permissions/request) |
| In V3 content-script `fetch` follows the page's CORS; host permissions work only in extension pages (background) | [MDN content scripts](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Content_scripts) |
| The V3 default CSP is `script-src 'self'; upgrade-insecure-requests;`; an extension that needs `http:` overrides `content_security_policy` without that directive | [MDN extension CSP](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Content_Security_Policy) |
| Android compatibility of a version signed through the store's API comes from `browser_specific_settings.gecko_android` in the manifest; the `gecko` id applies to it. The post does not say whether this differs for unlisted versions | [Changes to Android extension signing](https://blog.mozilla.org/addons/2023/10/05/changes-to-android-extension-signing/) |
| New extensions must declare `browser_specific_settings.gecko.data_collection_permissions`; the built-in consent exists from desktop 140 and Android 142 | [Firefox built-in data consent](https://extensionworkshop.com/documentation/develop/firefox-builtin-data-consent/), [announcement](https://blog.mozilla.org/addons/2025/10/23/data-collection-consent-changes-for-new-firefox-extensions/) |
| A self-distributed file must be signed through the add-on store (listed or unlisted); with `update_url` in the manifest Firefox installs higher versions from there; a web download does not install on Android (the file is installed from the hidden "Install extension from file" setting) | [Self-distribution](https://extensionworkshop.com/documentation/publish/self-distribution/), [Installing self-distributed extensions](https://extensionworkshop.com/documentation/publish/install-self-distributed/) |
| `web-ext lint` reports some Android-incompatible permissions, manifest keys and APIs, but the guide says it does not report every API that Firefox for Android lacks; `web-ext run --target=firefox-android` runs on a device or emulator over adb; `web-ext sign` takes the store's API key and secret and needs an id in a V3 manifest | Android guide, [web-ext](https://extensionworkshop.com/documentation/develop/getting-started-with-web-ext/) |
| Chromium extension service workers have no DOM and no `window`, are stopped when idle (timers are cancelled, global state is lost) and must keep state in the storage APIs | [Migrate to a service worker](https://developer.chrome.com/docs/extensions/develop/migrate/to-service-workers) |
| Chrome does not install a local or self-hosted `.crx` on Windows (since Chrome 33) or macOS (since Chrome 44); Linux can. The Chrome Web Store asks a one-time developer registration fee | [Alternative installation methods](https://developer.chrome.com/docs/extensions/how-to/distribute/install-extensions), [Register as a developer](https://developer.chrome.com/docs/webstore/register) |
| Kiwi Browser (Chromium with extensions on Android) was archived in January 2025; its extension code went into Edge Canary for Android. No source found that Edge's stable Android release runs arbitrary extensions | [Android Authority](https://androidauthority.com/kiwi-browser-shutting-down-3519510), [Neowin](https://www.neowin.net/news/kiwi-browser-takes-final-breath-but-at-least-some-of-it-will-live-on-in-microsoft-edge/) |

Existing extensions read for technique: section 15. Not verifiable from here: section 13, each with the checkpoint that settles it.

## 2. Decisions (all made)

1. **Directory**: `extension/` at the repository root, with its own `AGENTS.md`, `README.md` and `DEVLOG.md`.
2. **Manifest V3 on every browser, one codebase.** Firefox: `background: {"scripts": ["background.js"]}` (event page).
   Chromium: `background: {"service_worker": "background.js"}`. The background code is written for the stricter of the two (a
   service worker): no DOM, no `window`, no state in memory, no timer that must outlive one request. Nothing depends on a
   V3-only API: toolbar access goes through one wrapper (`action`), permissions through `optional_host_permissions`. The mature
   extensions read for this plan ship Manifest V2 on Firefox and V3 on Chromium (section 15), which is a warning about V3 on
   Firefox, mostly on Android: if checkpoint 10's Android check fails on a V3 gap, the Firefox build gets a V2 manifest variant
   from the same build script (`browser_action`, `optional_permissions`) and the plan continues unchanged.
3. **Minimum versions**: `gecko.strict_min_version` `140.0`, `gecko_android.strict_min_version` `142.0`.
4. **Add-on id** `extension@utubot.dev`. **Name** "u·tubot". Icons rendered from `assets/brand/` by `assets/brand/render.py`.
5. **Language and tooling**: plain JavaScript ES modules, no framework, no TypeScript. One bundler, `esbuild`, unminified, to
   produce `background.js` and `content.js` (content scripts cannot be modules). Dev dependencies are `esbuild`, `web-ext` and
   `eslint` only (plus `playwright` for the Chromium track, checkpoint 19), pinned in `package-lock.json`. Node 22 LTS. No
   runtime dependency and no polyfill package: `shared/api.js` is the only place that touches the extension API
   (`globalThis.browser ?? globalThis.chrome`, promise style; message handlers answer through `sendResponse` and return
   `true`, which both browsers support), and an eslint rule forbids `browser.` and `chrome.` anywhere else and `window` and
   `document` under `src/background/`.
6. **Network only in the background.** Content scripts and pages never hold the token and never call the backend; they send
   named messages and the background performs the fixed request. There is no generic "fetch this URL" message. The router has
   two message sets:
   - from **extension pages only** (sender URL under this extension's own base address, taken from `runtime.getURL("")` in
     `api.js`, so it is `moz-extension://…` on Firefox and `chrome-extension://…` on Chromium): `setup.fetch`,
     `setup.apply`, `pair`, `backend.set`, `token.set`, `health`, `me`, `prompts.list`, `prompts.import`, `prompts.refresh`,
     `prompts.default`, `settings.*`, `processed`, `open.set`, `diagnostics.read`;
   - from **content scripts on the two YouTube origins** (and extension pages): `assess`, `summary`, `insight`, `transcribe`,
     `transcript`, `prompts.list`, `captions.status`, `captions.prepare`, `captions.file`, `cuts.list`, `cuts.request`,
     `cuts.follow`, `settings.read`, `open.take`, `diagnostics.report`.
   Content scripts cannot read `storage.session` themselves on either browser, so the one-shot open requests (captions for a
   Processed tile, a carried cut) are written by a page with `open.set` and fetched once by the watch page's content script
   with `open.take`, which removes them.
   Anything else, another sender id, or a video id that does not match `^[A-Za-z0-9_-]{11}$` is rejected. UI handlers in the
   page ignore events with `isTrusted` false.
7. **Storage**: `storage.local` holds the backend URL, token, user name, switches, panel delay, the session prompt and the
   setup's pending prompt-set URLs. Never `storage.sync`. `storage.session` holds the verdict cache (2000 entries), ready
   summaries (100), captions answers (30) and the one-shot open requests. IndexedDB (background) holds the caption files:
   WebVTT only, at most 4 MiB each, keyed `<video id>/<lang>`, never replaced, not cleared by a backend or token change (as
   `UtubotCaptionStore`). A change of URL, token or backend version clears the `storage.session` caches, and nothing
   that failed is kept (as `UtubotManager`).
8. **Auth**: `Authorization: Bearer <token>` added by one function that sends it only to the stored backend (same scheme, host,
   port, path under the backend's). Every backend request is made with `credentials: "omit"` and `cache: "no-store"`, so the
   web UI's session cookie can never stand in for a missing token. `?token=` is never used. Caption files are fetched by the
   background and handed to the content script as text. A call that needs a token is not sent without one.
9. **Host permissions**: required `https://www.youtube.com/*`, `https://m.youtube.com/*`. Optional `https://*/*`, `http://*/*`.
   No other permission than `storage`. `permissions.request` is only ever called directly in a click handler, before any
   `await`. The flows:
   - **Import setup**: the click on "Import" resolves the typed address (pure, synchronous) and requests that origin, then
     fetches `/setup.json`. If `backend_url` has the same origin, the setup is applied. If it differs, nothing is applied yet:
     the page shows "This setup uses `<origin>`" with the button **Allow access to `<origin>`**; its click requests that origin
     and applies the setup. The typed origin's permission is removed afterwards when it is not the backend's.
   - **Advanced, backend URL**: "Save" is a click that requests the new origin (after the private-host rule), stores the URL on
     grant, and removes the permission of the previous origin. A refused request stores nothing and says so.
   - **Clearing the backend** removes its permission (`permissions.remove`).
   - **YouTube**: the popup and the options page call `permissions.contains` for both YouTube origins every time they open; when
     one is missing they show "u·tubot is not allowed to run on YouTube" with the button **Allow on YouTube** (a click that
     requests both). The background's `onInstalled` opens the options page, where this is the first thing shown when missing.
   - **A refused request** (the prompt answered "Don't allow", or closed) stores nothing, keeps the previous backend and
     shows "Permission was not given".
   - **Backend permission lost** (revoked in Firefox): a backend call that fails with a permission error makes the panel and
     the popup show "Allow access to `<origin>`" (the same button, in the options page).
10. **http**: `content_security_policy.extension_pages` is `script-src 'self'; object-src 'self'` (no
    `upgrade-insecure-requests`), and the setup code refuses `http` for a non-private host with the rule ported from
    `UtubotSetup.isPrivateHost`. A network error on an `http` backend is shown with one browser-neutral hint: "The browser may be
    blocking plain http to this server (an HTTPS-only setting or a local-network permission). Allow it for this server, or use
    https".
11. **Data consent**: `data_collection_permissions.required` = `["browsingActivity", "websiteContent", "authenticationInfo"]`
    (video ids and card text go to the user's own server; the token authenticates there), no optional entries.
12. **Captions in the page**: the standard text-track API on YouTube's `<video>` element (`video.addTextTrack` once per language
    label, cues as `VTTCue`, cues swapped on navigation because a track cannot be removed). No overlay element, no hook into
    YouTube's own caption menu. Reason: it needs no page structure, and it works in fullscreen and picture-in-picture.
    Contingency with a fixed trigger: if the owner's device pass shows YouTube suppressing native cues, the renderer behind
    `captions.js`'s `show(cues)` / `clear()` is replaced by an overlay inside the fullscreen-capable player container; nothing
    else changes. None of the extensions read for section 15 adds its own text track, so this stays the plan's least proven
    choice; it is why captions are in the MVP and the owner sees them on real YouTube at checkpoint 9.
13. **Cuts in the page**: a port of `UtubotCutSkipper`, driven the way the mature skip extensions do it (section 15) instead of
    by polling. While a cut is on and the video plays, one timer is armed for the next skipped part's start, computed from
    `currentTime` and `playbackRate`; it is re-armed on `play`, `playing`, `seeked`, `ratechange` and `durationchange` and
    cancelled on `pause`, `waiting` and `emptied`. `timeupdate` stays as the safety net with the TV's 2 s entry window, for a
    timer that fired late. The jump is `video.currentTime = end`; the skipper sets an `ownSeek` flag before the assignment and
    clears it on the next `seeked`, so its own jump is not taken for a user seek. Any other `seeking` event is the user's and
    wins: the part plays. A skipped part that ends within 0.5 s of the video's end jumps to `video.duration`, so the video
    ends instead of hanging. The cut is applied only to the main player's video (not a hover preview or the miniplayer of
    another video), only while `|cut.duration_ms - video.duration * 1000| <= 2000`, and not while an ad plays. The
    sponsor-segment merge of the TV is not ported (the browser has no built-in sponsor skip).
14. **UI**: one host element with a closed shadow root, attached to the document (moved into `document.fullscreenElement` while
    one exists). It contains the u·tubot button, the panel (Summary, Answer, Captions, Cut), the passive glance card, toasts. DOM
    is built with `textContent` only. What the extension puts into YouTube's own DOM is limited to: the mark label and the chip
    on a card, the `display` of a hidden card, one `data-utubot` marker attribute, and the text track. The backend address, the
    token and the user name never appear in a page-visible node, attribute or `data-*` value. A test greps the content-script
    sources for `innerHTML`, `outerHTML`, `insertAdjacentHTML` and for any use of the settings fields outside the shadow root
    code. On the phone the panel is a bottom sheet.
15. **Page knowledge in one file**, `content/site.js`, built from section 15's lessons:
    - Site kind: `m.youtube.com` is the mobile site, anything else the desktop site.
    - Video id: from the URL (`/watch?v=`, `/shorts/<id>`, `/live/<id>`), 11 characters.
    - Navigation: YouTube's own events where they exist (`yt-navigate-start` and `yt-navigate-finish` on `document` for the
      desktop site, `state-navigateend` on `window` for the mobile site), the Navigation API's `navigate` event where the
      browser has it, and a 500 ms URL poll plus `popstate` as the fallback that needs no YouTube name. All of them lead to the
      same "the video id or the path changed" check, so a renamed event costs latency, not function.
    - Main video element: a page can hold several `<video>` elements (the main player, a hover preview, the miniplayer). The
      main one is the visible video inside the main player container that has a duration; it is looked up again on every
      navigation and whenever the player container's children change (a `MutationObserver`), because YouTube replaces or moves
      the element. On the mobile site the element reports no duration until it has loaded, so the lookup repeats until it does.
    - Ad state: the player container carries a marker class while an ad plays; it is read on `play`, `playing`,
      `durationchange` and before every skip or cue decision. Ads stitched into the stream by the server shift the video's
      clock; the length rule of decision 13 catches that for cuts (the cut is held back), while captions have no length to
      compare and can run shifted for such a video: a known limit of this version. Reading the server-ad offset needs a
      script in the page's own world, which this version does not have (decision 27).
    - Cards: a card is found by its container (the list of renderer and lockup element names, one list per site) or, for an
      unknown container, by an anchor whose `href` is a watch or shorts link. YouTube reuses card elements for other videos,
      so each card's link is watched for an `href` change and the card is evaluated again; marks are keyed by video id and
      re-applied whenever a scan finds them missing (YouTube removes foreign nodes); scans are throttled to one per 50 ms; on
      the mobile site a scan also follows `touchend`, `scrollend` and navigation with a decaying schedule (100 ms to 10 s),
      because cards arrive late there. A card whose container is not recognised is marked but never hidden.
    - The element-name lists in `site.js` are written fresh, in this plan's own grouping (by what a card is: a video in a
      grid, in a list, in the suggestions, a Short), from the stand-in fixtures and the owner's notes from the smoke runs.
      Section 15 says which names exist; no list is carried over from another project's file.
    - Diagnostics: `site.js` reports what it found (site kind, main video found and its duration, ad marker seen, which
      navigation signal fired last, card containers recognised and unrecognised, caption track mode and cue count) to the
      background with `diagnostics.report`; the popup shows it as plain text with a Copy button. It contains no address,
      token, user name or video title.
    - Orphaned content scripts: after an extension update the old content script keeps running without an extension context.
      Every timer and observer callback first checks that the extension context is alive and tears everything down when it is
      not.
16. **Assess mapping** (the same on both sites; anything not listed is not assessed and gets no chip for marks):

    | Page (path) | `section` |
    |---|---|
    | `/` | `home` |
    | `/feed/subscriptions` | `subscriptions` |
    | `/results` | `search` |
    | `/@name`, `/channel/…`, `/c/…`, `/user/…` and their tabs | `channel` |
    | `/watch` (the suggestions beside or below the player) | `other` |
    | `/feed/history`, `/playlist`, `/feed/playlists`, `/feed/library`, `/feed/you`, `/feed/channels`, `/shorts/…`, everything else | not assessed |

    Cards in a Shorts shelf on an assessed page are assessed with `is_short: true`. Fields per card, each omitted when not found
    (only `video_id` is required): `video_id` (from the link), `title` (the title element's text, else the link's `title` or
    `aria-label`), `channel` (text of the card's channel link), `channel_id` (only when that link is `/channel/UC…`),
    `duration_s` (the thumbnail's time badge parsed as a clock), `is_short` (a `/shorts/` link), `is_live` (a live badge the
    site layer recognises), `views` and `published` (the two parts of the card's metadata line, as on the TV), `description`
    (search results only, the snippet). The backend's assess prompt also accepts optional context
    (`is_subscribed`, `upload_date`, `likes`, `dislikes`, `subscriber_count`, `channel_description`, `channel_titles`; `ai/CONTRACT.md`).
    The TV sends `is_subscribed` when its card knows it; the extension sends the same optional context where the page or the
    signed-in user's subscription list exposes it, each field omitted when not found (`shared/meta.js` `videoToJson`, mirroring
    the TV's "only sent when true" rule for `is_subscribed`): `is_subscribed` when the watch page or the subscriptions feed marks
    the channel subscribed, `upload_date` from the card's metadata, `likes`/`dislikes`/`subscriber_count` when shown (a "1.2M"
    count parsed to a number), and `channel_description`/`channel_titles` from the channel page and the videos it usually posts.
    The backend still fills the rest of the channel's usual titles itself from what it has seen. On the watch page the
    playing video's own facts are `title` (document title without the site suffix), `channel` (the owner link's text) and
    `duration_s` (the video element), `is_live` when the duration is not finite.
17. **Android differences are decided per row in the matrix**; code branches only on site kind and on
    `runtime.getPlatformInfo().os`, in `site.js` and `ui/layout.js`.
18. **Tests never contact YouTube.** Unit tests on Node (`node --test`). End-to-end tests drive real Firefox (Selenium,
    geckodriver, temporary add-on) against stand-in pages and the mock backend on loopback (sections 6 and 7).
19. **Backend and contract**: no endpoint, field or behaviour changes (section 8).
20. **Distribution, without GitHub Releases.** The extension never creates a GitHub Release, so the TV's 10-release and the
    backend's 20-release windows only ever hold APK releases; no app or backend change is needed. Unlisted signing with
    `web-ext sign --channel=unlisted`. The signed `u-tubot-<version>.xpi`, `SHA256SUMS` and `updates.json` are committed by the
    release workflow to the orphan branch `extension-updates` (the newest five `.xpi` files are kept, older ones removed in the
    same commit). The branch is never merged into another branch and always holds exactly one commit: each release replaces it
    with a force-push of that branch only, so removed files do not pile up in clones. The manifest's `update_url` is the raw
    URL of `updates.json` on that branch; its `update_link` is the raw URL of the `.xpi`. A git tag `utubot-ext-vX.Y.Z` is put
    on the released commit of `main` (as for the APK; a tag is not a release and none of the APK filters match it).
    A store-listed variant (no `update_url`) is built by the same script and submitted only after the owner confirms (D1).
21. **Versions and release trigger**: `extension/version` holds the full version, starting at `0.1.0`. A release happens only
    when a push to `main` carries a version in that file that has no `utubot-ext-v<version>` tag yet, so ordinary checkpoint and
    fix merges release nothing; a release is made by raising the number on purpose. The first release is the MVP at checkpoint 9. The store signs a version number once, which
    is the same rule. Releases are also off until the repository variable `UTUBOT_EXTENSION_RELEASES` is `on` (section 9).
22. **Pairing device name**: "Firefox (desktop)", "Firefox (Android)" or "Chromium (desktop)" (one name for Chrome, Edge and
    Brave: they cannot be told apart reliably); it is what the backend's job log shows as the client.
23. **Processed tiles open in the same tab** (the browser's Back returns to the list).
24. **Not built**: `ask`, `feedback`, `jobs`, voice, saved presets, admin pages (the TV app has none of them); keyboard shortcuts
    (`commands` does not exist on Android); embedded players; YouTube Music.
25. **Cross-browser layer, kept small**: `manifest.base.json` plus `manifest.firefox.json` and `manifest.chromium.json`, merged
    by `build.mjs` into the variants `firefox-unlisted`, `firefox-listed`, `firefox-test`, `chromium`, `chromium-test`.
    `browser_specific_settings` (ids, minimum versions, data consent) and the event page are Firefox-only keys; the service
    worker is the Chromium-only key; everything else is shared. Checkpoint 0 creates this split and `shared/api.js`, so the
    Firefox checkpoints never write Firefox-only code outside those files; the Chromium build and its tests come after the
    MVP (checkpoints 19 and 20) and do not slow it. Chromium on desktop means Chrome, Edge and Brave (minimum Chrome 121).
    Chromium on phones is not a target: Chrome for Android runs no extensions, Kiwi is archived, and Edge for Android's
    extension support is not confirmed for arbitrary extensions; the phone target is Firefox for Android.
26. **Licence (decided by the owner): the extension stays MIT, like the rest of the repository.** SponsorBlock, DeArrow, their
    shared library and Return YouTube Dislike are GPL-3.0, and ImprovedTube has its own copyleft terms. Their code is read to
    learn techniques and the facts of YouTube's page (element and event names); it is never copied, translated line by line
    or vendored. Code may be copied only from MIT, BSD or Apache-2.0 sources, with the attribution in
    `extension/THIRD_PARTY.md`. A checkpoint review rejects code whose structure follows a GPL file.
27. **No script in the page's own world** (`world: "MAIN"`) in this version. The mature extensions use one to read the
    player's own API (video data, ad events, the server-ad offset). It is the most intrusive and most fragile part of them,
    and what this plan needs works without it. Fixed trigger to add one later: the owner's use shows captions or cuts
    shifted by stitched ads often enough to matter.
28. **Companion of the web UI, kept possible** (section 18): the client takes any bearer token of the backend, whoever issued
    it; the extension keeps no state on the server that only it uses; every endpoint it calls is one the TV or the web UI
    also uses.

## 3. Feature-parity matrix

Chromium on desktop behaves as the "Desktop Firefox" column in every row. Rows are named by their `id` (first column), never by
a number: a new feature adds a row with a new id and renumbers nothing, so parallel pull requests do not collide on rebase.
Rows in the MVP (checkpoints 0 to 9b): `setup-import`, `pairing`, `first-launch-offers`, `connection-test`, `summary-view`,
`transcript-states`, `metadata` (the playing video), `prepare-hq-captions`, `hq-captions-playing`, `auto-select-captions`,
`caption-store`, `cut-while-playing`, `apply-cuts-auto`, `working-indicator`, `cache-drop`, `identity-about`.

"Panel" is the extension's own panel on a watch page; "chip" is the small u·tubot button the extension adds to a card; "popup"
is the toolbar button's popup (on Android: the extension's entry in the extensions menu).

| id | TV feature (code) | Contract | Desktop Firefox | Firefox for Android |
|---|---|---|---|---|
| setup-import | Import setup: typed host or URL, `/setup.json`, stores backend, defaults, then pairing (`UtubotSetup`, `UtubotSetupFlow`) | `GET /setup.json` | Options page, first item; opens on install; permission flow of decision 9. `update_url` is ignored (APK only) | Same; the options page opens in a tab |
| pairing | Pair with code (`UtubotPairing`) | `POST /v1/pair`, `GET /v1/me` | Options page: 6 digits, then "Paired as <user>"; pending prompt sets imported after it | Same |
| first-launch-offers | First-launch offers (setup, then pairing; "Don't ask again") | none | Options page opens once on install; the popup shows "Import setup" until configured, and "Allow on YouTube" when that permission is missing | Same |
| connection-test | Test connection, Advanced URL and token (`UtubotConnectionTest`, `setUrlManually`) | `GET /v1/health`, `GET /v1/me` | Options page; saving the URL requests the new origin and releases the old one | Same |
| assess-switch | Assess switch; one call per row emission, hide or mark, unfiltered on error or timeout (`UtubotManager.resolve`, `VerdictCache`) | `POST /v1/assess` | Options switch. Cards on the pages of decision 16 are batched (at most 50, one call per 300 ms batch, `wait_ms` 1200, given up after `wait_ms` + 500 ms); the assess body carries the channel and video context of `ai/CONTRACT.md` (`is_subscribed`, `upload_date`, `likes`, `dislikes`, `subscriber_count`, `channel_description`, `channel_titles`) where the page or the signed-in user's subscription list exposes it, each omitted when not found (`shared/meta.js`); `hide` hides the card container, `mark` adds a coloured label; pending verdicts are asked again when the cards are next scanned | Same on `m.youtube.com` |
| mark-only | Mark only, never hide | none (local switch; setup default) | Options switch | Same |
| answer-in-label | AI answer in the video menu, answer in the label (`UtubotMenu`, `UtubotAnswerModel`) | `GET /v1/videos/{id}/insight` | Chip menu on a card and "Answer" tab of the panel; the chip shows `answer_short` when known and the switch is on. When the answer is longer than the panel, the text crawls slowly and smoothly at the reading pace from the options page, pauses on any key and resumes after a moment; up/down still scroll manually, and waiting long enough shows the whole text | Same; chip tap opens the sheet and the answer crawls by itself at the reading pace when it is longer than the sheet |
| summary-panel-mode | Summary panel mode: passive preview after the focus delay (`PanelCoordinator`, `FocusDebouncer`, `UtubotPanelView`) | `GET /v1/videos/{id}/summary?prompt=panel`, fallback first prompt of `GET /v1/prompts` on 400/404 | Hovering a card for the panel delay shows the passive glance card (bottom right, never takes focus); moving away drops the request; Escape hides it | No hover on touch: with the mode on, each card's chip opens the glance sheet on tap; it requests `prompt=panel` like the TV panel |
| summary-panel-toggle | Summary panel on/off toggle (quick toggle, menu item, setting) and the panel delay (1, 1.8, 3, 5 s) | none (local; setup default) | Toggle in the popup, in the chip menu and in the options page; delay choice in the options page | Toggle in the popup, chip menu and options page; the delay has no effect (tap) and is hidden |
| summary-view | Summary view: prompt list, long summary, session prompt, Retry (`UtubotSummaryOverlay`) | `GET /v1/prompts`, `GET /v1/videos/{id}/summary?prompt=<key>`, `POST /v1/videos/{id}/retry` | "Summary" tab of the panel and "Summary options" on the glance card: prompt list left, text right, source line, Retry. Retry calls `POST /v1/videos/{id}/retry` first, whatever it answers, then asks again; when the text is longer than the panel, it crawls slowly and smoothly at the reading pace from the options page, pauses on any key and resumes; up/down still scroll manually, and waiting long enough shows the whole text | Bottom sheet with the prompt list as a selector above the text; Retry works the same and the text crawls by itself at the reading pace when it is longer than the sheet |
| card-summary-touch | The card's Summary touch entry on a tablet: a u·tubot symbol at the top-end of the thumb opens the Summary view directly, and a long press of the card opens the u·tubot menu (cut picker, AI answer); the symbol is visible only while the screen is touch (`Helpers.isTouchSupported`), hidden on a D-pad screen, and a tap reuses the menu's request (`UtubotUiHost.request(SUMMARY, video)`) | none | The browser has no D-pad, so there is no tablet/key split: the card chip opens the glance card first and the Summary view is the panel's "Summary" tab or the glance card's "Summary options" (row `summary-view`), one tap further. No direct Summary symbol on the card | Same; the card chip opens the glance sheet on tap, the Summary view one tap further |
| transcript-states | Transcript states with the server's words, countdown, Transcribe in background, follow-up polling, at most 6 long polls per request (`UtubotPanelModel`, `UtubotStateText`, `UtubotCountdown`, `UtubotManager.MAX_POLLS`) | `transcript_status` fields, `POST /v1/videos/{id}/transcribe`, `GET /v1/videos/{id}/transcript` | Same states, same intervals (4 s view, 20 s glance) and the same poll cap, in the panel, the glance card and the answer | Same |
| metadata | Metadata on every insight, summary, transcribe call; `is_live` too on cut calls (`UtubotMeta`, `UtubotClient.addMeta`, `cutUrl`) | query `title`, `channel`, `duration_s` (`is_live` for cuts) | From the card or the watch page (decision 16) | Same |
| prompts | Prompts: list, choose default, Import from URL, Refresh all (`UtubotSettingsPresenter.showPrompts`) | `GET /v1/prompts`, `PUT /v1/prompts/default`, `POST /v1/prompts/import`, `POST /v1/prompts/refresh` | Options page, Prompts section | Same |
| prepare-hq-captions | Prepare HQ captions (`UtubotMenu.prepareCaptions`) | `POST /v1/videos/{id}/captions` | Chip menu and "Captions" tab | Same |
| hq-captions-playing | HQ captions while playing: check at start, poll while queued or running, add and select when ready, "captions ready" toast (`UtubotCaptionsFollower`, `ExoPlayerController` hooks) | `GET /v1/videos/{id}/captions`, `GET .../captions/{lang}.vtt` | Follower in the content script; ready track becomes a native text track on the video element, selected by the rule of row `auto-select-captions`, toast for a job that finished while playing. Track on/off and language are in the "Captions" tab (YouTube's own caption menu is not touched) | Same |
| auto-select-captions | Auto-select HQ captions switch; a user-requested track is selected whatever the switch says | none (local switch; setup default) | Options switch; same rule | Same |
| caption-store | Permanent caption store, works without the backend (`UtubotCaptionStore`); Settings, u·tubot, Caption storage shows its size, videos and tracks, warns past 200 MiB, and deletes tracks older than 30, 90 or 365 days or all after a confirmation (`UtubotCaptionStore.usage`, `deleteOlderThan`, `deleteAll`) | none | IndexedDB in the background; a stored video makes no request. Its size and deletion are left to the browser's site-data controls; the size/delete panel is checkpoint 18 work | Same store; the size/delete panel is checkpoint 18 work |
| cut-picker | Director's cut picker: Quick/Watched mode row, presets with state, apply or take off, ask for a build, kept parts; a failed preset shows its reason and Retry (Watched offers Use Quick), picking it asks again (`UtubotMenu.showCuts`) | `GET /v1/videos/{id}/cuts` (`default_mode`, `modes`, `by_mode`), `POST /v1/videos/{id}/cuts {"preset","mode","force"?}` | "Cut" tab and chip menu; a Quick/Watched segment above the presets follows the user's setting when opened; mode-specific labels (`· Watched`), states and errors, with a "Transcribe with u·tubot" switch per video (`force`); picking a ready cut from a card opens the video with the cut carried (one-shot request, as `applyOnOpen`); a failed Watched preset shows Retry and Use Quick, which requests Quick | Same |
| cut-qr | "Describe on phone…" with QR (`UtubotCutQrView`) | `POST .../cuts {"await_prompt":true,"mode"}`, `PUT /v1/cut-requests/{id}` (mode switch while waiting), `GET /cuts/{id}` | A keyboard exists, so: "Describe here" (text box, `POST .../cuts {"prompt","mode"}`), and "Open cut sheet" which creates the waiting request and opens `<backend>/cuts/<id>` in a new tab (voice and saved presets live there). No QR code; the waiting card shows its mode and can switch Quick/Watched | Same |
| cut-speech | Describe by voice: record the custom-cut description, transcribe it on the backend, then create the cut with it (`UtubotCutSpeechView`, `UtubotSpeechInput`, `AudioCapture`, `UtubotSpeechProbe`) | `POST /v1/speech` (multipart audio in, text out, optional `language` hint, `413` over `[speech] max_upload_bytes`), `POST .../cuts {"prompt"}` | A keyboard exists, so the extension takes the description itself (text box, `POST .../cuts {"prompt"}`), exactly as the `cut-qr` row's "Describe here". The recording UI is TV only: the TV records its microphone and uploads the WAV to `POST /v1/speech`; the extension has no microphone UI and no row for it | Same |
| cut-while-playing | Cut while playing: ready cut announced with one-press Apply, or applied automatically; waiting or building request followed; skips with "Skipped 1:20" and a 5 s Back (`UtubotCutController`, `UtubotCutFollower`, `UtubotCutSkipper`) | `GET /v1/videos/{id}/cuts`, `GET /v1/cuts/{id}?wait_ms=10000` | Same flow; the toast has "Back" (returns to the skipped part); length rule ±2 s; paused during ads | Same |
| apply-cuts-auto | Apply ready cuts automatically | none (local switch) | Options switch | Same |
| cut-seekbar | Dimmed skipped parts on the seek bar (`UtubotCutSeekBar`); picking a kept part in the cut picker seeks the playing video to its start and keeps the cut applied (`UtubotMenu.partsCategory`, `UtubotCutController.jumpToPart`) | none | A slim timeline in the "Cut" tab shows kept and skipped parts; kept parts are a clickable list that seeks the playing video to that part's start and keeps the cut applied. YouTube's seek bar is not modified | Same |
| sponsor-merge | Sponsor-segment merge of a cut jump; SponsorBlock fully off while a cut is applied (no skip, no prompt) | none | Not applicable: the browser has no built-in sponsor skip. While a u·tubot cut is applied, SponsorBlock skipping is fully off over the cut's ranges and the cut's jump goes past the sponsor segments set to skip; in the contract's "Clients" section | Not applicable |
| processed-section | Processed section and opening a tile with its HQ captions (`UtubotProcessedSection`, `UtubotProcessedOpen`) | `GET /v1/processed?limit=50` | Extension page "Processed" (from the popup and the panel): tiles with the processed line and its duration, empty and failed states; a tile opens the watch page in the same tab with a one-shot captions-open request | Same, opened from the popup |
| working-indicator | Working indicator and busy badge (`UtubotWorkingIndicator`, `UtubotBadgeController`, `UtubotBusyTracker`) | none | Three-dot indicator in the panel, glance card and answer; toolbar badge while calls are in flight (shown after 300 ms) | Indicator only (no toolbar badge) |
| cache-drop | Caches dropped on a backend, token or backend version change; failures are never kept (`UtubotManager`) | none | `storage.session` verdict and summary caches cleared on any of the three; nothing that failed is kept; caption store kept | Same |
| browse-cache | Browse cache, "Browse refresh" minutes, "Refresh section" (`UtubotBrowseCache`) | none | Not applicable: YouTube's site owns its loading. In the contract's "Clients" section | Not applicable |
| self-update | App self-update from the setup's `update_url` (`UtubotUpdates`) | `GET /app/update.json` | Not applicable: Firefox updates extensions (`update_url` of the manifest, or the store) | Not applicable |
| identity-about | Own identity, About links, unofficial disclaimer | none | Name, icons, About section in the options page with this repository's links and the disclaimer | Same |
| cut-mode-watched | Watched cut mode: Watched preset state, a build's `video`/`grids`/`describing` stages, progress and ETA, failed fallback to Quick, user default (`UtubotMenu.modeRow`, `UtubotCutController`) | `GET /v1/videos/{id}/cuts` (`modes`, `by_mode`), `POST .../cuts {"mode":"watched"}`, `PUT /v1/cut-requests/{id}` (mode), `GET /v1/me` (`cuts_watched`), `POST /v1/me/settings {"settings":{"cuts":{"cut_mode"}}}` | "Cut" tab and chip menu: Quick/Watched segment, Watched labels with about-length, `video`/`grids`/`describing` stages with progress and ETA, failed Watched with its reason, Retry and Use Quick; the waiting request switches mode; the options page has the default-mode choice and disables Watched with the server's reason | Same |
| transcribe-audio | Transcribe from audio, ignoring YouTube captions (`UtubotMenu.prepareCaptions(..., force)`), and HQ captions from the audio | `POST /v1/videos/{id}/transcribe?force=true`, `POST /v1/videos/{id}/captions {"force":true}` | Chip menu and "Captions" tab: "Transcribe from audio" (and the HQ captions request with `force` when the switch is on); the usual transcript states and polling follow. The transcript it replaces is the backend's, so the panel shows the new progress while the old captions are still stored. The same switch on the cut request builds cuts from it | Same |
| video-opens-with-cut | A video opens with the chosen cut, else the preset used last; no ready cut for it means uncut and the ready cuts offered (`UtubotCutFollower`, `UtubotCutController`) | `GET /v1/videos/{id}/cuts` (`selection`), `PUT /v1/videos/{id}/cut-choice` | Same selection; a pick (preset, typed cut or off) is recorded with the same route, and only the selected cut is applied on open; the player's Cut tab shows "Cut: <label> · <length>" | Same |
| cut-time-playing | Cut time while playing: the active cut's name, the position and length in cut time and the current part number (`UtubotCutController`, `UtubotCutTime`) | none | While a cut is on and the video plays, the player's cut indicator shows the cut time "<pos> / <length> of <name>" and, in a kept part, "<n> of <total>"; the full-video clock stays next to it. Paused, it shows where the playback is in the cut | Same |
| cut-end-time | Cut end time on the player's hourglass: the remaining kept time, marked `✂`, with the full video's end when no cut plays (`EndingTimeView`, `UtubotCutController.getPlayingCut`, `UtubotCutTime.remainingKeptMs`) | none | The watch page's cut indicator adds the cut's end time, marked as the cut's; with no cut, skipping off or past the last kept part it shows the full video's end | Same |
| channel-cut-defaults | Channel cut defaults: the cut picker stores "Always use this mode for this channel" or clears it (`UtubotMenu.showCuts`) | `GET /v1/videos/{id}/cuts?channel_id`, `GET|PUT|DELETE /v1/cut-channels`, `mode_rule` on cuts, `channel_id` on requests; resolution is request > channel > user > server | "Cut" tab and sheet: the channel's mode, a quick/watched/follow-user choice, sent as `PUT /v1/cut-channels/{id}`; watched stays disabled until `cuts_watched` | Same |
| whats-new | What's new: app versions and backend deploys as text, with release time and changes (`UpdatesSettingsPresenter`, `UtubotChangelog`) | `GET /v1/changelog?kind=app\|backend` | Options page, "Updates" section: two lists (App versions, Backend deploys), each entry expandable. "What's new in X" after an update is TV only (the add-on's own version history is the store's) | Same list in the options page |
| cut-ready-elsewhere | A cut ordered here that becomes ready elsewhere: waiting list, question one at a time, Yes opens it with the cut, No/Back stays, failure message next open (`UtubotCutWaitlist`, `UtubotCutWatcher`, `UtubotCutNotices`) | `GET /v1/cuts/{id}` | A page notification on youtube.com: "Director's cut ready: <title> (<length>). Play?"; Yes opens the watch page with the cut request, No dismisses it and leaves the page and the player as they are; ordered cuts are followed in the background from the page | Same; only while a youtube.com page is open |
| cut-jump-badge | Kept-part jump and outside-the-cut badge (`UtubotCutNavigator`, `UtubotCutBadge`; issue 104) | none | The "Cut" tab and the watch page read the same cut document: a keyboard shortcut (default Alt+Right / Alt+Left, configurable in the options page, Off) jumps to the next/previous kept part, first press keeps the site's seek, none left does nothing; while the playback is in a cut-out range a small badge says "Outside the cut · ▶▶ next part in 2:10" (or that no part follows) and goes away in a kept part | Same, with a touch button next to the timeline in place of the shortcut |
| cut-seek-skip | A seek stays in the kept parts while a cut is on, and a toggle turns the cut's skipping off to watch the cut-out parts (`UtubotCutSkipper.snapToKept`, `UtubotCutController.onSeekEnd`, `UtubotCutController.toggleSkipping`, `UtubotCutSkipAction`) | none | "Cut" tab and chip menu: a "Skip cut-out parts" switch turns the applied cut's skipping off, the cut staying selected and its skipped parts staying on the timeline so they can be watched, and turns it back on, jumping out of a skipped part the playback is in. While skipping is on, a seek from the timeline's kept parts or the extension's own forward/rewind snaps a landing in a skipped part to the next kept part's start (forward) or the previous one's end (back). YouTube's seek bar is not modified (row 22) | Same |
| cuts-offline | Cuts served from cache when the backend is slow or down (`UtubotDiskCache.cuts`, `UtubotClient.cutsCache`, `UtubotManager.cutsObserve`): the menu shows the cached list at once, re-validates it in the background with If-None-Match, refreshes on a fresh list, and shows the cache under a "stale" notice when a refresh fails, never blocking on the server | `GET /v1/videos/{id}/cuts` carries a strong ETag and `Cache-Control: max-age`; a matching If-None-Match answers 304 | The cut menu is served from the extension's own storage on a cache hit, re-validates with If-None-Match, and shows the cache under a notice when a refresh fails | Same |
| content-cache | One cache, every artifact reused: a transcript's word-time run answers "Prepare HQ captions", cuts and watched cuts without a second speech recognition; the `asr` stage of the job reports `cached`/`reused_from_job`/`saved_s` | `asr` stage `cached`/`reused_from_job`/`saved_s` (job detail) | Not applicable: the extension does no extraction and has no jobs UI, so it shows no job-stage details; the reused-ASR fields are backend metadata the web UI job detail page renders, and job reports are read unchanged. In the contract's "Clients" section | Same |
| feature-models | Feature models (admin): which modelgate alias serves each feature (`glance`, `summary`, `answer`, `triage`, `analysis`, `captions`, `cuts`, `cuts_vision`), with the last seven days of calls, tokens, cost and median/p90 time per feature, the per-run cost and wall time on the result, and the admin switch validated against modelgate's alias list (`feature.py`) | `GET /v1/admin/features`, `PUT /v1/admin/features/{feature} {"alias"}`, `DELETE /v1/admin/features/{feature}` | Not applicable: this is the server's admin page, not a TV app feature and not the extension's. Admin pages are the web UI's (Part 1, "Out of scope"); both clients link to the web UI for it. The choice is server-wide, stored in the DB and effective on the next call, so neither client needs it | Not applicable |
| user-provider | Per-user AI provider key, daily cost budget and request cap (`PUT`/`GET`/`DELETE /v1/me/provider`, `[usage] user_budget_usd` and `user_requests_per_min`) | `PUT`/`GET`/`DELETE /v1/me/provider`, `[usage]` limits, `usage` and `provider` on `GET /v1/users` and `GET /v1/admin/users` | Not applicable: the user's own upstream is stored on the server and routes their calls transparently, so the extension's cuts and answers already run on it through the same endpoints and bearer token; the daily budget and request cap are enforced on the bound user regardless of client, and the usage/provider tables are the admin (web UI) page. In the contract's "Clients" section | Not applicable |
| inbox | Inbox: one tile per ready result (cut, summary, research, captions), newest first, an unread count and badge, and an open per result kind (`UtubotInboxSection`, `UtubotInboxOpen`) | `GET /v1/inbox?limit=50`, `POST /v1/inbox/read`, `POST /v1/inbox/read-all`, `POST /v1/inbox/dismiss` | Extension "Inbox" page (from the popup and the panel): a tile per result with the result line and, for research and captions, its language, an unread badge and empty and failed states; a summary or a research result shows its view in the panel, a cut opens the watch page in the same tab, and a caption result opens it with a one-shot captions-open request; reading clears the badge (`read`/`read-all`, shared per user across clients) and a tile is hidden with `dismiss` | Same, opened from the popup |
| cut-ready-on-page | A cut ordered from a thumbnail/card that opens by itself when ready while the page is still open, otherwise the cut-ready-elsewhere prompt; the open picker re-renders when a building cut becomes ready (`UtubotCutFocus`, `UtubotCutNotices`, `UtubotMenu`) | `GET /v1/cuts/{id}` | The "Cut" tab and the cut sheet update live when a build becomes ready (the "Building…" row becomes the ready state). A cut ordered from a youtube.com page opens the watch page with the cut while that page is open (the extension's "still on the page", mirroring the TV's no-video-playing browse focus); if the page was closed the cut-ready-elsewhere page notification is asked instead | Same; only while a youtube.com page is open |
| voice-control | Voice control (plan `ai/VOICE_CONTROL_PLAN.md`, #189): per-device consent and the command history (`GET /v1/me` `features.voice`, `device`, `voice`; `/setup.json` `realtime_url`); later the live socket, the TV as a screen and the Talk page | `GET /v1/me`, `GET /setup.json`, `GET|PUT /v1/me/voice`, `PUT /v1/me/devices/{id}/voice`, `GET|POST|DELETE /v1/voice/commands` | Checkpoint 1 (backend and web UI only) needs nothing in the extension: it ignores the new keys. Intended: the playing tab is a screen for the player and cut tools and the panel has a Talk button. Whether an MV3 background may hold a WebSocket under the extension's rules is checked first in the voice plan's checkpoint 12; if it fails the socket is held by the panel page while it is open, or the row becomes a recorded exception in the contract's "Clients" section | Same |
| error-ledger | Failures of the app's own backend calls are reported to the error ledger (`UtubotClient.reportFailure`, `UtubotFailureThrottle`); the admin sees counts per category per day on the web admin page "Error ledger" | `POST /v1/ledger`, `GET /v1/admin/ledger` | Background `createClient(..., {reportFailures: true})` reports transport and 5xx failures with the same throttle (one per message a minute, ten a minute); the page is the web admin | Same |

## 3a. Parity notes for backend-only cut changes

The no-target map/reduce cap (UTB-146: long videos cut by map/reduce kept ~99% for presets with no target length) is a backend
cut-build behaviour change only. The wire contract did not change in a way the extension consumes: the cut document gained the
additive `kept_s`/`target_s`/`cap_s` fields, and the extension reads `kept_ms`, which was always present, so it shows the cut's
own length exactly as before. No `extension/` file and no matrix row change were needed; the fix is TV-app (`UtubotCutsParser`
keeps the real per-preset length on screen) plus backend (`cuts.py`: cap no-target map/reduce builds at `map_max_keep_frac` of
the video and trim by rank, log kept/removed seconds per excerpt, supersede and requeue the near-full cuts made before the
algorithm). This note is the extension's side of the parity box for that pull request.

The "skim the film" cut (UTB-223: a built-in preset that keeps the story beat by beat to about half a film's length) is a
backend-only change on the wire. The cut picker already offers every preset the server lists, so `cut-skim-film` ("Skim the film")
appears in the extension's "Cut" tab and chip menu without a matrix row change, and it runs in the viewer's chosen mode: `quick`
from the timed transcript, or `watched` when picked for the vision pass. The fraction target is a backend computation; the cut
document still carries the effective `target_s` and the real `kept_ms`, which the extension reads for the label length. No
`extension/` file and no matrix row change were needed; this note is the extension's side of the parity box for that pull request.

The one-time web sign-in link (issue 203: `POST /v1/web-login`, `GET /web-login/<token>`) is a TV-and-tablet feature: the TV's
"u·tubot web admin" entry opens the web admin in the device's browser, signed in. The extension already runs inside a browser, and its
options page links the same web admin the user signs into normally, so it has no equivalent entry; no `extension/` file and no matrix row
change were needed. This note is the extension's side of the parity box for that pull request.

## 4. Architecture

```
extension/
  manifest.base.json       shared keys (release shape, no loopback match)
  manifest.firefox.json    Firefox-only keys: ids, minimum versions, data consent, event page
  manifest.chromium.json   Chromium-only keys: service worker, minimum Chrome version
  version                  full version, starts at 0.1.0
  build.mjs                esbuild + manifest variants (decision 25)
  src/background/          main.js (message router), client.js, auth.js, setup.js, permissions.js,
                           cache.js (storage.session), captionstore.js (IndexedDB), busy.js
  src/shared/              models.js (parsers), statetext.js, panelmodel.js, countdown.js, cutskipper.js,
                           vtt.js, policy.js, meta.js, messages.js (message names and sets), debounce.js,
                           api.js (the only extension-API access)
  src/content/             main.js, site.js, cards.js, player.js, captions.js, cuts.js, followers.js
  src/content/ui/          host.js (shadow root), panel.js, glance.js, sheet.js, toast.js, layout.js, styles.css
  src/pages/               options.html/js, processed.html/js, popup.html/js
  src/_locales/en/         messages.json (strings carried over from utubot_strings.xml)
  tests/unit/              node --test
  tests/fixtures/site/     www/*.html, m/*.html (hand-written stand-ins)
  tests/e2e/               pytest + selenium (uv project): conftest.py, refusing_proxy.py, user.js, tools.lock
```

- **Background (event page on Firefox, service worker on Chromium)** is a stateless executor: one message in, one backend request, one answer. It may be unloaded when
  idle, so nothing lives only in its memory: caches are in `storage.session`, timers (followers, countdowns, hover delay) run in
  the content script of the tab that needs them, and a long poll never asks for more than 20 s (`wait_ms` cap, below Firefox's
  idle limit).
- **Content script** (`document_start`, so the navigation listeners exist before the first navigation; both YouTube origins,
  top frame only) starts `site.js` navigation watching, then per page:
  `cards.js` on the pages of decision 16 (a `MutationObserver` batches new anchors), `player.js` on watch pages (waits for the
  `<video>` element, emits video id changes, ad state, duration), with `captions.js`, `cuts.js` and the panel bound to it.
- **Desktop page** (`www.youtube.com`) and **mobile page** (`m.youtube.com`) share every module. They differ in `site.js` (the
  list of card container names, the field lookups) and `layout.js` (panel docked right against bottom sheet, hover against
  chip). Both sites are single-page apps that reuse, move and replace their video element: every per-video object is torn down on a
  video id change and on a change of the main video element.
- **Captions hook**: `captions.js` owns one text track per language label on the video element; on a ready answer it parses the
  WebVTT (`vtt.js`: header, timings, cue text, `[S1]` prefixes kept as text) and adds cues; on a video change it removes the cues
  and sets the track to `disabled`; while an ad plays the track is `hidden`.
- **Cuts hook**: `cuts.js` owns the active cut, the skipper, the toast, the Apply offer, and the length and ad guards.
- **CORS and origin**: the backend needs no change because background requests with a granted host permission are not subject to
  CORS and bearer calls are not origin-checked (section 1). The mock answers `OPTIONS` with 405 and sends no CORS headers, so a
  regression that moves a call into a content script fails a test.
- **Errors**: a failed assess leaves cards untouched; a missing video element, an unknown page shape or a thrown error in
  `site.js` turns that feature off for the page and logs once under the `u-tubot` prefix. Nothing is ever removed from the page
  except by a `hide` verdict.

## 5. Privacy

`docs/privacy.md` gains a "Browser extension" section (checkpoint 9):

- What leaves the browser, to the user's backend only: the same fields as the TV (card metadata for assess, the video id with
  title, channel and duration, the pairing code and device name, the token).
- YouTube cookies, account and history are never read or sent; backend requests carry no cookies either.
- "YouTube's own scripts run in the same page. They can see what the extension adds there: the mark labels, which cards are
  hidden, and the text of the HQ captions while they are shown. They cannot see your server's address, your token or your user
  name: those never enter the page."
- Thumbnails of the Processed page load from YouTube's image host.
- Nothing goes to the authors. The store listing (if any) links to this page.

## 6. Offline and YouTube-access rules

- No test, CI job, emulator run or agent check may load any YouTube or Google address. This includes thumbnails.
- Stand-in pages are hand-written from the structure `site.js` relies on (anchors with watch links inside the listed container
  names, one `<video>` element, a title element); they are not copies of YouTube pages and contain no YouTube script.
- A fixture video is generated at test time with `ffmpeg` (test pattern, 240 s, low resolution) and served from loopback.
- The **test variant** of the build (`build.mjs --variant firefox-test`) differs from the release manifest in exactly three ways: the
  content-script matches and required host permissions are `http://127.0.0.1/*` (the fixture pages, nothing else); the two
  YouTube origins move from required to optional host permissions (so a test starts without them and can exercise "Allow on
  YouTube"; the notice code checks the same two origins in every variant); and the
  `<meta name="utubot-fixture-site" content="www|m">` override is enabled. A unit test fails if the unlisted or listed variant
  contains a loopback match or the override.
- **Loopback layout of the tests**: fixture pages on `127.0.0.1` (required permission of the test variant). The mock backend
  listens on `127.0.0.2` and `127.0.0.3`, which no manifest names, so they stay optional: a permission request for them is a
  real request and `permissions.remove` really removes them. `localhost` is not used.
- **Prompt driver** (how a permission prompt is answered in e2e): the preference
  `extensions.webextOptionalPermissionPrompts` is `false` in `user.js`, so Firefox grants a request without showing the
  doorhanger. Firefox still requires the user-action context, so a request made after an `await` is still rejected and the
  tests still catch that mistake. "Don't allow" cannot happen with this preference; the refusal paths are unit tests with
  `permissions.request` stubbed to answer false (checkpoint 4), and the real doorhanger with both answers is exercised by hand
  in the recorded runs of checkpoint 4 (desktop) and checkpoint 10 (Android). No browser-chrome automation is used.
  Two assumptions carry this, each with its fallback, decided now:
  - *The auto-grant preference still enforces the user-action rule.* If checkpoint 4 finds that a request after an `await` is
    granted with the preference on, that one case becomes a unit test (the request helper refuses to run when not called
    synchronously from a handler, checked with a stub) and the real rejection is added to the recorded hand run of checkpoint 4.
  - *A WebDriver click counts as a user action for `permissions.request`.* If checkpoint 4 finds it does not, the permission
    cases keep their e2e form for everything after the grant by seeding the grant through a test-variant-only page button
    wired to the same handler, and the click-to-prompt path itself is checked in the recorded hand runs of checkpoint 4 (desktop) and
    checkpoint 10 (Android) and again by the owner at checkpoint 9.
  Either outcome is recorded in this section when it is found.
- **The guard, fully specified:**
  - `tests/e2e/refusing_proxy.py`: a stdlib Python HTTP and CONNECT proxy on a loopback port that answers every request with 502
    and records method and host. It is the only proxy; exactly `127.0.0.1`, `127.0.0.2` and `127.0.0.3` are exempt (`network.proxy.no_proxies_on`,
    `network.proxy.allow_hijacking_localhost` false). No e2e test sends a request to any other address, private ones included:
    the private-address rule is unit-tested without a request, and a real private-address request is made only in the
    Android emulator run (checkpoint 10, the emulator's host alias).
  - `tests/e2e/user.js`: the committed preference file every test profile starts from. It sets the manual proxy for HTTP and
    HTTPS to the refusing proxy and turns off, by name: application and add-on updates and add-on metadata, the blocklist and
    remote settings, telemetry and health report, Normandy and experiments, safe browsing lists, captive-portal and
    connectivity checks, DNS over HTTPS (`network.trr.mode` 5), DNS and link prefetch, speculative connections, the push
    service, new-tab content and sponsored tiles, search suggestions and search-engine updates, location services, default
    browser and first-run pages. A unit test checks that each named group has its preference in the file.
  - The suite ends with a check that fails when the proxy recorded any request at all, printing the hosts. A new Firefox
    service that phones home is fixed by adding its preference to `user.js`, never by relaxing the check.
  - Selenium runs with `SE_OFFLINE=true` and explicit binary paths (`FIREFOX_BIN`, `GECKODRIVER_BIN`); Selenium Manager never
    downloads. `tests/e2e/tools.lock` pins the exact Firefox version (an ESR 140 point release, so the oldest supported version
    is what is tested) from Mozilla's release archive and the geckodriver version from the geckodriver project's GitHub
    releases, each with its source URL and SHA-256; CI downloads both before the suite starts and verifies the hashes. The download step is the job's only network use.
  - Network namespace: **always for local and agent runs** (`tests/e2e/run-offline.sh` starts the suite in a namespace with
    loopback only, as the emulator recipe in `docs/development.md`), **not in CI** (hosted runners; the proxy guard and the
    preference file are the CI guard).
- The Android emulator runs (checkpoints 10 and 18) use a namespace with no route out. The fixture pages are reached as
  `127.0.0.1` through `adb reverse` (the test variant's required origin). The backend is reached as `10.0.2.2:<port>`, the
  emulator's alias of the host's loopback, so the mock also listens on `127.0.0.1` in that namespace; `10.0.2.2` is in no
  manifest, so Import setup shows the real permission prompt. The backend is never typed as `127.0.0.1` there.
- **Chromium track** (checkpoint 19): the same fixtures and mock, driven by Playwright with the unpacked `chromium-test`
  build in a persistent Chromium profile. Chromium is started with a host-resolver rule that maps every name except the
  loopback addresses to "not found", so nothing can leave even before a test installs its routes (the technique of the
  hermetic suite in section 15). The browser comes from Playwright's pinned download in CI (the job's only network use) and
  runs with `PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` afterwards.
- The real-YouTube check is the owner's own use of a released build. Agents never do it. This is a deliberate difference
  from the extensions of section 15, which keep live-YouTube suites; one of them has its live test switched off.

## 7. Test approach

| Layer | Tool | Covers |
|---|---|---|
| Unit | `node --test`, no browser | client URLs and query fields, `credentials: "omit"` on every request, auth scoping, setup resolution and the private-host rule, message sets, parsers, state text, panel model and countdown (fake clock), poll cap, cut skipper (the cases of `UtubotCutSkipperTest`), VTT parser, policy, section mapping, caches, manifest variants |
| Static | `eslint`, `web-ext lint` (it catches some Android-incompatible keys and APIs, not all), the greps of decision 14 and for any host other than the placeholders | both platforms |
| Mock backend | pytest in `ai-backend/tests/test_emulator_mock.py` | every `/__mock` control of section 8 |
| End to end, desktop | pytest + Selenium + geckodriver, headless Firefox, test variant, the mock backend, the fixture server, the guard of section 6 | setup and pairing with both permission flows on optional loopback origins, missing YouTube permission, marks and hiding, glance and Summary view with every transcript state, answer, captions while playing and from the store, cuts, Processed |
| End to end, mobile layout | same harness, `m` fixtures, 360 px viewport, touch events | the Android behaviours of the matrix in the mobile page shape |
| Android runtime | Android emulator, Firefox for Android installed from Mozilla's APK, `web-ext run --target=firefox-android` | checkpoint 10: install, YouTube permission state and the "Allow on YouTube" button, the real permission prompt with both answers, pairing, storage, held requests, `http` to a private address. Checkpoint 18: a mark, a summary, captions and a cut on the fixture pages. By an agent, not in CI |
| API availability | checkpoint 18's audit: every extension-API call in `api.js` checked against MDN's compatibility table for Firefox for Android 142 | what lint does not report |
| Owner smoke runs | the owner, the unsigned build, the popup diagnostics | after checkpoints 5 and 7: whether the page facts the player layer and the captions rest on hold on real YouTube |
| End to end, Chromium | Playwright, unpacked `chromium-test` build, same fixtures and mock, resolver rule | checkpoint 19: the MVP flows and whichever parity features exist, in a service worker background |
| Real YouTube | the owner, a released build (first at checkpoint 9b) | page-structure drift |

## 8. Backend, contract and mock changes

- **Backend code: none.** No new endpoint, field, header or CORS rule. No app change either (decision 20 keeps the release
  readers untouched).
- **`ai/CONTRACT.md`** (in this pull request): the section "Clients" (text in section 10) and the corrected sentence about
  `transcript_hash` (the TV applies a cut by the length check; the hash is carried, not compared).
- **`.github/pull_request_template.md`** (in this pull request).
- **`scripts/emulator_mock_backend.py`** (checkpoint 1, all at once, so no later checkpoint invents a control). Existing
  behaviour and defaults stay, so the TV recipes in `docs/development.md` keep working:

  | Addition | Control and answer |
  |---|---|
  | Request log | `GET /__mock/requests` -> `{"requests":[{"method","path","query","authorization":bool,"cookie":bool,"origin":bool}]}` (never a header value); `GET /__mock/requests?clear=1` empties it. `/__mock/*` calls are not logged |
  | `OPTIONS` | any path -> `405`, logged |
  | Listen addresses | `--host ADDRESS`, repeatable (default as today); the e2e harness passes `127.0.0.2` and `127.0.0.3` |
  | Pairing user | `--user NAME` (default `emu`, as today); `POST /v1/pair` and `GET /v1/me` answer that name. The extension's tests keep the default and expect "Paired as emu" |
  | Setup with another origin | `GET /__mock/setup?backend=URL` makes `/setup.json` answer that `backend_url` (empty value: back to its own base). Tests type `127.0.0.2:<port>` and set `http://127.0.0.3:<port>`, the same server under another origin |
  | Hold | `GET /__mock/hold?path=PREFIX&seconds=S` holds every later request whose path starts with `PREFIX` for `S` seconds before answering (`seconds=0` clears) |
  | Assess verdicts | `GET /__mock/assess?video=ID&action=none\|mark\|hide[&label=TEXT][&status=ready\|pending][&answer=TEXT]` sets one video's verdict (`answer` fills `answer_short`); `GET /__mock/assess?delay=S` delays every assess answer; `GET /__mock/assess?fail=500` makes assess answer that status (`fail=0` clears) |
  | Panel prompt refusal | `GET /__mock/set?panel=ok\|400\|404`: the status of a `prompt=panel` summary request |
  | Failure with a reason | `GET /__mock/set?mode=failed&reason=private` adds `reason` to the `failed` answer (absent: as today) |
  | Prompts writes | `POST /v1/prompts/import {"url"}` -> a canned set whose id is the URL's last path part, then listed by `GET /v1/prompts`; `POST /v1/prompts/refresh` -> `{"ok":true}`; `PUT /v1/prompts/default {"key"}` -> `{"default":key}` and the list's `default` follows, `404` for an unknown key |
  | Processed | `GET /v1/processed?limit=N` -> two canned videos in the contract's shape with loopback thumbnails; `GET /__mock/processed?state=items\|empty\|fail` |

- **`docs/`**: `docs/install.md` (Firefox section), `docs/privacy.md` (section 5), `docs/development.md` (build, tests, the
  offline guard, the new mock controls), `README.md` (Features).

## 9. Build, signing, distribution

- `node build.mjs --variant <name>` (decision 25) writes `extension/dist/<variant>/`; `web-ext build` zips it.
- Signing: `web-ext sign --channel=unlisted` with `WEB_EXT_API_KEY` and `WEB_EXT_API_SECRET` from repository secrets
  (`AMO_JWT_ISSUER`, `AMO_JWT_SECRET`). The keys are never committed, printed or written to an artifact; `extension/.gitignore`
  lists `.amo-credentials`, `web-ext-artifacts/`, `dist/`.
- **Release wiring** (one path, named):
  - `utubot-ci.yml`, job `changes`: new outputs `extension` (extension files changed) and `extension_release` (push to `main`,
    and the version in `extension/version` has no `utubot-ext-v<version>` tag).
  - `utubot-ci.yml`, new job `extension-release`: `needs: [changes, backend, extension]` (it reads all three results; `!cancelled()` in its
    condition, as the APK `release` job, so a skipped `backend` does not skip it); runs only in this repository, on a push, when
    `extension_release` is true, `extension` succeeded, `backend` succeeded or was skipped, and the repository variable
    `UTUBOT_EXTENSION_RELEASES` is `on`; its one step is
    `gh workflow run utubot-extension-release.yml --ref main --field sha=$GITHUB_SHA`. The variable is unset until the owner
    has added the signing secrets, so the merge of checkpoint 9 (version `0.1.0`, untagged) starts nothing; the first push
    after the owner sets it releases. The existing `release` job (APK) is not changed.
  - `.github/workflows/utubot-extension-release.yml` (`workflow_dispatch` with `sha` and `dry_run`, `ubuntu-24.04`, one run at
    a time), in this order:
    1. Secrets check. If `AMO_JWT_ISSUER` or `AMO_JWT_SECRET` is empty and this is not a dry run: write the notice "Extension
       signing secrets are not configured; nothing was released" to the log and the step summary and end the run
       successfully. Nothing is committed, tagged or published, and no unsigned file is ever published. A run on `main` is
       never failed for missing secrets.
    2. Guards: the commit is on `main`; the version's tag does not exist; the version is higher than every existing
       `utubot-ext-v*` tag; CI is green for the commit by the same rule as the APK workflow's `ci_green` (a completed
       successful `u-tubot CI` run on `main` for the commit, or, for the run that dispatched this workflow, an in-progress run
       whose `extension` job succeeded and whose `backend` job succeeded or was skipped). The rule is not a shell function in
       the workflow: it is the command `ci-green` of `scripts/utubot_ci_changes.py`, a pure function over the runs and jobs
       JSON that the workflow fetches with `gh api` and passes in, unit-tested in `ai-backend/tests/test_ci_changes.py`. The
       APK workflow keeps its own function unchanged. A failed guard fails this run with its reason.
    3. Build, lint, unit tests, sign; write `SHA256SUMS` and `updates.json` (id, version, `update_link`, `update_hash`,
       `strict_min_version` for both platforms).
    4. Replace the single commit of `extension-updates` (the new files plus the newest four earlier `.xpi` files) and put the
       tag `utubot-ext-v<version>` on the released `main` commit. No GitHub Release is created.
    A run by hand follows the same steps. A dry run stops after step 3 and uploads the unsigned package, the checksums and
    `updates.json` as workflow artifacts only.
  - **Owner setup list for releases** (D4), in this order: create the developer account; add the secrets `AMO_JWT_ISSUER` and
    `AMO_JWT_SECRET`; make `parity-box` a required status check for `main` (branch protection or ruleset; until then the
    check only shows red and does not block a merge); set the variable `UTUBOT_EXTENSION_RELEASES` to `on`.
  - Before the first release, checkpoint 9 checks that no branch ruleset or protection blocks the workflow's push to
    `extension-updates` (`gh api repos/{owner}/{repo}/rulesets`) and records the result.
- The listed variant has no `update_url` and is uploaded by the owner (or with `web-ext sign --channel=listed`) only after D1's
  second step is confirmed.
- **When**: the release wiring is built at checkpoint 9, the end of the MVP, so the owner's setup list above is needed
  then, not at the end of the plan. Later checkpoints release by raising the version.
- **Chromium** (checkpoint 20): the release workflow also attaches nothing to GitHub Releases. It writes
  `u-tubot-chromium-<version>.zip` (the unpacked `chromium` build) to the same `extension-updates` branch. Installing it is
  "Load unpacked" with developer mode on (works on Windows, macOS and Linux; no automatic update; Chrome shows a developer-mode
  reminder). A self-hosted `.crx` is not built: Chrome refuses it on Windows and macOS. The Chrome Web Store (unlisted
  visibility, one-time registration fee, review) and Edge Add-ons are the real distribution and are submitted only on the
  owner's word (D8); the same zip is what gets uploaded.
- Install instructions (`docs/install.md`): desktop, download the `.xpi` and use "Install Add-on From File" (a raw file link
  does not start the install by itself); Android, save the file, unlock the hidden menu, "Install extension from file".

## 10. The standing rule (exact texts, all three in this pull request)

`AGENTS.md`:

> - Two clients, one feature set: every new or changed AI feature is specified, built and tested for the TV app (`stutubot`
>   flavor) and the browser extension (`extension/`, plan in `ai/BROWSER_EXTENSION_PLAN.md`) in the same pull request or in two
>   linked ones. If one client cannot have it, `ai/CONTRACT.md` ("Clients") says which and why. A plan or pull request for an AI
>   feature that names only one client is incomplete. Transition: until checkpoint 18 of that plan has landed, the extension
>   side of a new AI feature is its row in the plan's parity matrix (section 3), added in the same pull request. The
>   extension stays MIT: GPL or other copyleft extensions may be read for techniques, never copied; code is copied only from
>   MIT, BSD or Apache-2.0 sources, with attribution.

`.github/pull_request_template.md`:

```
- [ ] AI feature parity: this change works in the TV app and the browser extension, or `ai/CONTRACT.md` ("Clients") says why
      one of them does not have it. Until the extension exists: the feature's row is in `ai/BROWSER_EXTENSION_PLAN.md`.
      (Not an AI feature: tick and write "n/a".)
- [ ] `ai/CONTRACT.md` changed together with the code that changes the wire.
- [ ] No test or check contacts YouTube; no host, token or key in the tree.
```

`ai/CONTRACT.md`, section "Clients" after "App behaviour summary": the two clients, the four exceptions with their reasons
(matrix rows `cut-qr`, `sponsor-merge`, `browse-cache`, `self-update`), and the sentence that the extension sends the bearer token from its background context only, with
no cookies and never `?token=`.

Enforcement beyond review (checkpoint 0): a workflow of its own, `.github/workflows/utubot-parity.yml`, with the single job
`parity-box` on `ubuntu-24.04`.

- Trigger: `pull_request` with the types `opened`, `edited`, `synchronize`, `reopened` only. It has no `push` trigger, so it
  never runs for `main`. Ticking the box in the description re-runs only this small job, not the test pipeline.
- It is not part of `utubot-ci.yml` and no job there depends on it, so a missing tick never hides the backend, app or
  extension results.
- It blocks a merge only once the owner makes `parity-box` a required status check for `main` (section 9, owner setup list);
  that is the intended end state.
- Rule (`scripts/utubot_ci_changes.py parity`): fail when the pull request changes `common/**/utubot/**`,
  `smarttubetv/**/utubot/**` or `ai/CONTRACT.md`, changes nothing under `extension/` and not this plan, and the description has
  no ticked parity box. Otherwise pass.
- Inputs: the changed files from the GitHub API (as the `changes` job does); the description through the environment
  (`env: PR_BODY: ${{ github.event.pull_request.body }}`, read with `os.environ`), never interpolated into a `run:` line. The
  description is only matched against a fixed pattern, never executed or printed.

## 11. Checkpoints

Tiers follow the repository's model policy: **Fast** for straightforward implementation from this plan, **Heavy** for the
tricky parts. Every checkpoint ends with a clean-context review by the same tier that implemented it (a separate reviewer with
the plan, the diff and the evidence, never the implementer's own session), and its findings are fixed before the next one
starts. Before the final outcome review, the whole result gets a Heavy clean-context review; the plan and the outcome are then
reviewed by the plan reviewer. One pull request per checkpoint, each updating `extension/DEVLOG.md`.

Order and gates:

- **0 to 9b are the MVP** (desktop Firefox, section 17), in this order. Each checkpoint's own review is the only gate, with
  these named steps in between:
  - **Owner smoke run 1**, after checkpoint 5, and **owner smoke run 2**, after checkpoint 7: the owner loads the unsigned
    `firefox-unlisted` build through `about:debugging` on real YouTube and sends back the popup's diagnostic text (decision
    15). No agent opens YouTube. Work on the next checkpoint goes on meanwhile; a difference the owner reports is fixed in the
    site layer, with a fixture for it, before checkpoint 9.
  - **MVP review**, after checkpoint 9 and before the first signed release: a Heavy clean-context review of checkpoints 0 to
    9 as one result (token scoping, the two message sets, the permission flows, what enters the page, the release workflow),
    then the plan reviewer's outcome review of the same. Only after both pass does the owner set
    `UTUBOT_EXTENSION_RELEASES` to `on`. The same pair of reviews is repeated for the whole result after checkpoint 21.
- **10 is the Android gate**: 18 (the Android pass) does not start until it has passed or the V2 fallback has been written
  into this plan. It does not block 11 to 17, which are desktop work with mobile-layout tests.
- A request held on one video must never show on the next: checkpoints 6, 7 and 8 each carry that test.
- **11 to 18** complete parity on Firefox. **19 and 20** are the Chromium track; they depend only on the MVP and may run
  beside 11 to 18 when a second agent is free, otherwise after 18. **21** is the owner's pass and the store steps.
- **C1 to C4** are the web UI companion (section 18): after 21, re-planned against `main` before they start.
- Every checkpoint's Done When is a test or a recorded check on its own pull request. Review rules for licences: a diff whose
  structure follows a GPL file is rejected (decision 26).

| # | Scope | Main files | Done when | Tests | Tier |
|---|---|---|---|---|---|
| 0 | Skeleton and CI: `extension/` with `manifest.base.json`, `manifest.firefox.json`, `manifest.chromium.json`, the build script and its variants, `shared/api.js` and its lint rules, empty background and content script, `extension/AGENTS.md` (with the licence rule) and `THIRD_PARTY.md`; change classification moved out of the workflow into `scripts/utubot_ci_changes.py` with the outputs `backend`, `app`, `release`, `extension`, `extension_release`, and its `parity` command with the `utubot-parity.yml` workflow (section 10); `NON_APP` gains `extension/`; `extension` job | `extension/*`, `scripts/utubot_ci_changes.py`, `ai-backend/tests/test_ci_changes.py`, `.github/workflows/utubot-ci.yml`, `.github/workflows/utubot-parity.yml` | unit test of the classifier: a file list with only `extension/…` gives `extension` true, `app` false, `release` false; the existing cases (backend only, app file, pipeline file, docs only) give the answers the inline script gave; `parity` fails a contract change without the ticked box and passes it with the box, with an `extension/` change, or with a body that contains shell metacharacters (read from the environment). `web-ext lint` has no errors on the Firefox variants; the Chromium variant has a service worker and no Firefox-only key; the release variants contain no loopback match; eslint rejects `browser.`/`chrome.` outside `api.js` and `window`/`document` under `src/background/` | `test_ci_changes.py`; unit: manifest variants, lint fixtures; the pull request's own CI run | Fast |
| 1 | Mock backend controls: every row of section 8's table, `--host` included | `scripts/emulator_mock_backend.py`, `ai-backend/tests/test_emulator_mock.py`, `docs/development.md`; `BACKEND` path filter gains the script | one test per control passes against the script started on a loopback port; the defaults answer exactly as before (the existing recipes' requests are replayed in a test) | `test_emulator_mock.py` | Fast |
| 2 | Background core, no UI: client with every endpoint of section 1, `credentials: "omit"`, auth scoping, setup resolution and private-host rule, permission helpers, message router with the two sets, caches; no state in memory (service-worker rule) | `src/background/*`, `src/shared/{models,messages,api}.js` | unit: each endpoint's method, path and query (metadata, `is_live` for cuts); no request without `credentials: "omit"`; the header only for URLs under the backend; `http` to a public host refused; a content-script sender cannot call a page-only message; a bad video id is rejected; the router gives the same answers after its module is loaded afresh between two messages (nothing kept in memory) | unit (ported cases of `UtubotClientTest`, `UtubotSetupTest`) | Fast |
| 3 | The e2e harness, proven with one trivial test: fixture server on `127.0.0.1`, mock on `127.0.0.2` and `127.0.0.3`, refusing proxy, `user.js`, `tools.lock` with the download and hash step, `run-offline.sh`, Selenium offline setup, CI steps | `tests/e2e/*`, `.github/workflows/utubot-ci.yml` | e2e: the test variant loads as a temporary add-on in the pinned Firefox, its content script marks the `127.0.0.1` fixture page, the background answers a `health` message from the mock on `127.0.0.2`, and the proxy recorded nothing; `run-offline.sh` gives the same result inside the namespace; a deliberately added request to a non-loopback name makes the final check fail (then removed) | unit: `user.js` groups, `tools.lock` format; the one e2e | Heavy |
| 4 | Options page: Import setup with both permission flows, pairing, test connection, Advanced URL and token, switches, the YouTube permission notice, popup stub | `src/pages/{options,popup}.*`, `tests/e2e/test_setup.py`, `tests/unit/permissions.test.js` | e2e (mock origins are optional permissions, prompts answered by the auto-grant preference, section 6): import `127.0.0.2:<port>`, pair, "Paired as emu"; `permissions.contains` is true for `http://127.0.0.2/*` only after the Import click; the request log shows the header on `/v1/me` and not on `/setup.json` or `/v1/pair`, no `Cookie` on any request (a cookie for the mock's origin is planted first), no `OPTIONS`. With `/__mock/setup?backend=http://127.0.0.3:<port>` nothing is applied and `127.0.0.3` is not granted until "Allow access to http://127.0.0.3:<port>" is clicked; then calls go to that origin and `permissions.contains` is false for `127.0.0.2`. Advanced: saving the other origin grants it and removes the old one. Calling the request outside a click (a test hook that awaits first) is rejected by Firefox and nothing is stored. The YouTube origins start ungranted in the test variant: the options page and popup show "Allow on YouTube", the click grants both and the notice goes; after `permissions.remove` it is back. `http` on loopback pairs with HTTPS-Only mode off and on (loopback is exempt). The proxy recorded nothing. Unit, with `permissions.request` stubbed to answer false: Import, "Allow access" and Advanced store nothing, keep the previous backend and show "Permission was not given"; private literals (`10.0.0.5`, `192.168.1.10`, `host.local`) are accepted for `http` and a public name is refused, without any request. Recorded hand run in desktop Firefox with the preference off: the real prompt answered "Don't allow" (nothing stored) and allowed; a request held 20 s answered; a request held 45 s, result recorded | unit as listed; e2e as listed; the recorded hand run | Heavy |
| 5 | Site layer, player part (decision 15): site kind, navigation by events with the poll fallback, video id, main video element among several and its replacement, ad state, duration; the diagnostics report and its popup view; watch fixtures for `www` (and one for `m`, used from checkpoint 10 on) that dispatch the navigation events, replace the video element and carry a hover-preview video | `src/content/{site,player,main}.js`, `src/pages/popup.*`, `tests/fixtures/site/**` | e2e on the watch fixture: an in-page navigation is noticed through the event within 100 ms and, with the events removed from the fixture, through the poll within 1 s; the video id, duration and ad events fire once per change; a second playing `<video>` (preview) is never taken for the main one; replacing the main `<video>` element re-binds; an unknown page shape logs once and changes nothing; with the extension context gone every timer stops; the popup shows the diagnostic lines for the fixture and they contain no address, token or title. After the merge: owner smoke run 1, its diagnostic text recorded in `extension/DEVLOG.md` | unit: URL and id parsing, the main-video rule over element descriptions; e2e as listed | Heavy |
| 6 | Summary of the playing video: the shadow-root host and panel, panel model, state text, countdown, poll cap, working indicator; the panel prompt's short summary on top and the Summary view (prompt list, session prompt, Transcribe in background with follow-up) | `src/shared/{panelmodel,statetext,countdown}.js`, `src/content/ui/{host,panel}.js` | e2e on the watch fixture with the mock's modes: `ready`; `needs_transcript` (server `message` shown, Transcribe starts the job, progress every 4 s, the summary arrives); `delayed` (server `error`, countdown, no retry before `retry_after_s`); `failed` with and without `reason`; `auto_transcribe`; `panel=404` falls back to the first prompt; requests carry `title`, `channel`, `duration_s`; a request stops after 6 long polls; choosing a prompt reloads the text and is kept for the session; no page-visible node holds the backend address; stale answer: with `/__mock/hold` on video A's summary request, navigate in the page to video B and release the hold: B's panel never shows A's text | unit: ported cases of `UtubotPanelModelTest`, `UtubotStateTextTest`; e2e as listed | Heavy |
| 7 | HQ captions: prepare, follower, VTT parser, native text track on the main video, auto-select rule, toast, caption store, ad pause | `src/content/{captions,followers}.js`, `src/shared/vtt.js`, `src/background/captionstore.js` | e2e on the watch fixture with the generated video: a job that turns ready while playing adds a showing track whose active cue text matches the mock's file at a known time, with the toast; with auto-select off the track is listed and not showing; after a browser restart with the mock stopped the stored track still shows and no request is made; a file over 4 MiB or without the WEBVTT header is not stored; a video change clears the cues; the track is hidden while the ad flag is set; the preview video gets no track; stale answer: with the hold on video A's captions status and on its file request (two cases), navigate to video B and release: no cue and no track label of A is on B, and A's file is still stored under A; the diagnostics show the track's mode and cue count. After the merge: owner smoke run 2 (are the cues visible on real YouTube), recorded; "not visible" triggers decision 12's contingency before checkpoint 9 | unit: VTT parser, follower (ported cases of `UtubotCaptionsFollowerTest`), store rules; e2e as listed | Heavy |
| 8 | Cuts in the player (decision 13): skipper with the armed timer and the `timeupdate` net, follower, length and ad guards, end-of-video rule, ready offer and automatic apply, toast with Back | `src/content/cuts.js`, `src/shared/cutskipper.js`, `src/content/followers.js` | e2e: with the mock's cut, playback crossing 60 s continues at 108 s within 300 ms of the boundary, at 1x and at 2x speed, and the toast shows "Skipped 0:48"; Back returns into the skipped part and it plays; a user seek into a skipped part plays; the skipper's own jump is not taken for a user seek; pausing before a boundary and resuming still skips; a cut whose last skipped part reaches the end ends the video; a cut built for 200 s on the 240 s video is refused with the message; a request that becomes ready while playing is applied from the current position; automatic apply applies without the offer; nothing is skipped while the ad flag is set or in the preview video; stale answer: with the hold on video A's cut list and on its followed request (two cases), navigate to video B and release: nothing is offered, applied or skipped on B | unit: skipper (ported cases of `UtubotCutSkipperTest`, without sponsor segments) and its timer arithmetic with a fake clock, follower (ported cases of `UtubotCutFollowerTest`); e2e as listed | Heavy |
| 9 | **MVP release machinery and the first signed build.** The `extension-release` job, the release workflow, the `ci-green` command, `updates.json`, the `extension-updates` branch, install and privacy docs, README | `.github/workflows/utubot-extension-release.yml`, `.github/workflows/utubot-ci.yml`, `scripts/utubot_ci_changes.py`, `docs/install.md`, `docs/privacy.md`, `README.md` | unit: `extension_release` is true only for an untagged version on a push to `main`; the `ci-green` command accepts a completed green run and the dispatching in-progress run with a green `extension` job, and refuses a red or missing one; `updates.json` is valid for a given version and hash. A dry run of the workflow (signing skipped without secrets) produces the package, checksums and `updates.json` as artifacts and creates no GitHub Release. Without the variable `UTUBOT_EXTENSION_RELEASES` the merge starts no release; a run by hand without secrets ends successfully with the notice and publishes nothing; the ruleset check is recorded. The tree and the logs contain no key. Then, after the **MVP review** has passed and the owner has set the secrets and the variable: one signed version is on the branch and installs on desktop Firefox | unit; workflow dry run; the first signed release | Fast |
| 9b | **The MVP in the owner's hands.** The owner installs the signed file and uses it on real YouTube; a second version proves the update path; every finding is fixed here or moved to a named later checkpoint | `src/content/site.js` and whatever the findings touch, `tests/fixtures/site/**`, `extension/DEVLOG.md` | the owner's findings list is recorded in `extension/DEVLOG.md` and each entry is closed by a fix with a fixture of the page shape that broke, or carries the number of the later checkpoint that takes it; after a version bump the installed copy updated itself (or the failure is recorded with what the owner did instead); the checkpoint closes when the list has no open entry | regression fixtures; the owner's confirmation | Heavy |
| 10 | **Gate: Manifest V3 on Android.** Emulator run of the test variant with the MVP features | `extension/README.md` (the recipe), `extension/DEVLOG.md` (the recorded run) | recorded log of: install; the YouTube permission state after install and the "Allow on YouTube" button; Import setup of `10.0.2.2:<port>` with the real permission prompt, once answered "Don't allow" (nothing stored, "Permission was not given") and once allowed; pairing; settings surviving a Firefox restart; a request held 20 s by `/__mock/hold` answered (must pass); a request held 45 s, longer than Firefox's 30 s event-page idle timeout, with the result recorded (answered: a pending request keeps the page alive; lost: the 20 s cap stays the rule and the result is added to section 4 of this plan); `http` to `10.0.2.2` with HTTPS-Only mode off (must pair) and on (result recorded; if it is blocked, the hint of decision 10 must be what the user sees); the summary, captions and a cut on the `m` watch fixture. A V3 gap found here adds the V2 variant for Firefox and records the decision in this plan | Android runtime check | Heavy |
| 11 | Site layer, cards part (decisions 15 and 16): section mapping, card discovery by container and by anchor, fields, recycled cards (`href` change), throttled scans, the mobile scan schedule, mark re-application; browse fixtures for both sites that add cards late, reuse a card element for another video and remove foreign nodes | `src/content/{site,cards}.js`, `tests/fixtures/site/**` | e2e on `www` and `m` fixtures: cards added after load are found once, with the fields of decision 16; each path of the mapping table gives its section or none; a card element whose link changes to another video is evaluated again and loses the old video's mark; a mark removed by the page is back after the next scan; 500 cards added at once cause at most one scan per 50 ms; a card with an unknown container is found through its anchor | unit: section, clock and field parsing; e2e as listed | Heavy |
| 12 | Assess: switch, batching, verdict cache, marks, hiding, mark only, answer in label, pending re-ask, caches dropped on connection change | `src/content/cards.js`, `src/shared/policy.js`, `src/background/cache.js` | e2e with `/__mock/assess`: a `hide` verdict hides its card and a `mark` shows its label on both fixtures; with mark only the hidden card is shown with a mark; `delay=5` or `fail=500` leaves every card visible; a `pending` verdict is asked again on the next scan; one call carries at most 50 videos and the page's section; a history fixture page sends no assess; an unrecognised container is never hidden; no page-visible node holds the backend address | unit: policy, cache, batcher; e2e as listed | Fast |
| 13 | Glance on cards: the glance card (hover) and glance sheet (chip), the Summary panel toggle and delay, busy badge, "Summary options" into the Summary view | `src/content/ui/{glance,sheet}.js`, `src/shared/debounce.js` | e2e: a hover of the panel delay shows the passive card with the `prompt=panel` summary and its states; a shorter hover sends nothing; moving away drops the request and a late answer is ignored; the `m` fixture opens the sheet from the chip; the toggle in the popup, chip menu and options page turns the mode off everywhere | unit: ported cases of `PanelCoordinatorTest`, `FocusDebouncerTest`; e2e as listed | Fast |
| 14 | AI answer and the chip menu: the "Answer" tab and the card's menu (answer, summary, prepare captions, cut) | `src/content/ui/panel.js`, `src/shared/panelmodel.js` | e2e: the answer shows question, answer, key points and source, counts a delay down and follows a transcription; the chip shows `answer_short` when known and the switch is on; each menu item starts its flow for that card's video | unit: ported cases of `UtubotAnswerModelTest`; e2e as listed | Fast |
| 15 | Prompts section of the options page: list, choose default, Import from URL, Refresh all, pending prompt sets after pairing | `src/pages/options.*` | e2e: import adds the set to the list; choosing a default sends `PUT /v1/prompts/default` and the list follows; refresh sends its request; an unknown key shows the server's error; the setup's `prompt_set_urls` are imported after pairing | e2e as listed | Fast |
| 16 | Cut picker and its ways in: presets with state, build request, kept parts and timeline, "Describe here", "Open cut sheet", the carried cut from a card | `src/content/ui/panel.js`, `src/content/cuts.js` | e2e: the picker shows each preset state of the mock; a `none` preset posts `{"preset"}` with `title`, `channel`, `duration_s`, `is_live` and is followed to ready; picking the applied cut takes it off; "Describe here" posts `{"prompt"}`; "Open cut sheet" posts `{"await_prompt":true}` and opens `<backend>/cuts/<id>`; a ready cut picked on a card opens the watch fixture with the cut applied, once; a kept part's click seeks | unit: state text, part formatting; e2e as listed | Fast |
| 17 | Processed page and its open, full popup, About | `src/pages/{processed,popup}.*` | e2e with `/__mock/processed`: tiles in the mock's order with the processed line; empty and failed states; a tile opens the fixture watch page in the same tab and its HQ track is showing with auto-select off; the one-shot request does not carry to a second open; no image request leaves loopback | unit: tile text (ported cases of `UtubotProcessedTilesTest`); e2e as listed | Fast |
| 18 | Android pass and parity audit: sheet layout, touch targets, the full Android runtime check, the API availability audit, every matrix row tied to its evidence | `src/content/ui/{layout,sheet}.js`, `extension/README.md` | every matrix row has a passing test or a recorded Android check named next to it in `extension/README.md`; every extension-API call in `api.js` is listed with its Firefox for Android support from MDN; the recorded emulator run covers install, setup, a mark, a summary, captions and a cut; no horizontal scroll at 360 px | e2e mobile layout; Android runtime check | Heavy |
| 19 | Chromium build and tests: the `chromium` and `chromium-test` variants, the service-worker background (no code change expected beyond `api.js`; any found is fixed here), the Playwright harness with the resolver rule, the `extension-chromium` CI job | `manifest.chromium.json`, `src/shared/api.js`, `tests/e2e-chromium/*`, `.github/workflows/utubot-ci.yml` | Playwright, unpacked build, pinned Chromium: setup and pairing (the `chromium-test` variant lists the mock's loopback addresses as required host permissions, because Chromium's permission dialog cannot be answered by the test driver; the request, grant, removal and refusal logic is covered by the Firefox e2e and the unit tests, and Chromium's real dialog with both answers by checkpoint 20's recorded hand install), the summary, captions and a cut on the watch fixture, a mark and a hide on the browse fixture; a request held 20 s is answered after the service worker had no other activity; after the service worker is stopped by the test a message still gets its answer (state came from storage); `http` on loopback works; the resolver rule's log shows no lookup of a non-loopback name. Recorded results (not gates): `http` to a private non-loopback address, and a 45 s held request | unit suite unchanged and green; Playwright e2e as listed | Heavy |
| 20 | Chromium packaging and docs: the zip on the `extension-updates` branch, "Load unpacked" instructions, the store checklist (what a Chrome Web Store and an Edge Add-ons submission needs: listing text, privacy answers, the mock backend as the reviewers' test server) | `.github/workflows/utubot-extension-release.yml`, `docs/install.md`, `extension/README.md` | the release dry run also produces the Chromium zip with its checksum; a hand install of that zip by "Load unpacked" in Chrome and in Edge is recorded with the MVP flows working against the mock, including the real permission dialog allowed and refused; nothing is submitted to a store | workflow dry run; recorded hand install | Fast |
| 21 | Owner's real-device pass and fixes on every target (Firefox desktop and Android, one Chromium browser); the Android install of the unlisted file and the Android update check; then, only on the owner's word, the store listings (D1, D8) | `src/content/site.js`, fixtures | the owner used released builds on real YouTube and each matrix row is ticked or has an issue; the phone picked up a second version through `update_url` or the result is recorded and the store listing proposed; every fix adds the page shape that broke to the fixtures | regression fixtures | Heavy |
| C1 | Companion, pairing hand-off (section 18): a web UI page that creates a pairing code for the signed-in user and hands it to the extension; the extension redeems it | web UI `js/pages/devices.js`, `src/background/setup.js`, `ai/CONTRACT.md` | to be fixed when the checkpoint is re-planned; outline in section 18 | backend web UI tests, extension e2e | Heavy |
| C2 | Companion, deep links both ways: "Open in u·tubot" from a YouTube page, "Play on YouTube" from the web UI with the captions and cut requests | web UI video page, `src/content/main.js`, `ai/CONTRACT.md` | as above | as above | Fast |
| C3 | Companion, shared settings: the extension's switches read from and written to the per-user settings document | `ai-backend/src/utubot/settings.py`, `src/background/*`, `ai/CONTRACT.md`, docs | as above | backend tests, extension e2e | Heavy |
| C4 | Companion, one Processed list: the extension's page and the web UI's list show the same items and link to each other | web UI, `src/pages/processed.*` | as above | as above | Fast |

## 12. CI

- This repository is public: every job runs on `ubuntu-24.04` hosted runners, never self-hosted. Actions are pinned by SHA like
  the existing ones.
- Job `extension` in `.github/workflows/utubot-ci.yml` runs when `extension/`, `ai/CONTRACT.md`,
  `scripts/emulator_mock_backend.py` or the pipeline itself changed: Node 22, `npm ci`, `eslint`, unit tests, build of the Firefox
  variants, `web-ext lint`, then `uv sync --frozen` in `extension/tests/e2e`, `ffmpeg`, the pinned Firefox and geckodriver of
  `tools.lock`, and the e2e suite headless behind the refusing proxy.
- `NON_APP` gains `extension/`, so an extension change is not an app change and never starts an APK release. The `backend` job
  also runs when `scripts/emulator_mock_backend.py` or `scripts/utubot_ci_changes.py` changed (their tests live there).
- Job `extension-chromium` (from checkpoint 19): same triggers; builds the `chromium-test` variant and runs the Playwright
  suite of section 6.
- Job `extension-release` and the release workflow: section 9. The `parity-box` job in its own workflow: section 10.
- The Android runtime check is not in CI (it needs an emulator and a Firefox APK); its evidence is the recorded log of
  checkpoints 10 and 18.

## 13. Could not be verified from here

| Item | Why | Settled by |
|---|---|---|
| The exact element names of YouTube's desktop and mobile pages (card containers, field lookups, ad marker) | agents never load YouTube | checkpoint 9 (owner, desktop Firefox, the player part) and checkpoint 21 (every target), with the "never hide an unknown container" rule until then |
| YouTube leaving native text-track cues visible on its video element | same; no extension read for section 15 does it | checkpoint 9 (the MVP's first real use); contingency in decision 12 |
| Manifest V3 behaving on current Firefox for Android, and whether the YouTube permission is granted at install there | no device here; Mozilla's guide still prefers V2 | checkpoint 10 |
| A pending message answer keeping the event page alive past Firefox's 30 s idle timeout | documented only in general terms | checkpoint 4's hand run (desktop) and checkpoint 10 (Android): 20 s must pass, 45 s recorded |
| `http` requests to a private address from the background once `upgrade-insecure-requests` is removed, with HTTPS-Only mode and Firefox's local-network access rules | MDN states the opt-out; not tried | loopback with and without HTTPS-Only in checkpoint 4 (expected: works, loopback is exempt); a non-loopback private address in checkpoint 10 (`10.0.2.2`), then the owner's own server in checkpoint 21 |
| Firefox applying `update_url` updates from raw file URLs (content types), and Firefox for Android applying them to a file-installed extension at all | not documented | checkpoint 9 (desktop, owner), checkpoint 21 (Android, owner); the store listing is the fallback |
| A version signed as unlisted being installable on Android with only `gecko_android` in the manifest | the signing post does not address unlisted | checkpoint 9's first signed file, installed in checkpoint 21 |
| Whether sending card data to the user's own server needs the three consent categories or fewer | Mozilla's page does not cover self-hosted servers | the signing validator at checkpoint 9; declaring them is the safe side |
| Whether YouTube's navigation events, the player container, the ad marker class and the card element names read from other extensions' code (section 15) are still current | read from their repositories on 2026-11-24, not from YouTube | checkpoint 9 (owner, desktop), checkpoint 21; the URL poll and the anchor fallback work without them |
| Chromium: `http` to a private address from the service worker (Chrome's local-network rules), optional host permission prompts, a 20 s request in an idle service worker | not tried | checkpoint 19 |
| The Chrome Web Store fee amount and whether review accepts an extension that needs the user's own server | the register page says "one-time" without the amount; review is case by case | owner decision D8, at submission |
| Edge for Android (or another Chromium phone browser) running this extension | no source found | not planned; noted in decision 25 |
| The web UI's newer phone work that is not on `main` yet | only `main` was read | section 18's checkpoints are re-checked against `main` before they start |
| An update from the V3 build to a V2 build of the same id keeping its settings, token, caption store and granted permissions (only if decision 2's fallback is used; it would reach desktop users of the MVP too) | not tried | checked on a desktop profile before such a release; if data is lost, the fallback ships as a separate Android-only build instead |
| `utubot.dev` as the id's domain part | an add-on id needs no real domain, but it is permanent | owner decision D5 |

## 14. Review response and owner additions

The three review tables below keep the checkpoint numbers of the plan they reviewed (revision `129048d0`). Old to current:
0 to 4 unchanged; 5 (Android gate) is 10; 6 (site layer) is 5 (player) and 11 (cards); 7 (assess) is 12; 8 (glance core) is 6
and 13; 9 (Summary view, answer) is 6 and 14; 10 (prompts) is 15; 11 (captions) is 7; 12 (cuts in the player) is 8; 13 (cut
picker) is 16; 14 (Processed) is 17; 15 (Android pass) is 18; 16 (release) is 9; 17 (owner pass) is 21.

### Owner additions (2026-11-24, after the plan review was approved)

| Addition | Change |
|---|---|
| Not Firefox-only: plan for Chromium browsers too | Decisions 2, 5 and 25 (one V3 codebase, base plus per-browser manifest, one API module, background written for a service worker); checkpoints 19 and 20 after the MVP; sections 6, 7, 9, 12 gained the Chromium parts; Chromium phones are not a target (decision 25); new owner decision D8. Plan, branch and pull request renamed to "browser extension" |
| Learn YouTube handling from existing extensions | Section 15 (what was read, techniques, file references); decisions 13 (timer-driven skipping, end-of-video rule, main video only) and 15 (navigation events, main video lookup, ad state, recycled cards, mobile scans, orphaned scripts) rewritten; checkpoints 5, 7, 8 and 11 changed to match; decision 27 (no page-world script) |
| Licence | Decided by the owner: MIT stays, techniques are re-implemented, GPL code is never copied, only permissively licensed code may be copied with attribution. Decision 26, `AGENTS.md`, checkpoint 0 (`extension/AGENTS.md`, `THIRD_PARTY.md`). Not an open decision |
| Ship an MVP as soon as possible | Section 17 and the reordered section 11: checkpoints 0 to 9 are the MVP on desktop Firefox (setup, pairing, summary of the playing video, HQ captions, cut skipping, signed unlisted build); the Android gate moved behind it; the release wiring moved to checkpoint 9, so D4 is needed there |
| Mid-term: companion of the web UI | Section 18, decision 28, checkpoints C1 to C4 (not MVP, not parity); no owner decision needed now |

### Fourth review (re-check of the owner additions)

| Finding | Change |
|---|---|
| M1 no whole-result review before the first signed release | Section 11: the named "MVP review" step (Heavy clean-context review of 0 to 9, then the plan reviewer) before `UTUBOT_EXTENSION_RELEASES` is switched on; checkpoint 9's signed release waits for it |
| M2 first real-page contact too late; checkpoint 9 open-ended | Owner smoke runs after checkpoints 5 and 7 with the popup diagnostics (decision 15, section 11); checkpoint 9 is the release machinery and first signed build (Fast), new checkpoint 9b is the owner's use and the fixes (Heavy, closes when the findings list is empty or moved); Part 1 "How you try it" rewritten |
| M3 stale-answer rule without a test | Checkpoints 6, 7 and 8: hold video A's request, navigate to B, release, nothing of A shown, added or applied |
| L1 sender check names Firefox's scheme | Decision 6: the base address from `runtime.getURL("")` |
| L2 device name on Chromium | Decision 22: "Chromium (desktop)" |
| L3 http hint names one browser | Decision 10: one browser-neutral hint |
| L4 the V2 fallback reaches desktop users too | Section 13: the update keeps data and permissions or the fallback ships as an Android-only build |
| L5 element lists close to a GPL file | Decision 15 and section 15: lists written fresh in the plan's own grouping |
| L6 content scripts cannot read `storage.session` | Decision 6: `open.set` (pages) and `open.take` (content script) |
| L7 two different MVP totals | Part 1 and section 17 both say about 85 hours (the smoke-run diagnostics, the MVP review and 9b added to the earlier 74) |

### First review

| Finding | Change |
|---|---|
| H1 extension releases crowd APK releases out of the 10 and 20 release windows | Decision 20: the extension never creates a GitHub Release; the signed file and `updates.json` live on the `extension-updates` branch, a tag marks the commit. Decision 21: a release only on a deliberate version bump. No app or backend change. Section 1 gained the fact; D1 reworded |
| H2 second permission request after an async fetch | Decision 9: explicit "Allow access to `<origin>`" button; `permissions.request` only directly in a click handler. Mock control and e2e case in checkpoints 1 and 4 |
| H3 mock backend additions unspecified; "Paired as owner" | Section 8 table lists every control and answer; checkpoint 1 builds them all with tests; Done When texts use the mock's user `emu` |
| M1 missing YouTube permission, Android | Decision 9 ("Allow on YouTube" in popup and options, `permissions.contains` on open), matrix row `first-launch-offers`, e2e in checkpoint 4, Android check in checkpoint 5, fact added to section 1 |
| M2 session-cookie fallback | Decision 8: `credentials: "omit"` and `cache: "no-store"` on every request; unit test (checkpoint 2), planted-cookie e2e with the request log (checkpoint 4); contract text says "no cookies" |
| M3 assess fields undecided | Decision 16: path-to-section table and the per-card fields; tested in checkpoints 6 and 7 |
| M4 Advanced URL without a permission step | Decision 9 and matrix row `connection-test`; e2e in checkpoint 4 |
| M5 missing constants | `MAX_POLLS` 6 and the captions cache of 30 in section 1, decision 7, matrix row `transcript-states`, checkpoint 8 |
| M6 release wiring contradictory | Section 9 names the `changes` outputs, the `extension-release` job, the workflow's inputs and refusal rules; section 12 points to it |
| M7 checkpoints too large | The connection checkpoint became 2, 3, 4 and the gate 5; summaries became 8, 9, 10; cuts became 12, 13 |
| M8 standing rule without transition; references missing | Transition clause in the rule; the contract "Clients" section and the pull request template are in this pull request; a CI check of the parity box in checkpoint 0 (section 10) |
| M9 YouTube scripts can observe page-visible additions | Section 5 text, Part 1 risk, decision 14's list of what enters the page and its test |
| M10 offline guard underspecified | Section 6: named proxy file, committed `user.js` with the listed groups, `SE_OFFLINE`, pinned Firefox and geckodriver with hashes, namespace always locally and never in CI |
| M11 checkpoint 0 not provable on its own pull request | The classifier becomes a script with a unit test; that test is the Done When |
| Firefox claim: lint coverage on Android | Sections 1 and 7 reworded; API availability audit against MDN in checkpoint 15 |
| Firefox claim: Android signing post and unlisted | Section 1 reworded; listed in section 13, settled by checkpoints 16 and 17 |
| L1 `is_live` on cut calls | Section 1, matrix row `metadata`, checkpoints 2 and 13 |
| L2 contract says the TV checks `transcript_hash` | The contract sentence is corrected in this pull request |
| L3 panel toggle, delay and assess switch without rows | Matrix rows `assess-switch` and `summary-panel-toggle` |
| L4 Processed tile: same or new tab | Decision 23: same tab |
| L5 initial version | Decision 21: `0.1.0` |
| L6 Android update check placement | Moved to checkpoint 17 (owner) |
| L7 message router restrictions, untrusted events | Decision 6 |
| L8 own seek against user seek | Decision 13 (`ownSeek` flag), tested in checkpoint 12 |
| L9 local-network access and HTTPS-Only mode | Checkpoints 4 and 5, section 13 |
| L10 review tier | Section 11: same-tier clean-context review per checkpoint as the model policy says, plus a Heavy clean-context review of the whole result before the final outcome review |

### Second review (re-check)

| Finding | Change |
|---|---|
| N1 permission e2e could not pass; prompt driver undecided | Section 6: fixtures on `127.0.0.1` (the only required loopback origin), mock on `127.0.0.2` and `127.0.0.3` (optional, so requests and removals are real), YouTube origins optional in the test variant; prompt driver is the auto-grant preference; refusals are unit tests with a stubbed `permissions.request`; the real prompt with both answers is in checkpoint 5's recorded runs. Decision 9 states what a refusal does. Mock gains `--host` |
| N2 "CI is green" unworkable for a dispatched run; missing secrets | Section 9: the APK workflow's `ci_green` rule copied with the job names changed; missing secrets end the run successfully with a notice and publish nothing; the `extension-release` job needs the repository variable `UTUBOT_EXTENSION_RELEASES`, so the checkpoint 16 merge starts nothing. D4 mentions the variable |
| N3 parity-box check gaps | Section 10: own workflow `utubot-parity.yml`, job `parity-box`, `pull_request` types with `edited`, no `push` trigger, independent of the test jobs, description passed through the environment |
| N4 private-address http case against the proxy guard | Section 6: no e2e request leaves the three loopback addresses; private literals are unit-tested without a request; expected outcomes stated (loopback works with and without HTTPS-Only; the non-loopback case is `10.0.2.2` in checkpoint 5, off must pair, on is recorded with the hint of decision 10) |
| N5 checkpoint 3 still too large | Split into 3 (harness and CI steps, one trivial e2e) and 4 (options page and permission cases); later checkpoints renumbered, the gate is 5 |
| N6 which commit the tag marks | Decision 20: the released `main` commit |
| N7 geckodriver source | Section 6: geckodriver from its project's GitHub releases, Firefox from Mozilla's archive, both with URL and hash in `tools.lock` |
| N8 removed files stay in the branch history | Decision 20: the branch is never merged and always holds one commit (force-push of that branch only) |
| N9 a 20 s hold proves nothing about the idle timeout | Checkpoint 5: 20 s must pass, 45 s (past the 30 s idle timeout) is run and recorded, on Android and desktop |
| N10 rulesets may block the branch push | Section 9 and checkpoint 16: ruleset check before the first release |

### Third review (approval, five lows)

| Finding | Change |
|---|---|
| R1 backend origin on the emulator | Section 6: the backend is `10.0.2.2:<port>` there (optional origin, real prompt), fixtures stay on `127.0.0.1` |
| R2 two untested assumptions without fallback | Section 6, prompt driver: a stated fallback for each (unit test plus recorded run; a test-only page button plus recorded runs and the owner check) |
| R3 `backend` missing from `needs` | Section 9: `needs: [changes, backend, extension]` with `!cancelled()` |
| R4 `ci_green` not unit-testable in YAML | Section 9 and checkpoint 16: the `ci-green` command of `scripts/utubot_ci_changes.py` with its unit test |
| R5 is `parity-box` required | Sections 9 and 10, D4: the owner makes it a required status check for `main`, in the release setup list |

### Open lows

None of the lows of either review is left open. Two items stay open by nature and are tracked in section 13, not here: the real
YouTube page shapes and the Android update path.

## 15. Lessons from existing extensions

What was read, on 2026-11-24, from their public repositories (never from YouTube):

| Project | Licence | Revision | Read for |
|---|---|---|---|
| SponsorBlock (`ajayyy/SponsorBlock`) | GPL-3.0 (LGPL-3.0 before an early commit, `LICENSE-HISTORY.txt`) | `8cdda0b` | segment skipping, video listeners, ad flag, mobile controls, manifests, tests |
| maze-utils (`ajayyy/maze-utils`, the library SponsorBlock and DeArrow share) | GPL-3.0 | `89005da` | navigation, video element lookup, card discovery, the page-world script, cleanup |
| DeArrow (`ajayyy/DeArrow`) | GPL-3.0 | `482cf99` | card containers and links, titles on cards |
| Return YouTube Dislike (`Anarios/return-youtube-dislike`) | GPL-3.0 | `21d6e71` | navigation handling, per-browser manifests, the hermetic test suite |
| ImprovedTube (`code-charity/youtube`) | its own copyleft terms (not a standard licence) | default branch of that day | ad marker, navigation events, the player's caption API |

**Rule (decision 26, owner's decision): techniques and facts are taken, code is not.** The names of YouTube's elements, classes
and events are facts about YouTube's page and are recorded below; every line that uses them is written fresh for this
repository under MIT. Nobody copies, translates or vendors a file from these projects. If copied code is ever wanted, it comes
from an MIT, BSD or Apache-2.0 source and is listed in `extension/THIRD_PARTY.md`.

### Navigation in a single-page site

- The desktop site announces navigation with `yt-navigate-start` and `yt-navigate-finish` on `document`; both are visible to
  a content script. Return YouTube Dislike resets its per-video state on start and initialises on finish
  (`Extensions/combined/ryd.content-script.js`). maze-utils listens to `yt-navigate-finish` in the content script and, in its
  page-world script, also to `yt-navigate-start` and `yt-player-updated` (`src/video.ts` `addPageListeners`,
  `src/injected/document.ts` `init`). ImprovedTube also uses `yt-page-data-updated`.
- The mobile site has no such events on `document`; maze-utils uses `state-navigateend` on `window` there
  (`src/injected/document.ts`, `src/thumbnailManagement.ts`).
- maze-utils additionally uses the browser's Navigation API (`navigation` `navigate` event) when present, and re-checks the
  video id at several later moments instead of trusting one signal (`src/video.ts` `setupVideoModule`, `checkIfNewVideoID`).
- Return YouTube Dislike guards against answers that arrive for the previous video (its tests hold the first video's answer,
  navigate, then release it): a late answer must never paint the new page (`Extensions/e2e/README.md`).
- **Taken**: decision 15's navigation list (events, Navigation API, poll fallback), tear-down on start, and the rule already
  in the plan that a late answer is dropped by a request generation. Checkpoint 5 tests the event path and the poll path
  separately; checkpoints 6, 7 and 8 each hold the first video's answer, navigate and release it.

### Finding the player and the video element

- There can be several `<video>` elements: the main player, a hover preview (`#inline-preview-player`), the miniplayer.
  maze-utils picks the visible one, prefers the one outside the miniplayer, treats a video as "the" video only when it has a
  duration, and re-runs the lookup when the element is replaced, by observing the children of the player's video container
  (`src/video.ts` `refreshVideoAttachments`, `setupVideoMutationListener`; `src/dom.ts` `isVisible`).
- The main player container is `#movie_player`; the video sits in `.html5-video-container` (same file).
- On the mobile site the element can exist with no duration yet; the lookup is repeated (`src/video.ts` `getVideo`).
- The video id comes from the URL for watch, shorts and live paths, 11 characters (`parseYouTubeVideoIDFromURL`).
- **Taken**: decision 15's "main video element" rule and the re-binding on replacement; captions and cuts bind to the main
  video only; checkpoint 5's fixtures contain a preview video and replace the main one.

### Ads

- A class on the player (`ad-showing`) marks a playing ad; SponsorBlock reads it on `play` (`src/content.ts` `updateAdFlag`)
  and refuses to schedule skips while it is set (`startSponsorSchedule`); ImprovedTube checks the same class.
- The player's own `onAdStart` and `onAdFinish` events and the offset of ads stitched into the stream are only reachable from
  a script in the page's world; maze-utils subtracts that offset from every time it reads or sets
  (`src/injected/document.ts`, `src/video.ts` `getCurrentTime`, `setCurrentTime`).
- **Taken**: the class check, read at the moments listed in decision 15. **Not taken**: the page-world script (decision 27);
  the cost is stated in decision 15 and in Part 1's risks.

### Skipping segments (the model for director's cuts)

- SponsorBlock does not poll. It computes the time until the next segment from the current time and the playback rate and
  arms one timer; every `play`, `playing`, `seeking` and `ratechange` re-arms it, `pause` and `waiting` (buffering) cancel
  it (`src/content.ts` `startSponsorSchedule`, `setupVideoListeners`).
- The browser's reported `currentTime` lags real playback, more so in Firefox; SponsorBlock keeps a "virtual time" from a
  timestamp of the last known time and the rate, and uses larger safety margins on Firefox (`getVirtualTime`,
  `updateVirtualTime`, the `isFirefoxOrSafari` branches of `startSponsorSchedule`).
- End of video: a skip that lands at or within half a second of the end needs its own handling, or the video loops, hangs or
  the playlist misbehaves (`skipToTime`, `endTimeSkipBuffer`).
- A skip is not attempted while the ad flag is set or while the video id is changing (`startSponsorSchedule`).
- **Taken**: decision 13's armed timer, re-arm and cancel events, the half-second end rule, and timing tests at 1x and 2x in
  checkpoint 8. Kept from the TV instead: the user's seek into a skipped part plays (SponsorBlock re-skips), the 2 s entry
  window as the safety net, and the "Skipped … / Back" toast. **Not taken**: virtual time; the 300 ms tolerance of
  checkpoint 8 is the measure of whether it is needed.

### Cards and thumbnails

- The element names of cards on both sites (the desktop `ytd-…-renderer` family, the newer `yt-lockup-view-model`, the
  mobile `ytm-…-renderer` family, the Shorts lockups) are kept in one list per site (maze-utils `src/thumbnail-selectors.ts`;
  DeArrow `src/videoBranding/videoBranding.ts` for the link inside a card).
- YouTube reuses a card element for another video: maze-utils watches each card's link for an `href` change and treats the
  card as new (`src/thumbnailManagement.ts` `newThumbnails`).
- Scans are throttled (one per 50 ms), handled cards are remembered and forgotten once they leave the document; on the
  mobile site scans are triggered by touch, scroll end and navigation and repeated on a decaying schedule up to 10 s, because
  cards appear late (same file, `mobileNewThumbnailHandler`).
- The page-world script can learn about new cards earlier (by wrapping the custom-element definitions and the site's own
  data requests); the fallback when that fails is a plain `MutationObserver` (`src/injected/document.ts`).
- YouTube removes nodes it does not know from some containers a while after navigation (a comment in ImprovedTube's
  `blocklist.js`).
- A video id can also be read from the thumbnail image's address when the link has none (`src/video.ts` `extractVideoID`).
- The lists in this repository are not carried over from those files: the names are facts, but `site.js` groups and orders
  them its own way and grows them from the fixtures and the owner's smoke runs (decision 15).
- **Taken**: decision 15's card rules (two lists, `href` watching, throttle, mobile schedule, idempotent marks keyed by video
  id, the anchor fallback) and checkpoint 11's fixtures for each. **Not taken**: wrapping the site's functions.

### Captions and text tracks

- None of the projects adds its own text track. ImprovedTube switches YouTube's own captions through the player's API
  (`getOption('captions', 'tracklist')` in `www.youtube.com/player.js`), which needs the page's world and only handles
  YouTube's tracks.
- **Consequence**: decision 12 (a native text track on the video element) is not backed by an existing extension. It stays
  because it needs no page structure; its contingency (an overlay) and its early real-world check (the MVP) are in the plan.

### Mobile site and Android

- The mobile site is recognised by its host name (`pageInfo.ts` `onMobile`; Return YouTube Dislike `state.js` `isMobile`),
  has different element names, and builds and removes its player controls as they are shown and hidden, so anything attached
  to them must be re-attached (SponsorBlock `handleMobileControlsMutations`).
- SponsorBlock declares Firefox for Android from version 113 in its manifest (`manifest/firefox-manifest-extra.json`).
- **Taken**: the extension's own UI lives in its own host element, never inside YouTube's controls, so the re-attach problem
  does not arise; the `m` fixtures of checkpoints 5 and 11.

### Manifests and browsers

- All of SponsorBlock, DeArrow and Return YouTube Dislike keep one codebase with a base manifest and per-browser additions
  merged at build time (`manifest/*.json` and `webpack/webpack.manifest.js`; `Extensions/combined/manifest-*.json`).
- All three ship **Manifest V2 on Firefox** (background scripts) and **Manifest V3 on Chromium** (service worker).
- Content scripts run at `document_start`; the page-world script is a second content script with `world: "MAIN"` on Chromium.
- After an extension update the old content script lives on without an extension context; maze-utils checks
  `chrome.runtime?.id` before acting and runs cleanup listeners (`src/cleanup.ts`).
- **Taken**: decision 25 (base plus per-browser manifest), `document_start`, the dead-context check. **Different on
  purpose**: V3 on Firefox too (decision 2), with the V2 variant as the stated fallback.

### Tests

- SponsorBlock: unit tests, and one Selenium test against live YouTube that is switched off (`test/selenium.test.ts`, `xtest`).
- Return YouTube Dislike: a hermetic browser suite. The real unpacked build runs in a persistent Chromium profile; requests
  to YouTube's origin are answered from fixture pages; its own API is a loopback fake; a host-resolver rule denies every
  non-loopback name from the first moment, because the background starts before any route can be installed; mobile is
  covered with an Android user agent and touch input; stale-answer races are tested by holding responses
  (`Extensions/e2e/README.md`, `playwright.extension.config.js`). It also keeps opt-in live-YouTube suites.
- **Taken**: the resolver rule and the loopback fake for the Chromium track (section 6), held responses for race tests (the
  mock's `/__mock/hold`). **Different on purpose**: no live-YouTube suite at all (repository rule).

## 16. Chromium track

- **Targets**: Chrome, Edge and Brave on desktop, Chrome 121 or newer. Not phones (decision 25).
- **What differs from Firefox**, all of it inside `manifest.chromium.json`, `shared/api.js` and the test harness:

  | Topic | Firefox | Chromium |
  |---|---|---|
  | Background | event page (`background.scripts`) | service worker (`background.service_worker`): no DOM, stopped when idle, state only in storage; the background code is written for this from checkpoint 2 on |
  | API object | `browser`, promises | `chrome`, promises in V3; one module hides the difference, messages answer through `sendResponse` |
  | Required host permissions | asked at install, revocable | granted at install, revocable in the extension's site-access settings |
  | Optional host permissions | `permissions.request` in a click, prompt | the same call and rule, Chromium's dialog |
  | `http` to a private server | CSP override removes the upgrade | no upgrade in the default policy; Chrome's local-network rules may apply (section 13, checkpoint 19) |
  | Data consent keys, add-on id, minimum versions | `browser_specific_settings` | not present; `minimum_chrome_version` |
  | Toolbar badge, popup, options page, storage, IndexedDB, text tracks | same | same |
  | Distribution | signed unlisted file with `update_url`; store later | "Load unpacked" zip; Chrome Web Store and Edge Add-ons later (D8) |

- **Accounts and costs** (only when the owner decides D8): a Chrome Web Store developer account with a one-time
  registration fee and a review of each version; an Edge Add-ons account. Neither is needed for the zip.
- **Checkpoints**: 19 (build and tests) and 20 (packaging and docs), after the MVP, not in its way.

## 17. MVP and estimate

**MVP** = checkpoints 0 to 9b, desktop Firefox: skeleton and CI, mock controls, background core, test harness, setup and
pairing, the player part of the site layer with the diagnostics, the summary of the playing video, HQ captions, cut skipping,
the release machinery, the MVP review, the signed unlisted release and the owner's use of it. Two owner smoke runs on real
YouTube (after 5 and 7) come before the release. It leaves out, on purpose: cards (marks, hiding, glance, chips), the AI
answer, the prompts settings, the cut picker (a cut is requested from the TV or the web UI and offered by the extension when
ready), the Processed page, Android, Chromium. The owner's signing setup (D4) is needed at checkpoint 9; until then the build
is loaded by hand.

Estimate in local-agent hours, implementation plus its clean-context review and one repair round. These are planning
figures, not measurements; a checkpoint that needs a second repair round adds about a third.

| Checkpoints | Hours | Note |
|---|---|---|
| 0, 1, 2 | 4 + 4 + 6 | Fast tier, may overlap (1 touches only the mock) |
| 3, 4 | 8 + 9 | Heavy; the harness is the main unknown |
| 5, 6 | 9 + 10 | Heavy; 5 includes the diagnostics; smoke run 1 costs the owner minutes |
| 7, 8 | 10 + 10 | Heavy; smoke run 2 after 7 |
| 9 | 5 | Fast |
| MVP review | 4 | Heavy whole-result review, then the plan reviewer |
| 9b | 6, plus what the findings need | Heavy; open-ended by nature, the figure assumes a handful of page-shape fixes |
| **MVP total** | **about 85** | one heavy agent at a time: 8 to 11 working days, plus the owner's days of use in 9b |
| 10 | 6 | Android gate |
| 11 to 17 | 8 + 5 + 6 + 5 + 4 + 6 + 5 | parity on desktop |
| 18 | 8 | Android pass and audit |
| 19, 20 | 10 + 5 | Chromium |
| 21 | owner time, plus fixes as found | |
| **After the MVP** | **about 68** | |
| C1 to C4 | not estimated | re-planned first (section 18) |

## 18. Mid-term: companion of the web UI

The backend already serves a phone-first web UI at `/` (`docs/server.md`, "Web UI"; pages for home, cuts, devices, prompts,
transcripts, jobs, filtering, models, account). Mid-term the extension is its companion in the browser: the web UI is where
things are managed, YouTube with the extension is where they are watched. Nothing below is in the MVP or in the parity
checkpoints.

**What companion means**

- **One sign-in.** Today the extension pairs with a 6-digit code typed by hand. As a companion, a signed-in web UI page
  ("Devices") offers "Pair the browser extension": it creates a code for the signed-in user with the existing
  `POST /v1/me/pair` and hands it over; the extension redeems it with the existing `POST /v1/pair` and gets its own device
  token. The extension never uses the web UI's session cookie (decision 8 stays), so revoking the device in the web UI keeps
  working. Hand-over mechanism for checkpoint C1: the web UI navigates to a page of its own whose address carries the
  single-use code in the fragment; the extension, which already holds the host permission for the backend, notices that
  address in its own tab listener, redeems the code and replaces the page with "Paired". No new permission (the backend's host permission is what lets the
  extension see that tab's address) and no new backend endpoint.
- **Deep links both ways.** From a YouTube page: "Open in u·tubot" in the panel opens the video's page in the web UI (its
  jobs, transcript, cuts). From the web UI: "Play on YouTube" opens the watch page with a fragment the extension reads
  (`#utubot=captions` and, for a cut, the request id), which is the cross-site form of the one-shot open requests the
  extension already uses for its own Processed page. The fragment carries no token and no address.
- **Shared settings and prompt sets.** Prompt sets are already per user on the server, so they are shared from day one. The
  extension's switches (assess, mark only, summary panel, automatic captions, automatic cuts) are local today, like the TV's;
  as a companion they follow the per-user settings document (`GET` and `PUT /v1/me/settings`), so a change in the web UI
  reaches the extension.
- **One Processed list.** The extension's Processed page and the web UI show the same `GET /v1/processed` items and link to
  each other.

**What the first version must not block** (each is already a decision above; decision 28 names them together)

- The client and auth layer take a base address and any bearer token; nothing assumes the token came from the typed pairing
  code. A token handed over by the web UI flow is stored and used the same way.
- No extension-only state on the server: what the extension keeps (switches, caches, the caption store) is local, and what
  must be shared goes through endpoints the web UI and the TV also use.
- No extension-only endpoint. Every call in section 1's list is used by the TV or the web UI; the companion work adds to the
  shared contract, never a private one.
- Settings are read through one module (`settings.read` in decision 6), so moving their source from local storage to the
  settings document changes that module only.
- Open requests (captions, a carried cut) already have one entry point in the content script; a fragment becomes a second
  source for the same entry point.
- Video pages are addressed by video id everywhere, so a link can be built in either direction without a lookup.

**Contract and backend work it implies** (later checkpoints, each re-planned against `main` and reviewed before it starts)

| Checkpoint | Backend, web UI and contract work | Extension work |
|---|---|---|
| C1 pairing hand-off | web UI: the "Pair the browser extension" action and its hand-over page; contract: the hand-over address documented under "Web UI endpoints"; no new endpoint | redeem the code from the hand-over address; keep the typed code as the fallback |
| C2 deep links | web UI: a page per video id (it has none today; jobs, transcript, cuts and captions of one video) and "Play on YouTube" links; contract: the fragment format under "Clients" | "Open in u·tubot"; read the fragment into the existing open requests |
| C3 shared settings | backend: an `extension` section in the settings document (or the reuse of the `tv` section's `summary_panel` and `auto_captions` plus new fields), additive, with defaults, docs and tests as `ai-backend/AGENTS.md` requires; contract: the settings document | read settings from the document with the local values as the offline fallback; write through `PUT /v1/me/settings` |
| C4 one Processed list | web UI: a Processed page if it has none by then, with links to the video page | link the extension's page to it |

C3 is the only one that changes the backend's stored data, and it is additive. The standing rule applies to it in the other
direction too: a setting added for the extension is specified for the TV app as well, or the contract says why not.

**Owner decision**: none needed now. The choice inside C3 (a new `extension` section or reuse of the `tv` section) is made
when C3 is planned.
