## 2026-11-26 (Android tablet: installs, step 1 of #201)

- The merged manifest required `android.software.leanback`, `android.hardware.usb.host` (MediaServiceCore) and, through the leanbackassistant module, leanback again, so the Play-style feature filter and `pm install` refused the package on a tablet (`INSTALL_FAILED_MISSING_FEATURE`). `smarttubetv/src/main/AndroidManifest.xml` now declares leanback, USB host and Bluetooth as `required="false"` with `tools:node="replace"`. The LAUNCHER intent filter was already on `SplashActivity` (with LEANBACK_LAUNCHER), no orientation is locked (`unspecified`). `UtubotTabletManifestTest` guards both.
- Emulator check not done: the p100 emulator (37.2.13) segfaults at start for every AVD, the TV one included, in and out of a network namespace; the tablet AVD (default android-34 image, 1920x1200 at 240 dpi) was created and removed again. Larger gaps are separate issues, linked from #201.

## 2026-11-26 (SponsorBlock off while a cut is applied, issue #145)

- `SponsorBlockController.skipSegment` returns early while `UtubotCutController.isCutActive()` (a cut is applied to the video that plays), so the sponsor skip and prompt are off and cannot clash with the cut's own jump (`seekToKeptPart`, the cut's skips, the skip toggle). The cut's jump still goes past sponsor segments (one jump). Back on when the cut is taken off or the video has none. Tests: `SponsorBlockControllerTest` (inside, at the start of, straddling a cut-out part).

## 2026-11-26 (parity matrix row ids, issue #132)

- `ai/BROWSER_EXTENSION_PLAN.md` section 3: the matrix's first column is a stable `id` (`cut-picker`, `whats-new`) instead of a running
  number, so a row added by one pull request no longer collides with another on rebase. References in the plan, `ai/CONTRACT.md`,
  `ai/CUT_MODES_PLAN.md` and `ai/RESEARCH_MODE_PLAN.md` name rows by id. The parity check reads no table, so it is unchanged.
  `test_parity_matrix_rows_have_unique_stable_ids` guards uniqueness and rejects numeric ids.

## 2026-11-26 (What's new, issue #175)

- Settings, Updates, "What's new": the app's versions and the backend's deploys (`GET /v1/changelog`) as rows, an entry opens its text in the
  scrolling long-text view. After an update, "What's new in X" is offered once (`UtubotWhatsNew`, from the 6 hour update check; a fresh
  install shows nothing). The release notes fall back to their text, not a QR code, when the device has no WebView. QR codes remain only
  where the purpose is opening an address on a phone (release page, About links, the cut request sheet). Not built here: Gradle runs in CI.

## 2026-11-26 (UTB-146 r2: parity box for the no-target map/reduce cut cap)

- The long-video cut cap fix changes `ai/CONTRACT.md` and `common/utubot/` but no `extension/` file or the browser-extension plan,
  so the `parity-box` check failed. The no-target map/reduce cap is a backend cut-build behaviour only: the wire contract is
  unchanged and the extension reads `kept_ms` as before, so no extension change is needed (the TV keeps the real per-preset length
  on screen). Added the extension's side of the parity box to `ai/BROWSER_EXTENSION_PLAN.md` so the check passes; backend tests
  green (1298), ruff clean.

## 2026-11-24 (director's cuts: Quick/Watched backend)

- Backend now serves two cut modes: Quick stays transcript-only and the default; Watched is an opt-in picture path that stores a
  small video copy, describes 2x2 frame grids with `[llm.cuts_vision]`, joins them to transcript units and asks the same
  `[llm.cuts]` editor. The request/cut documents, stage list, picker state, `progress`/`eta_s`, failure `fallback` to Quick, and
  per-user `cut_mode` are additive; the contract and server docs carry them. Watch modules are adapted from the owner's r2t4
  scene-analyser under MIT (`ai-backend/THIRD_PARTY.md`, `watch/LICENSE`). Tests never use YouTube or a real model, and the CI
  backend installs the `watched` extra.
- The TV/phone/extension mode UI and `scripts/emulator_mock_backend.py` are still to do; no bake-off/labelled-set gate was run in
  this environment (owner-only work on the owner's model endpoint).

# u·tubot devlog

## 2026-11-26 (cuts: seek stays in the kept parts, and a toggle to watch them, issue 142)

- While a cut is on, a forward/rewind seek moves in cut time and never lands in a cut-out part. The seek lands in
  `UtubotCutController.onSeekEnd`, where the direction is taken from the position the seek started from (`mSeekFromPos`, tracked by
  the watcher and refreshed on every seek) and `UtubotCutSkipper.snapToKept` snaps a landing inside a dropped range to the range's
  edge — the end for a forward seek, the start for a backward one — so a seek within a kept part stays put and a longer press jumps
  between part boundaries.
- A new player toggle (`UtubotCutSkipAction`, the `action_utubot_cut_skip` button next to the cut button) flips `mSkipActive`. Off,
  the cut's skipping stops and the seek no longer snaps, so the cut-out parts can be watched, but the cut stays selected and its skips
  stay dimmed on the seek bar; on, it resumes and jumps out of any drop the playback sits in. The button shows only while a cut is
  applied (`PlayerUI.setCutSkipActive`), and turning the cut off, a video change or a finish hide it.
- Tests: the snap edges and the kept-part stay in `UtubotCutSkipperTest`, the forward/backward snap, the seek with skipping off and the
  toggle resume in `UtubotCutControllerTest`.

## 2026-11-26 (frequent update checks, issue #200)

- The update schedule now reads its interval from the settings after every check: "Update check interval" (5, 15, 60 or 360 min;
  default 5 min, was a fixed 6 hours). Settings, u·tubot: new "Development mode" switch, on by default in the built-in flavor: an
  update found while no video plays opens the dialog at once with Install selected (the APK is already downloaded by then). A playing
  video is never interrupted; the existing deferral offers the update when the player closes.
- Tests: schedule re-reads the interval, settings defaults, development-mode flag. Gradle ran only the update/settings tests and the
  app compile.

## 2026-11-26 (UTB-163 r1: the kept-part seek stays on its own video, parity row)

- A part of another video's cut (a list card's picker open while another video plays) must not move the video that plays:
  `jumpToPart` now takes the cut and checks `isPlayingVideo`, with a test for that case; the start is also clamped at 0.
