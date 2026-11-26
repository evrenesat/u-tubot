## 2026-11-26 (error ledger review pass, issue #206)

- Rebased onto main (db schema and the `Deps` wiring kept both sides). Fixed: the admin page's counts table crashed on an undefined
  variable; per-day buckets are UTC (`_day` used local time); numeric patterns (403, 410, 429, 401) need word boundaries; one shared
  `LedgerService` instead of two. The admin page and `GET /v1/admin/ledger` show the `youtube_forbidden` usage metric (#226) per day beside
  the ledger instead of duplicating it. The TV (`UtubotClient`) and the extension (`createClient`) report their own transport/5xx failures
  to `POST /v1/ledger`, throttled. Migration: `failures` is `CREATE TABLE IF NOT EXISTS` (test opens an old DB).

## 2026-11-26 (a refused download retries, then asks the TV for captions, issue #205)

- A 403 from yt-dlp (audio download and metadata extract) is retried with the next `[youtube] player_clients` entry (default `web`, `android`)
  after `forbidden_backoff_s`; only after the last one is the failure classified (breaker opened once).
- A cut whose transcript job failed with a refused download waits up to `[cuts] client_captions_wait_s` (120 s) for the TV's captions
  (`/captions/client`) with the request in `needs_transcript` and error "YouTube refused the server; using the TV's captions…", then builds
  or fails. The TV's cut picker shows that message. The `youtube_forbidden` usage metric counts refusals per day.
- Migration: none (the metric is a row in the existing `usage_daily`). Tests: `test_youtube_retry.py`, three in `test_cuts_api.py`.

## 2026-11-26 (UTB-223 the "skim the film" cut, a fraction target)

- New built-in cut preset `cut-skim-film` ("Skim the film"): it keeps the story beat by beat — the scene's best moments, in order,
  no cut mid-shot or mid-sentence — to about half the film's length, inferred from the scenes themselves. It has no description (the
  preset infers the story), and it runs in either mode: `quick` from the timed transcript, or `watched` when the viewer picks it for
  the vision pass. It is offered like the other built-in presets (`GET /v1/videos/{id}/cuts`).
- Fraction target: a built-in preset can target a fraction of the video instead of a fixed length (`[cuts] preset_target_frac`,
  `0 < f < 1`, validated). Its target is `duration_s * f`, applied after `preset_target_s` and only when the video is long enough to
  fall outside the band, so `target_s` in the cut document is the effective fraction target. `cut-skim-film` defaults to `0.5`.
- Film-length handling: the film preset is a film-length cut, so for a film too long for one request the map/reduce path limits it to
  `[cuts] map_max_keep_frac` of the video (the model still picks), and it builds from any timed transcript — auto captions, an ASR
  transcript when the film has poor or no captions, or the download.
