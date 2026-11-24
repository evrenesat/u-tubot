# u·tubot Firefox extension: implementation plan (issue #72)

Status: draft for owner approval, revised after two plan reviews (section 14). Nothing is implemented until Part 1's
decisions are answered.
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
| D1 | How people get the extension | **A signed file kept in this repository (its own branch, not the Releases page, not the add-on store); a new version only when we raise the version number; store listing later** | Available the day it is built, no store review to wait for, low-profile while we learn how often YouTube's page changes break it. It stays off the Releases page on purpose: the TV app and the server read that page to find APK updates, and extension entries would crowd the APKs out. Cost: on the phone the install is a few extra taps through a hidden Firefox menu, and automatic updates on the phone are not confirmed yet (see Risks). Listing in the store later fixes both and is a separate, public step you confirm then. |
| D2 | Manifest version | **Manifest V3** (no service worker, Firefox's event page) | The issue asks for V3 where Firefox supports it. Firefox supports it on both platforms. Mozilla's Android guide still says V2 is the safer choice, so an early checkpoint proves V3 on an Android emulator before the features are built; the code avoids V3-only features so a fallback to V2 would be a small manifest change. |
| D3 | Oldest Firefox supported | **Firefox 140 on the computer, 142 on Android** | These are the first versions with Firefox's built-in "this extension sends data" consent screen, which new extensions must use. Older versions would need our own consent screen. |
| D4 | A Mozilla add-on developer account and its signing keys | **You create the account, add two repository secrets and switch releases on with one repository variable** | Signing is required even for a file we host ourselves. Only you can create the account; the keys live only in repository secrets, never in the tree. Until you switch it on, nothing tries to release. |
| D5 | The extension's permanent ID | **`extension@utubot.dev`** | It can never change after the first signed version (an update with another ID installs as a second extension). It matches the app's `dev.utubot.tv`. |
| D6 | Plain-http servers | **Allowed for private addresses only** (home network, VPN), as in the TV app | A home server without a certificate keeps working. A public address must be https. |
| D7 | The standing rule | **In force now, with a transition** (this pull request adds it to `AGENTS.md`, the pull request checklist and the contract) | Every AI feature is planned, built and tested for the TV app and the extension, or the contract says why one side cannot have it. Until the extension is usable (checkpoint 15), a new AI feature only has to add its row to this plan's matrix. |

## Risks

- **YouTube changes its page.** The extension reads YouTube's page structure, which changes without notice. Captions and cuts are
  built on the standard video element, so they survive most changes; marks, hiding and the card buttons are the fragile part. All
  page knowledge is in one file, a failure degrades to "nothing shown" (never a broken page), and the owner's real-device pass is
  the check after each YouTube change.
- **No automated test may open YouTube** (repository rule). Tests run against hand-written stand-in pages, so a real YouTube
  difference is only found in your own use. This is the same position as the TV app.
- **YouTube's own scripts can see what the extension puts in the page**: mark labels, which cards are hidden, and the caption
  text. Your server address, token and user name are never put in the page.
- **Ads** play in the same video element. The extension pauses captions and cut skipping while an ad plays; that detection is
  page knowledge and can break.
- **Phone install and updates with a self-hosted file** are clumsy (hidden menu) and the automatic update path on Android is
  unconfirmed. Mitigation: the store listing (D1, later).
- **Mozilla's V3 support on Android** has had gaps, and on the phone Firefox does not show that an extension is waiting for
  permission to run on a site. Mitigation: the Android proof (checkpoint 5), and an "Allow on YouTube" button in the extension.
- **Store review** (if listed later) may ask how to test without a server; we point reviewers to the mock backend.

## How you try it

1. After checkpoint 4: load the build in desktop Firefox (`about:debugging`), import your setup, pair, see "Paired as …".
2. After each later checkpoint: the same build gains one feature group; the pull request says what to click.
3. After checkpoint 16: download the signed file (the link is in `docs/install.md`) on the computer and the phone and use
   YouTube normally. On the computer: Add-ons, the cog, "Install Add-on From File". On the phone: Settings, About Firefox, tap
   the logo five times, then Settings, "Install extension from file".

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
| The TV does not call `ask`, `feedback`, `jobs`, `speech`, `cut-presets`, `me/settings` | same file (no such call) |
| Settings list and order | `UtubotSettingsPresenter.buildCategories`; keys in `UtubotSettings` (`assess`, `mark_only`, `answer_in_menu`, `summary_panel`, `auto_captions`, `auto_cuts`, `wait_ms`, `panel_delay_ms`, `browse_refresh_minutes`) |
| Video menu items: AI answer, u·tubot summary, Summary panel on/off, Prepare HQ captions, Director's cut… | `UtubotMenu.append` |
| Assessed sections: Home `home`; Subscriptions and channel groups `subscriptions`; Search `search`; a channel page `channel`; Suggestions `other`; History, playlists, Watch later and channel lists are not assessed | `UtubotPolicy.sectionName` |
| `VideoMeta` fields the TV fills: `video_id`, `title`, `channel`, `channel_id`, `duration_s`, `is_short`, `is_live`, `description`, `views`, `published` | `UtubotMeta` |
| Cut requests also carry `is_live` in the query | `UtubotClient.cutUrl` |
| Timing and size constants: assess wait 1200 ms (cap 3000) + 500 ms slack, 50 videos per call; panel delay 1/1.8/3/5 s; summary and insight `wait_ms` 20000, at most 6 long polls per request while `pending` (`MAX_POLLS`); transcript polls 4 s (view) and 20 s (panel); retry 1 s to 10 min; captions poll 10 s, 2 h, 5 errors; cut follow `wait_ms` 10000, 30 min, 5 errors; cut length tolerance 2 s; skip entry window 2 s; caption file cap 4 MiB; caches: verdicts 2000, ready summaries 100, captions answers 30 | `UtubotSettings`, `UtubotManager`, `UtubotPanelModel`, `UtubotCaptionsFollower`, `UtubotCutFollower`, `UtubotCutSkipper`, `UtubotCaptionStore`, `VerdictCache` |
| The cut's `transcript_hash` is parsed but not compared by the TV; the length check is the guard (the contract sentence that said otherwise is corrected in this pull request) | `UtubotParser`, `UtubotModels`, `UtubotCutController` |
| Private-host rule for http (loopback, RFC1918, link-local, CGNAT, `.local`, `.lan`, `.internal`, `.home.arpa`, `.ts.net`, single-label) | `UtubotSetup.isPrivateHost`, `resolveUrl` |
| The mock backend is one stdlib Python file. It pairs as user `emu` with token `utb_emulator`, serves a setup whose `backend_url` is its own base, answers every `assess` with `action: "none"`, has summary, insight, transcript, captions and cuts with `/__mock/*` switches, and has no prompts import, refresh or default, no `processed`, no request log, no CORS headers | `scripts/emulator_mock_backend.py` |
| CI treats every path not in `NON_APP` as an app change, which also triggers an automatic APK release; a change to `utubot-ci.yml` itself runs every job | `.github/workflows/utubot-ci.yml` (`NON_APP`, `PIPELINE`, `release`) |
| The APK readers list GitHub Releases by count before filtering by tag: the TV's release notes read the newest 10, the backend's app sync and status the newest 20 (`sync_releases_per_page`). Tags alone are not listed by either | `common/src/stutubot/res/values/release_notes.xml`, `ai-backend/src/utubot/appsync.py`, `status.py`, `config.py` |
| There was no pull request template (this pull request adds one) | `.github/` |
| Tests, CI, emulators and agents never contact YouTube; only the deployed backend does | `AGENTS.md`, `ai-backend/AGENTS.md`, `docs/development.md` ("Offline mode") |

Firefox (read 2026-11-24):

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

Not verifiable from here: section 13, each with the checkpoint that settles it.

## 2. Decisions (all made)

1. **Directory**: `extension/` at the repository root, with its own `AGENTS.md`, `README.md` and `DEVLOG.md`.
2. **Manifest V3**, `background: {"scripts": ["background.js"]}` (event page, no `service_worker` key, no `persistent`).
   Nothing in the code depends on a V3-only API: toolbar access goes through one wrapper (`action`), permissions through
   `optional_host_permissions`. If checkpoint 5's Android check fails on a V3 gap, the fallback is a V2 manifest variant from the
   same build script (`browser_action`, `optional_permissions`), and the plan continues unchanged.
3. **Minimum versions**: `gecko.strict_min_version` `140.0`, `gecko_android.strict_min_version` `142.0`.
4. **Add-on id** `extension@utubot.dev`. **Name** "u·tubot". Icons rendered from `assets/brand/` by `assets/brand/render.py`.
5. **Language and tooling**: plain JavaScript ES modules, no framework, no TypeScript. One bundler, `esbuild`, unminified, to
   produce `background.js` and `content.js` (content scripts cannot be modules). Dev dependencies are `esbuild`, `web-ext` and
   `eslint` only, pinned in `package-lock.json`. Node 22 LTS. No runtime dependency.
6. **Network only in the background.** Content scripts and pages never hold the token and never call the backend; they send
   named messages and the background performs the fixed request. There is no generic "fetch this URL" message. The router has
   two message sets:
   - from **extension pages only** (sender URL under this extension's own `moz-extension://` base): `setup.fetch`,
     `setup.apply`, `pair`, `backend.set`, `token.set`, `health`, `me`, `prompts.list`, `prompts.import`, `prompts.refresh`,
     `prompts.default`, `settings.*`, `processed`, `captions.open`;
   - from **content scripts on the two YouTube origins** (and extension pages): `assess`, `summary`, `insight`, `transcribe`,
     `transcript`, `prompts.list`, `captions.status`, `captions.prepare`, `captions.file`, `cuts.list`, `cuts.request`,
     `cuts.follow`, `settings.read`.
   Anything else, another sender id, or a video id that does not match `^[A-Za-z0-9_-]{11}$` is rejected. UI handlers in the
   page ignore events with `isTrusted` false.
7. **Storage**: `storage.local` holds the backend URL, token, user name, switches, panel delay, the session prompt and the
   setup's pending prompt-set URLs. Never `storage.sync`. `storage.session` holds the verdict cache (2000 entries), ready
   summaries (100), captions answers (30) and the one-shot open requests. IndexedDB (background) holds the caption files:
   WebVTT only, at most 4 MiB each, keyed `<video id>/<lang>`, never replaced, not cleared by a backend or token change (as
   `UtubotCaptionStore`). A change of URL or token clears the `storage.session` caches (as `UtubotManager`).
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
    `UtubotSetup.isPrivateHost`. A network error on an `http` backend is shown with the hint "If Firefox's HTTPS-Only mode is
    on, add an exception for this server or use https".
11. **Data consent**: `data_collection_permissions.required` = `["browsingActivity", "websiteContent", "authenticationInfo"]`
    (video ids and card text go to the user's own server; the token authenticates there), no optional entries.
12. **Captions in the page**: the standard text-track API on YouTube's `<video>` element (`video.addTextTrack` once per language
    label, cues as `VTTCue`, cues swapped on navigation because a track cannot be removed). No overlay element, no hook into
    YouTube's own caption menu. Reason: it needs no page structure, and it works in fullscreen and picture-in-picture.
    Contingency with a fixed trigger: if the owner's device pass shows YouTube suppressing native cues, the renderer behind
    `captions.js`'s `show(cues)` / `clear()` is replaced by an overlay inside the fullscreen-capable player container; nothing
    else changes.
13. **Cuts in the page**: a port of `UtubotCutSkipper` driven by the video element's `timeupdate` plus a 250 ms timer while a cut
    is on. The jump is `video.currentTime = end`; the skipper sets an `ownSeek` flag before the assignment and clears it on the
    next `seeked`, so its own jump is not taken for a user seek. Any other `seeking` event is the user's and wins: the part
    plays. The cut is applied only while `|cut.duration_ms - video.duration * 1000| <= 2000` and no ad is playing. The
    sponsor-segment merge of the TV is not ported (the browser has no built-in sponsor skip).
14. **UI**: one host element with a closed shadow root, attached to the document (moved into `document.fullscreenElement` while
    one exists). It contains the u·tubot button, the panel (Summary, Answer, Captions, Cut), the passive glance card, toasts. DOM
    is built with `textContent` only. What the extension puts into YouTube's own DOM is limited to: the mark label and the chip
    on a card, the `display` of a hidden card, one `data-utubot` marker attribute, and the text track. The backend address, the
    token and the user name never appear in a page-visible node, attribute or `data-*` value. A test greps the content-script
    sources for `innerHTML`, `outerHTML`, `insertAdjacentHTML` and for any use of the settings fields outside the shadow root
    code. On the phone the panel is a bottom sheet.
15. **Page knowledge in one file**, `content/site.js`: site kind (`www` or `m`), video id from the URL, navigation detection
    (URL change polled every 500 ms plus `popstate`; no YouTube event names are required), card discovery (anchors whose `href`
    is a watch or shorts link), the card container (closest of a fixed list of renderer tag names), ad detection. A card whose
    container is not recognised is marked but never hidden.
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
    (search results only, the snippet). On the watch page the playing video's own facts are `title` (document title without the
    site suffix), `channel` (the owner link's text) and `duration_s` (the video element), `is_live` when the duration is not
    finite.
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
    fix merges release nothing; a release is made by raising the number on purpose. The store signs a version number once, which
    is the same rule. Releases are also off until the repository variable `UTUBOT_EXTENSION_RELEASES` is `on` (section 9).
22. **Pairing device name**: "Firefox (desktop)" or "Firefox (Android)"; it is what the backend's job log shows as the client.
23. **Processed tiles open in the same tab** (the browser's Back returns to the list).
24. **Not built**: `ask`, `feedback`, `jobs`, voice, saved presets, admin pages (the TV app has none of them); keyboard shortcuts
    (`commands` does not exist on Android); embedded players; YouTube Music.

## 3. Feature-parity matrix

"Panel" is the extension's own panel on a watch page; "chip" is the small u·tubot button the extension adds to a card; "popup"
is the toolbar button's popup (on Android: the extension's entry in the extensions menu).

| # | TV feature (code) | Contract | Desktop Firefox | Firefox for Android |
|---|---|---|---|---|
| 1 | Import setup: typed host or URL, `/setup.json`, stores backend, defaults, then pairing (`UtubotSetup`, `UtubotSetupFlow`) | `GET /setup.json` | Options page, first item; opens on install; permission flow of decision 9. `update_url` is ignored (APK only) | Same; the options page opens in a tab |
| 2 | Pair with code (`UtubotPairing`) | `POST /v1/pair`, `GET /v1/me` | Options page: 6 digits, then "Paired as <user>"; pending prompt sets imported after it | Same |
| 3 | First-launch offers (setup, then pairing; "Don't ask again") | none | Options page opens once on install; the popup shows "Import setup" until configured, and "Allow on YouTube" when that permission is missing | Same |
| 4 | Test connection, Advanced URL and token (`UtubotConnectionTest`, `setUrlManually`) | `GET /v1/health`, `GET /v1/me` | Options page; saving the URL requests the new origin and releases the old one | Same |
| 5 | Assess switch; one call per row emission, hide or mark, unfiltered on error or timeout (`UtubotManager.resolve`, `VerdictCache`) | `POST /v1/assess` | Options switch. Cards on the pages of decision 16 are batched (at most 50, one call per 300 ms batch, `wait_ms` 1200, given up after `wait_ms` + 500 ms); `hide` hides the card container, `mark` adds a coloured label; pending verdicts are asked again when the cards are next scanned | Same on `m.youtube.com` |
| 6 | Mark only, never hide | none (local switch; setup default) | Options switch | Same |
| 7 | AI answer in the video menu, answer in the label (`UtubotMenu`, `UtubotAnswerModel`) | `GET /v1/videos/{id}/insight` | Chip menu on a card and "Answer" tab of the panel; the chip shows `answer_short` when known and the switch is on | Same; chip tap opens the sheet |
| 8 | Summary panel mode: passive preview after the focus delay (`PanelCoordinator`, `FocusDebouncer`, `UtubotPanelView`) | `GET /v1/videos/{id}/summary?prompt=panel`, fallback first prompt of `GET /v1/prompts` on 400/404 | Hovering a card for the panel delay shows the passive glance card (bottom right, never takes focus); moving away drops the request; Escape hides it | No hover on touch: with the mode on, each card's chip opens the glance sheet on tap; it requests `prompt=panel` like the TV panel |
| 9 | Summary panel on/off toggle (quick toggle, menu item, setting) and the panel delay (1, 1.8, 3, 5 s) | none (local; setup default) | Toggle in the popup, in the chip menu and in the options page; delay choice in the options page | Toggle in the popup, chip menu and options page; the delay has no effect (tap) and is hidden |
| 10 | Summary view: prompt list, long summary, session prompt (`UtubotSummaryOverlay`) | `GET /v1/prompts`, `GET /v1/videos/{id}/summary?prompt=<key>` | "Summary" tab of the panel and "Summary options" on the glance card: prompt list left, text right, source line, Retry | Bottom sheet with the prompt list as a selector above the text |
| 11 | Transcript states with the server's words, countdown, Transcribe in background, follow-up polling, at most 6 long polls per request (`UtubotPanelModel`, `UtubotStateText`, `UtubotCountdown`, `UtubotManager.MAX_POLLS`) | `transcript_status` fields, `POST /v1/videos/{id}/transcribe`, `GET /v1/videos/{id}/transcript` | Same states, same intervals (4 s view, 20 s glance) and the same poll cap, in the panel, the glance card and the answer | Same |
| 12 | Metadata on every insight, summary, transcribe call; `is_live` too on cut calls (`UtubotMeta`, `UtubotClient.addMeta`, `cutUrl`) | query `title`, `channel`, `duration_s` (`is_live` for cuts) | From the card or the watch page (decision 16) | Same |
| 13 | Prompts: list, choose default, Import from URL, Refresh all (`UtubotSettingsPresenter.showPrompts`) | `GET /v1/prompts`, `PUT /v1/prompts/default`, `POST /v1/prompts/import`, `POST /v1/prompts/refresh` | Options page, Prompts section | Same |
| 14 | Prepare HQ captions (`UtubotMenu.prepareCaptions`) | `POST /v1/videos/{id}/captions` | Chip menu and "Captions" tab | Same |
| 15 | HQ captions while playing: check at start, poll while queued or running, add and select when ready, "captions ready" toast (`UtubotCaptionsFollower`, `ExoPlayerController` hooks) | `GET /v1/videos/{id}/captions`, `GET .../captions/{lang}.vtt` | Follower in the content script; ready track becomes a native text track on the video element, selected by the rule of row 16, toast for a job that finished while playing. Track on/off and language are in the "Captions" tab (YouTube's own caption menu is not touched) | Same |
| 16 | Auto-select HQ captions switch; a user-requested track is selected whatever the switch says | none (local switch; setup default) | Options switch; same rule | Same |
| 17 | Permanent caption store, works without the backend (`UtubotCaptionStore`) | none | IndexedDB in the background; a stored video makes no request | Same |
| 18 | Director's cut picker: presets with state, apply or take off, ask for a build, kept parts (`UtubotMenu.showCuts`) | `GET /v1/videos/{id}/cuts`, `POST /v1/videos/{id}/cuts {"preset"}` | "Cut" tab and chip menu; picking a ready cut from a card opens the video with the cut carried (one-shot request, as `applyOnOpen`) | Same |
| 19 | "Describe on phone…" with QR (`UtubotCutQrView`) | `POST .../cuts {"await_prompt":true}`, `GET /cuts/{id}` | A keyboard exists, so: "Describe here" (text box, `POST .../cuts {"prompt"}`), and "Open cut sheet" which creates the waiting request and opens `<backend>/cuts/<id>` in a new tab (voice and saved presets live there). No QR code | Same |
| 20 | Cut while playing: ready cut announced with one-press Apply, or applied automatically; waiting or building request followed; skips with "Skipped 1:20" and a 5 s Back (`UtubotCutController`, `UtubotCutFollower`, `UtubotCutSkipper`) | `GET /v1/videos/{id}/cuts`, `GET /v1/cuts/{id}?wait_ms=10000` | Same flow; the toast has "Back" (returns to the skipped part); length rule ±2 s; paused during ads | Same |
| 21 | Apply ready cuts automatically | none (local switch) | Options switch | Same |
| 22 | Dimmed skipped parts on the seek bar (`UtubotCutSeekBar`) | none | A slim timeline in the "Cut" tab shows kept and skipped parts; kept parts are a clickable list (seek). YouTube's seek bar is not modified | Same |
| 23 | Sponsor-segment merge of a cut jump | none | Not applicable: the browser has no built-in sponsor skip. In the contract's "Clients" section | Not applicable |
| 24 | Processed section and opening a tile with its HQ captions (`UtubotProcessedSection`, `UtubotProcessedOpen`) | `GET /v1/processed?limit=50` | Extension page "Processed" (from the popup and the panel): tiles with the processed line, empty and failed states; a tile opens the watch page in the same tab with a one-shot captions-open request | Same, opened from the popup |
| 25 | Working indicator and busy badge (`UtubotWorkingIndicator`, `UtubotBadgeController`, `UtubotBusyTracker`) | none | Three-dot indicator in the panel, glance card and answer; toolbar badge while calls are in flight (shown after 300 ms) | Indicator only (no toolbar badge) |
| 26 | Caches dropped on a backend or token change (`UtubotManager`) | none | `storage.session` caches cleared; caption store kept | Same |
| 27 | Browse cache, "Browse refresh" minutes, "Refresh section" (`UtubotBrowseCache`) | none | Not applicable: YouTube's site owns its loading. In the contract's "Clients" section | Not applicable |
| 28 | App self-update from the setup's `update_url` (`UtubotUpdates`) | `GET /app/update.json` | Not applicable: Firefox updates extensions (`update_url` of the manifest, or the store) | Not applicable |
| 29 | Own identity, About links, unofficial disclaimer | none | Name, icons, About section in the options page with this repository's links and the disclaimer | Same |

## 4. Architecture

```
extension/
  manifest.json            source manifest (release shape, no loopback match)
  version                  full version, starts at 0.1.0
  build.mjs                esbuild + manifest variants: unlisted, listed, test
  src/background/          main.js (message router), client.js, auth.js, setup.js, permissions.js,
                           cache.js (storage.session), captionstore.js (IndexedDB), busy.js
  src/shared/              models.js (parsers), statetext.js, panelmodel.js, countdown.js, cutskipper.js,
                           vtt.js, policy.js, meta.js, messages.js (message names and sets), debounce.js
  src/content/             main.js, site.js, cards.js, player.js, captions.js, cuts.js, followers.js
  src/content/ui/          host.js (shadow root), panel.js, glance.js, sheet.js, toast.js, layout.js, styles.css
  src/pages/               options.html/js, processed.html/js, popup.html/js
  src/_locales/en/         messages.json (strings carried over from utubot_strings.xml)
  tests/unit/              node --test
  tests/fixtures/site/     www/*.html, m/*.html (hand-written stand-ins)
  tests/e2e/               pytest + selenium (uv project): conftest.py, refusing_proxy.py, user.js, tools.lock
```

- **Background (event page)** is a stateless executor: one message in, one backend request, one answer. It may be unloaded when
  idle, so nothing lives only in its memory: caches are in `storage.session`, timers (followers, countdowns, hover delay) run in
  the content script of the tab that needs them, and a long poll never asks for more than 20 s (`wait_ms` cap, below Firefox's
  idle limit).
- **Content script** (`document_idle`, both YouTube origins, top frame only) starts `site.js` navigation watching, then per page:
  `cards.js` on the pages of decision 16 (a `MutationObserver` batches new anchors), `player.js` on watch pages (waits for the
  `<video>` element, emits video id changes, ad state, duration), with `captions.js`, `cuts.js` and the panel bound to it.
- **Desktop page** (`www.youtube.com`) and **mobile page** (`m.youtube.com`) share every module. They differ in `site.js` (the
  list of card container names, the field lookups) and `layout.js` (panel docked right against bottom sheet, hover against
  chip). Both sites are single-page apps that reuse one video element: every per-video object is torn down on a video id change.
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

`docs/privacy.md` gains a "Firefox extension" section (checkpoint 16):

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
- The **test variant** of the build (`build.mjs --variant test`) differs from the release manifest in exactly three ways: the
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
  in the recorded runs of checkpoint 5. No browser-chrome automation is used.
- **The guard, fully specified:**
  - `tests/e2e/refusing_proxy.py`: a stdlib Python HTTP and CONNECT proxy on a loopback port that answers every request with 502
    and records method and host. It is the only proxy; exactly `127.0.0.1`, `127.0.0.2` and `127.0.0.3` are exempt (`network.proxy.no_proxies_on`,
    `network.proxy.allow_hijacking_localhost` false). No e2e test sends a request to any other address, private ones included:
    the private-address rule is unit-tested without a request, and a real private-address request is made only in the
    Android emulator run (checkpoint 5, the emulator's host alias).
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
- The Android emulator runs (checkpoints 5 and 15) use a namespace with no route out and `adb reverse` to the mock and fixture
  servers.
- The real-YouTube check is the owner's own use of a released build. Agents never do it.

## 7. Test approach

| Layer | Tool | Covers |
|---|---|---|
| Unit | `node --test`, no browser | client URLs and query fields, `credentials: "omit"` on every request, auth scoping, setup resolution and the private-host rule, message sets, parsers, state text, panel model and countdown (fake clock), poll cap, cut skipper (the cases of `UtubotCutSkipperTest`), VTT parser, policy, section mapping, caches, manifest variants |
| Static | `eslint`, `web-ext lint` (it catches some Android-incompatible keys and APIs, not all), the greps of decision 14 and for any host other than the placeholders | both platforms |
| Mock backend | pytest in `ai-backend/tests/test_emulator_mock.py` | every `/__mock` control of section 8 |
| End to end, desktop | pytest + Selenium + geckodriver, headless Firefox, test variant, the mock backend, the fixture server, the guard of section 6 | setup and pairing with both permission flows on optional loopback origins, missing YouTube permission, marks and hiding, glance and Summary view with every transcript state, answer, captions while playing and from the store, cuts, Processed |
| End to end, mobile layout | same harness, `m` fixtures, 360 px viewport, touch events | the Android behaviours of the matrix in the mobile page shape |
| Android runtime | Android emulator, Firefox for Android installed from Mozilla's APK, `web-ext run --target=firefox-android` | checkpoint 5: install, YouTube permission state and the "Allow on YouTube" button, the real permission prompt with both answers, pairing, storage, held requests, `http` to a private address. Checkpoint 15: a mark, a summary, captions and a cut on the fixture pages. By an agent, not in CI |
| API availability | checkpoint 15's audit: every `browser.*` call in the sources checked against MDN's compatibility table for Firefox for Android 142 | what lint does not report |
| Real YouTube | the owner, a released build | page-structure drift |

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

- `node build.mjs --variant unlisted|listed|test` writes `extension/dist/<variant>/`; `web-ext build` zips it.
- Signing: `web-ext sign --channel=unlisted` with `WEB_EXT_API_KEY` and `WEB_EXT_API_SECRET` from repository secrets
  (`AMO_JWT_ISSUER`, `AMO_JWT_SECRET`). The keys are never committed, printed or written to an artifact; `extension/.gitignore`
  lists `.amo-credentials`, `web-ext-artifacts/`, `dist/`.
- **Release wiring** (one path, named):
  - `utubot-ci.yml`, job `changes`: new outputs `extension` (extension files changed) and `extension_release` (push to `main`,
    and the version in `extension/version` has no `utubot-ext-v<version>` tag).
  - `utubot-ci.yml`, new job `extension-release`: needs `changes` and `extension`; runs only in this repository, on a push, when
    `extension_release` is true, `extension` succeeded, `backend` succeeded or was skipped, and the repository variable
    `UTUBOT_EXTENSION_RELEASES` is `on`; its one step is
    `gh workflow run utubot-extension-release.yml --ref main --field sha=$GITHUB_SHA`. The variable is unset until the owner
    has added the signing secrets, so the merge of checkpoint 16 (version `0.1.0`, untagged) starts nothing; the first push
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
       whose `extension` job succeeded and whose `backend` job succeeded or was skipped). The function is copied from
       `utubot-release.yml` with the job names changed, not redesigned. A failed guard fails this run with its reason.
    3. Build, lint, unit tests, sign; write `SHA256SUMS` and `updates.json` (id, version, `update_link`, `update_hash`,
       `strict_min_version` for both platforms).
    4. Replace the single commit of `extension-updates` (the new files plus the newest four earlier `.xpi` files) and put the
       tag `utubot-ext-v<version>` on the released `main` commit. No GitHub Release is created.
    A run by hand follows the same steps. A dry run stops after step 3 and uploads the unsigned package, the checksums and
    `updates.json` as workflow artifacts only.
  - Before the first release, checkpoint 16 checks that no branch ruleset or protection blocks the workflow's push to
    `extension-updates` (`gh api repos/{owner}/{repo}/rulesets`) and records the result.
- The listed variant has no `update_url` and is uploaded by the owner (or with `web-ext sign --channel=listed`) only after D1's
  second step is confirmed.
- Install instructions (`docs/install.md`): desktop, download the `.xpi` and use "Install Add-on From File" (a raw file link
  does not start the install by itself); Android, save the file, unlock the hidden menu, "Install extension from file".

## 10. The standing rule (exact texts, all three in this pull request)

`AGENTS.md`:

> - Two clients, one feature set: every new or changed AI feature is specified, built and tested for the TV app (`stutubot`
>   flavor) and the Firefox extension (`extension/`, plan in `ai/FIREFOX_EXTENSION_PLAN.md`) in the same pull request or in two
>   linked ones. If one client cannot have it, `ai/CONTRACT.md` ("Clients") says which and why. A plan or pull request for an AI
>   feature that names only one client is incomplete. Transition: until checkpoint 15 of that plan has landed, the extension
>   side of a new AI feature is its row in the plan's parity matrix (section 3), added in the same pull request.

`.github/pull_request_template.md`:

```
- [ ] AI feature parity: this change works in the TV app and the Firefox extension, or `ai/CONTRACT.md` ("Clients") says why
      one of them does not have it. Until the extension exists: the feature's row is in `ai/FIREFOX_EXTENSION_PLAN.md`.
      (Not an AI feature: tick and write "n/a".)
- [ ] `ai/CONTRACT.md` changed together with the code that changes the wire.
- [ ] No test or check contacts YouTube; no host, token or key in the tree.
```

`ai/CONTRACT.md`, section "Clients" after "App behaviour summary": the two clients, the four exceptions with their reasons
(matrix rows 19, 23, 27, 28), and the sentence that the extension sends the bearer token from its background context only, with
no cookies and never `?token=`.

Enforcement beyond review (checkpoint 0): a workflow of its own, `.github/workflows/utubot-parity.yml`, with the single job
`parity-box` on `ubuntu-24.04`.

- Trigger: `pull_request` with the types `opened`, `edited`, `synchronize`, `reopened` only. It has no `push` trigger, so it
  never runs for `main`. Ticking the box in the description re-runs only this small job, not the test pipeline.
- It is not part of `utubot-ci.yml` and no job there depends on it, so a missing tick never hides the backend, app or
  extension results.
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
reviewed by the plan reviewer. One pull request per checkpoint, each updating `extension/DEVLOG.md`. Checkpoint 5 is a gate:
6 and later do not start until it has passed or the V2 fallback has been written into this plan.

| # | Scope | Main files | Done when (each is a test or a recorded check on this checkpoint's own pull request) | Tests | Tier |
|---|---|---|---|---|---|
| 0 | Skeleton and CI: `extension/` with manifest, build script, three variants, lint, empty background and content script, `extension/AGENTS.md`; change classification moved out of the workflow into `scripts/utubot_ci_changes.py` with the outputs `backend`, `app`, `release`, `extension`, `extension_release`, and its `parity` command with the `utubot-parity.yml` workflow (section 10); `NON_APP` gains `extension/`; `extension` job | `extension/*`, `scripts/utubot_ci_changes.py`, `ai-backend/tests/test_ci_changes.py`, `.github/workflows/utubot-ci.yml`, `.github/workflows/utubot-parity.yml` | unit test of the classifier: a file list with only `extension/…` gives `extension` true, `app` false, `release` false; the existing cases (backend only, app file, pipeline file, docs only) give the answers the inline script gave; `parity` fails a contract change without the ticked box and passes it with the box, with an `extension/` change, or with a body that contains shell metacharacters (read from the environment). `web-ext lint` has no errors; the release variants contain no loopback match | `test_ci_changes.py`; unit: manifest variants; the pull request's own CI run | Fast |
| 1 | Mock backend controls: every row of section 8's table, `--host` included | `scripts/emulator_mock_backend.py`, `ai-backend/tests/test_emulator_mock.py`, `docs/development.md`; `BACKEND` path filter gains the script | one test per control passes against the script started on a loopback port; the defaults answer exactly as before (the existing recipes' requests are replayed in a test) | `test_emulator_mock.py` | Fast |
| 2 | Background core, no UI: client with every endpoint of section 1, `credentials: "omit"`, auth scoping, setup resolution and private-host rule, permission helpers, message router with the two sets, caches | `src/background/*`, `src/shared/{models,messages}.js` | unit: each endpoint's method, path and query (metadata, `is_live` for cuts); no request without `credentials: "omit"`; the header only for URLs under the backend; `http` to a public host refused; a content-script sender cannot call a page-only message; a bad video id is rejected | unit (ported cases of `UtubotClientTest`, `UtubotSetupTest`) | Fast |
| 3 | The e2e harness, proven with one trivial test: fixture server on `127.0.0.1`, mock on `127.0.0.2` and `127.0.0.3`, refusing proxy, `user.js`, `tools.lock` with the download and hash step, `run-offline.sh`, Selenium offline setup, CI steps | `tests/e2e/*`, `.github/workflows/utubot-ci.yml` | e2e: the test variant loads as a temporary add-on in the pinned Firefox, its content script marks the `127.0.0.1` fixture page, the background answers a `health` message from the mock on `127.0.0.2`, and the proxy recorded nothing; `run-offline.sh` gives the same result inside the namespace; a deliberately added request to a non-loopback name makes the final check fail (then removed) | unit: `user.js` groups, `tools.lock` format; the one e2e | Heavy |
| 4 | Options page: Import setup with both permission flows, pairing, test connection, Advanced URL and token, switches, the YouTube permission notice, popup stub | `src/pages/{options,popup}.*`, `tests/e2e/test_setup.py`, `tests/unit/permissions.test.js` | e2e (mock origins are optional permissions, prompts answered by the auto-grant preference, section 6): import `127.0.0.2:<port>`, pair, "Paired as emu"; `permissions.contains` is true for `http://127.0.0.2/*` only after the Import click; the request log shows the header on `/v1/me` and not on `/setup.json` or `/v1/pair`, no `Cookie` on any request (a cookie for the mock's origin is planted first), no `OPTIONS`. With `/__mock/setup?backend=http://127.0.0.3:<port>` nothing is applied and `127.0.0.3` is not granted until "Allow access to http://127.0.0.3:<port>" is clicked; then calls go to that origin and `permissions.contains` is false for `127.0.0.2`. Advanced: saving the other origin grants it and removes the old one. Calling the request outside a click (a test hook that awaits first) is rejected by Firefox and nothing is stored. The YouTube origins start ungranted in the test variant: the options page and popup show "Allow on YouTube", the click grants both and the notice goes; after `permissions.remove` it is back. `http` on loopback pairs with HTTPS-Only mode off and on (loopback is exempt). The proxy recorded nothing. Unit, with `permissions.request` stubbed to answer false: Import, "Allow access" and Advanced store nothing, keep the previous backend and show "Permission was not given"; private literals (`10.0.0.5`, `192.168.1.10`, `host.local`) are accepted for `http` and a public name is refused, without any request | unit as listed; e2e as listed | Heavy |
| 5 | **Gate: Manifest V3 on Android.** Emulator run of the test variant | `extension/README.md` (the recipe), `extension/DEVLOG.md` (the recorded run) | recorded log of: install; the YouTube permission state after install and the "Allow on YouTube" button; Import setup with the real permission prompt, once answered "Don't allow" (nothing stored, "Permission was not given") and once allowed; pairing; settings surviving a Firefox restart; a request held 20 s by `/__mock/hold` answered (the plan's long-poll cap, must pass); a request held 45 s, longer than Firefox's 30 s event-page idle timeout, with the result recorded (answered: a pending request keeps the page alive; lost: the 20 s cap stays the rule and the result is added to section 4 of this plan); `http` to the emulator's host alias `10.0.2.2` (a private address that is not loopback) with HTTPS-Only mode off (must pair) and on (result recorded; if it is blocked, the hint of decision 10 must be what the user sees). The same real-prompt and 45 s checks are run once by hand in desktop Firefox and recorded. A V3 gap found here adds the V2 variant and records the decision in this plan | Android runtime check | Heavy |
| 6 | Site layer: site kind, navigation, video id, section mapping, card discovery, containers and fields, ad state, player lifecycle; fixtures for both sites | `src/content/{site,cards,player,main}.js`, `tests/fixtures/site/**` | e2e on `www` and `m` fixtures: cards added after load are found once, with the fields of decision 16; each path of the mapping table gives its section or none; a simulated in-page navigation tears down and rebuilds; the video id, duration and ad events fire; an unknown page shape logs once and changes nothing | unit: URL, id, section, clock parsing; e2e: discovery, navigation | Heavy |
| 7 | Assess: switch, batching, verdict cache, marks, hiding, mark only, answer in label, pending re-ask, caches dropped on connection change | `src/content/cards.js`, `src/shared/policy.js`, `src/background/cache.js` | e2e with `/__mock/assess`: a `hide` verdict hides its card and a `mark` shows its label on both fixtures; with mark only the hidden card is shown with a mark; `delay=5` or `fail=500` leaves every card visible; a `pending` verdict is asked again on the next scan; one call carries at most 50 videos and the page's section; a history fixture page sends no assess; an unrecognised container is never hidden; no page-visible node holds the backend address | unit: policy, cache, batcher; e2e as listed | Fast |
| 8 | Summary core and glance: panel model, state text, countdown, poll cap, working indicator, busy badge, the glance card (hover) and glance sheet (chip), the Summary panel toggle and delay | `src/shared/{panelmodel,statetext,countdown}.js`, `src/content/ui/{host,glance,sheet}.js` | e2e with the mock's modes: `ready`; `needs_transcript` (server `message` shown); `delayed` (server `error`, countdown, no retry before `retry_after_s`); `failed` with and without `reason`; `auto_transcribe` (progress shown, summary arrives); `panel=404` falls back to the first prompt; requests carry `title`, `channel`, `duration_s`; a hover shorter than the delay sends nothing; a request stops after 6 long polls; the `m` fixture opens the sheet from the chip | unit: ported cases of `UtubotPanelModelTest`, `UtubotStateTextTest`, `PanelCoordinatorTest`; e2e as listed | Heavy |
| 9 | Summary view and AI answer: panel tabs, prompt list and session prompt, Transcribe in background with follow-up, answer with the same states | `src/content/ui/panel.js`, `src/shared/panelmodel.js` | e2e: choosing a prompt reloads the text and is kept for the session; Transcribe starts the job, progress is followed every 4 s and the summary arrives; the answer shows question, answer, key points and source, counts a delay down and follows a transcription | unit: ported cases of `UtubotAnswerModelTest`; e2e as listed | Fast |
| 10 | Prompts section of the options page: list, choose default, Import from URL, Refresh all, pending prompt sets after pairing | `src/pages/options.*` | e2e: import adds the set to the list; choosing a default sends `PUT /v1/prompts/default` and the list follows; refresh sends its request; an unknown key shows the server's error; the setup's `prompt_set_urls` are imported after pairing | e2e as listed | Fast |
| 11 | HQ captions: prepare, follower, VTT parser, native text track, auto-select rule, toast, caption store, ad pause | `src/content/{captions,followers}.js`, `src/shared/vtt.js`, `src/background/captionstore.js` | e2e on the fixture watch page with the generated video: a job that turns ready while playing adds a showing track whose active cue text matches the mock's file at a known time, with the toast; with auto-select off the track is listed and not showing; after a browser restart with the mock stopped the stored track still shows and no request is made; a file over 4 MiB or without the WEBVTT header is not stored; a video change clears the cues; the track is hidden while the ad flag is set | unit: VTT parser, follower (ported cases of `UtubotCaptionsFollowerTest`), store rules; e2e as listed | Heavy |
| 12 | Cuts in the player: skipper, follower, length and ad guards, ready offer and automatic apply, toast with Back | `src/content/cuts.js`, `src/shared/cutskipper.js`, `src/content/followers.js` | e2e: with the mock's cut, playback crossing 60 s continues at 108 s and the toast shows "Skipped 0:48"; Back returns into the skipped part and it plays; a user seek into a skipped part plays; the skipper's own jump is not taken for a user seek; a cut built for 200 s on the 240 s video is refused with the message; a request that becomes ready while playing is applied from the current position; automatic apply applies without the offer; nothing is skipped while the ad flag is set | unit: skipper (ported cases of `UtubotCutSkipperTest`, without sponsor segments), follower (ported cases of `UtubotCutFollowerTest`); e2e as listed | Heavy |
| 13 | Cut picker and its ways in: presets with state, build request, kept parts and timeline, "Describe here", "Open cut sheet", the carried cut from a card | `src/content/ui/panel.js`, `src/content/cuts.js` | e2e: the picker shows each preset state of the mock; a `none` preset posts `{"preset"}` with `title`, `channel`, `duration_s`, `is_live` and is followed to ready; picking the applied cut takes it off; "Describe here" posts `{"prompt"}`; "Open cut sheet" posts `{"await_prompt":true}` and opens `<backend>/cuts/<id>`; a ready cut picked on a card opens the watch fixture with the cut applied, once; a kept part's click seeks | unit: state text, part formatting; e2e as listed | Fast |
| 14 | Processed page and its open, full popup, About | `src/pages/{processed,popup}.*` | e2e with `/__mock/processed`: tiles in the mock's order with the processed line; empty and failed states; a tile opens the fixture watch page in the same tab and its HQ track is showing with auto-select off; the one-shot request does not carry to a second open; no image request leaves loopback | unit: tile text (ported cases of `UtubotProcessedTilesTest`); e2e as listed | Fast |
| 15 | Android pass and parity audit: sheet layout, touch targets, the full Android runtime check, the API availability audit, every matrix row tied to its evidence | `src/content/ui/{layout,sheet}.js`, `extension/README.md` | every matrix row has a passing test or a recorded Android check named next to it in `extension/README.md`; every `browser.*` call in the sources is listed with its Firefox for Android support from MDN; the recorded emulator run covers install, setup, a mark, a summary, captions and a cut; no horizontal scroll at 360 px | e2e mobile layout; Android runtime check | Heavy |
| 16 | Release: the `extension-release` job, the release workflow, `updates.json`, the `extension-updates` branch, install and privacy docs, README | `.github/workflows/utubot-extension-release.yml`, `.github/workflows/utubot-ci.yml`, `scripts/utubot_ci_changes.py`, `docs/install.md`, `docs/privacy.md`, `README.md` | unit: `extension_release` is true only for an untagged version on a push to `main`; the copied `ci_green` accepts a completed green run and the dispatching in-progress run with a green `extension` job, and refuses a red or missing one; `updates.json` is valid for a given version and hash. A dry run of the workflow (signing skipped without secrets) produces the package, checksums and `updates.json` as artifacts and creates no GitHub Release. Without the variable `UTUBOT_EXTENSION_RELEASES` the merge starts no release; a run by hand without secrets ends successfully with the notice and publishes nothing; the ruleset check is recorded. With the owner's secrets and the variable: one signed version is on the branch and installs on desktop Firefox, and after a version bump the installed copy updates itself. The tree and the logs contain no key | unit; workflow dry run; owner check of install and update on desktop | Fast |
| 17 | Owner's real-device pass and fixes; the Android install of the unlisted file and the Android update check; then, only on the owner's word, the store listing | `src/content/site.js`, fixtures | the owner used a released build on desktop and Android on real YouTube and each matrix row is ticked or has an issue; the phone picked up a second version through `update_url` or the result is recorded and the store listing proposed; every fix adds the page shape that broke to the fixtures | regression fixtures | Heavy |

## 12. CI

- This repository is public: every job runs on `ubuntu-24.04` hosted runners, never self-hosted. Actions are pinned by SHA like
  the existing ones.
- Job `extension` in `.github/workflows/utubot-ci.yml` runs when `extension/`, `ai/CONTRACT.md`,
  `scripts/emulator_mock_backend.py` or the pipeline itself changed: Node 22, `npm ci`, `eslint`, unit tests, build of the three
  variants, `web-ext lint`, then `uv sync --frozen` in `extension/tests/e2e`, `ffmpeg`, the pinned Firefox and geckodriver of
  `tools.lock`, and the e2e suite headless behind the refusing proxy.
- `NON_APP` gains `extension/`, so an extension change is not an app change and never starts an APK release. The `backend` job
  also runs when `scripts/emulator_mock_backend.py` or `scripts/utubot_ci_changes.py` changed (their tests live there).
- Job `extension-release` and the release workflow: section 9. The `parity-box` job in its own workflow: section 10.
- The Android runtime check is not in CI (it needs an emulator and a Firefox APK); its evidence is the recorded log of
  checkpoints 5 and 15.

## 13. Could not be verified from here

| Item | Why | Settled by |
|---|---|---|
| The exact element names of YouTube's desktop and mobile pages (card containers, field lookups, ad marker) | agents never load YouTube | checkpoint 17 (owner), with the "never hide an unknown container" rule until then |
| YouTube leaving native text-track cues visible on its video element | same | checkpoint 17; contingency in decision 12 |
| Manifest V3 behaving on current Firefox for Android, and whether the YouTube permission is granted at install there | no device here; Mozilla's guide still prefers V2 | checkpoint 5 |
| A pending message answer keeping the event page alive past Firefox's 30 s idle timeout | documented only in general terms | checkpoint 5 (20 s must pass, 45 s recorded, on Android and desktop) |
| `http` requests to a private address from the background once `upgrade-insecure-requests` is removed, with HTTPS-Only mode and Firefox's local-network access rules | MDN states the opt-out; not tried | loopback with and without HTTPS-Only in checkpoint 4 (expected: works, loopback is exempt); a non-loopback private address in checkpoint 5 (`10.0.2.2`), then the owner's own server in checkpoint 17 |
| Firefox applying `update_url` updates from raw file URLs (content types), and Firefox for Android applying them to a file-installed extension at all | not documented | checkpoint 16 (desktop, owner), checkpoint 17 (Android, owner); the store listing is the fallback |
| A version signed as unlisted being installable on Android with only `gecko_android` in the manifest | the signing post does not address unlisted | checkpoint 16's first signed file, installed in checkpoint 17 |
| Whether sending card data to the user's own server needs the three consent categories or fewer | Mozilla's page does not cover self-hosted servers | the signing validator at checkpoint 16; declaring them is the safe side |
| `utubot.dev` as the id's domain part | an add-on id needs no real domain, but it is permanent | owner decision D5 |

## 14. Review response

Checkpoint numbers below are the current ones.

### First review

| Finding | Change |
|---|---|
| H1 extension releases crowd APK releases out of the 10 and 20 release windows | Decision 20: the extension never creates a GitHub Release; the signed file and `updates.json` live on the `extension-updates` branch, a tag marks the commit. Decision 21: a release only on a deliberate version bump. No app or backend change. Section 1 gained the fact; D1 reworded |
| H2 second permission request after an async fetch | Decision 9: explicit "Allow access to `<origin>`" button; `permissions.request` only directly in a click handler. Mock control and e2e case in checkpoints 1 and 4 |
| H3 mock backend additions unspecified; "Paired as owner" | Section 8 table lists every control and answer; checkpoint 1 builds them all with tests; Done When texts use the mock's user `emu` |
| M1 missing YouTube permission, Android | Decision 9 ("Allow on YouTube" in popup and options, `permissions.contains` on open), matrix row 3, e2e in checkpoint 4, Android check in checkpoint 5, fact added to section 1 |
| M2 session-cookie fallback | Decision 8: `credentials: "omit"` and `cache: "no-store"` on every request; unit test (checkpoint 2), planted-cookie e2e with the request log (checkpoint 4); contract text says "no cookies" |
| M3 assess fields undecided | Decision 16: path-to-section table and the per-card fields; tested in checkpoints 6 and 7 |
| M4 Advanced URL without a permission step | Decision 9 and matrix row 4; e2e in checkpoint 4 |
| M5 missing constants | `MAX_POLLS` 6 and the captions cache of 30 in section 1, decision 7, matrix row 11, checkpoint 8 |
| M6 release wiring contradictory | Section 9 names the `changes` outputs, the `extension-release` job, the workflow's inputs and refusal rules; section 12 points to it |
| M7 checkpoints too large | The connection checkpoint became 2, 3, 4 and the gate 5; summaries became 8, 9, 10; cuts became 12, 13 |
| M8 standing rule without transition; references missing | Transition clause in the rule; the contract "Clients" section and the pull request template are in this pull request; a CI check of the parity box in checkpoint 0 (section 10) |
| M9 YouTube scripts can observe page-visible additions | Section 5 text, Part 1 risk, decision 14's list of what enters the page and its test |
| M10 offline guard underspecified | Section 6: named proxy file, committed `user.js` with the listed groups, `SE_OFFLINE`, pinned Firefox and geckodriver with hashes, namespace always locally and never in CI |
| M11 checkpoint 0 not provable on its own pull request | The classifier becomes a script with a unit test; that test is the Done When |
| Firefox claim: lint coverage on Android | Sections 1 and 7 reworded; API availability audit against MDN in checkpoint 15 |
| Firefox claim: Android signing post and unlisted | Section 1 reworded; listed in section 13, settled by checkpoints 16 and 17 |
| L1 `is_live` on cut calls | Section 1, matrix row 12, checkpoints 2 and 13 |
| L2 contract says the TV checks `transcript_hash` | The contract sentence is corrected in this pull request |
| L3 panel toggle, delay and assess switch without rows | Matrix rows 5 and 9 |
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

### Open lows

None of the lows of either review is left open. Two items stay open by nature and are tracked in section 13, not here: the real
YouTube page shapes and the Android update path.