- The parity box failed because the fix touches `common/utubot/` without an extension file or the plan: row 22 of
  `ai/BROWSER_EXTENSION_PLAN.md` now records the TV kept-part seek (the extension's clickable kept-part list is the same), so it passes.
- Common unit tests green, app compile green.

## 2026-11-26 (rebase on #116: part jumps use seekToKeptPart)

- `jumpToPart` now lands through `UtubotCutController.seekToKeptPart` (the one place for kept-part jumps, with the sponsor merge and the end clamp). `seekToKeptPart` also seeks when no cut is applied (no skipper), so a part picked before applying still jumps.

## 2026-11-26 (clicking a kept part jumps the playing video to it, issue 140)

- Pressing a kept part in the cut's parts list now seeks the playing video to that part's start (clamped to the video length) and
  leaves the cut applied, so playback continues from there until the next dropped range. The picker closes first, like the other
  rows. Before, the parts were read-only and a press did nothing.
- `UtubotCutController.jumpToPart` does the seek and keeps the cut (it neither applies nor turns it off); a seek of the user wins and
  is where the skipper starts again, like any other seek. `UtubotMenu` gives each part a callback that closes the picker and calls
  it; no live player of the video (a list card) takes the seek.

## 2026-11-26 (director's cuts quality, port of #106)

- Units: caption fragments close a unit after a quote or bracket that ends the sentence; rolling auto-caption repeats (the tail of
  the previous fragment at the start of the next) are dropped only for YouTube's automatic captions, an authored caption or ASR
  text keeps a genuine repeat (`build_units(..., rolling=)`). A repeat after a pause is kept.
- Finalize: kept parts are merged and short parts dropped on the model's boundaries clamped to the video, then padded, so padding
  cannot pull a dropped gap into a merge or keep a part the model made too short.
- Target length: `select_for_target` charges the merged, padded, clamped length and skips parts under `min_part_s`, so the cut it
  counts is the cut `finalize_parts` returns and a bridged gap cannot push it past the band.
- Highlights prompt names the payoff moments and the filler to skip, next to main's many-short-moments wording.
- `keep_guards(cfg, preset_id, target_s)` is the one place that decides the guards (main's rules: `short_presets`, highlights and
  length targets skip the lower guard, only a typed prompt keeps the upper one); the quick build, the watched build and the bench
  use it, so the watched build now honours `short_presets` too.
- Cut bench: scores the production message, its repair round and the one-pass target retry, reads chapters, 16 requests.
- TV: a tick landing anywhere inside a drop skips it (a seek is a backwards move or one over a tick of the speed), a seek the user
  ends inside a drop plays, and the trailing drop says "End of cut" with "Watch the rest".
- Not ported from the closed PR: its `keep_guards`/`keep_guards_for` rework (lower guard for the no-filler preset only, none for a
  typed prompt) contradicts main's `short_presets` rule, and its `min_guard` parameter of `finalize_parts`.

## 2026-11-26 (cuts: the player shows cut time and part number, flow-80)

- While a director's cut is applied, the player's cut button shows the cut's name and the position and length in cut time
  ("3:10 / 5:00 of Highlights"), plus the current part when the playback is in one (" · part 2 of 7"). The full-video time
  stays on the player's own clock. The label updates every playback tick as the playback moves and shows the same snapshot
  while paused; the menu still switches the cut or turns it off.
- `UtubotCutTime.of` maps a video position to the cut time and the kept part it is in: the cut time is the kept parts before
  the position plus how far into the current part it is, and the part number is 1-based, 0 in a drop or before the first / past
  the last part. The kept length is the cut's own (`kept_ms`), the sum of the parts only when the cut reports none. The label
  is rewritten only when it changes, so a tick that computes the same string leaves the button alone.
- Tests: `UtubotCutTimeTest` (inside a part, first and last part, past the last, between parts, before the first, no parts,
  null cut) and `UtubotCutControllerTest` (the button shows the cut time and part number, the label follows the playback, a
  same position does not rewrite it). Harness `CutsHarnessActivity` shows the cut time and part number.

## 2026-11-26 (cuts: seek stays in the kept parts, and a toggle to watch them, issue 142)

- While a cut is on, a forward/rewind seek moves in cut time and never lands in a cut-out part. The seek lands in
  `UtubotCutController.onSeekEnd`, where the direction is taken from the position the seek started from (`mSeekFromPos`, tracked by
  the watcher and refreshed on every seek) and `UtubotCutSkipper.snapToKept` snaps a landing inside a dropped range to the range's
  edge — the end for a forward seek, the start for a backward one — so a seek within a kept part stays put and a longer press jumps
  between part boundaries.
- A new player toggle (`UtubotCutSkipAction`, the `action_utubot_cut_skip` button next to the cut button) flips `mSkipActive`. Off,
  the cut's skipping stops and the seek no longer snaps, so the cut-out parts can be watched, but the cut stays selected and its skips
  stay dimmed on the seek bar; on, it resumes and jumps out of any drop the playback sits in. The button shows only while a cut is
  applied (`PlayerUI.setCutSkipActive`), and turning the cut off, a video change or a finish hide it.
- Tests: the snap edges and the kept-part stay in `UtubotCutSkipperTest`, the forward/backward snap, the seek with skipping off and the
  toggle resume in `UtubotCutControllerTest`.

## 2026-11-26 (cuts: the menu is served from cache when the backend is slow, issue 146)

- The TV now caches the cuts list per video and opens the menu instantly when the backend is slow or down: it serves the cached
  list straight away, refreshes in the background, and keeps the cached copy when the backend answers 304 (If-None-Match). The
  backend returns a strong ETag and `Cache-Control: max-age` on `GET /v1/videos/{id}/cuts` and answers 304 while nothing changed
  (already in the backend checkpoint). The list is immutable once built, so the ETag is computed internally from the ready cuts and
  is not put on the wire for individual cuts (backward with old rows).
- Storage lives in `UtubotDiskCache` (one file per video, capped at `MAX_CUTS`, refreshed on expiry, deleted on a bad read); the
  network layer is `UtubotClient.cutsCache`, which returns the cached copy on 304 instead of touching the body; the flow is in
  `UtubotManager.cutsObserve`, which emits the cached list immediately (render), only a fresh list on first successful load (not when
  a cache already existed), nothing on 304, and a stale notice on failure if a cache exists. The menu shows the cached cuts at once and,
  when the backend has not answered, a "Refreshing…" category.
- The emulator mock backend serves the same ETag/304 on the cuts list, so the offline path is exercisable without a real server.
- Tests: disk cache (load/put/clear, expiry, cap, bad read), the client's 200-with-ETag and 304 paths, and the manager's full offline
  flow (instant cache, no re-render of an existing cache, 304, stale on failure, cache survives a restart). All green.
- Parity: the extension serves the cut menu from its own storage the same way and shows the cache under a notice on a failed refresh
  (parity matrix row 33). The ETag/304 on the cuts list is in `ai/CONTRACT.md`.

## 2026-11-26 (TV uploads its caption tracks to the backend, issue 149)

- `VideoLoaderController` calls `UtubotClientCaptions.onFormatInfo`: in the background, once per video per app session, the TV
  fetches the timed text (json3) of at most the original-language and the user-language track (no other YouTube request) and posts
  them to `POST /v1/videos/{id}/captions/client`. Only with a configured, paired backend; failures are logged, never shown, and the
  next play tries again. Extension: no caption track read yet, noted in `ai/CONTRACT.md`.

## 2026-11-25 (cuts: the explicit pick wins over stale answers, issue 103)

- The TV keeps the viewer's own pick or off per video until the backend carries it: a cuts answer or a followed request that was
  built before that write landed can no longer replace the cut the viewer just picked or bring one back after an off. The pick
  guards its open and is dropped on finish; an off stays until the viewer picks a cut on this TV again.
- A chosen preset with no ready cut (its request failed or no longer matches the video) offers the other ready cuts instead of
  opening the video uncut with no offer. A chosen request that is still building is followed, not offered around.
- Tests: stale last/off/ready answers and a late followed request in `UtubotCutControllerTest`, a chosen preset without a ready
  cut in `UtubotCutFollowerTest`.

## 2026-11-25 (a video opens with the chosen cut, issue 103)

- The cut follower no longer takes the first ready preset: `GET /v1/videos/{id}/cuts` now carries a `selection`, and only that cut
  is applied when the video opens. The selection is the viewer's choice for the video, else the preset they used last when it has a
  ready cut here; with neither, the video plays uncut and every ready cut is offered with one Apply each (never the first silently,
  also with "apply ready cuts automatically" on).
- The backend keeps the choice per `(user, video)` and the last-used preset per user (`cut_choices`, `cut_last_presets`); creating
  or filling a cut request records it, and the TV records a pick or an off with `PUT /v1/videos/{id}/cut-choice` (`UtubotClient.chooseCut`,
  `UtubotManager.rememberCutChoice`/`forgetCutChoice`).
- The player button shows the applied cut ("Cut: No filler · 12:40") through the new `PlayerUI.setButtonLabel` hook, and the video
  menu still switches it or turns it off.
- Tests: backend `TestCutChoice` (chosen wins, last used, no ready for the last preset, several ready in any order, typed choice, off),
  TV follower/controller/parser/client cases. Extension parity row `cut-mode-watched`.

## 2026-11-25 (long-video cuts keep almost everything, issue 125)

- A long video cut by map/reduce no longer keeps nearly all of itself when the preset has no target length: each
  excerpt applies the task locally, a no-target build is capped at `[cuts] map_max_keep_frac` (default 0.90) and the
  highest-ranked parts are kept, and the TV picker still shows each cut's own length.
- Old bad cuts are repaired once on server start (or `utubot cuts repair`): the affected request and cut row are
  superseded and the same user, video and preset are queued again with the current algorithm version. The map and
  reduce job events now log what each excerpt kept and removed.

## 2026-11-25 (a failed cut retries; no-filler keeps nearly all, issue 99)

- A failed cut request no longer sticks in the picker: the TV starts a fresh request when a failed preset is picked
  (its state shows the reason and Retry), the web UI keeps its Retry, and the backend never reuses a failed row.
  A fresh request also rebuilds after a server limit changes.
- `cut-no-filler` and the other removal presets have no upper keep guard: a 96-99 % keep is a valid cut. Their cut
  summary says the result plainly ("Removed 1:12 of filler, 2 % of the video"); when nothing is removed the request
  is ready with "No filler found". Detailed guard messages name what was found and what to try.

## 2026-11-24 (frozen engine claim contract, issue 93)

- `ai/ENGINE_CLAIM_CONTRACT.md`: phase 2 checkpoint P0, the frozen wire contract of P.3.3. Requests (ask, renew, `DELETE`,
  lookup by `client_ref`, read by id), the claim object and states, every `409`/failed reason with its sentence, the times
  and renewal rules, release and retry life cycle, and the D-P11 semantics.
- `ai/CUT_MODES_PLAN.md`: P.3.3 and the P0 checkpoint link to the contract; P.1, P.6, P.7 (H3, N1) and P.9 now state the
  owner's take-it-at-once decision instead of the earlier wait-for-runs text.
- `ai-backend/tests/test_engine_claim_contract.py`: the contract keeps every config key, endpoint, state and reason, a
  sentence per reason, the plan's reason set and the D-P11 wording; it fails on drift.

## 2026-11-25 (a cut that becomes ready while the viewer is elsewhere, issue 96)

- A director's cut ordered on the TV while it is still waiting or building is kept in `UtubotCutWaitlist` (one row per request,
  surviving a restart). `UtubotCutWatcher` follows each through `GET /v1/cuts/{id}` from the app-wide `UtubotAppHooks`, so the
  follow no longer depends on the video being in the player. `UtubotCutNotices` asks "Director's cut ready: <title> (<real
  length>). Play?" wherever the app is, one cut at a time: Yes carries the cut through the #64 path and opens the video, No (or
  Back) only closes the question and leaves the screen and the playback position alone.