- Docs: `ai/CONTRACT.md` (Director's cuts addendum: the fraction target and the film preset), `CHANGELOG.md` (Unreleased), and
  `config.example.toml` (documents `preset_target_frac`).
- Tests: `tests/test_cuts_skim_film.py` (the preset, its scene instruction, the fraction target, validation of the fraction range,
  a build to half the film's length, and a build from an ASR transcript). Updated `test_cuts.py`, `test_cuts_api.py`, `test_glance.py`
  to list the new preset. Full suite green (the two `test_watch_*` collection errors and the pre-existing `watched`-extra assertion
  are unrelated to this change).

## 2026-11-26 (voice control checkpoint 1: consent, history, contract; issues #188, #181)

- `[voice] enabled` (default `false`, `VoiceConfig`): with it off the voice routes answer 404, `/v1/me` only gains `features.voice = false`,
  `/setup.json` and the device list are unchanged and the web UI shows no voice page. Replayed in `test_voice_api.py`
  (`test_old_clients_see_nothing_new_while_voice_is_off`).
- `voice.py` (`VoiceService`, `install_voice_routes`): `GET|PUT /v1/me/voice` (retention, all-off, overview with the server's consent text),
  `PUT /v1/me/devices/{id}/voice` (a switch-on needs `consent_version`), `POST|GET|DELETE /v1/voice/commands[/{id}]` (text, tool, args,
  outcome, marks; never audio; rate limited; `403` for a paired device that has not switched voice on). `/v1/me` gains `device` and `voice`
  and `/setup.json` gains `realtime_url` only when voice is on. Revoking a device deletes its consent row.
- Retention: `retention_days` per user (default 30, 0 keeps nothing); expired rows are pruned on write, on read and when the number
  shrinks. The scheduled sweep and the end-to-end all-off audit are checkpoint 11.
- Migration: three `CREATE IF NOT EXISTS` tables (`device_voice`, `user_voice`, `voice_commands`), no column added to an existing table, so
  the live database opens with all data intact and a rollback needs no database step; `test_a_database_from_before_voice_opens_...` builds
  the previous schema with data, opens it and checks the data and the previous INSERTs.
- Web UI: TVs page "Voice control" card (switch per device with consent text, spoken replies, hands-free, retention, all-off) and a "Voice"
  page (history, delete one or all), both only when `features.voice`. Demo seeds voice data; screenshots at 1440 and 390 px checked.
- Mock backend (`scripts/emulator_mock_backend.py`): `/__mock/voice?enabled=1` and the same routes (test in `test_emulator_mock.py`).
- Contract section "Voice control", parity row `voice-control`, the "Clients" exception, `docs/server.md`. No TV code.
## 2026-11-26 (UTB-240 watched store test failed on machines without the `watched` extra)

- `test_cuts_api.py::TestChannelModes::test_watched_cannot_be_stored_while_it_is_not_configured` failed on machines without the
  `watched` extra (no Pillow): `watched_available` checks the installed dependencies before the config, so the error was
  "not installed" instead of "not configured" (CI installs `--extra watched`, so it passed there).
- Fix: the test now monkeypatches `utubot.watch.watched_not_configured` (same pattern as the adjacent
  `test_a_channel_watched_default_downgrades_when_unavailable`), so it exercises the 409 refusal in any environment.
- Verified: `test_cuts_api.py` without the extra (72 passed) and the full suite with `uv sync --frozen --extra watched`
  (1478 passed); `ruff check` and `ruff format --check` clean.

## 2026-11-26 (UTB-160 one cache, every artifact reused incl. ASR)

- Issue 147: the ASR cache now serves every feature from one run instead of recognising again for the next need. A `transcript` job
  runs speech recognition with word times (the strongest answer), so a later "Prepare HQ captions" reuses that one run rather than
  recognising again. The cache key is `v{VERSION}:{audio_sha}:{separation}:{langclass}` (`langclass` = requested language or `auto`);
  `want_words` is no longer part of it, so a segments-only ask and a words ask share a row.
- The result is stored under the language the audio was recognised in (`result.language`), not the requested one, so a language-detected
  transcript answers a later ask for that language; an automatic ask (no language) scans every cached answer for the audio and reuses the
  strongest valid one (words preferred, real/mixed preferred). Wordless/interpolated results are no longer stored with a `:wm-` suffix;
  they are reused only when the feature needs times (`chain_gives_words`).
- The stored payload carries a `job` provenance field, so a reused run reports `reused_from_job` (the originating transcript/cut job) and
  `saved_s` (estimate of recognition seconds avoided). `score.py`'s `cached_engine_words` query matches the new key format.
- Tests: `test_caption_source.py` (transcript then HQ captions = one ASR call, `reused_from_job` set), `test_cuts_api.py` (cut then HQ
  captions reuse), `test_cuts_watched.py` (a second watched build reuses the archived video + grids, describing cached); existing
  `test_job_report.py` `StubAsr` now returns words, `test_asr_recheck.py` pins `ASR_CACHE_VERSION == 5`. Full suite green.
- Data migration: `Database._migrate_asr_cache_v4` copies every `v4:` ASR row to its `v5:` key (strongest answer per audio/variant/language wins, old rows kept, never overwrites a v5 row, idempotent), so existing transcripts and cuts keep their recognition; test in `test_caption_source.py`.
- Contract: `ai/CONTRACT.md` documents the transcript's word-time run, the shared cache, and the `asr` stage `cached`/`reused_from_job`/`saved_s`.

## 2026-11-26 (readable changelog)

- `releasenotes.py`: one allow/deny table turns PR titles into at most 6 short lines per version ("New:", "Fixed:", "Changed:", then
  "+ N smaller fixes"), skipping docs/tests/CI/refactors/plans/devlog/parity/contract/dependency changes; backend deploys with
  nothing visible say "Maintenance only". `scripts/utubot_release.py` loads the same module for app release notes and has an optional
  `rewrite-notes --repo R [--apply]` for existing release bodies.
- `utubot changelog rebuild` (also run at start) rewrites stored entries in the short form; idempotent. `[llm.changelog]` (optional
  task, e.g. the `fast` alias) may reword a new deploy entry within a 2 s budget; any error keeps the deterministic lines.

- Review fix: `feature_calls` telemetry is swept once a day on record (it was never swept); the new tables are `CREATE IF NOT EXISTS`, so an existing DB opens with its transcripts and cuts untouched (test in `test_feature.py`).

## 2026-11-26 (backend version monotonic on shallow clones, issue #191)

- Backend version is `0.<series>.<HEAD commit time UTC YYYYMMDDHHMM>+<sha>` instead of the commit count, which a shallow clone
  undercounted (could go backwards between deploys). Same value for shallow and full clones; package-version fallback unchanged.

## 2026-11-26 (version histories, issue #175)

- Real backend version `0.<series>.<commit count>+<sha>` from the checkout's git (`buildinfo.py`), in `/v1/health` and `/v1/me`.
- `changelog` table (additive): a deploy entry at start when the running commit is new (merged subjects since the previous one,
  grouped New/Fixed), app release notes and times from `sync-github`; `GET /v1/changelog?kind=app|backend`; web UI Updates lists.

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
## 2026-11-26 (per-channel cut mode, port of #118)

- A new cut resolves its mode as request, owner's channel default, owner's `cuts.cut_mode`, then `[cuts] default_mode`
  (`CutService.resolve_mode_rule`); cut requests keep `mode_rule` and `channel_id`, the picker answer adds `mode_rule`,
  `channel_id`, `channel_name`, `channel_mode`. Defaults live in `cut_channel_modes(user, channel_id)`; `GET|PUT|DELETE
  /v1/cut-channels[/{id}]`. A default `watched` while unavailable runs quick and still reports its rule; storing `watched` then
  answers 409. `channel_id` rides as a query param on the cut read, create and fill routes.
- TV: the cut sheet sends the channel id and offers "Always use <mode> for this channel" / "Follow your default". Web UI: a
  "Channel defaults" card on the Cuts tab. Ported from the closed #118 onto main's mode plumbing; the request-time snapshot columns
   (`channel_mode`, `user_mode`, `server_mode`) of that PR were not ported.

## 2026-11-26 (per-feature model aliases, issue 148)

- Admin chooses the modelgate alias each feature runs on. `GET /v1/admin/features` returns every feature row plus the alias list
  the switch is validated against; `PUT /v1/admin/features/{feature} {"alias"}` points one feature at an alias (refused with `400`
  for an unknown feature, an empty alias, or an alias not in the list, nothing applied); `DELETE /v1/admin/features/{feature}`
  drops the override back to the `config.toml` default (`404` when there is none). The choice is server-wide, stored in a
  `feature_models` row, effective on the next call (no restart), and logged in `feature_audit`.
- Model resolution is explicit model (per-user `models` or a prompt `model`) first, else the admin override, else the
  `[llm.<task>]` default: the override only replaces the default, so a call that names a model routes as before. `feature.py`
  carries the `FeatureStore` (override/current/fallback, audit, the known-alias list) and `FeatureUsage` (per-call telemetry,
  last-7-days calls/tokens/cost and median/p90 time).
- Cost is estimated, not billed: `(prompt+completion tokens) * price_usd_per_million[alias] / 1e6`, null when the alias has no
  price (`[usage] price_usd_per_million`, `window_days` default 7, `keep_days` retention). Every model call records its feature,
  alias, wall time and tokens in `feature_calls`.
- Per-feature runs expose their cost and wall time on the result: insight, summary, ask and cut answers gain `cost_usd` and
  `elapsed_s` via the `feature_run()` context manager around each call.
- Schema is additive: `feature_models(feature PK, alias, changed_at, changed_by)`, `feature_calls(id PK AUTOINCREMENT, feature,
  alias, ts, elapsed_ms, prompt_tokens, completion_tokens, cost)` + `feature_calls_feature` index, `feature_audit(id PK
  AUTOINCREMENT, feature, from_alias, to_alias, changed_by, at)` (both alias columns nullable: a fresh override has no `from`, a
  reset has no `to`).
- Tests: `tests/test_feature.py` (page lists features and the mock aliases; setting an alias routes the next call to it; unknown
  and empty aliases are refused and leave the default; reset returns to default and a second reset is `404`; responses carry
  `cost_usd`/`elapsed_s`; cost is recorded and unknown without a price; `cost_for`, `median_p90`, `FeatureUsage`, `feature_run`,
  override/current-alias). No test reaches YouTube or a real model. `ai/CONTRACT.md` documents the routes and schema.
- Web UI: `web/ui/js/pages/admin.js` gains a Features page (`#/admin/features`, linked from the users page) — one card per
  feature showing the alias in force, an "overridden" pill, the select validated against the returned alias list, a Reset to
  default button, the audit history and the cost/time tiles. The demo (`tests/webui_demo.py`) seeds an `analysis` override on
  `smart` plus a week of `feature_calls` so the page renders populated. `tests/test_webui.py` also covers the three routes as
   admin-only.

## 2026-11-26 (client caption upload, issue 149)

- `POST /v1/videos/{id}/captions/client` takes the tracks a client already has (json3, srv3, vtt; at most 10 of 2 MiB, configurable),
  picks one like the server's own fetch does and stores it in `transcripts` with the new nullable `origin = client` column. An
  automatic upload never replaces a fresh manual copy or an ASR transcript; real captions clear the no-captions and failure holds and
  end the wait of a fetch sitting in the gate (`TranscriptService._await_fetch`), so cuts and summaries pick it up at once. The
  server's fetch path already prefers a fresh stored copy, and a queued fetch stands down when a client copy lands. New srv3 parser.
- TV: `UtubotClientCaptions` uploads the original-language and user-language tracks once per video per session. The extension has no
  caption track to send yet (`ai/CONTRACT.md`, Clients).

## 2026-11-24 (UTB-25 watched cuts, backend checkpoints 1-4)

1. **Modes.** `[cuts] default_mode` / `UserPolicy.cut_mode` (per-user `cuts.cut_mode`, read-only on the TV, changed in the web
   UI), optional `mode` on POST/PUT cut routes, mode-aware cache keys and duplicate requests. `GET /v1/videos/{id}/cuts` gains
   `default_mode` and `modes[{id,label,default,available,reason,eta_s}]`, each preset gains `by_mode`; the top-level preset state
   stays the caller's default mode. Request rows carry `mode`, `progress`, `eta_s` and a Watched-only `fallback` (the same preset's
   Quick state); stages add `video`, `grids`, `describing`, `in_line`; cut documents carry `mode` and
   `watched{grids,model,partial,coarse}`. `GET /v1/me` features adds `cuts_watched`.
2. **Video/grids.** `media import` (`--kind video|audio`) and an archive video entry. `watch/ffmpeg.py` runs blocking ffmpeg with a
   cancel event in one worker thread per build; `watch/video.py` downloads a <=360p copy through `YoutubeGate`, stores it and
   refuses over 90 min/1 GiB and below the free-space floor. `frame_selector.py`/`grids.py` are adapted from r2t4 under MIT:
   low-resolution luma/motion/dhash analysis, hard cuts, adaptive chunks, the quiet-stretch shared grid (which stops at a real hard cut),
   four-frame selection, 2x2 grids <=512 px cells, manifest. `max_grids=240` with four length-raising steps and a final budget split. `video_scenes`
   is keyed by video sha and settings, not the transcript.
3. **Describing/TDT.** `[llm.cuts_vision]`, same-provider fallback validation, Pillow extra `watched`. One sequential request per
   grid through a bounded transcript/carry context; one bad-JSON retry, one halved-context retry on upstream HTTP 400; unseen
   grids stay empty; over 20 % unseen refuses. The slim TDT validator accepts optional `content` labels for #88. Descriptions are
   cached per video sha + model + transcript; partial rows resume; `scene_labels` are written from a stored TDT. Admin
   `GET /v1/admin/videos/{id}/tdt`; archive removal drops watched rows.
4. **Join/editor.** Silent stretches become `(no speech)` units, S lines keep picture evidence, only `#` ids are keepable, scene
   lines collapse same-kind repeats, kept boundaries snap outward <=1 s to a real cut but never across speech. The editor reuses
   the Quick validator/repair/pad/merge/keep-guard rules; the Watched prompt addition forbids keeping S lines. Watched builds run
   once per server (`in_line` for the second), write progress/ETA by the configured weights, and offer Quick on failure. The
   Quick fallback state is resolved without starting a build.
5. Tests: `tests/synth_video.py` (ffmpeg lavfi, 60 s, four hard cuts and a 30 s still stretch), `test_watch_grids.py`, `test_watch_tdt.py`,
   `test_watch_memory.py`, `test_watch_join.py`, `test_cuts_watched.py` (end-to-end mock vision, cache reuse, in-line queue, failure/Quick,
   over-limit before download, unavailable, user default, admin/remove paths), `test_cli_media.py` (offline
   `media import` for video and audio); `mock_openai.py` now accepts image parts and answers the describe format
   incl. bad JSON/400. No test reaches YouTube or a real model; CI installs `--extra watched`.
6. Deviations: the model alias/timings come from the owner's command, not a bake-off; there is no `scripts/grid_bench.py`,
   labelled-set or cutbench watched gate here yet (owner-only, never CI/repo). The client mode switch (TV/web UI/extension) and
   mock backend are not in this backend change. `temp/plan.md` remains the source; `THIRD_PARTY.md` lists the r2t4 copy.

# DEVLOG

## 2026-11-26 (highlights cut of a long video kept only two parts, issue 139)

- Problem: a 5-minute `cut-highlights-5` of a 68-minute video came back as two long blocks instead of the strongest short
  moments spread across the whole video. On a long transcript the cut runs the map/reduce path (#95): each excerpt proposed
  its best stretch and the reduce kept the biggest, and the prompt only asked for "the most interesting minutes", so the model
  proposed a few long blocks rather than many short moments.
- `prompts.py`: the `cut-highlights-5` instruction now asks for many short, distinct moments - the best scene or beat in each
  part of the video, jumped across the start, middle and end, as several separate parts, not a few long blocks. The instruction
  rides into the one-pass, map and reduce calls, so the map proposes granular candidates the reduce can mix and match.
- Tests: `tests/test_cuts_longvideo.py::TestHighlightsSpread` builds a long video of many short highlight bursts spread through
  it (through the map/reduce path) and asserts the cut keeps many short parts (>= 8, each under 45 s) in the first, middle and
  last third; a second case keeps the band when the highlight content exceeds the target.
- The recorded cutbench scores (`fixtures/cuts-scores-2026-11-20.json`, `fixtures/cuts/CHOICE-2026-11-20.md`) cover the short
  set only and carry no highlights request, so they are unchanged; a real 68-minute video's cut is regenerated on the owner's
  server by re-running the preset, never from an agent.
- Verified: `uv run ruff check`, `uv run ruff format --check`, `uv run pytest -q` (1287 passed, the two `test_watch_*`
  collection errors are a pre-existing missing `Pillow` optional extra, unrelated to this change).

## 2026-11-25 (long videos: no-target cuts keep almost everything, issue 125)

- Problem: a long video goes through map/reduce; with a preset that has no target length (`cut-demo`, a saved
  preset) each excerpt proposed all of itself and the reduce kept every candidate, so the cut kept ~99 % and the
  upper keep guard did not apply to named presets.
- `cuts.py`: the map note now asks each excerpt to apply the task locally, not to propose every part that fits. A
  no-target map/reduce build has a hard maximum, `[cuts] map_max_keep_frac` (default 0.90): each excerpt is trimmed
  to its share and the final choice is trimmed at unit boundaries, keeping the highest-ranked parts. A target cut is
  unchanged. Every `map` event now records the excerpt's kept/removed seconds and part count; the `reduce` event
  records kept seconds and the target or cap.
- Repair: `cuts.algo_version` (additive, default 0) remembers the build algorithm. `CutService.start()` (unless
  `repair_on_start` is false) and `utubot cuts repair [--dry-run]` find older cuts on the map/reduce path with no
  target that kept over `repair_near_full_frac` (0.90), supersede their requests and rows, and queue the same user,
  video and preset or prompt again. A rebuilt cut carries the current version, so it is not repaired twice.
- Tests: `test_cuts_longvideo.py` (100-minute fixture, over-inclusive model, preset and typed prompt stay under 95 %,
  configurable cap, per-excerpt log), `test_cuts.py` (cap trimming), `test_cuts_repair.py` (dry run, targeted/small/
  current cuts left alone, requeue once, orphan cut), `UtubotCutsParserTest` (each ready preset keeps its own length).

## 2026-11-25 (Tailscale Serve sign-in, UTB-105)

- New optional `[auth]` section: `tailscale_identity` (default off) and `tailscale_users` (tailnet login to local user;
  case-insensitive). With it on, a safe request (`GET`, `HEAD`, `OPTIONS`) from a loopback peer carrying
  `Tailscale-User-Login` signs in as the mapped local user and gets the normal session cookie. The raw peer is checked, not
  `X-Forwarded-For`; unmapped logins and unknown local users are refused; writes keep the session CSRF requirement, and a request
  with no session cannot start one through an unsafe method. Password, token, device tokens and the public site are unchanged.
- `GET /v1/auth/session` reports the session created on that request as cookie-backed with its CSRF token, so the page can write
  immediately. Docs and the config example say to enable this only on a tailnet-only listener.
- Tests: `tests/test_tailscale.py` covers the mapped flow and an authenticated write, case-insensitive mapping, unmapped and
  non-loopback peers (including a spoofed forwarded address), the default-off gate, password sign-in beside it, and loopback parsing.
## 2026-11-25 (the viewer's cut choice, issue 103)

- `GET /v1/videos/{id}/cuts` gains `selection` (`chosen` | `last` | `off`, with the ready `cut`): the video opens with the
  viewer's choice for it, else the preset used last when it is ready here, else nothing so the client offers the ready cuts.
- `cut_choices` (per user and video: preset, request, or off) and `cut_last_presets` (per user) are additive tables. Creating a
  preset/prompt request or filling a waiting one records the choice; `PUT /v1/videos/{id}/cut-choice` records a pick or off.
  Dismissing a request clears it when it was the choice. `CutService.choose`/`_selection` hold the rules.
- Tests: `tests/test_cuts_api.py::TestCutChoice` for chosen cut wins, last-used preset, no ready cut for the last preset, several
  ready cuts in any order, a typed cut, off and bad bodies. Contract, server docs and the TV/extension parity row updated.

## 2026-11-25 (a failed cut does not stick; no-filler accepts a nearly full keep, issue 99)

- Problem: the TV picker ignored a `failed` preset (no new request), and `cut-no-filler` refused a 96-99 % keep
  with "Nothing to cut", so a video with little filler could not use the preset.
- `cuts.py`: `finalize_parts` takes `guard_max` separately from the lower `guard`; a named preset keeps a valid
  near-full result, a typed prompt without a target keeps the upper guard. Guard messages now name the kept length,
  the video length, the percentage and what to try. Removal presets (`cut-no-filler`, `cut-answer`, `cut-demo`)
  put the result in the cut's `summary`: "Removed 1:12 of filler, 2 % of the video"; keeping everything is the
  normal `ready` state "No filler found" (other removal presets say "Nothing was removed").
- `create` already ignored failed rows; tests now pin that a failure does not block a fresh request and that the
  same preset rebuilds after a server limit changes. TV picker: `CutPreset.canRequest()` lets a failed preset start
  a fresh request, and its state text ends in Retry. Web UI already had Retry on failed cards and the sheet.
- Tests: `test_cuts_api.py` (failed then retried, changed limit, 98 % keep message, nothing removed), `test_cuts.py`
  (guard messages, upper guard off while lower stays on).
## 2026-11-24 (R2: per-video artifact cache and non-sticky errors, issue 7)

- Failure policy: a busy model is never remembered (`bg.is_remembered`; `TaskRegistry` skips `LLMBusyError`), other model failures
  for `[summary] failure_cooldown_s` (30 s -> 120 s), a video that cannot be read for `[transcripts] video_failure_ttl_s` (1 h -> 15 min),
  an empty caption track for `empty_track_retry_s` (1 h -> 15 min). "No captions" stays 3 days: it is a complete answer, not an error,
  and re-asking YouTube is what the pacing rules avoid; Retry bypasses it.
- `POST /v1/videos/{id}/retry` (`ArtifactCache.retry`, new `artifacts.py`) clears every remembered failure of a video (fetch holds, "no
  captions", failed summary/insight/answer tasks, failed analysis) and keeps stored successes; `TaskRegistry.forget_video`,
  `TranscriptService.clear_failures`.
- Admin: `GET/DELETE /v1/admin/videos/{id}/artifacts` lists and purges the cached artifacts of one video by kind.
- Media archive: opt-in `[archive] eviction = "lru"` (default `never`, the EVR-154 rule that the archive never deletes by itself still
  holds unless the owner turns it on): least recently used entries go when a download would start at the quota, never an entry used
  within `evict_protect_s` or the file just stored. New nullable column `media_archive.last_used_at`, stamped by `lookup`.
- Summary cache key is unchanged (video, prompt key, content hash, language); the model is already part of the content hash.
## 2026-11-25 (example-config tests off the host data dir)

- Problem: backend CI was red on the captions start-offset branch. The three tests that load
- Problem: backend CI was red on the captions seam-dedupe branch. The three tests that load
  `config.example.toml` used its `data_dir` (`/var/lib/utubot`) and so read the host's `users.toml`,
  which belongs to the service and cannot be read by the test runner.
- `tests/conftest.py`: an `example_config` fixture loads the example with `users_path` pointed at
  `tmp_path/users.toml`, keeping the example's declared users and defaults and touching no host file.
- `test_glance.py`, `test_prompts_summary.py`, `test_security.py`: use the fixture; `test_security`
  also asserts the example's `data_dir` stays and the users path is the temp file.
## 2026-11-25 (forced ASR from the audio and the captions gate, issue 107 r0)

- Default stays YouTube captions. `POST /v1/videos/ID/transcribe?force=true` and `"force": true` on
  `POST /v1/videos/ID/captions` skip the caption recheck (`caption_recheck` says `skipped` / `forced`) and build from the audio even when
  captions exist. A forced transcript replaces a stored caption transcript (`TranscriptService.store_asr(replace=...)`); an ASR
  transcript already stored is still `ready`, and a queued job is promoted (`jobs.force_job`) instead of adding a second one.
- `jobs.force` (additive column, default 0) keeps the request on the job, so a retry stays forced. A force that arrives while the job is
  already running wins too: the caption and transcript runners re-read it after the recheck and switch to the audio path. The transcript
  endpoint reports `transcribing` while a forced job runs although the old captions are still stored.
- Non-English automatic (ASR) tracks are rebuilt from the audio in their own language (`prefer_asr_non_english`, default true) instead
  of proofreading YouTube's text; manual and English tracks keep the improve path.
- Cuts can force it too: `"force": true` on `POST /v1/videos/ID/cuts` (additive `cut_requests.force`), TV cut sheet toggle, and a forced
  request never joins an unforced one. An existing timed caption transcript is replaced by the ASR one.
- Web UI: "Ignore YouTube captions" switch in *Transcribe a video*; TV: "Transcribe from audio" and the cut sheet's
  "Transcribe with u·tubot" toggle.
- `captions-gate` (offline) compares a candidate `captions-score --json` with YouTube auto captions/a baseline: `hit >= gate_hit_min`
  and `gate_hit_margin` over the baseline, `loose` not below and `>= gate_loose_min`, `words.within_s >= gate_words_within_min`, at most
  `gate_max_short_cues` cues under `gate_short_cue_s`, cue-offset median `<= gate_median_max_s` (0.30 s) and p95 `<= gate_p95_max_s`
  (1.0 s) with neither worse than the baseline, and `meaning` (`--reference-translation`; token F1) `>= gate_meaning_min` (0.5) and
  strictly above the baseline. `--attestation` writes the result even on failure; `gate_required` makes a job refuse to store without a
  current passing attestation. Thresholds are `[captions] gate_*`.
- The Hindi fixture and its recorded reference/meaning evaluation are still owner work: no recorded fixture is checked in here.
- Tests: forced transcript over existing captions, force promotion and mid-run force (`test_captions.py`, `test_transcript_flow.py`),
  non-English ASR rebuild, gate-required storage, cut force (`test_cuts_api.py`), gate pass/fail/median/p95/meaning/attestation
  (`test_caption_gate.py`), meaning (`test_meaning.py`), Android force body (`UtubotCutsClientTest`).

## 2026-11-25 (example-config tests off the host data dir, backend CI red)

- Problem: the three tests that load `config.example.toml` read its `data_dir` (`/var/lib/utubot`) and therefore the host's
  `users.toml`; where that file belongs to the service the tests fail with a permission error (backend CI failure on the
  u-tubot#80 update-notification pull request).
- `tests/conftest.py`: an `example_config` fixture loads the example file with `Config.users_path` pointed at `tmp_path/users.toml`,
  so the declared users and defaults are exactly the example's and no host file is touched.
- `tests/test_glance.py`, `tests/test_prompts_summary.py`, `tests/test_security.py`: use the fixture; `test_security` also asserts
  the fixture keeps `data_dir` from the example and reads no host users file.
## 2026-11-24 (target length review follow-ups, issue 86)

- Problem: `select_for_target` measured padded parts before `finalize_parts`, so merging a gap under
  `merge_gap_s` could push a targeted cut over the band (the long-video test allowed +5 s); changing
  `length_tolerance` or `over_ask_frac` served the old targeted cut from cache.
- `cuts.py`: `select_for_target(..., duration_s=...)` measures the selection with `finalize_parts`
  (`guard=False`) and binary-searches the last part's unit boundary to stay at or under the band; the
  returned parts are still un-finalized, so the caller pads them once. `_ask_parts` passes the video
  duration for one-pass and map/reduce. The cache version now includes `length_tolerance` and
  `over_ask_frac` when a target is set (non-target keys are unchanged).
- `cutbench.py`: the one-pass path passes the transcript duration too.
- Tests: duplicate and out-of-range ranks, adjacent parts finalized into the band, the upper band edge,
  and a cache rebuild when either band setting changes; the long-video `+5 s` allowance is gone.
- `ai/CONTRACT.md`: the band is checked after finalization; the cache version carries both settings.
## 2026-11-24 (partial rolling caption rows)

1. `align.caption_cues` drops a leading run of two or more words from a caption row that repeats
   the end of the previous overlapping row, so YouTube's automatic rolling windows no longer show
   the repeated tail twice. Word comparison ignores case and punctuation; a repeat after a gap is
   kept. Exact duplicate rows are still dropped. Tests in `tests/test_align.py`.
- Verified: `uv run ruff check`, `uv run ruff format --check`, `uv run pytest -q` (1137 passed).

## 2026-11-24 (captions seam dedupe by word time, u-tubot #51)

- `chunking.dedupe_words` now decides a seam repeat by bare token and start time (`DEDUPE_START_S`, 0.3 s) instead of needing two
  identical words in the text sequence, so a single word doubled across a chunk seam is dropped once and a word the chunks time
  differently is not matched by text alone. `dedupe_segments` keeps its two-word rule (segments have no per-word times).
- Tests: a single doubled word at the seam, the same token said at a different time kept, and only one copy of a repeated word dropped.
  `docs/captions.md` (Chunking and stitching) updated.
## 2026-11-24 (sync-github uses conditional requests and backs off, issue 81)

- Problem: the timer asked GitHub for the release list every five minutes, even when it had not changed, and an anonymous rate
  limit logged the same warning on every run.
- `appsync.py`: `SyncState` stored in `app_dir/sync-state.json` keeps the last release list, its ETag and `X-RateLimit-Reset`. The
  listing request sends `If-None-Match`; a `304` reuses the stored list and still fetches only `release.json`, as before. A
  `403`/`429` with `X-RateLimit-Remaining: 0` stores the reset; runs before it exit `75` without a request. `TransientError.notice`
  tells the CLI to print one warning per rate-limit state, and a later successful run says the limit cleared. A `200` that says the
  quota is exhausted is remembered too. Dry runs write nothing, so a dry run never creates the state file.
- Tests: the fake GitHub serves an ETag, answers `304` to a matching `If-None-Match` and records API statuses; covered conditional
  second run, remembered reset and skip, exhausted quota on a successful response, CLI warning once and recovery.
- Docs: `docs/server.md` Updates, `deploy/README.md` and `config.example.toml` name the token as the preferred setup and describe
  conditional requests and the reset backoff.

## 2026-11-24 (frozen engine claim contract, issue 93)

- `tests/test_engine_claim_contract.py` reads `../ai/ENGINE_CLAIM_CONTRACT.md` and `../ai/CUT_MODES_PLAN.md` and fails if a
  config key, endpoint, state, `409` reason or reason sentence is missing, or if the plan link and the D-P11 wording drift.
  The contract is the root `ai/` file of checkpoint P0; no backend code changed.

## 2026-11-24 (captions: no source proofread before translation, reasoning off)

1. A captions job that will translate skips proofreading the source text (`proofread` skipped with reason `translated`);
   the translated text is proofread once, after translation. A translated job used to pay for both passes, and on a
   token-heavy script the source batches could exhaust the answer budget with truncated JSON and add nothing the
   translation kept.
2. `[llm.captions]` defaults to `reasoning_effort = "none"`. Proofreading and translation answer with JSON over many short
   strings; config.example.toml and docs carry the reason.

## 2026-11-24 (cut length for saved presets and typed prompts, issue 100)

- Problem: only built-in presets had a target length, so the owner's saved "half" preset kept 75 % and 82 %.
- `cuts.py`: `parse_length_intent` (English: half, a third, a quarter, N %, N minutes/min, under N minutes, shorter by half; positions such
  as "the first half", "skip the first 5 minutes" and conflicting lengths give None), `length_target_s`, `effective_target_s(..., length)`;
  `CutService.target_for` takes the built-in target, else the saved preset's explicit length, else the parsed text (built-in wording is never
  parsed). One-pass and map/reduce use the target as before; the cache version already carries it, so an earlier untargeted cut rebuilds once.
- `prompts.py` / `app.py` / `models.py`: `Prompt.length_min` / `length_frac` (additive, in the content hash only when set); `POST/GET
  /v1/cut-presets` take and return them.
- Web UI: "Length of the preset" field on the cut sheet (`10 min` or `50%`), saved presets list their length.
- Tests: `tests/test_cuts_length.py`.

## 2026-11-24 (director's cuts: map/reduce for long videos, issue 95)

- Problem: a long video failed with "too long to cut in one pass (no map/reduce yet)": the whole transcript went in one request and
  `[cuts] max_input_tokens` (24000) refused the rest.
- `cuts.py`: the model calls moved into `CutEngine` (no request, job or database knowledge, so `cutbench` drives the same code).
  `CutEngine.pick_parts` goes one pass when `fits`; otherwise `plan_chunks` splits the units into excerpts of at most
  `map_chunk_tokens` (starting on chapter boundaries, chapters packed while they fit, an oversized chapter split evenly,
  `map_overlap_units` shared with the previous excerpt). Each excerpt is asked in parallel (`map_parallel`; the provider limiter still
  caps it) for ranked candidate parts in the #85 answer format, with its share of the target (empty answers allowed), one retry per failed
  excerpt then "Part i of n ... could not be analysed". Candidates of neighbouring excerpts that share units merge.
  The reduce call sees candidates as numbered lines (time range, label, rank inside its excerpt, `reduce_excerpt_chars` of text), answers
  in the same format with `from == to`, and its answer is expanded to one part per candidate over the real units, so
  `select_for_target` (rank selection, trim, band retry) is the one-pass code. Candidates that exceed `max_input_tokens` are narrowed
  in rounds (groups keep their share plus the over-ask; `max_reduce_rounds`). Typed prompts: the map collects, the reduce applies the prompt.
- Cache key and version unchanged (a long cut is as valid as a one-pass cut). Fixed while there: the picker's `_ready_cut` looked up the
  version without the target length, so a ready `cut-highlights-5` of a video over the band never showed as ready.
- `[cuts] max_input_tokens` default 24000 -> 80000 (about 80% of a 100k alias; keep it at that share of the `[llm.cuts]` alias's context);
  new `map_chunk_tokens`, `map_overlap_units`, `map_parallel`, `reduce_excerpt_chars`, `max_reduce_rounds`.
- Progress: stages `map` (events with `done`/`of`) and `reduce`; the request document gains `progress` (additive, `ai/CONTRACT.md`);
  the web UI shows "reading the long video in parts (3 of 9)".
- `cutbench.py`: `LONG_TRANSCRIPT` (3.4 h, two key sections, lowered limits via `cuts_overrides`), `score_all(long_video=True)`,
  `cut_bench.py --long`; `mock_openai` hands cut answers the first user message (a repair round no longer hides the question).
- Tests: `test_cuts_longvideo.py` (3 h fake transcript in the band, overlap, typed prompt, one-pass kept, failed excerpt retried and fatal,
  rounds, rounds exhausted, progress, picker, cache reuse), chunk/candidate units in `test_cuts.py`, long case in `test_cutbench.py`.

## 2026-11-24 (cuts respect the target length, issue 82)

- Problem: `cut-highlights-5` on a 1005 s video kept 681 s; the length was only a wish in the prompt and the guard is off for it.
- `cuts.py`: `[cuts] preset_target_s` (`cut-highlights-5` = 300), `length_tolerance` 0.15, `over_ask_frac` 0.2. With a target the prompt names it
  and asks for a `rank` per part; `select_for_target` takes parts by rank (no rank = video order) until the target, trims the last
  one at a unit boundary to stay under the band, returns video order. Below the band: one retry that names the measured length,
  then a clear error. Typed prompts, saved presets and videos no longer than the band keep the old behaviour. The cache version
  includes the target, so old highlights cuts rebuild.
- Cut document gains `kept_s` and `target_s` (additive, `ai/CONTRACT.md`).
- `cutbench.py`: `BenchRequest.target_s`, `RequestResult.length_err`, `summarize()["mean_length_err"]`; the router fixture has a
  60 s highlights request.
- Tests: ranked selection, trim, old format, retry and failure paths (`test_cuts.py`, `test_cuts_api.py`), length accuracy (`test_cutbench.py`).

## 2026-11-24 (audio stream start offset)

1. The 16 kHz ASR WAV keeps the first audio stream's container `start_time`: a positive offset
   is filled with `adelay` silence, a negative one is trimmed with `atrim`. `ffmpeg` stage detail
   gets `start_offset_s` when it is not zero; the captions-score windows use the same origin for
   their onsets and cached-word comparison.
2. `ASR_CACHE_VERSION = 4`, because older cached answers were made from unpadded audio and would
   shift every cue by the container offset. `audio_start_offset`/`start_offset_filter`/
   `transcode_wav` live in `captions/asr.py`; docs and the affected version assertions are updated.

## 2026-11-24 (processed videos review round 1)

- `tests/test_processed.py`: a dismissed cut stays out — a video with only dismissed requests is absent, and a video with a caption
  plus a dismissed cut lists no cuts; `limit` 0 and 201 answer 400 (the router's validation handler). No code changed.

## 2026-11-23 (processed videos: backend endpoint, GitHub #66 step 1)

- `GET /v1/processed?limit=N` (default 50, at most 200) combines the caller's `jobs` kind
  captions and non-dismissed `cut_requests` read-only, one item per video, newest `updated_at`
  first. Title and thumbnail come from cached metadata with fallbacks, caption states use the
  `GET /v1/jobs` names, cuts carry preset labels, and `summary` is any stored summary for the
  shared video. No new table or storage; dismissed cuts stay out.
- New `processed.py` service wired into `Services`; `tests/test_processed.py` covers empty,
  mixed items (title/thumbnail/state/label/summary/last change), limit counting videos and
  another user's rows staying invisible. Docs in `ai/CONTRACT.md` and `docs/server.md`.
- Verified `uv run pytest -q` 1048 passed and ruff check/format clean. The TV's Processed
  section is a later step.

## 2026-11-21 (director's cuts checkpoint 4 review round 1)

1. `save_set` refuses the reserved `cut-presets` prompt-set id unless `from_cut_store` (the
   sheet's own save/delete paths), so `PUT /v1/prompts/sets/cut-presets` and prompt imports
   answer 400 and cannot silently replace the owner's saved presets. Test added.
2. `[speech] max_record_s` defaults to 50 and the phone's fallback matches: the live modelgate
   route's oMLX whisper returns upstream 500 "Engine not started" over about 55 s (EVR-524), and
   the phone sends one file. A longer description takes several Speak taps; each answer appends.
   config.example.toml and docs/server.md carry the reason; the demo also uses 50.
3. `tests/webui_demo.py` reads the optional PORT argument (`APP_PORT`, LLM port + 1) instead of
   hard-coding 8791.

## 2026-11-21 (subtitle timing checkpoint 3 v2: honest scorer, YouTube word times as a check and for fill cues)

Spec: `temp/sync-design/agent-plan-cp3-v2.md`. Replaces CP3 of `agent-plan.md`; the time warp and audio referee are not built.

1. **Scorer** (commit 1). `normalize_language` strips a YouTube track suffix (`-orig`, `-auto`, `-asr`): `hi-orig` is `hi`, `pt-br` and `zh-hans`
   as before. `captions-score` forces that language on the reference, reports per window `language` and `latin_share`, the document gets
   `spoken_language`, `reference_language_ok` (the CLI prints a warning when false) and a `words` block (cached raw engine words against the
   windows' words: `matched`, `matched_share`, `median_s`, `p10_s`, `p90_s`, `within_s`; `null` without a cached `v3:` row with words).
2. **YouTube word offsets.** `parse_json3_words`, `track_kind_of`, `FetchResult`/`Transcript` `words` and `caption_kind`, additive columns
   `transcripts.words`, `transcripts.caption_kind`. `TranscriptService.get(want_words=True)` treats a captions row with `caption_kind IS NULL` as a
   miss (one gated fetch) and falls back to it on any `YoutubeDelayed` (cooldown included). `improve(ref_words=, caption_kind=)`; `caption_recheck` found carries both.
3. **`ref_check`** (`captions/reference.py`, pure). Block-wise `SequenceMatcher` anchors (or caption-row first tokens), agreement, regions; stage
   `ref_check` ok/warn/skipped (`no_reference|too_few_anchors|other_script`); `captions.timing.ref_check` has `anchors`, `median_s`, `within_s`, `regions`.
   Changes no times. Config `ref_*` (config.py, config.example.toml).
4. **Fill cues from YouTube words** (`align.word_cues`): unheard speech rows (stretches of overlapping rows) become cues built from the reference words
   in the gap, moved by the job's median offset; manual tracks and tags keep the row rule. `align` detail `fill_from_words`; `timing.reference`
   (words) and `timing.fill_from_words`; `real_share` is untouched.
5. **Short cues and credits.** `segment.merge_short` (run by `finish_cues`, `merged_short`); `halluc_credits` dropped in every chunk (`sanity.FLAG_CREDIT`,
   `AsrRouter._drop`); `TIMING_VERSION = 5` (3 stays unused, as CP4 noted). ASR cache version is NOT bumped (see review round 1). The CP1 first-cue gate [4.2, 4.9] is withdrawn (no evidence, see the spec); no `cue_lead_s`.

Deviations from the spec:

- `normalize_language`: only the suffix rule (tail in `TRACK_SUFFIXES`); the "head is a known base code" clause is not needed and would change `zh-hans`.
- `halluc_credits` is its own list; the four lines were not also added to `halluc_phrases` (that list's rate rule would only re-drop them in a rechecked chunk). They are flagged `credit` (not `phantom`) and counted in `hallucination_drops`.
- Fill stretches: the gap's reference words are taken from the span of the chain of overlapping unheard rows (clipped to the gap between speech cues), not from "every wordless gap"; a wordless gap that no unheard row touches gets nothing.
- `agreement(pairs, total, cfg, source)` takes the reference token count (needed for `anchor_share`); `check()` is the entry the pipeline calls. The `ref_check` stage is emitted in words mode only (not for estimated or missing words).
- Regions use a centred rolling median of `ref_region_min_anchors` pairs, extended to adjacent pairs that deviate on their own; the test finds exactly one region for a chunk shifted by 1.5 s.
- Added config `ref_script_gap_share` (0.5): a Latin-share gap above it between reference and engine words is `other_script`.

Review round 1 fixes:

1. `TranscriptService.get(want_words=True)`: a legacy row is returned on any `YoutubeError` or `NoCaptions` from the refetch (never the audio-only path because words are missing).
2. A legacy row is used at once when the caption/metadata classes are not healthy (breaker open or probing); no waiting.
3. The credit drop belongs to the chunk review: skipped with `review=False` (`captions-score` default) and `asr_recheck = false`.
4. `ASR_CACHE_VERSION` stays 3: `drop_cached_credits` removes credit lines when a cached answer is read (the engine drops them when it stores). Nothing in this change needs a new ASR cache, so no re-transcription on the Mac: only the first captions job per video refetches the YouTube track once.
5. Tag tokens (`[Music]`, `(applause)`, notes, multi-token tags) are left out of the reference words of a fill cue.
6. `parse_json3_words` drops a prefix of an event that repeats the suffix of the previous event (two or more words, or one word at the same time).
7. A word-timed fill cue shorter than `min_cue_s` is stretched within the gap (to the next fill cue or the gap end) instead of dropped.
8. `merge_short` also runs on the audio-only `run()` path (`timing.merged_short`); a join keeps the union of the words, and a cue without words joined to one with keeps those words with `words_match_text` False.
9. Production steps below reordered.

Production verification (coordinator, never from agents; commands run on the backend host), in this order:

1. Deploy.
2. Score the old tracks of `ti3gVlNnXoY`, `EQWLxadmae0`, `TCSgH7l2Isg`: `uv run utubot captions-score VIDEO --reference ENGINE --windows 12 --window-s 30 --json`. `reference_language_ok` must be true; the `words` block is expected to be a number where a cached `v3` answer exists (null otherwise). Record `words` and `overall` as baselines.
3. `uv run utubot captions-regen --video ID` for each; read the job detail page: `ref_check`, `align` (`fill_from_words`, `merged_short`), `asr` `hallucination_drops`, `caption_recheck` found with `words` > 0, `captions.timing` (`reference`, `ref_check`). No "Altyazı M.K." cue in `EQWLxadmae0`.
4. Re-score with the step 2 command; gates: Hindi `words.within_s >= 0.85`, `loose` not below the baseline, at most 2 cues under 0.7 s, `fill_from_words > 0`; `TCSgH7l2Isg` within 2 points of its baseline on the same engine (name the engine used in step 2 and in step 4; the Mac engine was full last time and the faster-whisper `small` fallback answered).
5. When `ref_check` warns, listen to two of the listed regions (open the video at the region start) and record by ear whether the speech matches the engine's cues or YouTube's timing; that is the decision point for a time warp.
6. Existing transcripts without `caption_kind` are refetched once on the next captions job.

## 2026-11-21 (translation batch mismatch no longer fails the job)

1. Production: one translate batch of a 228-cue episode returned the wrong number of strings and failed the whole captions job after ASR and
   proofread had succeeded. `CaptionPipeline.translate` now retries such a batch (or a non-list / invalid JSON answer) once with a stricter
   message ("Return exactly N strings"), then splits it in halves recursively; a single cue that still fails keeps its source text.
2. The job fails (as before, "translation length mismatch") only when more than `[captions] translate_max_untranslated_share` (0.1) of the cues
   stay untranslated. The `translate` stage detail carries `batches`, `retried`, `split`, `untranslated`; status `warn` when `untranslated > 0`.
   `LLMBadJSONError` (subclass of `LLMError`) tells invalid JSON from other LLM failures. Job page text, docs and contract updated.
3. CP4 behaviour (split stats, `Cue.words`, legacy path) untouched.
4. Review fix: the job fails as soon as `untranslated` exceeds the share (checked per failed cue, so a model that always fails costs a few dozen calls, not ~150 per batch); an empty-string item for a non-empty source counts as a failed item (retry/split).

## 2026-11-21 (cold ASR engine: wait, do not fall through; issue 57)

1. A server that is still loading its model (oMLX: HTTP 500 "Engine not started", also 500/502 saying not started, not loaded or model is loading, any 503,
   refused connections) is now `EngineError.transient` (`warmup_state`). `AsrRouter._transcribe` retries it on the same engine with backoff
   (`asr_warmup_wait_s` 90, `asr_warmup_retry_s` 3, doubling, `asr_warmup_max_step_s` 20) before falling through; `sleep` is injectable.
2. One wait per engine: the first chunk leads (`_lead`), the others wait on its event (`_warm`) and then retry their own request. The retry
   runs outside `OpenAIEngine._resolve`'s lock (the exception releases it first), so a transient during the `auto` probe marks no mode.
3. Events: `asr_wait` (engine, waited_s, attempts, outcome) and `asr_fallback` reason `engine_unavailable` on giving up (engine marked
   unhealthy). Job page text, docs, contract updated. Timeouts, 4xx and other 500s are unchanged.

## 2026-11-21 (CP4 review round 1 fixes)

1. Legacy mode (`timing_mode = "legacy"`) again produces the old output: `Proofreader.polish` rebuilds cues without words and overflows through
   `retime_split` (counted in `split_by_chars`); `translate` keeps one cue per source cue with `wrap_lines(...) or [full]`. Test compares with
   the old result.
2. `split_cue` clamps: every piece lies in the cue, starts increase by at least `word_min_s`, each piece lasts at least `word_min_s` (a cue
   shorter than that is shared evenly); a cue ending before its last word no longer gives a zero-length piece or pieces past `cue.end`.
3. Exact mapping compares normalised tokens (`chunking.bare`, case and punctuation stripped; `segment.tokens_match`), not counts. A mismatch
   goes `at_pause`. Proofread sets `words_match_text` False when it changed tokens; pieces of an `at_pause` split are False too.
4. A last piece shorter than `min_cue_s` stretches too, up to the next cue's start (`split_cue(room_end=)`, passed by proofread and translate).
5. Caption-row splits from `caption_cues` / `merge_words_into_cues(retime=False)` are caption-timed and no longer count as `char_timed_cues`.
6. TIMING_VERSION 3 is reserved for CP3; CP4 jumps to 4 on purpose.

## 2026-11-21 (subtitle timing checkpoint 4: proofread and translate keep real times)

Plan: `temp/sync-design/agent-plan.md` (CP4). Before: a proofread text that overflowed a cue went through `retime_split` (character-count
time over the cue's span), a translation that did not fit became one over-long line, and `Cue.words` was dropped by proofreading and
translation.

- `segment.split_cue(cue, text, cfg, stats)` + `SplitStats`: lines packed with `forced_lines`, groups of `max_lines`; with words, `exact` (text
  still maps token for token onto the words, a speaker prefix token excluded) or `at_pause` (each cut to the widest word gap whose time
  fraction lies within `split_search_frac` (0.2) of the text's character share; nearest boundary when none is in range); without enough
  words `retime_split` (`by_chars`). Pieces keep `speaker` and their slice of `words`.
- `Cue` gained `words_match_text` (False after translation, so a translated cue is never cut "exactly" by chance) and `char_timed` (set
  by `retime_split`; counted in `sync_score.char_timed_cues`, and the final count after proofreading and translation is stored in
  `captions.timing.char_timed_cues`).
- `Proofreader.polish` and `CaptionPipeline.translate` carry words through (`dataclasses.replace`); `translate` splits overflow with
  `split_cue`. `proofread` and `translate` stage details: `split_exact`, `split_at_pause`, `split_by_chars`, `overlong` (lines still over
  the limit, i.e. one word longer than the line). `merge_words_into_cues(retime=True)` keeps `words`; fill cues have none. `TIMING_VERSION = 4`.
- Docs: `docs/captions.md`, `docs/server.md`, `ai/CONTRACT.md`, job page text (`jobtext.js`).

Deviations from the plan:

1. Padding is done inside `split_cue` instead of by the caller: a non-last piece lingers `cue_linger_s` and stretches to `min_cue_s` only
   into the gap before the next piece. The caller's `pad_cues` / `enforce_timing` would also touch cues in legacy mode.
2. The first piece starts at the source cue's start and the last ends at its end (the plan's "first word start / last word end" would drop
   the snap and linger already applied to the cue); interior boundaries are real word times.
3. `by_chars` is counted per cue, not per piece. `char_timed_cues` is also in the `sync_score` event (before text passes) and the final
   value is in the stored `timing`, since the text passes run after that event.
4. `translate(cues, target, stats=None)` takes an optional `SplitStats`.
5. The CP4 acceptance on the Hindi episode (production) was not run here.

## 2026-11-21 (subtitle timing checkpoint 2: wrong-language and hallucinated chunks)

Plan: `temp/sync-design/agent-plan.md` (CP2), builds on CP1. Evidence: EQWLxadmae0, first 600 s chunk labelled English, 20 segments,
"Thank you." every 30 s over continuous Turkish speech.

- `captions/sanity.py` (pure): `flag_segments` (`no_speech`, `repeat_loop`, `phantom`, `compressed`, `low_confidence`), `chunk_health`, `review`
  (reasons `language_mismatch`, `hallucination`, `sparse`), `drop_flagged`. Config `halluc_*`, `sparse_*`, `asr_recheck`, `asr_recheck_chunk_s`
  (`config.py`, `config.example.toml`).
- `AsrRouter.transcribe(expected_language=, review=)`: after `gather_all`, per chunk with a reason the ladder runs (forced language, smaller
  windows, next engine that serves the language), keeps the best by `ChunkHealth.rank()`, then drops flagged segments and the words inside them. Everything per
  chunk timing (SpanResult), never on the global real/interpolated share. The ladder runs after all first answers, so it cannot re-enter
  `OpenAIEngine._resolve`'s lock (tested with a real auto-mode engine on a mock transport). Single-engine chains work: steps 1 and 2 only.
- `asr_recheck` event, `asr` stats `rechecked_chunks`, `hallucination_drops`, `dropped_s`; `ASR_CACHE_VERSION = 3`, `TIMING_VERSION = 2`
  (so `captions-regen` lists CP1 tracks); `jobtext.js` text; docs (`docs/captions.md` "Chunk review", `docs/server.md`, `ai/CONTRACT.md`).
- Pipeline: `expected_language = requested or normalize_language(video_meta.language)`, for `run`, `improve` and `transcribe` alike (computed in `_asr_stage`).
- Tests: `test_sanity.py`, `test_asr_recheck.py` (forced language, smaller window, next engine, unrecoverable loop, healthy chunks untouched, review off,
  failing retry, sparse chunk, auto-mode lock), `test_sync_metric.py::test_hallucinated_chunk_recovers`, jobtext cases.

Deviations from the plan:

- `drop_flagged` returns the dropped segments (not a count) as its third item; the router counts them and sums their seconds.
- The metadata language is only a hint: when more than `asr_expected_override_share` (0.5) of the audio is heard as one other language the heard one is
  expected (a wrong upload language must not make every chunk be "corrected" into the wrong language). New config key.
- A language the engine was told (`language` given or a forced retry) is not checked on the first pass: only detected languages can mismatch.
- The evidence chunk alone flags only 23% of its seconds (20 x 7 s of 600 s), below `halluc_chunk_share` (0.3): it is the language mismatch (metadata `tr`) and
  the sparse rule that catch it. Drops apply to chunks that had a reason only (a lone phantom in a healthy chunk stays).
- `captions-score` references are not reviewed by default; `--review` opts in (documented).
- The hint is not in the ASR cache key (the key is unchanged apart from the `v3` prefix); documented.
- An `asr_recheck` attempt that raises (`ASRError`) is logged with `outcome = "failed"` and the first answer is kept.

Review round 1 fixes:

1. Code-switching: the audio overriding the hint makes the language unknown (no `language_mismatch` at all); no hint needs `asr_expected_dominant_share` 0.8; a lone
   mismatch needs `asr_mismatch_minority_share` 0.25 (`sanity.review`); a re-listen in another language is accepted only when not clearly worse (`asr_recheck_min_chars_ratio`,
   `asr_recheck_logprob_slack` over the unflagged speech, no more flagged share); only a mismatch forces a language, the other rungs use the language the first pass heard.
   Tests: correct hint on a code-switched video, an English stretch in a Hindi video, forced-only-for-mismatch, the evidence case still replaced.
2. Repeats: `repeat_loop` needs low confidence or a compression flag; it is dropped only when the smaller-window pass did not say the same text (`repeated_texts`);
   `phantom`/`no_speech` always go. Tests: confident chorus kept, chant re-heard kept, "Thank you" loop removed.
3. Budget: `asr_recheck_max_share` (worst chunks first, at least one chunk; deviation: a single chunk over the share is still allowed, otherwise a short video could never be repaired),
   `asr_recheck_max_requests`, a sparse-only chunk gets one rung. The agree-within-30% rule was dropped as redundant once sparse-only has one rung. Counts in the `asr` stats.
4. Ranking: word timing breaks ties, characters count up to `asr_recheck_chars_cap`, estimated words never replace real ones (unless the first was a hallucination).
5. Cache: a result with an unresolved chunk (budget skip, or all rungs failed) is not cached (`cache = "not_stored_unresolved"`). "Unresolved" means the ladder could not be done,
   not that a deliberate "kept" verdict is repeated every run.
6. Drops run after stitching on absolute times, inside re-listened spans (a phantom in a neighbour's overlap goes too). Test.
7. `ASRResult.dropped` ([start, end, reasons]) and `.chunks` ([start, end, language]) are in the v3 cache payload (additive; v3 was never deployed).
8. A rung only runs on engines that serve its language. 9. The `asr_recheck` text shows `detected_after` and the skipped cases. 10. Tests: short tail never sparse, a drop spanning a seam.

Review round 2 fixes:

1. `repeated_texts` ignores doubted segments (low `avg_logprob`, high compression ratio): a deterministic loop ("Altyazi M.K.") the engine makes up again in the windowed pass is still dropped; a repeat confirmed with confidence is kept. Tests in `test_sanity` and `test_asr_recheck`.
2. Budget and request-cap skips are deterministic: those results are cached (`skipped_chunks` in the stats). Only a chunk whose every rung failed with an engine error is `unresolved` and keeps the result out of the cache.
3. `_acceptable` without an `avg_logprob` on either side requires chars >= `asr_recheck_min_chars_ratio_no_logprob` (0.8) of the first answer (test: 0.6 kept, 0.9 replaced).

Production steps for CP2 (coordinator, after deploy; `<config>`, `<ref>` as in CP1):

1. Regenerate the video: `uv run utubot --config <config> captions-regen --video EQWLxadmae0` (all three videos regenerate anyway: `TIMING_VERSION` is 2 now).
2. Job log of the new job: an `asr_recheck` with `start_s` 0, `end_s` 600, `reason` containing `language_mismatch` and `outcome = "replaced"` (action
   `forced_language`; if the Mac engine still answers wrongly, `smaller_window` follows). `asr` carries `rechecked_chunks >= 1`.
3. Stored track: no cue in 0-600 s whose text is only "Thank"/"you."/"Thank you." and its characters in 0-600 s within 0.5-2x the per-chunk median
   (`sqlite3` on the stored VTT, or `GET /v1/videos/EQWLxadmae0/captions/tr.vtt`).
4. `uv run utubot --config <config> captions-score EQWLxadmae0 --reference <ref> --at 300 --window-s 120 --json`: `loose >= 0.85`.
5. The other two videos (`ti3gVlNnXoY`, `TCSgH7l2Isg`): no `asr_recheck` with `action = "dropped"` over real speech. List every drop (`dropped_segments`,
   `dropped_s`) here and spot-check against the audio; scores (step 4 pattern of CP1) not more than 2 points below CP1.
6. If a healthy video shows rechecks, read the `reason` and `flagged_share_before`; tune `sparse_chunk_ratio` / `halluc_chunk_share` rather than switching `asr_recheck` off
   (the switch is `[captions] asr_recheck = false`, no redeploy needed beyond a config reload).

## 2026-11-21 (subtitle timing checkpoint 1: real word times, repair, cues from words)

Plan: `temp/sync-design/agent-plan.md` (CP1). Causes measured earlier: the production engine (oMLX, mlx-audio) returns words only for the
form field `word_timestamps=true`, so `timestamp_granularities[]` got none and every word time was interpolated silently; `improve()` then
bucketed the words into YouTube windows of +-0.4 s and dropped the rest.

- Engine word modes (`AsrEngineConfig.word_timestamps` = `auto|granularities|flag|both|none`, `extra_form`, `condition_on_previous_text`).
  `auto` sends both fields first and falls back per the plan; words are read from the top level or from `segments[].words`; segment
  quality metrics (`no_speech_prob`, `avg_logprob`, `compression_ratio`) and word `probability` are kept. Every word carries its
  provenance (`Word.timing`: real, interpolated, repaired, suspect); `ASRResult.word_timing` / `stats` summarise it; `asr_chunk` events
  and `GET /v1/status` (`word_times`) show it. `asr_words_required` passes over an engine without word times (`no_word_times`).
- `captions/wordtimes.py`: `repair_words` (monotonic, stretched, zero-length, squeezed runs) and `classify`, run on every job against the
  audio's silences (`word_timing` event). `captions/syncscore.py`: `phrase_onsets`, `score_starts`, `self_check` (`sync_score` event).
- Cues: `align.cues_from_words` (speech cues from the words, caption cues no word touches kept as fill cues), `merge_words_into_cues(retime=False)`
  for estimated word times, `segment.pad_cues` (linger after the last word, anchored on it so a snapped cue is not pushed twice).
  `timing_mode = "legacy"` restores the old path; legacy tracks get no `timing_version`.
- ASR cache v2 (`v2:` key prefix; raw words with provenance, segment metrics, `word_timing`, `stats`); only a `real` answer is cached
  (`cache = "not_stored_no_word_times"` otherwise). New additive `captions.timing_version` / `captions.timing` columns, `timing_version`
  in the captions status track list.
- CLI: `utubot captions-score` (stored track vs. windows of the archived audio transcribed by a named engine; never YouTube) and
  `utubot captions-regen` (queues background jobs for tracks with no or an older `timing_version`).
- Tests: `tests/synth_speech.py` (truth timeline, Whisper-style answers with DTW flaws, rolling caption rows, tone audio, scripted engine),
  `tests/test_sync_metric.py` (real words hit 1.00 / loose 1.00; a segment-only engine hits 0.16), wordtimes, syncscore, align, engine,
  cache, report, migration and CLI tests. 876 tests.

Deviations from the plan, all small:

- The metric WAV is a tone wherever the truth has a phrase (not silence): repair uses the silences, so silent audio would make every
  stretched word look like a head stretch.
- `cues_from_words` takes an optional `silences` and snaps before it pads; it is split into `word_cues` + `finish_cues` so the pipeline can
  count the moved boundaries. `pad_cues` counts the linger from the last word, not the cue end.
- `self_check.starts_in_silence` counts a start that lies more than `sync_late_s` after a silence began *and* more than `sync_early_s`
  before it ends (a start at the end of a silence is where a cue should start).
- The late-end check of the sync test ignores cues held to `min_cue_s`; `captions-score` drops each window's first onset (a cut, not a phrase).
- `captions-regen --legacy` lists only tracks without any `timing_version`.
- `auto` probe order follows the plan (both, granularities, flag); the "400 to both" test uses a server that gives words to the field.

Review round 1 fixes:

1. `auto` word-mode probing: an answer without any text (a silent or music-only chunk) is returned as it is, decides nothing and costs no
   extra probes, the next chunk probes again; a 413, or a 400 that does not name the word fields, is raised instead of walking the forms.
2. `improve()` with estimated word times keeps the caption cues, text and timing (nothing is merged in; `align` skipped with
   `reason = "word_times_estimated"`); every caption token survives (tested on the 300 s talk).
3. ASR cache: real and mixed answers share the plain `v2:` key; an answer without word times is stored under `...:wm-<engines and their word
   modes>`, so a server that never gives words is not asked again but a new word mode misses. (The status of an engine whose config
   changed no longer reports the old instance's resolved mode.)
4. `word_cues`: coverage rule (replaced in round 2, see below).
5. Fill cues are clipped against each other before the linger and snap.
6. `captions-regen`: default limit `regen_limit_default` (20), skipped in legacy mode, and a track is not listed when a newer track of the
   video already has the current `timing_version` (terminates when the regenerated language differs).
7. `sync_score` is skipped with `reason = "no_silences"` when the audio has none; the report text shows null shares as n/a.
8. Cached three-item word rows load as `interpolated`. 9. A zero-length word with no room is neither marked repaired nor counted in
   `zero_length`. 10. Words still shorter than `word_min_s` after repair are marked `suspect` and counted in the new `unfixed`.
11. `captions-score`: `--at SECONDS` (repeatable), `--lang` picks the track (default: newest with a `timing_version`, else newest), `--spoken`
    for the audio language, output says which track was scored and gives `first_cue_start_s` and `max_cue_s`.
12. The rollback note in `docs/captions.md` says a full return to the old requests also needs `word_timestamps = "granularities"`.

Review round 2 fixes:

1. Fill rule (`align.word_cues`): a caption that is only a non-speech tag (`[..]`, `(..)`, music notes) is always a fill cue (clipped to
   the gap); a caption with text is a fill cue only when NO word overlaps its span widened by `align_window_s`. A spoken caption beside its
   own words is never repeated (the reproduced "so that's the plan" case is a test, as is a no-token-twice check on the 300 s talk).
   `fill_cover_min_share` is removed (config, example, docs); the `test_caption_source` expectation is back to 2 cues. Report text:
   "non-speech tags and captions in gaps with no heard speech".
2. Cache: the wordless (`wm-`) entry is read only while no engine of the chain is known to give words (resolved or pinned mode, or
   faster-whisper), so a fallback's estimate stops being served once the word engine recovers (tested with a flaky first engine).
3. Docs: `auto` walks the modes only on a 400 that names word/timestamp/granularities; servers that reject unknown fields with a generic
   400 must set `word_timestamps` explicitly.

Production steps (run by the coordinator after deploy; nothing here calls YouTube except the normal caption recheck of a regenerated job):

0. Answer shape (coordinator, 2026-11-21, before deploy): the production Mac endpoint was probed with BOTH `word_timestamps=true` and
   `timestamp_granularities[]=word,segment` on a 60 s Hindi clip: 200, words nested in `segments[].words` with keys `word`, `start`, `end`,
   `probability`. The production config pins `word_timestamps = "both"` on that engine (no probing); `auto` would also resolve to `both`.
1. Baseline with the old tracks, per video (the reference is the local faster-whisper engine; `<ref>` is its configured name). The old
   tracks have no `timing_version`, and `captions-score` falls back to the newest track then; it prints which track it scored:
   `mkdir -p temp/sync-design/score` then
   `systemd-run --scope -p Nice=19 uv run utubot --config <config> captions-score ti3gVlNnXoY --reference <ref> --windows 4 --window-s 120 --json > temp/sync-design/score/before-ti3gVlNnXoY.json`
   and the same for `TCSgH7l2Isg`. For `EQWLxadmae0` target the windows of the gate:
   `... captions-score EQWLxadmae0 --reference <ref> --at 1500 --at 2700 --window-s 120 --json > temp/sync-design/score/before-EQWLxadmae0.json`.
2. `uv run utubot --config <config> captions-regen --video ti3gVlNnXoY --video TCSgH7l2Isg --video EQWLxadmae0` (add `--dry-run` to list
   first), wait for the jobs, then repeat step 1 into `after-<id>.json`.
   The JSON has `track.first_cue_start_s` (gate: 4.2-4.9 s for the Hindi episode) and `track.max_cue_s` (gate: no cue longer than
   `max_cue_s`, 7 s; fill cues are clipped by the same limit); pick the regenerated track with `--lang` if the video has several.
3. Gates: Hindi episode: `word_timing` event `ok` with `real_share >= 0.99`; `loose >= 0.85`; `hit >= 0.60` and 20 points over the
   baseline; no speech cue over `max_cue_s`; first cue starts in 4.2-4.9 s. `TCSgH7l2Isg`: `hit` and `loose` within 2 points of the
   baseline. `EQWLxadmae0`: windows at 1500 s and 2700 s not worse (the first chunk stays broken until CP2). Record the `asr` stage
   seconds per audio minute of the Mac engine before and after, and update its `speed_factor` when it moved by more than a quarter.
4. If the faster-whisper reference is too noisy: also `--reference <mac engine> --window-s 30 --windows 12`; report both, tune no gate.

## 2026-11-21 (subtitle language setting)

- New per-user setting `captions_translate_to` (settings section `transcripts`, web UI Captions page, "Subtitle language" (empty with the server default as placeholder)):
  the language u·tubot captions are translated into. Unset follows `[captions] translate_to` (`en`); `off`/`none`/empty
  keep the spoken language (stored as `off`); a captions request that names its own `translate_to` still wins.
  `config.check_translate_target` validates it and the server default the same way.

## 2026-11-21 (director's cuts voice, EVR-512 round)

- EVR-512 blocking item fixed: the mic's `getUserMedia` acquisition window. `starting` disables the
  button and refuses a second attempt before the permission prompt resolves; `canceled` is set
  false at the start of the attempt, so a cancel while acquiring makes the late stream's tracks
  stop instead of starting a recorder on a detached button. That recorder can no longer be left
  live with no Stop or upload later at the length limit, and a double tap starts one acquisition.
- The Build/Dismiss cancel keeps the mic instance (`cancelMic()`), so a failed request leaves the
  old button wired to the sheet's lifecycle; both now toast a failure instead of an unhandled
  rejection. The error card resets the box and redraw signature, so the next successful poll
  replaces it instead of hitting the "same sheet" early return forever.
- `scripts/webui_cuts_check.cjs` is 49 checks. A deferred fake `getUserMedia` proves the mic is
  disabled while the prompt is open, a Build-cancelled acquisition releases the late stream with
  no recorder or `/v1/speech` POST, and a double tap makes exactly one call and one stream. The
  old `cuts.js` fails those five checks. Fresh demo and a rerun on a dirtied demo pass, 0 Chromium
  left.

## 2026-11-21 (director's cuts voice, checkpoint 3 review round)

- EVR-510 review fixes: the cut sheet's mic is tied to the sheet's lifecycle. The button is
  created once per sheet and reused across the poll's redraws, and `cancel()` clears the length
  timer, stops the recorder without uploading and releases the microphone when the sheet
  leaves waiting (Build, a preset chip, Dismiss, Back, the error card) or is torn down. A redraw
  mid-recording keeps the live Stop control instead of leaving a recorder the owner cannot stop.
- The spoken upload sends `recording.webm`/`recording.m4a` so STT servers that read the decoder
  from the filename extension accept it; a bare client filename gets the same extension in the
  backend. The multipart form is closed after the read (`await form.close()`), so a spooled temp
  file is unlinked before the response leaves.
- Plain errors now match the owner's view: an unreachable modelgate is `503` "busy" (retry is the
  right next move); a missing named provider is "not configured". `loadSpeech()` retries a
  transient `/v1/me` failure on the next draw instead of caching "no speech" for the page's life.
- `scripts/webui_cuts_check.cjs` is 38 checks: it forces a title change mid-recording (the sheet
  redraws, the Stop control and the one recorder stay), taps Build while recording, and leaves
  the sheet while recording; both cancel paths assert no `/v1/speech` POST and a released track.
  The old `cuts.js` fails the redraw and both cancel checks. Fresh demo and a rerun on a dirtied
  demo pass, 0 Chromium left.

## 2026-11-20 (director's cuts checkpoint 1: engine, phone pages, test set)

- Browser-check hygiene (the p100 crash of 2026-11-19 was ~9 orphaned headless Chromium
  processes from killed `webui_cuts_check.cjs` runs filling root's task limit): both browser
  scripts (`scripts/webui_cuts_check.cjs`, `docs/screenshots/webui/capture.cjs`) now close the
  browser in a `finally`, turn SIGTERM/SIGINT into a browser-closing exit, cap every Playwright
  wait at 10 s, and budget the whole run below the shell timeout (`BROWSER_BUDGET_MS`, default
  90 s — run the shell with a longer timeout). The check also resets the demo's cut knobs at the
  start and builds on per-run video ids, so a rerun after a killed run hits neither the demo's
  cached video metadata nor the shared cut cache of that killed run.
- Director's cuts backend (issue 36 / EVR-156): `cuts.py` cut engine (units, model answer
  validation with one repair round, padding/merge/drop, 10%/95% guards, per-user build cap,
  shared cache key), `cut_requests`/`cuts` tables, the routes behind `current_user`, the public
  `GET /cuts/{id}` QR redirect, and cuts job report rows. Cuts run as their own async tasks; the
  caption worker never claims a cuts job and its cancel/retry paths refuse them (a cut is
  retried or dismissed from its cut sheet).
- The phone pages: the Cuts tab (queue with thumbnails from the video id, states, parts list,
  retry/dismiss) and the cut sheet (`#/cuts/{id}`) with preset chips, the description box and
  the build stages. The web UI demo seeds a real build plus canned waiting/building/failed
  requests; demo fresh videos report a meta length that matches their short transcript so the
  keep guard measures the real thing. `scripts/webui_cuts_check.cjs` walks the whole life
  through the UI (22 checks) and blocks i.ytimg.com so the check never contacts YouTube.
- The offline test set (`utubot/cutbench.py`, five hand-marked transcripts x three requests,
  invented content) and `scripts/cut_bench.py` (score aliases against an OpenAI-compatible
  endpoint; one call per request, repair round included). Scores cover keep coverage, must-skip
  leaks and an excess-keeping budget (a "just the answer" cut that keeps half the video is a bad
  cut even when nothing marked leaked). Results: `fixtures/cuts/scores-2026-11-20.json`.
- Contract addendum (`ai/CONTRACT.md`, Director's cuts) and docs/server.md section.

## 2026-11-13 (delivery pipeline hardening, issue 17)

- `utubot app sync-github` now cross-checks each downloaded APK's own `AndroidManifest.xml` (`utubot/apkmanifest.py`, a small binary
  XML reader that agrees with `aapt2 dump badging` on real APKs) with the release metadata: package `dev.utubot.tv`, versionName, and
  versionCode when `release.json` gives one (a legacy release without it has a derived code and is not compared). No external tool.
- Release workflow: every path (automatic, tag push, dispatch) needs the commit on `main` and a green CI run; a manual release must be
  for the newest tag, with no existing release. CI's `release` job also waits for the backend job (skipped counts as passed).
- Database changes must stay additive so a rollback needs no migration step; `tests/test_db_migrations.py` enforces it, docs/server.md
  explains it. The `utubot-cd` controller changes of the same issue (transient deploy errors, the exit-2 ambiguity) live in the
  owner's ops repository.
## 2026-11-14 (caption pipeline review round 2: rebase on main, snapping, limits, cache order)

- Rebased on `main` (#41 tests-never-youtube, #45, #43 delivery-pipeline hardening) and fixed the semantic conflict the review
  found: the offline fixture fetcher (`youtube_fixtures.py`) now maps `parse_json3`/`parse_vtt`
  rows to `(start, text)` for `segments_to_text` the same way `YoutubeFetcher` does, and passes
  `segments=` into its `FetchResult`, so the improve path also works offline. The 4 fixture tests
  that failed on a trial merge pass again (16/16).
- Silence snapping (`align.py _snap_one`) moved boundaries onto pauses *inside* the cue — a start
  could move later onto the first word's pause and cut it, an end earlier than the last word. Now
  a boundary only moves outward (a start earlier, an end later, the last cue's end within the
  window), the nearest outward midpoint wins, and a boundary never crosses a neighbour. Tests for
  both cut-into-word cases and nearest-wins added.
- The improve path (`merge_words_into_cues`) stored each cue's ASR words as one unwrapped line —
  a 6 s cue of 18 words broke the 2x42 limit, and nothing but the proofreader re-wrapped it.
  Now the merged text is wrapped to the line limits, and text that does not fit one cue — or runs
  faster than `max_cps` — is re-split by `build_cues` over the words' own timings.
  `Proofreader.polish` re-splits over-crowded corrected text over the cue's span (`retime_split`)
  instead of keeping the unwrapped lines.
- Assignment in `merge_words_into_cues` is linear now (exact candidate window around one bisect
  position; cues are sorted and non-overlapping, so their ends are sorted too) and runs in
  `asyncio.to_thread` — measured 11.9 s for a 3 h track before, all inside the event loop.
- The ASR cache is checked before the vocal separation, and the cache key carries the separation
  mode (`asr_cache_key`): a retried job with a cache hit no longer runs demucs for nothing, and
  turning separation on does not keep serving ASR answers made from unseparated audio.
- The proofread guard also rejects a batch that comes back much shorter than its input
  (`< 1 / proofread_max_ratio`): dropped content is as suspicious as invented content. Cached
  batches are no longer written back on every cache hit.
- A captions job whose audio cannot be fetched (video gone, media class limited, archive full)
  now warns (`asr` warn, `audio_unavailable`) and proofreads the caption text as it is, instead of
  failing with the captions already in hand.
- `[captions] translate_to` is validated in `CaptionsConfig` (a language code, or `off`/`none`/`""`),
  so a bad config default fails at startup instead of answering 400 on every captions request;
  `proofread_batch` requires `>= 1` (0 would divide by zero).
- Known limitation (review nit, kept): caption-source transcripts cached before this PR have
  `segments = NULL`, so `TranscriptService.get(recheck=True)` returns the cached hit without timed
  segments and those videos build from the audio until the transcript TTL expires; new fetches
  store segments.
- Suite 724 passed, ruff clean.

## 2026-11-13 (review follow-ups: cassettes carry no URL at all, offline misses are not held)

- Review (EVR-168) found two leaks in the cassette sanitizer and one wrong hold; fixed:
- The sanitizer now keeps no URL at all: every `http(s)://…` string in a cassette becomes `<url>`
  (`strip_urls`), because signatures can hide in URL paths — YouTube HLS `manifest_url` carries
  the signature and the recorder's public IP in its path, which query-stripping left intact.
  `manifest_url` and `cookies` (yt-dlp can copy session cookies into the info dict) join the
  dropped keys, `protocol` goes too (replay never reads it), and the caption track text is
  stripped as well. The URL-free check now globs every committed `fixtures/youtube/*.json` for
  URL, signature and cookie text — a cassette the owner records later cannot slip through.
- An offline miss no longer records a failure hold: a missing cassette says nothing about the
  video, so `record_failure` ignores the `offline` reason and the next attempt (cassette
  recorded, or offline off) starts clean. The user-facing answer is still the `offline` video
  error, and no audio fallback is offered.
- Recorder hardening: `youtube-record` refuses when `CI` is set or `[youtube] offline` is on,
  and validates the video id before using it as a file name; the test DNS guard also refuses
  bytes hosts and trailing-dot names (`www.youtube.com.`).

## 2026-11-13 (English as the default caption target; owner direction on EVR-153 / #33)

- The goal is high-quality English captions for every requested video, whatever its source language; same-language captions are a side
  effect. `[captions] translate_to` (new, default `"en"`) is the default translation target of captions jobs: `POST
  /v1/videos/{id}/captions` with an unset (or null) `translate_to` — which is what the TV app's "prepare captions" sends — now resolves
  to the configured default instead of "no translation". `translate_to: "off"` (or `"none"`, or `""`) keeps the source language, and a
  config default of `"off"` makes that the default for everyone. The job row stores the resolved target, so the dedup key and the job
  report show the real target ("en").
- Quality bar on the English output: after the `translate` stage the translated text is proofread again (`Proofreader.enabled` gates it)
  with the title and description as context, so the English captions get the same punctuation/name pass as the source text. Both paths
  (`run` from audio, `improve` from the video's captions) go through `_finish`, so both benefit; the proofread stage cache is keyed by
  language and texts, so the two passes never collide.

## 2026-11-13 (lean HQ caption pipeline: improve existing captions, proofreading, alignment)

- Why: "HQ captions" was fast ASR cut into cues. GitHub #33 (EVR-153) wants a lean pipeline with two cases: a video that already has
  captions keeps their timing and gets better text; a video without captions gets the full audio path. Diarization is out of scope for
  now (owner, 2026-11-13).
- Captions first: a captions job now asks the transcript service what YouTube has (`caption_recheck`, same gate rules as transcript
  jobs). A caption track with timings and a matching language improves (`CaptionPipeline.improve`); anything else — no captions, a
  limited endpoint (`youtube_limited`), a track without timings, another language — builds from the audio (`run`), exactly as before.
  The recheck never holds the audio back.
- Improving existing captions: `transcripts.py` now parses timed segments (`start`, `end`, text) out of json3 (`dDurationMs`) and VTT,
   carries them through the fetch and the `transcripts` row (the existing `segments` column), and returns them on `Transcript.segments`.
  `captions/align.py caption_cues` turns them into cues (rolling repeats dropped, overlong text re-broken by `segment.retime_split` with
  time shared by length); `merge_words_into_cues` replaces each cue's text with the ASR words whose midpoint falls inside its window
  (margin `align_window_s`) and moves the boundaries to those words; a cue with no words keeps the caption text. When the ASR fails
  entirely (`optional_asr`), the caption text is proofread and stored as it is (`asr` warn event, `engines_unavailable`).
- Proofreading (`captions/proofread.py`): batches of `proofread_batch` (40) cue texts plus title/description (up to
  `proofread_context_chars`) to `[llm.captions]`; the answer must be a JSON array of the same length, non-empty, and within
  `proofread_max_ratio` (1.6) of the input length — otherwise the batch keeps its originals. An LLM failure warns per batch
  (`proofread_batch` child event) and never fails the job. Corrected batches are cached in the new `stage_cache` table
  (`captions/stages.py StageCache`), keyed by a sha256 of language, context and texts. Skips with `off` / `no_llm` events.
- Alignment for the audio path: after `build_cues`, `snap_cues` nudges cue boundaries to the midpoint of a nearby silence
  (`align_silence`, window `align_window_s`, silences by ffmpeg silencedetect with `silence_min_s`), never below `min_cue_s` and never
  across a neighbour (`align` event, mode `silence`; the improve path uses mode `merge`).
- Readability: `build_cues` now also splits when a cue would run faster than `max_cps` (20) characters per second (after `min_cue_s`).
- ASR stage cache: `_recognise` keys the ASR answer by audio sha256 (from the media archive row), `want_words` and the requested
  language; a cache hit skips the engines and reports `cached: true`. This makes a retried job (and a captions job after a transcript
  job for the same audio) skip the transcription — the audio itself is reused through the archive anyway.
- Vocal separation: `captions/separate.py`, off by default; `separation = "demucs"` runs `separation_cmd` (`demucs --two-stems vocals`,
  must be on the PATH) over the 16 kHz WAV and re-converts the vocals stem for ASR. Missing tool, failure or `separation_timeout_s`
  falls back to the original audio (`separation` event: ok / skipped `unavailable`), never fails the job. No music detector: the vocals
  stem of a speech-only mix is the mix.
- Diarization: the `diarization` stage only runs when `[captions] diarization` is not `none`; otherwise the stage is gone from the log.
  The pyannote capability is unchanged.
- Job report: new stages `separation`, `align` (mode `silence|merge`), `proofread` (corrected, warned, chars, cached) and
  `proofread_batch` (a batch that kept its text), all labelled in `jobtext.js` (batch warnings hang under the proofread stage).
  Config keys documented in `config.example.toml`; `docs/captions.md` rewritten around the two cases; `docs/server.md` and
  `ai/CONTRACT.md` list the new stages.
- Tests (`test_align.py`, `test_proofread.py`, `test_separate.py`, `test_stages.py`, `test_caption_source.py`, plus CPS/retime cases in
  `test_captions.py`): no YouTube anywhere — fake fetcher (now with timed `segments` and a configurable `lang`), mock ASR and mock LLM.
  The captions-job flow tests cover improve (ASR words re-time and replace the text, proofread applied), fallbacks (no captions, no
  timings, other language, broken ASR, audio without speech) and the stage cache (a retried job reports `cached: true` and reads the
  audio from the archive). Suite 694 passed, ruff clean.
- Review fixes: the caption track's language reaches ASR as its base code (an automatic track reports `en-orig`, which
  faster-whisper rejects hard); the improve path no longer fails when the ASR succeeds but hears nothing (music video with captions:
  the caption text is proofread and stored, `no_speech` warn); the `align` event's `moved` count compares against a snapshot of the
  boundaries (`snap_cues` mutates in place); the admin archive removal also clears the video's `stage_cache` rows (was promised by the
  docstring, never wired).

## 2026-11-13 (auto-transcribe when the length is unknown, issue 26)

- Why: with captions limited no metadata is fetched as a side effect, so a request without `duration_s` (web UI, other clients) got
  `needs_transcript` instead of an automatic job.
- `YoutubeFetcher.meta` (one yt-dlp request, `metadata` class, no caption download) and `TranscriptService.ensure_length`: only when
  the length and live flag are unknown, the `metadata` class is healthy and the video has no hold; paced through the gate at the
  caller's priority; stored with the video's metadata; never raises; not repeated within `transcripts.meta_retry_s` (in memory).
- `Transcription.auto` is async: when the policy would apply it asks for the length first, then decides. If the length rules the audio
  out (live, too long) the answer is refreshed (`can_transcribe`, `estimate_s`, message) or, with captions limited, becomes `delayed`.
- Review fixes (Opus, PR 46): the length request runs as its own task, one per video (shared by concurrent callers, promoted when an
  interactive caller joins a background one), and the endpoint waits for it only up to the caller's `wait_ms` cap
  (`Transcription.auto(wait_s=...)`); past that the ask-first answer goes out and the task still stores the length for the next poll.
  `ensure_length` now really never raises (a last `except Exception` logs; the `_meta_tried` stamp stops a retry loop), and
  `YoutubeFetcher.meta` refuses in `offline` mode like `__call__`.
- Tests: `test_audio_fallback.py`, `test_auto_transcribe.py` (slow length request answers within `wait_ms`, unexpected error is not a
  500), `test_youtube_fetch.py` (swallowed error, offline guard). Suite 759 passed, ruff clean.

## 2026-11-13 (media archive: keep every downloaded file, issue 34)

- Why: a job downloaded a video's audio, transcribed it and deleted everything; the next job downloaded the same audio again. Owner rule:
  never throw away downloaded media, never fetch the same thing twice. The report hooks were ready (`audio_download.source` =
  `downloaded|from_archive`, the report says "From the media archive"); now there is a real archive behind them.
- `utubot/media_archive.py` (new): content-addressed store. `lookup(video_id, kind)` → newest row for the video, original track first,
  verified on disk (a row whose file vanished is dropped, the video is fetched and stored again). `store(...)` copies the download into
  `files/<sha256[:2]>/<sha256>.<ext>` under `[archive] path` (empty: `<data dir>/archive`), fsync, `os.replace`, identical bytes stored
  once, the scratch original unlinked; the row carries format id, codec, bitrate, language, original flag, size, sha256, fetch time and the
  job id. `require_room` refuses a download at `quota_bytes` (0: no limit) with `MediaArchiveFull` — warn/stop, never silent deletion;
  `store` warns at `warn_frac` (0.9) and keeps a file that pushes usage over the quota. `remove(video_id)` is the one admin cleanup (a file
  another row still uses stays); `sweep_scratch` clears crash-left staging files at start, rows never.
- Pipeline: `_recognise` looks the video up in the archive first — a hit skips the gate and the download entirely (`audio_download` with
  `source=from_archive`), a miss checks the room, downloads as before and gains a `media_archive` stage (`bytes`, 12-char sha256 prefix)
  that keeps the file; the job then reads the audio from the archive. On a store failure (`MediaArchiveError`) the job fails and the scratch
  directory survives (`_keep_for_archive` checks the unwinding exception in the `finally`), so the download is not thrown away. Jobs map
  both errors to clear messages ("The media archive is full; an admin must free space…"). No magic numbers: `[archive]` in
  `config.py` + `config.example.toml`.
- Admin surface: `Services.archive`; `GET /v1/admin/archive?video_id=&limit=` (usage vs quota, state ok/warn/full, entries newest first,
  full sha256 — admin only), `DELETE /v1/admin/archive/{video_id}` (404 when nothing stored), `archive` in `GET /v1/admin/status`. Web UI:
  *Admin → Media archive* (`#/admin/archive`, usage card, one row per video with format/size/sha/age, Remove with confirm), linked from the
  users page; `jobtext.js` names the `media_archive` stage.
- Tests (`tests/test_media_archive.py`, no YouTube — the fake downloader and the env fixture): store/lookup round trip, content-addressed
  dedupe, original-first lookup, missing file pruned, quota stop before a download, warn state, job reuses the archive on the second run
  (downloader called once, `from_archive` in the event), job fails clear when full, admin API auth (401/403) and removal, scratch sweep
  leaves the archive alone. Suite 654 passed, ruff clean.

## 2026-11-13 (tests and dev servers never hit YouTube: fixtures and offline mode, GitHub #35)

- Why: the owner rule says tests, CI and agent verification runs never touch YouTube; the pytest guard (`block_youtube`) covered yt-dlp and
  httpx, but nothing replayed real YouTube answers and a running backend (emulator, E2E) had no way to work without the network.
- Fixtures: new `youtube_fixtures.py`. A cassette (`fixtures/youtube/<video id>.json`) keeps one video's recorded yt-dlp info dict and the
  caption track text, sanitized: every `url`/`fragment_base_url`/`http_headers` key is dropped and remaining strings have URL queries
  stripped (they carry signed tokens; `sanitize_info`, checked by tests). `utubot_demo.json` is a hand-written demo cassette; the owner
  records real ones with `utubot youtube-record VIDEO_ID` — the one command that reaches YouTube, guarded to refuse under pytest.
- Offline dev-proxy mode: `[youtube] offline = true` (`fixtures_dir` moves the cassette dir). `YoutubeFetcher` refuses before yt-dlp, the
  gate refuses every media-class transfer (`YoutubeOffline`, a video error with reason `offline`, so no audio fallback is offered), and
  `build_services` wires `OfflineYoutubeFetcher`: cassettes answer through the same parsers as the real fetcher, unknown videos answer
  `offline` and are remembered as failed. Status (`/v1/... home`, admin status route data) shows `offline: true`. Cached transcripts and
  metadata keep working, so the emulator and `UtubotBackendE2eTest` can run against the real backend with no route out.
- Guard: `block_youtube()` also patches `socket.getaddrinfo`/`gethostbyname` — DNS-level refusal for anything the library patches miss
  (urllib, raw sockets). New `test_network_guard.py`, `test_youtube_fixtures.py`, `test_youtube_offline.py` (the real app serves the demo
  cassette's summary with the mock LLM, offline).

## 2026-11-13 (job report: event log, delivery, detail page)

- Why: the jobs list only showed kind/state/progress; a "ready" captions job for a Turkish video did not say what it produced or whether the TV
  fetched it. Every job now keeps a log and has a report page.
- Log: new `job_events(id, job_id, ts, stage, status, detail JSON)` table (index on job_id) and `job_id` columns on `captions` and
  `transcripts` (migrated; `store_asr(..., job_id=)`). `captions/events.py`: `JobEvents` (record, list, `deliver`, `backfill`), `JobTrace` bound
  per running job in a `ContextVar` (`events.bind`/`unbind`), module helpers `emit`, `stage(...)` (a running event, then ok/failed/skipped with
  `seconds`), `note` / `take_notes` (facts learnt deep inside a stage, for example the yt-dlp format), and `set_origin` (who is behind the HTTP request).
  A ContextVar instead of parameters because `pipeline.transcribe`, `ASRBackend.transcribe` and the downloaders have many stubs in tests and
  threads (`to_thread`, `gather`) inherit the context. Without a bound trace every helper is a no-op.
- Instrumented: `JobQueue` (queued with user, client, endpoint, trigger and priority; promoted; started; retry; restart; cancelled;
  caption recheck; stored; finished; failed with cause class, message and stage), `CaptionPipeline` (gate wait, audio download with
  format id / track kind / language / bytes / `source`, ffmpeg, ASR totals, text, diarization, cues, translate, stored), `AsrRouter` (chunking,
  one event per chunk with engine, model, seconds, characters and language, `asr_fallback` with `EngineError.code`, stitching via
  `chunking.StitchStats`), the diarizers (`events.note(skip=...)`). `audio_download.source` is `downloaded` or `from_archive`; the media archive
  (GitHub #34) sets it with `events.note(source=events.AUDIO_FROM_ARCHIVE)`.
- Privacy: `events.clean` filters every detail before it is stored (keys naming token/secret/cookie/header/url dropped; URLs, `key=value`
  secrets, bearer tokens, hex digests, `utb_`/`sk-` keys and mixed-case 32+ character runs replaced; text cut to 240 characters; depth and list
  limits). Failure text is `events.technical(exc)`, never `str(exc)` raw. A model name such as `whisper-large-v3-turbo+whisper-small` must
  survive, which is why the random-run rule needs upper case, lower case and a digit.
- Delivery: `JobQueue.record_captions_delivery` / `record_transcript_delivery` credit the job that made the stored track (`captions.job_id`) or
  transcript (`transcripts.job_id`, ASR only; older rows fall back to the video's newest ready job). Called from `GET .../captions` (with
  tracks), `.vtt`, `GET .../transcript` (ok, asr), ready summary / panel summary / ask, `GET /v1/jobs/ID/transcript.txt`. Client name:
  `client_of(request)` = device name, "Web UI" or "API token". `deliver` coalesces the same client and way within `delivery_coalesce_s` into
  one row with a `count`. `[captions] job_events_max` caps stage events per job (milestones always kept).
- API: `GET /v1/jobs/{id}` (`captions/report.py`, `JobReports`; owner or admin, else 404 like cancel/retry), `GET /v1/jobs/{id}/transcript.txt`,
  `detail_url` / `api_url` / `stage` / `delivered` / `delivered_at` on `GET /v1/jobs`. Routes that can queue a job call `mark_origin(request, user)`
  first (cancel and retry too). `Transcription.request(..., trigger=)` carries the policy that fired for automatic starts.
- Backfill: `JobQueue.__init__` writes one synthetic event (`finished`, or `queued` for waiting jobs) for every job without events; the report
  also synthesises one on the fly for jobs inserted by other means.
- UI: `pages/job.js` (route `#/jobs/ID`, hidden from the bar, Captions stays lit), `jobtext.js` (labels, one-line summaries, `collapse` folds a
  running event into the one that ends it; pure, checked with node in the tests), `transcripts.js` rows link to the report and show
  fetched / not fetched. Auto refresh every 3 s while the job is waiting or running, 15 s afterwards; the page redraws only when the data changed.
  Screenshots 22 to 24 and a new 13; `capture.cjs` also checks the job pages for sideways scroll and console (CSP) errors at 360 px.
- Owner rule (no YouTube in tests): `tests/conftest.py` `block_youtube()` makes yt-dlp `extract_info`/`download`/`urlopen` raise and the real
  httpx transports refuse YouTube hosts, in an autouse fixture and in `webui_demo.py`; tests stand in for `yt_dlp.YoutubeDL` or the fetcher and
  downloader. `webui_demo.py`: the gate close endpoint now resets the per-class breakers (it still set the old single-breaker fields), demo job
  reports with event logs (a Turkish captions job fetched by a TV, an unfetched transcript, a failed and a waiting job).
- Review fixes: `events.clean` now handles quoted keys and values, `Authorization`/`Proxy-Authorization` with Bearer/Basic/Digest values,
  bare `Bearer ...`, cookie values to the end of the line (also `Set-Cookie`), compound names (`hf_token`, `client_secret`, `x-api-key`) and
  `token abcdefgh1234` without a separator (only a value of 8+ characters with a digit), and scans at most 2000 characters; plain words such as
  "Keyboard: the build" or "token provided" stay. `delivered` rows are capped per job (`[captions] delivery_events_max`, 50): past it a
  delivery is counted into the newest row. `Database` sets `PRAGMA synchronous=NORMAL` with WAL: no corruption risk, but a power loss may drop
  the last few commits (a delivery count, a just-written session) instead of none.
- Tests: `test_job_report.py` (stage order for transcript and captions jobs, who asked and the policy, cancel/retry/restart/transient retries,
  caps, mocked yt-dlp format notes, mocked engine fallbacks and stitching, secrets/URLs, auth, delivery by client kind, backfill, the UI assets
  under the CSP and the report text through node).

## 2026-11-12 (audio when captions are limited)

- Why: production showed "YouTube is limiting transcript downloads, retrying in 34 minutes". Only the caption class (timedtext) was 429;
  audio downloads worked and the fast engine transcribes 30 minutes in about 30 s. The caption breaker also kept escalating because each
  probe after a cooldown was an interactive request that hit 429 again.
- Fallback: `Transcription.state()` (cheap, also behind `GET /transcript`), `blocked()` and `problem()` ask `captions_limited()` (the
  breaker is open or the probe is out: `YoutubeGate.interactive_ok(*FETCH_CLASSES)` is false) or get a fetch ended by a back-off reason
  (`rate_limited`, `forbidden`, `bot_check`, `cooldown`) and call `audio_fallback()`: `media` healthy and `can_transcribe` (not live, within
  `max_duration_s`, an engine serves the language) give the "no captions" fields (`transcript_status: none`, `can_transcribe`, `estimate_s`,
  message "Captions are temporarily unavailable from YouTube; transcribe the audio instead (~N s)?"; no `(~N s)` when the length is
  unknown), which `auto()` turns into a started job under the user's policy (`on_open` explicit, `on_dwell` also the panel, up to
  `auto_transcribe_max_minutes`). Nothing is remembered. A network error, no engine, a live or too long video, or a cooling `media`
  class (a bot check opens metadata and media) keep `delayed`. Existing delayed tests now cool `media` (`audio_unreachable`).
- Probing: `PROBE_CLASSES = (captions,)` are probe-only once half-open. `_acquire` refuses an interactive request for such a class
  (`YoutubeCooldown`, hint `captions_probe_retry_s`), lets exactly one background request through (`_Breaker.probing`, released in
  `_release`) and holds the other background waiters behind it; `promote` skips probe-bound waiters. `TranscriptService.probe_captions`
  starts that background fetch for the video of the first content request that finds the class half-open (never from `GET /transcript`,
  skipped for cached, held and no-captions videos). A complete yt-dlp answer without a caption track (`ANSWERED_NO_CAPTIONS`)
  counts as answered for the caption class too, so a probe on such a video closes it instead of leaving it half-open. An
  interactive transcript job skips its caption recheck while the probe is out; a background job may be the probe.
- Caps: `[youtube] captions_cooldown_max_s` (1800) is the ceiling of the caption class, `Retry-After` included, never above
  `cooldown_max_s`. Old tests that probed with an interactive request now probe with `BACKGROUND`.
- Stored transcripts: `_fetch` upserts captions with `WHERE source != 'asr'` (and clears engine/model/segments for caption rows), so a late
  or in-flight caption fetch returns the stored ASR transcript instead of replacing it; `cached()` already returned ASR first, so there is
  no refetch.
- Engines (PR #22 review): `_chunk_on` re-checks health after `limiter.acquire` and `_span_on` before each sub-chunk
  (`_passed_over`: unhealthy and a healthy engine later in the chain, `EngineError(penalize=False)`); unknown language sorts engines
  without `languages` first and `_span` redoes a chunk an allow-listed engine took when the detected language is outside its list (the
  result is kept as a last resort); `EngineError.isolated` (5xx, unreadable or oddly shaped answer, a non-connect/timeout transport error)
  marks the engine only after two different files failed with no success between (`_record_failure`, keyed by the wav path); connect and
  timeout failures, 429 and 401/403/404 still mark at once.
- yt-dlp: `ytdlp_runtime_options` always passes `js_runtimes={js_runtime: {path}|{}}` (yt-dlp looks the runtime up on PATH without a path);
  `pyproject.toml` requires `yt-dlp>=2025.11.12`, the first release with `remote_components` (checked in the 2025.10.22 and 2025.11.12
  wheels; the lock holds 2026.10.26 and its specifier is updated).
- Review fixes (PR #24): `store_asr` replaces captions older than `cache_ttl_s` (they are unusable: `cached()` ignores them), so an
  expired captions row no longer makes state() offer the fallback, run ASR and store nothing in a loop; a transcript job that ends with
  no usable transcript (`cached()` is None after `store_asr`) now fails with the recorded message instead of finishing silently.
  `[captions] asr_failure_window_s` (600): two isolated engine failures only count together when at most that far apart.
- Tests: `test_gate_probe.py`, `test_audio_fallback.py` (policy, panel, 429 now, probe flow, escalation cap, late captions, jobs), engine
  and media additions.

## 2026-11-12 (fast transcripts, issue #19)

- Gate: `YoutubeGate` keeps one shared pacer and one breaker per endpoint class (`captions` = timedtext, `metadata` = watch/player/yt-dlp
  extract, `media` = audio download; state in `youtube_gate_class`, the old single row is adopted by all three once). Why: the TV
  home screen's timedtext fetches got 429 while googlevideo audio downloads still worked, and the single breaker paused those too. Errors
  carry `klass` (`classify_failure`/`classify_status` take it), `run(..., classes=)` names what an operation needs, a block opens the class
  that got it (a bot check opens both yt-dlp classes), a success closes the classes it `answered` (`FetchResult.answered`). Pacing stays
  shared on purpose (the owner's request rate is one number); `healthy()/state()/cooldown_remaining()` without arguments mean "all
  classes", `snapshot()` feeds `GET /v1/status` (`youtube.classes`, `asr.engines`). Jobs are claimed while `media` is healthy; a transcript
  job skips its "did captions appear?" recheck when `metadata`/`captions` cool or answer delayed and goes straight to the audio.
- Audio: `captions/formats.py` picks the lowest-bitrate audio of the original track from yt-dlp's format list (a yt-dlp `format`
  callable; fallback chain in the module doc and `docs/captions.md`; `audio_format` is only the last resort). Real multi-track videos
  (checked on a 29 minute lecture with 20 languages) mark only the original (`... original (default)`), other tracks are plain language
  names, so "marked original wins" is the operative rule; dubbed/descriptive notes are excluded when no marker exists.
- JS runtime: `[youtube] js_runtime`, `js_runtime_path`, `remote_components` go to yt-dlp (`js_runtimes`, `remote_components`) for the
  metadata fetch and the download. Verified live without deno on PATH: no option = "No supported JavaScript runtime"; path only =
  "n challenge solving failed" (the solver script is missing); path + `remote_components = ["ejs:github"]` = clean and one more format.
- ASR: `captions/engines.py` (`AsrRouter`, `OpenAIEngine`, `FasterWhisperEngine`) replaced `OpenAIASR`/`FasterWhisperASR`.
  `[[captions.asr_engines]]` (name, kind, url, model, api_key_env, languages, max_chunk_s, max_parallel, timeout_s, priority,
  background_only, speed_factor, overhead_s); the old `asr_*` keys become one engine `default` (key optional). Selection: enabled (key
  env set, package present) -> serves a known language -> not background-only for interactive jobs -> healthy first -> priority (lower
  first). Failures fall through per chunk, the next engine re-cuts to its own limit; 5xx/429/transport/401/403/404 mark the engine
  unhealthy for `asr_unhealthy_s`, input rejections (400/413/415/422) do not; all unhealthy = try anyway. Per-engine `PriorityLimiter`
  (`max_parallel`) is shared by all jobs. Unknown video language lets restricted engines through (documented caveat).
- Chunking (`captions/chunking.py`): `plan_chunks` with 2 s overlap and a tail fold, WAV slicing in a thread, `stitch_*` cut at each
  overlap midpoint then drop a repeated seam (>= 2 words, only when the next chunk starts inside the overlap). Progress = done chunks /
  chunks. Transcripts keep `segments` (JSON), `engine`, `model` (new `transcripts` columns, migrated); `GET .../transcript` shows them.
- Policy: `Transcription.auto` acts on `auto_transcribe` / `auto_transcribe_max_minutes` (fields from the web UI branch's
  `UserPolicy`): explicit requests (summary view, insight, ask, ad-hoc) start on `on_open`/`on_dwell`, `prompt=panel` only on
  `on_dwell`; known length <= limit, `can_transcribe`, queue not full, else `needs_transcript` as before. Jobs have a `priority`
  (explicit = interactive, panel = background, promoted when the user opens the video); claim order is priority then age.
- Estimates: `download_overhead_s + duration / download_speed_factor + engine.overhead_s + duration / (speed_factor x min(max_parallel,
  chunks))` for the engine the selection would pick now.
- Real check (public videos, stub caption fetch, real yt-dlp and ASR endpoint): 5.6 min video: 3.9 s download (2.0 MB), 4.7 s ASR, 17.6 s
  whole job (about 4 s of that is the gate's mandatory gap between the caption check and the download); 29.5 min lecture: 2.5 s download
  (10.7 MB), 3.4 s ffmpeg, 16.4 s ASR (3 chunks in parallel, ~108x real time), 30.7 s whole job. Seams at 598 s and 1196 s were clean.
- Tests: `test_gate_classes.py`, `test_audio_formats.py`, `test_chunking.py`, `test_asr_engines.py` (stub engines, mock HTTP, the documented
  chain), `test_auto_transcribe.py` (policy, priorities, estimates, migration, end to end with ffmpeg), plus media/flow updates. The
  ask-first flow tests opt the owner out with `auto_transcribe = "off"`.

## 2026-11-12 (R4: phone web UI, per-user settings, web sign-in; issue #9)

- UI: `web/index.html` is now a static shell; `web/ui/app.css` and `web/ui/js/**` (ES modules, no build, no npm, no external requests)
  render Home, Models, Prompts, Filters, Captions, TVs, Updates, Account and Admin. DOM only through `h()`/`textContent` (a test greps
  for `innerHTML` and friends), CSP `default-src 'none'; script-src 'self'; style-src 'self'` on every response, no inline code. Phone
  first (bottom bar at 360 px, left sidebar from 900 px), dark and light (system, with a switch), no sideways scroll at 360 px
  (`docs/screenshots/webui/capture.cjs` checks it). `tests/webui_demo.py` serves canned data for screenshots.
- Sign-in (`webauth.py`, `passwords.py`): scrypt passwords (`utubot user passwd`, web UI), token sign-in kept but exchanged for a
  session, HttpOnly `SameSite=Lax` cookie (Secure through `security.is_https`: direct HTTPS or `X-Forwarded-Proto` from a trusted
  proxy), 30-day sliding sessions stored as SHA-256, CSRF = per-session `X-CSRF-Token` (derived from the session id) plus an `Origin`
  check, lockout per IP, per account and global in `login_failures` (a wrong password and an unknown user look the same, dummy
  verify). Bearer tokens (TVs, scripts) are untouched and need no CSRF.
- Settings: `UserPolicy` grew `models`, `mark_only`, `auto_transcribe`, `auto_transcribe_max_minutes`, `summary_delay_ms`,
  `summary_panel`, `auto_captions`, `update_checks` (validated ranges; thresholds <= 1.01, topics trimmed and deduplicated). They ride
  the existing override row (`policy_overrides`, now with `version` and `updated_at`), so `[default_policy]` -> `[users.policy]` ->
  override is the precedence and `None` fields follow `[summary]`/`[setup.defaults]`; `settings.py` is a view with PUT
  (partial, `null` resets, optional `version` -> 409) over that row and the prompt-default tables. `resolve_users` replaced the reload
  in `Auth._refresh` (users.toml edits no longer reload config.toml, `declared_users` keeps the file's users).
- Models in use: summaries use `with_user_model` (user model when the prompt has none; part of the content hash, so cached apart),
  insight/analysis/ask pass `model=`, title triage batches are keyed by (topics hash, model). The shared triage, insight and deep caches
  stay keyed without the model (documented). `modelcatalog.py` caches each provider's `/models` (5 min, error ttl, forced refresh
  rate-limited), remembers `model_seen` so a restart does not mark everything new, never returns keys.
- Status: `/v1/status` (gate, LLM and transcript counters from `usage_daily`, which `LLMClient` fills per call), `/v1/updates` (channel,
  cached GitHub release lookup, `sync.json` written by `utubot app sync-github`). Jobs: `cancel` (waiting only) and `retry`
  (failed/cancelled), state `cancelled`. Small additions: `/v1/me/devices|pair`, `/v1/videos/resolve`, `/v1/prompts/validate`,
  `/v1/users*` (create with password and no token, admin flag only for users.toml users).
- Tests: `test_websession.py` (login, cookie flags, CSRF, Origin, sliding expiry, lockout, password change, CLI), `test_settings.py`
  (document, validation, versions, precedence incl. config files, models applied to calls, admin routes, migration),
  `test_modelcatalog.py` (cache, refresh, new marks, errors, no secrets), `test_webui.py` (static assets and CSP, module graph, every
  route needs auth, admin-only routes, users, devices, jobs, status, updates, resolve).
- Review fixes: (1) a password change used to sign the browser out: the edge middleware re-issued the old, revoked session cookie after
  the handler had set the new one; the handler now owns the cookie (`fresh_session`, also for an admin setting their own password) and
  the middleware skips a response that already sets it. (2) Client IP behind two proxies: `[security] client_ip_header` (+
  `client_ip_header_secret_env`, `X-Utubot-Proxy-Secret`) names the client for a trusted peer that proves the secret (constant-time),
  ignored otherwise, XFF logic as before. (3) `SettingsService.update` re-reads the version after the model check and writes with a
  compare-and-set (`Auth.write_override(expected=)`); browser sessions must send `version` (428), bearer callers may omit it.
  (4) `allow_unlisted_models` is admin-only, and `PUT /v1/me/policy` refuses `models` from non-admins (it skipped the list check).
  (5) scrypt N=2^17 (`scrypt_max_concurrent` bounds the memory), old hashes verify (parameters are bounded when read) and are
  re-hashed on the next successful sign-in with a compare-and-set on the old hash.
- Left for R5: the enrollment link and QR for "Link a TV" (placeholder in the TVs page), first-run admin creation and the
  provider/key wizard in the UI, the TV reading `GET /v1/me/settings`, acting on `auto_transcribe` (server or TV).

## 2026-11-12 (review fixes for the YouTube gate)

- Breaker scope: only a 429, the bot check or a 403 on the watch/player/metadata request open it. A 403/410 on a caption or media
  URL and private, members-only, age-gated or unavailable videos raise `YoutubeVideoError` (`transcript_status: "failed"` + `reason`),
  recorded in `video_holds` (`[transcripts] video_failure_ttl_s`, 1 h) so they are not re-fetched; any such answer closes a half-open
  breaker and resets the escalation. `RATE_LIMIT_RE` no longer matches a bare "try again later".
- Jobs: `YoutubeDelayed` (including blocked) re-queues with `attempts` and `not_before` (gate clock), capped by
  `[captions] job_max_attempts` (3), then fails; a per-video error fails the job at once. Orphan `media/<id>` directories older
  than `media_orphan_age_s` are removed at start.
- Media lane: `YoutubeGate.run_started` holds the paced slot only until the download signals its first bytes (yt-dlp progress
  hook), then releases it; a 429 after the start still opens the breaker. yt-dlp gets a `match_filter` (live, duration) and
  `max_filesize`; the converted WAV is re-checked against `max_duration_s` before ASR.
- Soft-degraded answers: "no captions" is cached only from a complete yt-dlp answer (formats present, no caption language listed
  without formats); otherwise `delayed`. A caption file that parses to nothing is `delayed` with a `video_holds` entry
  (`empty_track_retry_s`, 1 h), never "no captions".
- ASR vs captions: a transcript job first re-checks YouTube (`get(recheck=True)`, ignores the no-captions memory) and uses captions
  if they exist; `store_asr` never replaces a `youtube_captions` row (a fresh complete "no captions" answer deletes a stale one).
- Tier-2 refunds the daily slot when the fetch ends delayed. `GET .../transcript` shows `job_id` only for the caller's own job;
  `state()` and the summary/insight/ask responses never carry one. `delayed` can appear on that endpoint (empty-track hold).
- Tests: scoped classification, per-video failures end to end, retry cap (network and blocked), media start gating, filters,
  sweep, soft-degraded answers, recheck, refunds, job-id scoping (`test_youtube_gate.py`, `test_youtube_fetch.py`, `test_media.py`,
  `test_transcript_flow.py`).

## 2026-11-12 (YouTube pacing, circuit breaker, no title-only summaries, ask-to-transcribe)

- Incident: one home IP, one user browsing the TV home screen: about 70 transcript fetches in 3 hours (26 interactive summaries, 41
  tier-2 analyses, insights, caption jobs) in bursts; YouTube answered `/api/timedtext` with 429. Every later fetch failed, the
  fetcher stored a `metadata_only` transcript (empty text, cached 30 days) and summaries were generated from the title (5 vague
  bullets, cached as ready).
- `youtube.py`: `YoutubeGate`, a process-wide pacer plus breaker for yt-dlp metadata, timedtext and audio download. At most
  `[youtube] max_concurrent` (1) in flight, `min_interval_s` (3 s) + random `jitter_s` between requests (measured from the end of the
  previous request), interactive before background, `promote(key)` lifts a queued background fetch when a user starts waiting on
  it. Breaker: 429, 403 or "Sign in to confirm you're not a bot" (also yt-dlp "rate-limited by YouTube") open it for `Retry-After`
  or `cooldown_base_s` * 2^(consecutive blocks - 1) up to `cooldown_max_s`; interactive callers get `YoutubeCooldown` immediately,
  background callers wait (paused, they hold no slot and no tier-2 semaphore) and the first request afterwards is the probe.
  State (`youtube_gate` row) survives restarts so a crash loop cannot hammer YouTube. Injectable `Clock` for tests.
- Failures are classified (`classify_failure`, `classify_status`) into `YoutubeBlocked` (opens the breaker), `YoutubeDelayed`
  (network, 5xx, empty caption body: transient, breaker untouched) or a sanitised `YoutubeError`; messages never carry URLs
  (`from None`, query strings stripped) and the `httpx`/`httpcore` loggers get a URL-redacting filter because httpx logs every
  request URL, signed caption tokens included, at INFO.
- `TranscriptService.get(video_id, priority)` is the only way to a transcript: cache, then "no captions" marker, then one shared
  in-flight fetch through the gate. `no_captions` table (3 day TTL, `[transcripts] no_captions_ttl_s`) replaces the empty
  `metadata_only` row. `Database` start-up deletes legacy `metadata_only` transcripts, summaries and insights.
- Metadata-only generation removed: `ContentService.source` no longer falls back to the title; `NO_TRANSCRIPT` prompt text gone.
  Summary/insight/ask answer `transcript_status` (`ok|delayed|none|transcribing|failed|null`): transient problem is
  `pending`+`delayed`+`error`+`retry_after_s` (not cached, not recorded as a task failure via the `expected` exception flag);
  no captions is `needs_transcript`+`none`+`can_transcribe`+`message`+`estimate_s` and makes no LLM call.
- `transcribe.py` (`Transcription`): state from the DB only (`ok`, active job -> `transcribing` with progress, recent failed job ->
  `failed`, marker -> `none`), `request()` for `POST /v1/videos/{id}/transcribe`, `status()` for `GET .../transcript` (adds
  `unknown`, not in the five values, for videos never looked at). Estimate = `asr_overhead_s` + duration / `asr_speed_factor`.
- Jobs: `jobs` table gained `kind` (`captions|transcript`), `title`, `finished_at` (ALTER on start). Transcript jobs reuse
  `CaptionPipeline._recognise` (gated download, ffmpeg, ASR), build cues, store the text as source `asr`. One active job per user
  and video; the same video never runs twice at once; `_claim` skips queued work while the breaker is open (state `waiting`); a
  job whose download is refused goes back to the queue. `GET /v1/jobs` (mine, any kind, `waiting|processing|ready|failed`) is the
  groundwork for the "check later" shelf (issue #16). `[captions] transcribe_max_active_per_user` caps queued jobs.
- Volume: tier-2 default cap 30/day; scheduled only for a title question or clickbait score >= threshold (unchanged rule) and now
  also only when the breaker is not open, the video is not known to lack captions and fewer than `[youtube] max_background_queue`
  background fetches wait. The fetch happens outside the assess `_bg` semaphore (a paused fetch no longer blocks triage).
  Audit: the only path to YouTube text is `TranscriptService.get`; summary prompts, insight, ask and tier-2 share one fetch per TTL.
  `[transcripts] max_concurrency` removed (superseded).
- Web UI: shows `needs_transcript` with a "Transcribe in background" button, stops polling on `delayed`, lists all jobs.
- Tests: `test_youtube_gate.py` (pacing, jitter, concurrency, priority, promotion, breaker open/close/exponential/Retry-After cap,
  paused-not-failed, persistence, log hygiene, classifiers), `test_youtube_fetch.py` (real `YoutubeFetcher` with a mock
  timedtext transport and injected extractor: 429+Retry-After, bot check, no captions + expiry, empty body, 5xx, once-per-TTL),
  `test_transcript_flow.py` (HTTP flow, ASR job end to end, `/v1/jobs`, tier-2 gating, legacy purge, column migration),
  `tests/fakes.py` (`FakeClock`).
- Known follow-ups: the TV app does not know `needs_transcript`/`delayed` yet (issue #16 shelf, "Transcribe in background?"
  action); diarization is not applied to transcript jobs; a job paused inside the gate while running shows as `processing`.

## 2026-11-12 (glance summaries, panel default, background long summaries)

- Owner request: the side-panel summary was too long for the screen and slow; titles that pose a question or tease a reveal
  should be answered first.
- New built-in prompt `builtin/glance` (<= ~280 chars, <= 3 short lines, plain text, `→ answer` line first when the title poses
  a question or is a curiosity gap, "Not answered in the video" otherwise, then 1-2 lines of gist; `max_tokens` 160). The
  triage `title_question` fills `{question}` (it already did; the glance and `answer-title` templates now use it, and both work
  when it is empty). `answer-title` rewritten with the same curiosity-first logic. Builtin set version 2.
- `Prompt.task` (`summary` default, `glance`): picks the `[llm.*]` table. `[llm.glance]` (optional; `reasoning_effort` "none"
  and `max_tokens` 160 by default) falls back to `[llm.summary]` with reasoning off. `content_hash` only includes `task` when
  it is not `summary`, so existing prompts keep their cached summaries; old prompt-set files validate unchanged.
- Defaults split: `GET /v1/prompts` returns `panel_default` next to `default` (and `panel_default` per prompt);
  `PUT /v1/prompts/panel-default {"key"}` (separate route chosen over a `panel_key` field on `/default`); stored in the new
  `user_panel_default` table (created by `CREATE TABLE IF NOT EXISTS`, no migration); resolution order user choice, then
  `[summary] panel_prompt`, then `builtin/glance`. `GET /v1/videos/{id}/summary?prompt=panel` resolves to it and returns the
  resolved key in `prompt`. Web UI got a "Use for the side panel" selector.
- `[summary] auto_long` (default false) and policy field `auto_long` (null = follow config): after a `prompt=panel` request ends
  ready, `ContentService.schedule_long` queues the user's `default` prompt at `BACKGROUND` priority through the existing
  per-provider limiter; skipped when cached, running, recently failed, or the same prompt as the panel one. Summary job
  creation was factored into `_start_summary` (shared by the interactive and background paths, same registry key, so joiners dedupe).
- Condense (map) step: system prompt asks for the passage that answers the title's question or reveals its tease first, on
  an `ANSWER:` line; the map user message now carries the video title and the triage question. Caveat: `condensed` rows made
  before this change are reused as they are (key is video + budget); `DELETE FROM condensed` rebuilds them.
- Review fix: background and interactive runs of one summary are separate registry tasks (`summary_task_key`: `summary` vs
  `summary-bg`), so a background failure never makes an interactive request `failed`, and an interactive request never
  joins a background task (it starts its own and cancels the background one; same result row, last write wins).
  `[summary] auto_long_max_concurrent` (2) caps background long jobs from task start (transcript fetch included); over the
  cap `schedule_long` skips and a later panel request retries.
- Known follow-ups: the Android panel still preselects `default` from `GET /v1/prompts` (needs `panel_default` or
  `prompt=panel`); no thumbnail text exists in the metadata the app sends, so only the title is used today.
- Tests: `tests/test_glance.py` (panel alias, `{question}` from triage, condense focus, `[llm.glance]` and its fallback,
  auto_long off/on/policy override/background priority/failure isolation/interactive takeover/concurrency cap, panel-default PUT and fallbacks, old prompt files and hashes).

## 2026-11-12 (sync-github)

- `utubot app sync-github --repo OWNER/NAME [--prerelease] [--dry-run]` (`appsync.py`): newest `utubot-vX.Y.Z` release from the
  GitHub API, `release.json` (version, versionCode, per-ABI SHA-256), download with a size cap, SHA-256 check, signature and
  signing-certificate check against `[app] signing_cert_sha256`, then `appchannel.publish`. Newer means higher versionCode; no-op
  otherwise. Exit 0 ok, 1 check failed or misconfigured, 75 GitHub unreachable or rate limited. A missing pin, or an
  `apksigner_path` that does not run, refuses loudly.
- Signature check: `apksigner_path` set runs `apksigner verify --print-certs`; unset uses `apksig.py`, a pure-Python reader of the
  APK Signing Block (v2, v3, v3.1) that verifies the RSA signatures (PKCS#1 v1.5, PSS), recomputes the chunked content digest and
  returns the signer certificates. ECDSA/DSA keys and v1-only APKs are refused with a pointer to apksigner. Tests use APKs signed by
  apksigner with a throwaway key (`tests/fixtures/*.apk.bin`) and OpenSSL signature vectors.
- Releases without `release.json`: ABIs from file names, hashes from `SHA256SUMS`, versionCode derived from the version.
- `[app]` gains `github_repo`, `github_token_env`, `signing_cert_sha256`, `apksigner_path`, `keep_versions` and sync limits.

## 2026-11-12 (review fixes, backpressure PR)

- summary/ask jobs now return their result (text, source) so deduped joiners read it; truncated
  summaries/answers sit in a short-TTL cache (`adhoc_ttl_s`) readable by all callers and the summary lookup also
  checks the ad-hoc row. Truncated map-step notes are never persisted in `condensed`.
- `llm.py`: one absolute deadline per logical call shared by truncation/bad-JSON retries; HTTP timeout clamped to the
  remaining deadline; a failed truncation retry returns the first (truncated) answer; HTTP error messages carry status
  and `error.code` only, never the response body.

## 2026-11-12 (truncated summaries)

- Bug: summaries cut mid-sentence were cached as ready. Per-prompt `max_tokens` overrode the task budget and reasoning
  models spent it on thinking (finish_reason=length). `max_tokens` is now the answer budget; `[llm] reasoning_headroom_tokens`
  (2048, per-task override, 0 allowed) is added to each request. `chat_result` retries once with double budget on length; if
  still cut the text gets " …", is logged kind=truncated and summaries are stored under the ad-hoc key (ad-hoc TTL).
- Built-in prompt budgets raised: tldr 700, answer-title 400, takeaways 900, worth-it 600, eli-new 700.

## 2026-11-12 (LLM backpressure)

- Production: the TV triggers /v1/assess per row, background triage saturated a fail-fast
  endpoint (503 engine_busy at its concurrency cap) and an interactive summary failed. Some
  triage calls failed with `no JSON found` (reasoning model, content empty or cut at max_tokens).
- `llm.py`: per-provider `PriorityLimiter` (`max_concurrent`, default 2; interactive before
  background; `reserved_interactive` slots background cannot take). Replaces the global
  `llm.max_concurrency`. Retries on 429/502/503/504 and connection errors with exponential
  backoff + jitter and Retry-After (seconds or date), bounded by a per-task deadline
  (`deadline_interactive_s`, `deadline_background_s`); never on other 4xx. Per-task
  `fallback = ["provider:model"]` after the prompt's own model; not used after a 4xx.
- JSON: `json_mode` per provider sends `response_format`; empty content with reasoning is a
  failure (reasoning is never parsed), retried once with `json_retry_max_tokens` and a
  "JSON only" nudge; failure kind logged (empty, truncated, no-json) without content. Plain
  `chat` also raises on empty output instead of caching an empty summary.
- `assess.py`: `coalesce_ms` window merges uncached videos from concurrent requests into shared
  batches (full batch flushes at once, in-flight dedupe unchanged).
- `errors.py`: busy failures surface as "the language model is busy, try again in a moment".
- Tests: `tests/test_backpressure.py` plus mock server knobs (busy, Retry-After, empty content).
  Docs: `docs/llm-providers.md` section "Fail-fast endpoints and backpressure".

## 2026-11-12 (overnight build)

- Built the backend: config, SQLite, OpenAI-compatible client (think-block and fence tolerant,
  one JSON retry), yt-dlp transcripts, batched triage plus tier-2 deep analysis, prompt sets,
  summaries/insight/ask with map-reduce, HQ caption pipeline with persisted job queue, web UI.
- Verified against real YouTube (metadata + captions for `jNQXAC9IVRw`) and real
  faster-whisper `small` int8 on CPU (19 s clip transcribed in about 7 s after model load).
  Needed `av<16`: PyAV 17+ breaks faster-whisper 1.2.1 (`metadata_errors`).
- Renamed project to u·tubot (package `utubot`, env `UTUBOT_*`).
- Hardening for public exposure: all routes token-gated except health/pair/app update,
  per-token and per-IP rate limits, body cap, strict 11-char video ids, constant-time compare,
  trusted-proxy X-Forwarded-For, docs endpoints disabled.
- Pairing: one-time 6-digit codes (hashed, 15 min), lockout per IP and globally, per-device
  revocable tokens, admin routes and UI.
- App update channel and `utubot app publish`.
- Multiple named LLM providers, per-task selection, `provider:model` prompt overrides.
- Pyannote diarization (community-1, token from `UTUBOT_HF_TOKEN`) implemented and tested with a
  stub only; not installed (torch) and no token tonight.

## 2026-11-12 (review fixes)

- SSRF: prompt-set import now goes through `urlguard.py`: every hop (manual redirect loop, max 5)
  needs http/https, default port, and only public resolved addresses (loopback, RFC1918,
  link-local, CGNAT, ULA, multicast, reserved, unspecified, mapped/6to4/NAT64/Teredo). The
  connection is pinned to the validated IP (Host header + SNI of the original name), so DNS
  rebinding between check and connect is closed. `summary.import_allow_hosts` bypasses it.
  The only other outbound fetch of a URL is the yt-dlp caption URL (from YouTube, not the caller).
- Error leakage: background/content/job failures return generic messages; details are logged
  server-side. Fetch/JSON errors no longer echo exception text.
- config.example.toml now holds working defaults (faster_whisper small int8, 4 threads,
  tier-2 cap 100, /var/lib/utubot paths).
- VTT accepts the Authorization header (already did via bearer; now tested and documented);
  `?token=` documented as discouraged.
- deploy: the service unit runs the venv binary with hardening and cache dirs under
  /var/lib/utubot/cache; README updated.

## 2026-11-12 (release preparation)

- `GET /setup.json` (public, rate limited) with `[setup]` config: name, backend and update URLs,
  pairing flag, app switch defaults and optional prompt set URLs, so a TV can configure itself
  from a short address. Documented in `ai/CONTRACT.md`.
- `utubot app publish` accepts several APKs, one per ABI (detected from `..._<abi>.apk`, or
  `--abi` for one file). It writes `downloadUrlList_<abi>` and `downloadUrlList` in update.json,
  plus `latest.json` (file names, sizes, sha256). `/app/latest/<abi>.apk` redirects (302) to the
  versioned file, so Downloader codes never change. `/app/info.json` and a public Download
  section on `/` (shown without a token) list the latest version, links and `[app]
  downloader_codes`.
- `security.trusted_proxies` now defaults to loopback only; add a reverse proxy address
  explicitly (docs/server.md).
- Version 0.2.0.
## 2026-11-26 (P1 review r4 fixes: user classes)

- Watched builds now yield to prime after their current grid. `describe_scenes` takes a
  `yield_check` and runs it once per grid; `WatchedBuilder.build`/`_describe` thread it through,
  and `CutService._run_build` drives it from `_wait_for_prime`. A running normal watched build
  therefore stops after the grid it is on while a prime demanding job waits, and the prime build
  takes the slot and runs before the normal one resumes with the same stored TDT (describing is
  resumable per grid). Replaced the mocked-builder wait test with one that drives the real
  describing loop (vision call mocked) and asserts the pause and that the prime build actually
  runs and finishes, then the normal build resumes.
- The watched yield no longer deadlocks. The single watched-build slot was held across the yield,
  so a normal build yielding to a prime build held the slot the prime build needed and neither
  finished. `_wait_for_prime` now releases the slot while a normal build waits and re-acquires it
  afterwards (`_watched_held` tracks what a request currently holds so the finally does not
  double-count); the prime build takes the freed slot and runs, then the normal build resumes.
- Caption/transcript jobs yield the same way. The single caption worker ran a job to completion,
  so a normal job yielding at an ASR-chunk boundary blocked the worker and the queued prime job
  could never be claimed. `_yield_to_prime` now calls `ClassGate.yield_if_prime`, which raises
  `JobYielded` instead of blocking; `JobQueue.run_one` puts the job back in the queue and returns,
  so the worker claims the prime job first and re-claims the normal one once no prime work is
  active. The job resumes from its saved state (its transcript and ASR cache are kept). Added a
  test that runs a running normal caption job against a queued prime job.
- `reserved_prime` only applies with `[classes]`: `Config.classes_configured` records whether the
  section was loaded and `LLMClient.limiter` keeps the slot only then, so without `[classes]` the
  route model is used exactly as before.
- Removed the dead `yield_check` map-reduce path in `CutEngine` (watched builds never call
  `pick_parts`); the yield now lives in the describing stage where it is reachable.