- The first check after a start does not wait: a cut that became ready while the app was closed is left to the cut picker and the
  Processed section, while a failed build reports its reason (at the next screen if there was none). Dismissed, ready and failed
  requests leave the list, anything over 30 minutes is old, and a backend or token change clears it. A cut of the video that is
  playing stays with the player's own follower once it has taken the cut over — applied, waiting for the length, or offered with
  Apply — so the app-wide notice does not ask a second time after the follower's own ready-cut offer (the follower clears its
  request the moment the cut is ready, so the offer itself is now read as the player handling it). A kept question the player
  takes over before it is shown is dropped instead of reopening the same video. A request the follower never learned, like one
  ordered from the cut sheet with no preset, still asks.
- A network error no longer loses an order: the watcher retries (1 s, 2 s, 5 s, 10 s, then every 30 s) until the cut is ready,
  failed or older than 30 minutes.
- Tests: `UtubotCutWaitlistTest` (persistence, one row per request, cap, clear, bad stored rows), `UtubotCutWatcherTest` (ordered
  or startup check, closed-app ready, failure reason, dismissed, old, errors kept until ready), `UtubotCutNoticesTest` (playing
  video and follower ownership, a follower's ready-cut offer and a cut taken over after the question was kept are not asked twice,
  the Yes path through the real open, popup text, Yes/No/Back, failure at the next screen), `UtubotScreenTest` (any
  screen, dialog over player) and `UtubotCutPromptQueueTest` (Yes opens, No stays, several cuts one at a time, a blocked question
  retried, no double answer). Browser extension: parity matrix row 34.
- Verified with JDK 25: the new tests and `:common:testStutubotDebugUnitTest` (all u·tubot tests), plus the TV module build.

## 2026-11-25 (kept-part jump, outside-the-cut badge, clear seek bar, issue 104)

- Double-press Right/Left (or Up/Down; Off) jumps to the next or previous kept part of an applied cut (`UtubotCutNavigator`,
  Settings, u·tubot, "Jump between kept parts"). The first press keeps its normal seek, a held key stays fast seek, any other key
  breaks the pair, and the next jump goes past the sponsor segments at its destination like the cut's own skips. A direction
  with no part left moves nowhere, and the second press is consumed there rather than falling through to a seek. The gesture is
  guarded while the controls/suggestions overlay owns the D-pad and while a quick-skip direction would consume the press (that
  direction loads another video), so it does not take Leanback or quick-skip presses. The controller keeps its place after
  `SponsorBlockController`; `VideoPlayerGlue` already sends every key-down through the chain before the progress bar seek, and
  the sponsor watcher's `onVideoLoaded` still starts the segment refresh the cut's skipper merges with before the cut applies.
- Inside a cut-out range a small unfocused badge at the top left says "Outside the cut · ▶▶ next part in 2:10" (or that no kept
  part follows) and goes away in a kept part (`UtubotCutBadge`).
- The seek bar draws kept parts bright cyan and cut-out ranges dark with a diagonal hatch, the knob stays on top, and a new
  segment list replaces the rectangles of the old one, so taking a cut off leaves only the sponsor colours (`SeekBar`). The
  colours and gesture are explained once (`UtubotCutSeekBar.segmentsFor`). Unit tests: `UtubotCutNavigatorTest`,
  `UtubotCutSeekBarTest`, `UtubotCutControllerTest` (state machine and guards) and the TV's `SeekBarSegmentsTest` (replacement).
- Browser extension: parity matrix row `cut-jump-badge` (keyboard shortcut, touch button, badge), row `cut-seekbar` unchanged. The jump lands in
  `UtubotCutController.seekToKeptPart` so a part picked from a list can reuse it. No extension
  code yet.

## 2026-11-24 (director's cuts for long videos, issue 95)

- Cuts no longer refuse long videos: a transcript over `[cuts] max_input_tokens` is read in excerpts (chapter boundaries, small overlap),
  each excerpt proposes ranked candidate parts, and one final call (rounds when there are too many candidates) picks the cut with the
  same length selection as a one-pass cut. The default `max_input_tokens` is now 80000; set it to about 80% of the cut alias's context.
  Progress stages `map` (i of n) and `reduce` ride on the request (`progress`, additive). Details in `ai-backend/DEVLOG.md`.

## 2026-11-24 (director's cut modes plan)

- `ai/CUT_MODES_PLAN.md`: the two-part plan for two director's-cut modes. Quick is today's transcript-based cut and stays the
  default; Watched adds what is on screen (a small video copy in the media archive, shot boundaries, sampled frames described
  by a local vision model, scene lines joined with the transcript units, the same editor model and the #82 length selection).
  Mode is a server default, a per-user default and a per-request field, shown in the TV picker, the phone cut sheet and the
  extension's Cut tab. Checkpoints 0 to 7, six owner decisions, a list of what could not be verified. Nothing is implemented.
- Revision 2 of the plan: the watched mode reuses the owner's earlier scene-analysis code (`evrenesat/r2t4`, `scene-analyser`)
  as its analysis engine, copied into `ai-backend/src/utubot/watch/` with attribution once the owner allows it (that repository
  has no licence; new owner decision 7). Timestamped 2x2 grids replace single frames, one vision request per grid with a bounded
  running context, the result stored as a slim Timed Descriptive Transcript that maps onto the cut units. The time estimates are
  replaced by that project's measured figures, and the vision model recommendation is now Qwen3.6-35B-A3B first.
- Revision 3 answers the plan review (approve with changes, eight mediums, ten lows; the plan's section 6): the #82 gate has
  an owner and a fallback, checkpoint 3 starts with an image-input probe of three named candidate aliases and adds a run of at
  least 100 grids at full context, the grid cap always fits a video within the 90-minute limit, the grid stage runs in a worker
  thread with its own `ffmpeg` module, an owner command `utubot media import` feeds offline runs, the waiting stage is
  `in_line`, and the cloud switch is no longer built.
- Revision 4: decision 2 now follows the owner's model research (three installed vision models, Qwen3.6-35B-A3B as the default,
  settled by a 45-minute bake-off that is the first step of checkpoint 3). A new last part, "Phase 2: priority classes and engine
  claims", not yet reviewed: prime and normal users, class-ordered queues, a model route per class, a claim on the big local
  engine through a small HTTP contract, an effort notch for Watched (Keyframes, Standard, Dense), per-account pairing on the TV,
  checkpoints P1 to P9 across four repositories.
- Revision 5 answers the phase 2 review (five high, eight medium findings; the plan's P.7): a claim is waited for at most three
  minutes and then ends in the Quick offer, the server refuses to start if a local or claimed route could reach the cloud, the
  claimed route never falls through, the claim contract is frozen first as its own file (checkpoint P0), renewal runs on a timer
  against the service's clock, TV account pairing fails closed, and the decisions are renumbered D-P1 to D-P11.
- Revision 6 answers the phase 2 re-check: nothing on the big engine is paused or switched for a claim any more. The claim
  service waits a bounded time for running work and tells the backend its deadline (`ready_by`); the backend shows the minutes
  left, gives up with the Quick offer and always deletes a claim it stops waiting for. The claimed route gets its own key.
- Revision 7 adds section 2.13, the data model for two later features (issues 88 and 89): cuts keyed by a source (a YouTube id
  or a title id with a release fingerprint and a duration tolerance), per-scene content labels in a queryable table, and an
  optional transition slot per boundary in the cut document. The columns land in checkpoint 1 with a test that old rows read.

## 2026-11-24 (director's cuts respect the target length, issue 82)

- The cut picker titles a ready preset with the cut's real length, "Highlights in 5 min · 5:02" (`UtubotCutController.presetTitle`,
  from `kept_ms`); unit test in `UtubotCutControllerTest`. The ready toast already showed the length. No upstream file touched.
- Backend: the highlights preset now has a target length with a tolerance and the server enforces it (`ai-backend/DEVLOG.md`).
  Browser extension: its cut checkpoints show the same real length (plan parity; no extension code yet).

## 2026-11-24 (browser extension plan, issue 72)

- `ai/BROWSER_EXTENSION_PLAN.md` (first written as `FIREFOX_EXTENSION_PLAN.md`): the two-part plan for a browser extension with
  parity for the u·tubot features. Firefox on desktop and Android is the main target, Chromium browsers on desktop follow from
  the same code. Owner decisions, the parity matrix against the TV code, architecture, the no-YouTube test approach, signing
  and distribution, checkpoints 0 to 21 plus the web UI companion checkpoints C1 to C4. No backend or app change is needed for
  parity; nothing is implemented yet.
- Three plan review rounds are answered in the plan's section 14 (extension builds stay off GitHub Releases, explicit
  permission buttons, every mock-backend control specified, requests without cookies, a fully specified offline test guard,
  the parity check as its own workflow).
- Owner additions of the same day: an MVP first (checkpoints 0 to 9: setup, pairing, the playing video's summary, HQ captions,
  cut skipping, a signed unlisted desktop Firefox build); a Chromium track after it; a "Lessons from existing extensions"
  section from reading SponsorBlock, its shared library, DeArrow, Return YouTube Dislike and ImprovedTube (navigation events,
  main video lookup, ad state, timer-driven skipping, recycled cards, hermetic tests), with the site, captions and cuts
  checkpoints changed to match; the licence rule (MIT stays, GPL code is read for technique and never copied); the mid-term
  role as companion of the web UI.
- Re-check of those additions: two owner smoke runs on real YouTube during the MVP (unsigned build, popup diagnostics), a
  whole-MVP review before the first signed release, the owner's use as its own checkpoint 9b, stale-answer tests in the
  summary, captions and cuts checkpoints.
- `AGENTS.md`: the standing rule that every AI feature is specified, built and tested for the TV app and the browser extension,
  with a transition, and the extension's licence rule. `ai/CONTRACT.md`: the "Clients" section, and the cut paragraph no longer
  says the TV compares `transcript_hash` (it never did). `.github/pull_request_template.md`: the parity, contract and
  no-YouTube boxes.

## 2026-11-24 (Processed section review round 1)

- A backend or token change drops the Processed section's browse cache and cancels a cached refresh still in flight: `BrowsePresenter`
  registers a `UtubotSettings` connection listener (as `UtubotManager` does), so the tiles of the old connection's user can't be
  replayed under the new one. Test: user A's tiles cached, backend and token changed, focus Processed shows only the new answer.
- A saved sidebar keeps the ids of the default sections it knew; a restore adds any current default missing from them once, and
  a section the user turned off stays off. A sidebar saved before the set existed knew every default but
  `SECTIONS_ADDED_SINCE_KNOWN` (Processed now), so existing installs gain the section. Tests: an old saved sidebar gains Processed
  once, and a saved sidebar with it turned off keeps it off.
- Without a configured backend the section shows "Set the u·tubot backend address in the settings first" instead of
  "Bad backend address: ".
- Tests: `tests/test_processed.py` covers a dismissed cut staying out (a video with only dismissed requests is absent) and `limit`
  0/201 being 400; `BrowsePresenterProcessedTest` covers the cached replay after a connection change and the setup hint. Removed an
  edit artifact from BrowsePresenter's upstream comment.
- Verified with JDK 25: `:common:testStutubotDebugUnitTest` (1632 tests, 0 failures, 0 errors, 7 skipped), and in `ai-backend`
  `uv run pytest -q` (1050 passed) and `uv run ruff check` (clean).

## 2026-11-24 (Processed section, issue 66 steps 1-4)

- Backend (step 1): `GET /v1/processed?limit=N` (default 50, at most 200, auth) answers `{"videos":[...]}`, one item per video from
  the caller's caption jobs and non-dismissed cut requests, newest `updated_at` first; `summary` says whether a stored summary exists.
  A read-only `ProcessedService` combines rows already there (no new storage); `ai-backend/DEVLOG.md` and `docs/server.md` carry it.
- TV data layer (step 2): `UtubotModels` gained `ProcessedItem`/`ProcessedList` and their caption and cut entries,
  `UtubotParser.parseProcessed` and `UtubotClient.processed(limit)` read the endpoint with the bearer token, and
  `UtubotManager.processedObserve` is cancellable like the cuts one.
- Sidebar section (step 3): `UtubotProcessedSection` maps the answer to newest-first grid tiles with the processed line under the
  title ("HQ captions: ready • Cut ready: Only the demo • Summary ready", or the newest state for unfinished work); `BrowsePresenter`
  and `SidebarService` register it only in the built-in flavor, the browse cache of #65 is reused and empty/failed answers show
  `UtubotSectionError`.
- Opening a tile (step 4): `BrowsePresenter.onVideoItemClicked` recognizes the section's cards through their group (`UtubotProcessedOpen.isProcessed`)
  and opens them with `UtubotProcessedOpen.open`, which asks `UtubotCaptionsOpen` for the video's HQ captions and then starts the
  normal playback path (`PlaybackPresenter.openVideo`). The player takes that request when it sets the video, and selects the HQ track
  even with "Select HQ captions automatically" off; the request is for that playback only and expires if no player takes it.
- A ready cut is not carried again: the Processed open goes through the same playback path as #64, whose `UtubotCutController`
  follows the video (`GET /v1/videos/{id}/cuts`) and announces a ready cut with its one-press Apply dialog (or applies it by itself
  when "apply ready cuts automatically" is on). A tile with no cut starts plainly.
- Tests: `UtubotProcessedOpenTest` (4: the tile's captions selected with the automatic setting off, a ready cut offered by the player
  path, no cut and plain play, only the section's cards are Processed). The steps 1-3 tests (parser, client, tiles, presenter) stay.
- Docs: README Features and docs/install.md "Using it" list the section; docs/server.md and docs/captions.md say what its tiles show
  and that opening one selects the HQ captions.
- Verified with JDK 25: `:common:testStutubotDebugUnitTest` (1628 tests, 0 failures, 0 errors, 7 skipped),
  `:smarttubetv:assembleStutubotDebug`, and in `ai-backend` `uv run pytest -q` (1048 passed) and `uv run ruff check` (clean).

## 2026-11-24 (Processed sidebar section, issue 66 step 3)

- The built-in flavor has a sidebar section `Processed` past the other entries and before Settings (`UtubotProcessedSection.ID`,
  a reserved id 26 since `MediaGroup.TYPE_...` lives in the pinned sibling repo), registered in `BrowsePresenter` and
  `SidebarService` only with `UtubotSettings.isBuiltIn()`; the other flavors keep their sidebar.
- Its grid loads `GET /v1/processed` through `UtubotManager.processedObserve(50)`, a backend call, not YouTube; the answer is
  mapped to video tiles in its newest-first order (`UtubotProcessedSection.toGroup`). A tile has its video id, title, thumbnail
  and the processed line in the second title: "HQ captions: ready" (else the newest caption state), "Cut ready: …" with every
  ready preset's label or prompt (else the newest cut state), "Summary ready" when one is stored. The endpoint sends no channel,
  so the tile has none.
- The section keeps the browse cache of #65 (replay, background refresh, in-place id reuse); an empty answer shows
  "No processed videos yet" and a failed one "Can't load the processed videos: …" through `UtubotSectionError`, and a cached
  section keeps its cards when its refresh fails. Opening a tile is unchanged (step 4 is later).
- Tests: `UtubotProcessedTilesTest` (5: field mapping, each part and its state, ready preset labels, order, empty answer) and
  `BrowsePresenterProcessedTest` (5: registration, injected answer loaded into the grid, empty and failed states, a failed load
  with the view gone), following
  `BrowsePresenterCacheTest`'s style. `:common:testStutubotDebugUnitTest` and `:smarttubetv:compileStutubotDebugJavaWithJavac`
  are green with JDK 25.

## 2026-11-24 (update notification, u-tubot#80)

- The scheduled check (`AppUpdatePresenter.startAutomatic`) asks `/app/update.json` on every run (20 s after the start, then every 6 h)
  while "Notify about updates" is on, instead of being gated by the shared checker's 60 second "recently checked" window. The update
  dialog opens over the main menu as before; Back or "Not now" stores the offered version (`UtubotSettings`, dismissed update) so an
  automatic check doesn't offer it again until a newer one, while the manual "Check for updates" shows it. Tests: `AppUpdatePresenterTest`.
- The flavor decides "newer" by the channel's `versionCode` against the installed one (`UtubotUpdateChecker.isNewer`), as the backend
  publishes one per release and a version name can be shared (a build's `-dev` suffix); a manifest without codes falls back to the shared
  checker's version-name comparison. Test: `UtubotUpdateCheckerTest`.
- Review round 2: the dismissal stores the version name and code, so a higher code under the same name is offered again; changing the
  backend or update address clears it. A manifest with no download address is an error instead of "no update", and a cached APK whose
  name matches but whose code does not is discarded so the offered build is fetched. Tests: `AppUpdatePresenterTest`,
  `UtubotUpdateCheckerTest`.
- Parity: the browser extension has no update UI of its own (the browser updates it), so there is no extension row for this feature.
- Verified with JDK 25: `:common:testStutubotDebugUnitTest` (1646 tests, 0 failures, 0 errors, 7 skipped), `:smarttubetv:assembleStutubotDebug`.

## 2026-11-24 (browse cache review round 4)

- Channels multi-grid on a cached replay: only the view's first auto-selection keeps the cached uploads; every later channel the
  user selects loads its uploads (before, a FRESH cache blocked all selections for the whole window). A failed refresh clears the
  skip too. Tests: second channel on a fresh cache, after a failed channels refresh and after a failed uploads refresh.
- A cached rows refresh restores the focused card of a replaced row, as grids do (`BrowsePresenterCacheTest`).
- The cache keeps the added-Home-row metadata (type and channel id, `VideoGroup.setAddedHomeRow`); a replayed row's menus and
  hide section use it (`findAddedHomeRowChannelId` falls back to the group). Entries carry `format_version` (now 2): an entry of
  another version is dropped on read, so old entries aren't misread. Tests: round trip, hidden section, old-version entry.
- PR body: the entry cap is 512 KiB, not 8 MB.

## 2026-11-24 (browse cache review round 3)

- A cache entry now carries the section type that made its groups: a section whose layout changed (Playlists style, History shorts
  history, Channels old look after a restart) doesn't replay the old groups into another fragment. The entry is dropped on the read
  (memory or disk), and a style change drops the cache of the section it changes when the entry is for another layout, so a settings
  change while the presenter runs doesn't replay or save the old layout's groups under the new type. A cache already made for the
  new layout stays (e.g. at the next start the sections are made as rows first). Tests: `UtubotBrowseCacheTest` for a layout change
  in memory and on disk after a restart, `BrowsePresenterCacheTest` for Playlists style (and its cache at the next start), History
  shorts and Channels old look.
- A card removed, hidden or taken from a playlist while a cached refresh is still loading is kept out of that refresh's completion
  save (the load's groups still carry it), and a cache dropped by a removed author during that refresh isn't written back by the
  completion either. `BrowsePresenterCacheTest` drives a two-part refresh with the card removed after its first part, and an author
  removal before the completion.
- On a fresh cache replay of Channels with "auto load" off, the view's auto-selection no longer clears the cached uploads column:
  the replay keeps both columns there too (`BrowsePresenterCacheTest`).
- Docs: `docs/development.md` ("Checking the browse cache") and `ai/APP_INTEGRATION.md` state the layout check and the refresh-save
  filtering.

## 2026-11-24 (browse cache review round 2)

- A cached refresh that completes after the view is gone, or after the cached rows are dropped (an account change), no longer
  removes stale rows through a null view or list: the removal is skipped, so completion keeps the cards (or the cache) instead of
  crashing. An account or locale change also disposes an in-flight cached refresh, so it can't save the old account's or locale's
  rows after the cache is cleared. Tests complete a refresh with null cached rows, with the view gone, and after an account change.
- The channel-uploads multi-grid honours a fresh cache: its replayed channels auto-select a channel (see `ModernChannelsView`), but
  the presenter keeps the replayed uploads and makes no uploads request; only a stale background refresh loads the uploads after
  its channels. A failed uploads refresh shows the cached uploads column again (the channels' arrival had cleared the view's
  column), and the failed attempt isn't retried within the refresh window. Tests drive both columns with a fake uploads presenter.
- A card removed with Hide, Not interested or a playlist removal is taken out of the section's cache at once, so the next focus in
  the window doesn't replay it; removing an author's cards drops the section's cache because it can't patch every row. Test: the
  hidden card is gone from the replayed group and from the cache.
- `BrowsePresenterCacheTest` grew from 6 to 12 tests for these paths; docs: `docs/development.md` ("Checking the browse cache").

## 2026-11-24 (browse cache review round 1)

- A section that emits its rows in parts (Music: `Liked music`, then the music rows; Playlists: one per playlist) now keeps every
  part in one cache write at `onComplete`: the cache of the whole section is built from all the emission's rows, not replaced per
  part. Stale cached rows are taken out only after every part arrived, so a part that hasn't come yet keeps its replayed rows. A
  failed later part leaves the last whole cache and keeps `mCachedContentShown` set, so the cached cards stay on screen with no
  error page; the flag is cleared only once the whole load completes (not on a multi-grid's first column, which would turn off the
  cached uploads column). `BrowsePresenterCacheTest` drives two-emission sections through these cases with a fake view.
- The cache entry cap is 512 KiB (was 8 MiB): the JSON is parsed and written on the thread that shows or saves the section, so the
  cap bounds that stall. A larger entry is discarded (`UtubotBrowseCacheTest`). Cached rows have no page key (they come from cards
  alone): scrolling past replayed cards waits for the background refresh; a loaded row continues as before (stated in
  `docs/development.md` and asserted in `UtubotBrowseCacheTest`).

## 2026-11-23 (browse sections: stale-while-revalidate, issue 65)

- Every browse section now shows its last loaded content at once: `UtubotBrowseCache` keeps the emitted rows in memory and as
  per-section JSON under `files/utubot_browse`, keyed by the locale and the selected account. On focus `BrowsePresenter` replays
  them without a progress bar, then refreshes in the background only when the named setting "Browse refresh" (5, 10, 20, 30 or
  60 minutes, 10 by default) has passed. "Refresh section" and `refresh()` stay manual network loads.
- A cached-content refresh updates in place: rows reuse the old ids (matched by title and position) so a shelf replaces itself,
  rows that are gone are removed, a grid restores the card that had the focus, and a failed refresh keeps the cached cards and
  shows no error page. A row's next page replaces its stored copy (`append`), so scrolling also extends the cache.
- Account changes clear the cache (`onAccountChanged`), locale changes clear it in `onViewInitialized`, and the stored identity
  makes a cache from another locale or account unreadable. The channel-uploads multi-grid keeps its two columns by merging
  groups by position; local grids (queue, blocked channels) stay out because they are already instant and never load YouTube.
  The cache is kept out entirely in flavors without it (`UtubotSettings.isBuiltIn()`): the multi-grid column save checks
  `mBrowseCache == null` too, so the channel-uploads load in Electric Eel/SmartTube has no null dereference.
  Unit tests: `UtubotBrowseCacheTest` (policy boundary, disk restart, identity/invalidation, next page, card fields),
  `BrowseCachePolicyTest`, and the settings test for `Browse refresh`.
- Emulator walk on this host: AVD `tv` in a network namespace with only loopback, `0.json` seeded as the fake last Home content in
  `files/utubot_browse` (identity `en_US|`, `loaded_at_ms` of the run). Home, opened through `HomeLauncherActivity`, logged
  `Show cached section Home` at 19:45:38.678 and the `uiautomator` dump showed the four cached cards (`Cached card one` to
  `four`); the BrowsePresenter log had no `loadRowsHeader`/`updateRowsHeader` for Home. Music, opened next through
  `MusicLauncherActivity`, loaded YouTube and failed with `UnknownHostException` in `getLikedMusicTV` at 19:46:08.733 (its stack
  printed after the next focus). Home focused again at 19:46:07.830: `Show cached section Home`, again no Home load, and the dump
  had the four cards. The fake thumbnail URLs failed in Glide too, so this check covers the rows' replay, not images or a live
  YouTube run.
## 2026-11-24 (R2: disk cache of verdicts and summaries, Retry clears the backend's failure; issue 7)

- Retry (Summary panel, Summary view, AI answer) calls `POST /v1/videos/{id}/retry` first, then asks again; the call failing does not
  stop the request. The countdown of a `delayed` answer does not call it (the backend's own wait is respected). Docs: `ai/CONTRACT.md`.
- `UtubotDiskCache`: ready verdicts and ready summaries survive a restart. Scope = hash of backend address, token and the backend's
  version (`GET /v1/health`); another scope starts empty and the old scope's directory is removed. Entries expire after 3 days (a
  change of the backend's settings does not change its version), at most 2000 verdicts and 300 summaries. Failures, pending jobs
  and transcript states are never stored. Importing or refreshing prompts and setting the default prompt clear the summaries. Known
  limit: a default prompt changed from another device is only noticed after the 3 days or a new backend version.
- Review round 1: `clearSummaries` clears every scope's summaries, including a scope that has not been opened yet or is just the
  previous connection, so a prompt change before any summary request cannot serve a stored text of an earlier run. The backend's
  artifact inventory counts UTF-8 bytes (`LENGTH(CAST(... AS BLOB))`) instead of characters for text, json and vtt rows.
- Review round 4: a summary request that was already in flight when a prompt import, refresh or default change cleared the summaries
  is shown but not stored again; the manager's summary generation moves under the same lock as the clear, so neither the memory nor
  the disk gets the old prompt's text back. `UtubotSummaryCacheTest` waits a blocked request through a refresh and checks both caches,
  then a new request on the same backend version.
- Review r1: a connection switch while the disk cache is being opened no longer publishes the old scope over the new one (the opening
  captures the connection generation under the disk lock and drops what it loaded when the generation moved); `UtubotDiskScopeRaceTest`
  blocks the read through a token switch. The extension parity matrix and `ai/CONTRACT.md` ("Clients") record that the 3-day disk cache
  is TV only, and the archive docs and `store` log match the opt-in LRU eviction (a just stored file is never evicted right after).

## 2026-11-24 (CI app job: Robolectric no longer downloads at test time)

- Every Robolectric test class failed in CI since 23 Nov at `MavenArtifactFetcher` (an `IOException` while Robolectric fetched its
  android-all jars from Maven Central during the test run). `gradle/robolectric-offline.gradle` (applied in `common` and
  `smarttubetv`) now resolves the instrumented jars for sdk 28, 30, 33 and 34 as Gradle dependencies, copies them to
  `build/robolectric-deps` (`copyRobolectricDependencies`) and sets `robolectric.offline=true` plus `robolectric.dependency.dir`
  for every test task. Cause of the red CI: Maven Central answers 429 (Too Many Requests) to the GitHub runners, for poms and for the 150 MB jars; the CI action now installs a Gradle init script that sends every Central repository to Google's mirror
  The workflow also caches the jars. Add the artifact to that list when a test uses a new `@Config(sdk = ...)`.

## 2026-11-23 (director's cuts playable from lists and the player; u-tubot#64)

- Picking a ready preset in a picker opened from a list no longer asks a player for its length (and no longer claims a different
  length): `UtubotCutController.toggle` answers false without a player of that video, the menu carries the cut with `applyOnOpen`,
  and `PlaybackPresenter.openVideo` starts the video through the normal playback path with the cut applied as it opens.
- The player has the picker: `UtubotCutAction` puts "Director's cut…" next to the video stats button (`VideoPlayerGlue`), only in
  the built-in flavor with a backend, and `UtubotCutController.onButtonClicked` opens the same picker for the playing video.
- A ready cut announced at the video start offers a one-press Apply dialog; Settings, u·tubot gained "Apply ready cuts
  automatically" (default off), which applies such a cut by itself instead of offering it.
- A cut picked before the length is known waits for it instead of saying the lengths differ; the message now only appears for a
  real mismatch of the video that plays (`toggle` and `tryApplyPending`). A finish clears the applied cut, so a list picker for that
  video carries the cut to the reopened video instead of turning off a cut that is no longer playing.
- A cut that counted as pending for another video is dropped at the open, so no stale pending cut can claim a different length for
  the video that plays.
- Review round 1: a destroyed view the presenter still returns and a released engine no longer count as "the video that plays"
  (`isLivePlayer` requires `isEngineInitialized`), so the list picker of a just-played video always starts it with its cut instead of
  toggling/queueing against a dead player. The Apply offer closes at the next video and its press compares the cut's `videoId` to the
  current video; `tryApplyPending` drops a pending cut of another video instead of comparing only lengths.
- Unit tests cover the list picker (no player, another video, unknown length, real mismatch), the carried cut on open, the stale
  pending cut, the automatic apply, the ready-Apply dialog and its press after a playback change, a released player for the same
  video, and `UtubotCutAction.isAvailable`. Docs: `ai/APP_INTEGRATION.md` (player button, ids row, behaviour), `docs/development.md` ("Checking the director's cuts").
- Emulator walk (mock backend, 2026-11-23): the harness requested cut skipped 60 -> 108 s (`2 skips, keeps 2:36`); a ready cut at the open
  showed the Apply offer, which applied on one press; with "apply ready cuts automatically" on it applied without a dialog; a cut built for
  200 s on the 240 s video showed the different-length toast and stayed off. The app's list picker and the player button cannot be driven
  there: the mock has no browse content and the app's screens play YouTube videos only (docs/development.md notes the device pass).

## 2026-11-21 (director's cuts checkpoint 4 review round 1; live modelgate STT limit)

- EVR-520 blocking item fixed: a failed service-worker registration no longer strands the Cuts
  queue. `serviceWorker.ready` never settles when registration fails, so `takeSharedItem()` now
  races it with a timeout that starts first (1.5 s), and the tab starts `load()` and its 3 s
  poller before taking the shared link. Chrome with site data blocked, Firefox private windows
  and a proxy that does not pass `/sw.js` therefore keep the queue; the old code left the tab
  blank. The browser check is 69 checks (was 67): a `/sw.js`-404 context asserts the queue
  still lists its cards; the code at c5b6b44b fails both new checks with 0 cards.
- The Share target needs HTTPS and an installed app (Chrome builds a WebAPK only from an
  installed PWA); docs/server.md says so. The manifest now carries 192 px and 512 px PNG icons
  rendered from `icon.svg` beside the SVG one (Chrome's install is unreliable with an SVG-only
  manifest and no real WebAPK means no Share sheet entry).
- The mic's `dataavailable` handler now checks the attempt: an abandoned recorder's last chunk
  cannot join the new recording's upload when the owner taps Speak again after a cancel.
- `save_set` refuses the reserved `cut-presets` id unless the cut store writes it, so an import
  or `PUT /v1/prompts/sets/cut-presets` cannot silently drop the owner's saved presets.
- `tests/webui_demo.py` honours the optional `PORT` argument (`APP_PORT`, LLM port = port + 1)
  instead of always binding 8791, so a reviewer can run it beside another demo.
- Live modelgate STT (EVR-464) refuses a chunk over about 55 s (upstream 500 "Engine not
  started"; EVR-524). `[speech] max_record_s` defaults to 50 now (also the sheet's fallback), so
  one recording stays under it; a longer description is spoken in several taps and the answers
  append to the box. docs/server.md, config.example.toml and the CONTRACT say the limit and why.

## 2026-11-21 (director's cuts: saved presets, TV parts, Share target, checkpoint 4)

- The cut sheet saves a description as the owner's own preset: a name field and "Save as preset"
  write the user's `cut-presets` prompt set (`POST /v1/cut-presets`), so it becomes a chip on
  later sheets and a row of the TV picker. The Cuts tab lists saved presets with Delete
  (`GET`/`DELETE /v1/cut-presets`); the same name and description replace the earlier copy, and
  the set never shows in the summary prompt pickers. A built cut carries the saved label.
- A ready cut now shows its kept parts on the TV too: under each ready preset the picker lists a
  read-only "Kept parts" category (one line per part, "2:10 - 3:05  The demo", with the summary
  above them), so the owner can judge a cut before applying it (`UtubotMenu.partsCategory`,
  `UtubotCutController.formatPart`).
- The phone web UI is a PWA and takes Android's YouTube Share button: `/manifest.webmanifest`
  declares `/shared`, `/sw.js` keeps the newest shared link in the Cache API and redirects to the
  Cuts tab, and the page takes it once and starts a waiting request for that video's sheet. The
  manifest and the worker are public static files; CSP gained `manifest-src 'self'`.
- EVR-514's follow-ups are closed: the check's nonce is five base36 digits (every millisecond
  differs) instead of ten values; the mic keeps an `uploading` gate and a per-attempt counter, so
  a cancel during an upload cannot re-enable Speak for a second stream and a late `stop` event
  from the abandoned recording cannot upload or wipe the new one.
- The site's `Permissions-Policy` now allows the microphone for its own origin
  (`microphone=(self)`); camera and geolocation stay off. The old `microphone=()` would have
  refused a real phone's Speak tap (the browser check's fake stream hides that on a desktop).

## 2026-11-21 (director's cuts on the TV, second review round)

- An engine release no longer ends the follower of the video that stays: the HQ dialog's format change, the fixer's restart and the
  Home round trip release and initialize the engine and load the same video with no `onNewVideo`. `UtubotCutController.onEngineReleased`
  now only stops the skipper and the poll; the follower stays (`onFinish` ends it), so a request waiting or building through the
  restart is still followed, and the menu's next request is followed too (the follower keeps its video id). A new controller test
  covers both (the follower is injected into `UtubotManager`; the release path fetches a request that the old code dropped).
- A reload of the same video re-arms a cut that was still waiting for the video length: `onNewVideo` remembers `mCut` or `mPendingCut`
  before `stopSkipping` clears them, and only then wipes or re-arms.
- Known for the real-device pass (u-tubot#1): chapter markers still write straight to the seek bar
  (`SuggestionsController.addChapterMarkersIfNeeded`), so on a chaptered video the order of the `onMetadata` calls may hide the cut's
  dims (or replace the chapters); the sponsor colours race with chapters upstream too. Route them through `UtubotCutSeekBar` or check
  the order on the device.

## 2026-11-21 (director's cuts voice, checkpoint 3)

- The phone cut sheet gains a Speak/Stop mic (`MediaRecorder`, opus/webm first, mp4/aac fallback)
  and its recording goes to `POST /v1/speech`. The backend posts the audio to modelgate
  `/v1/audio/transcriptions` with `[speech] alias` (EVR-464) and returns only the text; nothing is
  stored, and the log has client, alias, bytes and duration, never the content. The text lands in
  the description box and stays editable: it is not sent automatically, and Build is still a tap.
- The upload has its own cap (`[speech] max_upload_bytes`, 4 MiB) through a per-path body-limit
  override, while the global `security.max_body_bytes` (256 KiB) stays for every other route. A
  per-user rate limit (`[speech] per_user_per_min`) stops retry loops; busy/timeouts answer plain
  "Speech service is busy, try again or type it." The sheet reads the recording limit
  (`[speech] max_record_s`) from `GET /v1/me`; the mic stops itself at that length.
- The webui check stubs `getUserMedia`/`MediaRecorder` with a fake webm blob and walks Speak → Stop
  through the real route; it asserts the text is in the box, focused, editable and not sent
  (the request is still waiting).
- Opus's merge note from EVR-509 is folded in: `onEngineReleased` keeps a ready `mPendingCut` that
  is still waiting for the video length, and `onEngineInitialized` restarts its poll (the same
  rearm as `onNewVideo`).

## 2026-11-20 (director's cuts on the TV, checkpoint 2)

- The video menu gains "Director's cut…": the picker of the cut presets with their state (ready shows "kept of total", again = off),
  a build request for a `none` preset, and "Describe on phone…" — a waiting request whose short address (`<backend>/cuts/<id>`) shows
  as a QR sheet (`UtubotCutQrView`) over the playing video, made on the device; Back takes it away, the video is not paused. The
  modern video-menu dialog cannot render QR categories (only the settings dialogs can), which is why the sheet is its own view.
- While playing (`UtubotCutController`, next to `SponsorBlockController` in `PlaybackPresenter`, gated by `isBuiltIn()`): when a video
  opens, `UtubotCutFollower` checks its cuts once (a ready cut is announced) and long-polls a waiting or building request (10 s polls,
  30 min cap, 5 errors) until it is ready, then the cut applies from the current position. A cut of another video length (±2 s) is not
  applied. Skips run through `UtubotCutSkipper`: only a crossing the playback made by itself skips (a seek of the user wins and
  plays), and the jump extends past sponsor segments set to skip that overlap or touch the destination (`SponsorBlockController.
  getActiveSegments()`), so the sponsor block's watcher finds nothing to jump at where the cut lands — one jump, not two. Every skip
  shows a transparent "Skipped 1:20" dialog with a Back for 5 s. The skipped parts are dimmed on the seek bar: the sponsor block's
  writes go through `UtubotCutSeekBar` now (its reset keeps a cut of the same video, its own markers are laid next to the cut's;
  without a cut it behaves exactly as before).
- The emulator check runs the real controllers against the mock backend's new cuts routes (`CutsHarnessActivity`; the mock's builds are
  ready after `--cuts-delay`, `/__mock/cuts` sets a ready cut, the cut document skips 25–45 % and 70–85 % of the video).
  Unit tests: `UtubotCutSkipperTest`, `UtubotCutFollowerTest`, `UtubotCutSeekBarTest`, `UtubotCutsParserTest`, `UtubotCutsClientTest`.

## 2026-11-13 (tests and agents never hit YouTube, issue 35)

- Owner rule made enforceable end to end (backend work, see `ai-backend/DEVLOG.md`): recorded/replayed YouTube fixtures
  (`ai-backend/fixtures/youtube/`, sanitized cassettes; `utubot youtube-record` records, owner only), an offline dev-proxy mode for the
  real backend (`[youtube] offline = true` — emulator and `UtubotBackendE2eTest` runs against it touch no YouTube server), and a
  DNS-level network guard in the pytest suite (yt-dlp, httpx and resolver refusal, autouse). Docs: `docs/development.md` ("Offline mode"),
  root and backend `AGENTS.md` (real YouTube access only through production), `ai/CONTRACT.md` (`reason: "offline"`), `config.example.toml`.

## 2026-11-13 (HQ captions did not show, issue 31)

- Report from a real TV (Android TV 14, Modern skin): the job finished, the TV fetched `/captions` and `/captions/tr.vtt` (200, 48 KB)
  and nothing appeared. Root cause (found in the player's log, track selection and the order of events): `ExoPlayerController` selected
  the HQ track when the tracks appeared, which also starts the download of the file, and about 1.5 s later `VideoStateController.onMetadata`
  ran `restoreSubtitleFormat()`: the subtitle choice saved in the settings ("no subtitles" by default) was applied again, which cleared
  the selection override ("Something went wrong. Selected track not found for renderer=2") and every later selection pass found no match.
  Not the cause: the MIME type, the numbered cues (the file parses), the language, the renderer, the style.
- Fix: `UtubotCaptions.mayRestoreSavedChoice` (what is selected is the HQ track of this video: the saved choice is not applied;
  the track of another video or any other track gives way as before). `UtubotCaptionsRestoreTest` runs the real `VideoStateController`
  and fails without the guard. Also: the HQ track is picked by id (`TrackSelectorManager.findBestMatch`; YouTube's track in the same
  language comes first in the list and won the match by language, and `selectFormat` took the two for the same pick), the CC button
  follows a track the app picked (`PlayerUIController.onTrackSelected`), and the subtitle tracks are read again after the tracks changed.
- Live: `UtubotCaptionsFollower` (on `UtubotScheduler`) asks for the captions of the playing video, polls a queued or running job every
  10 s (at most 2 h, 5 errors) and tells the player when they are ready; the player opens the source again with the track (`prepare(source,
  false, false)`, the position is kept, about 1-4 s of rebuffering), selects it (asked-for captions always, late ones by the setting)
  and toasts "u·tubot captions ready" only for a job that finished while playing. `Prepare HQ captions` tells the follower for the video
  that plays.
- Persistence: `UtubotCaptionStore` keeps the downloaded VTT under `files/utubot_captions/<video id>/<lang>.vtt` (+ `index.json` with the
  labels; the files are the truth, a lost index costs the labels). Only WebVTT of at most 4 MiB is stored, written beside the file and
  renamed, never replaced, never deleted, and a change of backend does not touch it. `UtubotCaptions.attach` merges stored tracks even
  without a backend; the backend's own answer is only used for tracks not stored yet. Unit tests: `UtubotCaptionStoreTest`,
  `UtubotCaptionsOfflineTest` (a restart, the backend gone, a change of backend, a failed download retried).
- Verification never touches YouTube (owner rule): the first runs on the emulator did play a real video (before the rule reached
  this work; their screenshots were dropped); everything kept was redone with a debug-only harness, `CaptionsHarnessActivity`, that
  plays a generated local MP4 through the real `ExoPlayerController` and `TrackSelectorManager`, with the mock backend serving the real
  `tr.vtt`, in a network namespace with no route out (`docs/development.md`, "Checking the HQ captions"). Checked: a job that finishes
  while playing (toast, track listed and selected, cues, position kept), the captions from the store with the backend off after a
  restart, auto-select off (offered, not selected), picking "Subtitles disabled" and the track again. Screenshots: `docs/screenshots/captions/`.
  The harness does not run the app's screens, so the saved-choice clash itself is covered by the unit test, not by the emulator.

## 2026-11-12 (server messages in the app, issue 25)

- The server's words win: `UtubotStateText.noCaptionsShort` (the passive panel) used the local "press Info to transcribe" whenever
  `can_transcribe` was true and ignored `message`, so the "Captions are temporarily unavailable..." text of the caption-limited
  answer never showed. Panel, Summary view and AI answer now show `message` and use the local strings only without one.
- Transcribing shows the estimate next to the percentage ("Transcribing… 40% (~4 min)"); a delayed answer shows the server's `error`
  and a one-second countdown to the next request (`UtubotCountdown` on the existing `UtubotScheduler`, `State.retryInSec`; the old
  single timer is the countdown's last tick). The Summary view's focus is not pulled to Retry on every tick (it moves only when the
  phase changes).
- `UtubotAnswerModel` (the AI answer) now waits like the Summary view: retries a delayed request after its time and follows a running
  transcription with `GET /transcript` (4 s) until the answer can be asked for. Before, an auto-started job left it on a stale
  "Transcribing…" until Retry.
- `duration_s`, `title` and `channel`: `insight`, `summary` and `transcribe` all send them (`UtubotClient.addMeta`, tested for each).
  The gap found: `Video.from(Video)` copies the media item and the badge but not the duration field, so a copied card could send no
  length; `UtubotMeta.durationSec` now falls back to the media item. `GET /transcript` takes the same optional fields only as a hint
  for its estimate and the app re-asks the summary (with metadata) after it, so it sends none. The app has no `ask` call.
- Settings tile icon: `settings_utubot.png` (302x302 RGBA, white on transparent) replaces `settings_aislist` for the u·tubot entry
  (Content filtering keeps the crossed-out "AI"). `assets/brand/render.py` renders it from `utubot-symbol-mono.svg`: the tile is
  dropped, white and the light dot stay, the grey u and ring become holes (read from the render's luminance, so antialiased edges are
  exact), then it is fitted into the canvas and padding measured from `settings_about.png`. `UtubotBrandingTest` checks the tile, the
  canvas, the padding and that every visible pixel is white.
- Checked on the emulator (Modern skin, mock backend, real cards): the panel with the server's caption-limited message, with an auto-started
  "Transcribing… 40% (~4 min)", with the server's delayed error and a live "Retrying in 39 s"; the u·tubot tile in Settings; the panel
  requests carry `title`, `channel` and `duration_s` (`/summary?wait_ms=20000&prompt=panel&title=Gabriela&channel=KATSEYE&duration_s=198`).
  `scripts/emulator_mock_backend.py` got `message`, `estimate`, `retry_after`, `progress` and the mode `auto_transcribe` for this.
  Screenshots: `docs/screenshots/r2/`.

## 2026-11-12 (own identity)

- New symbol: a play triangle holding a lowercase u, the interpunct a lime ball on its tip (an indigo ring cuts it off the white tip), on an
  indigo rounded square: three flat colors, no fonts, nothing near YouTube's red. Refined from the first draft with a larger, bolder u (the
  margin to the triangle's edges is measured, not guessed) and checked at 48 to 160 px on dark and light backgrounds. SVG sources, wordmark
  and banner in `assets/brand/`; `uv run assets/brand/render.py` (cairosvg pinned) renders the `stutubot` PNGs (icon, alternative icon,
  banner, the grey/red/default header logos) and the previews, and stops when the banner no longer repeats the symbol and wordmark markup.
  The `-v30` icon variant is gone: the same PNG serves every API level.
- Release notes (Settings, Updates) read this repository's releases (`api.github.com/repos/evrenesat/u-tubot/releases`) and list only the
  tags starting `utubot-v` (`release_notes_tag_prefix`, `GitHubReleases.parse(json, tagPrefix)`), newest first, the installed version bold
  with "(installed)". When GitHub can't be reached the changelog of the backend's `update.json` stands in (`fallbackToUpdateChannel`, not
  cached). It is the only release-notes view: the short About has none. Tests: `GitHubReleasesTest` (filter, order, drafts, installed),
  `GitHubReleasesLoadTest` (the tag filter over HTTP, GitHub's errors, the fallback and its own failure).
- About (short, the flavor's): Server (the backend address and a QR code of it, or "Not set up" which opens the setup), Feedback (issues),
  Releases, Git repository, all of this repository; no Donation; one credit "Based on Electric Eel and SmartTube" that opens QR codes of both
  repositories. `UtubotAboutTest` drives the dialog (rows, the address each QR code holds); `UtubotBrandingTest` checks every address and
  array of the flavor and the name.
- Settings, Debugging (Submit data to Electric Eel's server) is hidden in the flavor and `DataSubmitter.autoSubmit` does nothing without a server;
  the Danish and Finnish strings that said "Electric Eel" and the Android TV search label (default and Turkish) say u·tubot.
- README header with the symbol and a permanent disclaimer; `AGENTS.md` and `docs/development.md` say `main` is the default branch and
  work lands by pull request (`master` mirrors Electric Eel).
- Still upstream-named, on purpose or out of scope: the credit row and README credits; the "electriceel-storage" server protocol of
  Settings, System, Storage sync; the `SmartTubeBackup` backup folder name; internal package names and the `org.smarttube` search authority.
- Screenshots (Modern skin, emulator): `docs/screenshots/branding/`.

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
