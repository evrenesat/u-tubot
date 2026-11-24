# Director's cuts: quick and watched modes (plan)

Status: draft, waits for the owner's decisions (Part 1) and a plan review. Nothing is implemented.
Scope: two ways to build a director's cut. **Quick** is today's cut, made from the transcript only, and stays the default.
**Watched** is made from what is on screen plus what is said: the server downloads a small copy of the video, looks at
sampled frames with a vision model, and gives the editor model both. The mode is a server default, a per-user default and a
per-request choice, in the TV app and in the browser extension.
Related: #82 (target length is not enforced), #83 (quality review of the caption-based cut), #34 (media archive),
`ai/CONTRACT.md` ("Director's cuts"), `ai/BROWSER_EXTENSION_PLAN.md` (parity rule).

---

# Part 1: owner plan

## What changes for you

- The cut picker (TV, phone cut sheet, later the extension's Cut tab) gets a mode switch: **Quick (default)** and
  **Watched · about N min**. Pick a preset or describe a cut as today; the switch decides how it is built.
- Quick behaves as now: ready in seconds once a transcript exists.
- Watched runs in the background. You keep watching; the player says "Watched cut ready" with the one-press Apply it already
  has for cuts built on the phone. The phone's cut sheet shows a progress bar with the step it is on (video, frames,
  describing, editing).
- Watched can cut what quick cannot see: a demo with no talking, slides, a sponsor card on screen, "as you can see here".
- Both modes hold the preset's target length (the #82 fix is shared code, not done twice).
- If a watched cut fails, the picker says why and offers Quick with one press. A quick cut that is already ready stays usable
  while the watched one builds.
- Frames stay on your own engines. A cloud vision model is possible only behind a switch that is off.

## Time and space per video

All figures are estimates until checkpoints 2, 3 and 5 measure them on your engines; the picker shows the server's own
estimate, corrected from the last finished watched jobs.

| | Quick | Watched, first cut of a video | Watched, another preset of the same video |
|---|---|---|---|
| 20-minute video | 10 to 30 s | about 5 to 10 min | 20 to 60 s (the frames are already described) |
| 60-minute video | 20 to 60 s | about 8 to 15 min | 30 to 90 s |
| Stored | nothing new | a 360p video-only copy, about 50 to 100 MB per 20 min, in the media archive | nothing new |

One watched job runs at a time; others wait in line and say so.

## Decisions needed from you

1. **Default mode: Quick** (recommended). Watched is chosen per video, or set as your personal default in Settings.
2. **Vision model: local, picked by a measurement** (recommended). Checkpoint 3 runs a small frame test on your engines over
   the candidates (the model family behind the alias the cuts use today, which the gateway already lists with image input;
   Qwen3.6-35B-A3B; gemma-4-26B) and records the pick next to the existing cut-model pick. Alternative: you name the model
   now and the test only confirms it.
3. **Cloud vision: off** (recommended). The switch exists (`allow_cloud_frames`), is off by default, and when on the picker
   says "Watched (cloud)". Alternative: not building the switch at all.
4. **Keep the small video copy in the media archive** (recommended, same rule as audio in #34: a second look with a better
   model needs no new YouTube download; the archive quota is the limit). Alternative: delete it once the frames are described.
5. **Longest video for Watched: 90 minutes** (recommended; longer ones answer "too long for Watched, use Quick").
6. **When Watched fails: offer Quick with one press** (recommended). Alternative: fall back to Quick automatically and say so.

## Risks

- The local vision model may be too slow or too vague. Checkpoint 3 measures it before anything is built on top; if no local
  model passes, the plan stops there and you decide about decision 3.
- Watched may not beat Quick on ordinary talking videos. Checkpoint 5 measures both; if Watched is not better where the screen
  matters, it stays behind a server switch that is off.
- Each watched cut is one more media download through the YouTube gate. It shares the gate's pacing and breakers, so a blocked
  media class makes Watched unavailable, not Quick.

---

# Part 2: agent plan

## 1. Facts checked (repository state at `7868a34a`)

- Cuts: `ai-backend/src/utubot/cuts.py`. `build_units` merges caption fragments into numbered units; `serialize_units`
  writes the user message; `[llm.cuts]` answers JSON with unit id ranges; `parse_cut_answer`, `finalize_parts`,
  `cut_document`. `CutService` runs one async task per request, resumes `building` rows after a restart, shares one build per
  cache key `sha256(video|version|model|transcript_hash)`. Request stages: `transcript`, `model`, `checking`.
- Target length (#82, open): the length is only a sentence in the preset; `finalize_parts(guard=False)` accepts any length
  for `cut-highlights-5`. #82 specifies `target_s`, a tolerance, ranked parts and server-side selection.
- Bench: `cutbench.py` holds five invented transcripts with hand-marked keep and skip spans and scores a model callable; no
  network. The recorded pick is `ai-backend/fixtures/cuts/CHOICE-2026-11-20.md` (about 6 to 7 s per request on short
  transcripts).
- Media: `media_archive.py` stores files content-addressed with one row per `(video_id, kind)`; `KIND_VIDEO` is defined and
  unused. Only audio is downloaded today (`captions/pipeline.py` `download_audio`, through `YoutubeGate.run_started`, class
  `media`). `ffmpeg` is already required on `PATH`. The archive never deletes by itself; `DELETE /v1/admin/archive/{id}` is
  the only cleanup.
- LLM client: `llm.py` sends string message content only; `LLMTask` has `model`, `provider`, `fallback`, `reasoning_effort`,
  `max_tokens`. Priorities `INTERACTIVE` and `BACKGROUND` exist.
- Offline rule: `[youtube] offline` answers from caches and cassettes; cassettes hold no media ("recorded media is large and
  belongs in the media archive"). `tests/conftest.py` blocks YouTube for every test.
- Clients: TV picker `UtubotMenu.showCuts`, player side `UtubotCutController`, `UtubotCutFollower` (long-polls a request with
  `wait_ms` 10000), `UtubotCutSkipper`, `UtubotCutSeekBar`; phone cut sheet `web/ui/js/pages/cuts.js`; mock
  `scripts/emulator_mock_backend.py`; the extension does not exist yet (its cut picker is checkpoint 16 of the extension plan,
  cut playback checkpoint 8).
- Earlier design reused (the owner's private film-editing project, no application code, so ideas only): shot boundaries are
  technical observations and not scenes; every editorial claim cites supplied ids; unknown visual content stays unknown; a
  text-only model never invents what was on screen; frames go only to an endpoint the owner enabled; model output is untrusted
  JSON validated against supplied ids; caches are keyed by model, prompt and input fingerprints.

## 2. Decisions (all made, owner decisions of Part 1 assumed as recommended)

### 2.1 Modes and how one is chosen

1. Two mode ids: `quick` and `watched`. A cut, a request and a cache row each carry one.
2. Server default: `[cuts] default_mode = "quick"`. Watched exists only when `[llm.cuts_vision]` is configured and
   `[cuts.watched] enabled = true`; otherwise it is listed as unavailable with a reason and a build request for it answers
   `409 {"error":"Watched cuts are not configured on this server."}`.
3. Per-user default: `UserPolicy.cut_mode` (`null` follows the server; `"quick"`; `"watched"`), with the usual settings
   plumbing (`settings.py` `SECTION_FIELDS`, docs, contract, a test). A user default of `watched` on a server without it
   resolves to `quick`.
4. Per request: `POST /v1/videos/{id}/cuts` and `PUT /v1/cut-requests/{id}` take an optional `"mode"`. Omitted means the
   caller's resolved default. Unknown value: `400`.
5. The duplicate-request rule and the per-user build cap count a request by (video, preset or prompt, mode).

### 2.2 The watched pipeline

Stages, in order, each a job-report stage through `captions/events.py`. Transcript and video are fetched concurrently.

| # | Stage (`stage` value) | What it does | Cached by |
|---|---|---|---|
| 1 | `transcript` | As today (`_ensure_transcript`). A video with no speech at all is allowed in watched mode | transcript store |
| 2 | `video` | Archive lookup `(video_id, KIND_VIDEO)`, else one download through the gate, stored in the archive | archive row |
| 3 | `shots` | One `ffmpeg` pass over the file: shot boundaries | `video_scenes` row |
| 4 | `frames` | The frame plan (which timestamps), then JPEG extraction into scratch | plan in `video_scenes`; frames are scratch |
| 5 | `describing` | The vision model describes the frames in batches; `progress` counts frames done | `scene_descriptions` row |
| 6 | `model` | Scene lines and transcript units joined into one document; `[llm.cuts]` picks unit ranges | `cuts` row |
| 7 | `checking` | Validation, target-length selection (#82), boundary snap, padding and merge, guards | part of the `cuts` row |

**Video download.** A new `download_video` next to `download_audio`, same gate call (`run_started`, class `media`,
`BACKGROUND` priority, key `video:<id>`), same failure classification, no URL in any log. Video only, no audio. Selector
`[cuts.watched] video_format = "bestvideo[height<=360][ext=mp4]/bestvideo[height<=360]/best[height<=360]/worst"`,
`video_max_bytes = 1073741824`, `max_video_minutes = 90` (checked from the known length before any download; unknown length
is asked through `ensure_length` first). `archive.require_room()` before the download. Offline mode: archive only, else the
existing offline answer.

**Shots.** `ffmpeg` scene score on a reduced stream (`analysis_fps = 2`, `analysis_width = 320`, `scene_threshold = 0.30`),
parsed from the filter's metadata output; no new Python dependency. Shots shorter than `min_shot_s = 2.0` join the previous
one. Behind a small `ShotDetector` protocol so a second detector can be added. PySceneDetect (BSD-3-Clause, with OpenCV,
Apache-2.0) is licence-compatible and is the named alternative; it is added as an optional extra only if checkpoint 2's
boundary test fails with `ffmpeg` (it brings OpenCV and numpy into a small server).

**Frame plan** (pure function, deterministic, versioned by `FRAME_PLAN_VERSION`):

- one frame at the middle of every shot (never on the boundary, where transitions blur);
- in a shot longer than `long_shot_every_s = 30`, one more frame every 30 s (screen recordings and talking heads have few
  hard cuts);
- caps: `frames_per_minute_max = 6` and `max_frames = 240`. Over a cap: first thin the extra long-shot frames evenly, then
  join the shortest shots into their neighbours until the plan fits;
- extraction: JPEG at the stored height (360), `jpeg_quality = 4` (ffmpeg scale), in batches of at most 100 timestamps per
  `ffmpeg` process.

**Vision model.** A new task table `[llm.cuts_vision]` (same fields as other tasks; no default, like `[llm.cuts]`). Candidates
for the owner's server, measured in checkpoint 3: the model family behind the gateway alias the cuts already use (the
gateway lists it with image input), Qwen3.6-35B-A3B, gemma-4-26B. The pick is the alias with the best frame-test score among
those under `describe_s_per_frame_max = 4.0`; recorded in `ai-backend/fixtures/cuts/VISION-CHOICE-<date>.md`.
`llm.py` gains message content parts (`[{"type":"text"},{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}]`),
OpenAI-compatible, nothing provider-specific.

**Describing.** `describe_batch = 6` consecutive frames per call, each introduced by a text part
`Frame <k> at <mm:ss>`. System prompt: describe only what is visible, never guess, say `unknown` when unsure. Answer JSON:
`{"frames":[{"k","kind","text","on_screen_text","same_as_previous"}]}` with `kind` one of `talking_head`, `screen`, `slide`,
`demo`, `broll`, `title_card`, `sponsor_card`, `other`; `text` at most 200 characters; `on_screen_text` at most 120.
Validation: every `k` of the batch exactly once, known `kind`. One repair round per batch, then the batch's frames are marked
`not_seen`. More than `max_unseen_frac = 0.2` unseen frames fails the watched build; less proceeds and the cut says
`"partial": true`. Calls run at `BACKGROUND` priority with `describe_concurrency = 1`.

**Join.** New unit builder for watched mode, sharing `build_units`:

- speech units as today;
- a gap without speech longer than `silent_unit_min_s = 4.0` becomes `(no speech)` units, split at shot boundaries and at
  `unit_max_s`, numbered in the same sequence (so a silent demo can be kept by id like anything else);
- scene lines are written before the first unit they cover; a unit belongs to the shot it overlaps most; consecutive lines
  with the same `kind` and `same_as_previous` collapse into one line with the whole range.

```
Scenes and transcript (lines starting with S are what is on screen, lines starting with # are units you can keep):
S7 [03:10-03:55] screen: terminal, a build runs and stops; text: "error: linker failed"
#41 [03:10-03:18] so when I run it you can see it fails
#42 [03:18-03:31] (no speech)
```

On-screen text is untrusted data. It reaches only the editor model, whose answer is unit ids validated against the supplied
units, so the worst outcome of a hostile frame is a poor cut.

**Editorial call.** The text model `[llm.cuts]`, the same presets and instructions as quick, the same answer format (the one
#82 lands: ranked parts with a reason). The system prompt gains two sentences for watched mode (scene lines are evidence, only
`#` ids can be kept). `[cuts.watched] max_input_tokens = 48000`; over it, scene `text` is dropped from collapsed
`talking_head` runs first, then the build is refused with the existing "too long" message.

**Boundary snap.** After the #82 selection and before padding: a part's start moves back to a shot boundary, and its end
forward to one, when the boundary is within `snap_s = 1.0` and no speech unit lies in between. Never inward, never across
speech.

### 2.3 Target length (#82) in both modes

- #82 lands first for quick. Its selection (`target_s`, tolerance, ranks, trim at a unit boundary, one re-ask with the
  measured length) lives after `parse_cut_answer`, on units, so watched uses it unchanged; `(no speech)` units are ordinary
  units to it.
- The band is checked on the final document's `kept_ms` (after snap, padding and merge) in both modes.
- The real length is shown next to the label in both modes ("Highlights · 5:02", with "· Watched" when it is).
- Checkpoint 4 does not start before #82 is merged; checkpoints 1 to 3 do not depend on it.

### 2.4 Caching

- Video file: archive, one per video (`kind = "video"`).
- `video_scenes`: key `(video_sha256, FRAME_PLAN_VERSION + detector settings hash)`; shots and the frame plan as JSON.
- `scene_descriptions`: key `sha256(video_sha256 | plan key | vision model | describe prompt hash)`; shared by every preset,
  prompt and user. This is the expensive part and is paid once per video.
- `cuts`: the quick key stays byte-for-byte as it is (existing rows stay valid). The watched key is
  `sha256(video | version | model | transcript_hash | "watched" | descriptions key)`. New column `cuts.mode`.
- In-flight sharing (`_inflight`) is per key as today; a second watched request for the same video waits on the same
  describing work through a per-video lock.
- `DELETE /v1/admin/archive/{video_id}` also removes the video's `video_scenes` and `scene_descriptions` rows and counts
  them in its answer.

### 2.5 Budget, queue and what the user is told

- `[cuts.watched] max_concurrent = 1` server-wide; waiting requests are `building` with `stage = "queued"`.
- Request documents gain `mode`, `progress` (0 to 1; weights video 0.1, frames 0.1, describing 0.6, model 0.2) and `eta_s`.
- `eta_s` before the build: planned frames (or `frames_per_minute_max` x minutes when unknown) x seconds per frame, plus a
  fixed part; seconds per frame is the median of the last `eta_window = 20` finished watched jobs, `eta_s_per_frame = 3.0`
  until there are any. During the build it is recomputed from the frames left.
- `build_timeout_s = 1800`: a watched build that runs longer fails with "Watched took too long".
- Texts: picker "Watched · about 7 min"; on start "Watched cut is being prepared, about 7 min. Keep watching."; ready, as
  today, "Cut ready" with Apply.

### 2.6 Storage and cleanup

- Video: kept in the archive under its quota (owner decision 4). `keep_video = true`; with `false` the file and its archive
  row are removed when the descriptions are stored.
- Frames: scratch under the media scratch directory, `watched/<request id>/`, removed when describing ends (success or
  failure). `keep_frames = false` exists for debugging. The existing scratch sweep removes leftovers after a crash.
- Before a watched build: free space on the archive and scratch filesystems must exceed `min_free_bytes = 2147483648` plus
  the expected size, or the build fails with a clear message before any download.
- Nothing visual is stored in the database: descriptions are text.

### 2.7 Privacy

- Frames are sent only to the provider of `[llm.cuts_vision]`. `docs/privacy.md` gains this, the stored video copy, and the
  description text.
- `[cuts.watched] allow_cloud_frames = false`. While false: `fallback` entries of `[llm.cuts_vision]` must be on the same
  provider (config validation error otherwise), and the docs tell the admin to give that provider a gateway key that is not
  allowed to reach cloud engines (modelgate: a client without `allow_cloud`), so a re-routed alias is refused by the gateway
  and the watched build fails over to the Quick offer instead of sending frames out. The backend cannot see where an alias
  is routed; the guarantee is the gateway key.
- While true: `modes[]` carries `"cloud": true`, clients label the mode "Watched (cloud)", and `GET /v1/admin/status` says
  so.
- The description text does reach `[llm.cuts]` (as transcripts do today).

### 2.8 Failures and fallbacks

| Failure | Result |
|---|---|
| Watched not configured, video too long, live stream | refused at request time (`409`), nothing queued |
| Video refused by YouTube, media class blocked, archive full, disk reserve | request `failed`, plain reason |
| Vision model unavailable, gateway refusal, over 20 % frames unseen, timeout | request `failed`, plain reason |
| Editor model failure | as today |

A failed watched request document carries `"fallback":{"mode":"quick","state","request_id"?,"cut"?}` (the quick state of the
same preset or prompt). Clients show the reason and one action: "Use Quick" (applies a ready quick cut or posts the same
request with `"mode":"quick"`). `auto_fallback = false`; with `true` the server queues the quick request itself and the
request document says so. A partial watched cut (`"partial": true`) is applied normally and labelled "Watched (partly seen)".

### 2.9 Contract changes (all additive; `ai/CONTRACT.md`, "Director's cuts")

- `GET /v1/me` features: `"cuts_watched": bool`.
- `GET /v1/videos/{id}/cuts`: adds `"default_mode"`, `"modes":[{"id","label","default":bool,"available":bool,"reason"?,
  "eta_s"?,"cloud"?}]`; each preset adds `"by_mode":{"quick":{state fields},"watched":{state fields}}`. The preset's existing
  top-level `state`, `request_id`, `error`, `cut` keep describing the caller's default mode, so a client that ignores the new
  fields behaves as today.
- `POST /v1/videos/{id}/cuts`, `PUT /v1/cut-requests/{id}`: optional `"mode"`.
- Request document: `mode`, `progress`, `eta_s`, `fallback`; `stage` gains `queued`, `video`, `shots`, `frames`,
  `describing`.
- Cut document: `"mode"`, and for watched `"watched":{"frames":n,"model":"<alias>","partial":bool}`. `version` stays 1.
- `GET /v1/processed`: each cut entry gains `mode`.
- Settings document: `cut_mode`.
- Database (additive, `test_db_migrations.py`): `cut_requests.mode TEXT NOT NULL DEFAULT 'quick'`, `cut_requests.progress
  REAL`, `cuts.mode TEXT NOT NULL DEFAULT 'quick'`, tables `video_scenes`, `scene_descriptions`.

### 2.10 Clients (parity)

| | TV app (`stutubot`) | Phone web UI | Browser extension |
|---|---|---|---|
| Mode switch | First row of the cut picker (`UtubotMenu.showCuts`): "Mode: Quick (default)" / "Watched · about N min"; unavailable mode greyed with its reason; the choice holds for this picker session | Segmented control on the cut sheet and in "New cut" | Same control at the top of the Cut tab and in "Describe here" |
| Default marked | "(default)" from `modes[].default` | Same | Same |
| Preset states | From `by_mode[selected]` | Same | Same |
| Progress | Start toast with the estimate; `UtubotCutFollower` follows the request to ready; the ready announcement is unchanged | Progress bar, stage text, estimate | Stage text and estimate in the Cut tab |
| Failure | Dialog line with the reason and "Use Quick" | Same on the cut sheet | Same in the Cut tab |
| Length and mode label | "Highlights · 5:02 · Watched" in the picker and the Processed tile | Same | Same |
| Personal default | Read only (shown as default); changed in the web UI Settings | Settings page, "Cut mode" | Read only |

The extension has no cut picker yet. Following the standing rule's transition clause, checkpoint 1 adds a parity-matrix row
("Cut mode: quick or watched, default marked, progress, Quick offer on failure") to `ai/BROWSER_EXTENSION_PLAN.md` and extends
rows 18, 19 and 20; extension checkpoints 8 and 16 then build it. If those checkpoints have already landed when checkpoint 6
of this plan runs, the extension change is part of checkpoint 6. No "Clients" exception is needed.

`scripts/emulator_mock_backend.py`: `modes`, `by_mode`, `mode` on requests, `--cuts-watched-delay` (default 20 s) with the
stage sequence and `progress`, `/__mock/cuts?...&mode=` and a `state=failed&mode=watched` case with `fallback`.

### 2.11 Evaluation

- **Frame test** (`scripts/frame_bench.py`, run by hand against a real endpoint, never in CI): frames rendered by `ffmpeg`
  from known content (text slides at three sizes, a terminal-like text block, colour scenes, a title card), at 360 and 480
  lines. Scores: on-screen text recall, `kind` accuracy, valid JSON rate, seconds per frame. Picks the vision model and
  confirms or changes the 360-line choice.
- **cutbench, watched mode**: every fixture gains hand-written scene lines (no video, no vision model: this measures the join
  and the editor). Three new fixtures where the transcript alone misleads: a silent demo (the must-keep span has no speech),
  a walkthrough where the talk refers to the screen ("as you can see here") and the screen decides relevance, and a sponsor
  card shown while the talk sounds on-topic. `scripts/cut_bench.py --mode quick|watched|both`; the report adds per-mode
  columns, #82's length-accuracy column, and `visual keep` (recall on spans marked as screen-only).
- **Labelled set** (owner's server, never CI, never in the repository): six real videos the owner chose, two presets each,
  hand-marked keep and skip ranges in a small JSON file under `[cutbench] labelled_dir`. Media and cassettes are recorded by
  the owner (`utubot youtube-record` plus the archive); the run uses offline mode. Reports both modes side by side with a
  readable sample of the kept parts.
- **Gate** (checkpoint 5): on the three visual fixtures watched scores at least 0.15 higher than quick; on the other
  fixtures it is no more than 0.03 lower; length accuracy inside #82's band in both. If the gate fails, `[cuts.watched]
  enabled` stays `false` in the example config and the finding is filed as an issue.

### 2.12 Tests (never YouTube, never a real model)

- Synthetic video: `tests/synth_video.py` builds a 30 s clip with `ffmpeg` (`lavfi` sources, four hard cuts, drawn text),
  as `synth_speech.py` does for audio. Tests needing `ffmpeg` skip without it, like the existing media tests.
- `tests/mock_openai.py` accepts image content parts and answers the describe format (plus modes: invalid JSON once, missing
  `k`, refusal).
- The fake downloader pattern of `test_media_archive.py` supplies the video; `block_youtube()` stays autouse.
- Per checkpoint, see the table.

## 3. New and changed files (backend)

- `src/utubot/watch/__init__.py`, `watch/video.py` (download, archive), `watch/shots.py` (detector protocol, ffmpeg
  detector), `watch/frames.py` (plan, extraction), `watch/describe.py` (prompt, batching, validation, cache),
  `watch/join.py` (silent units, scene lines, snap), `watch/service.py` (the stage runner, queue slot, progress, eta).
- `cuts.py` (mode on requests, key, branch in `_run_build`, fallback field), `llm.py` (content parts), `config.py` and
  `config.example.toml` (`[llm.cuts_vision]`, `[cuts] default_mode`, `[cuts.watched]`, `UserPolicy.cut_mode`), `db.py`,
  `media_archive.py` (remove hook), `settings.py`, `processed.py`, `cutbench.py`, `prompts.py` (describe prompt, watched
  sentences), `web/ui/js/pages/cuts.js`, the settings page, `job.js`/`jobtext.js` (new stages).
- Docs: `ai/CONTRACT.md`, `docs/server.md` ("Director's cuts", "Job details"), `docs/privacy.md`, `docs/llm-providers.md`,
  `ai/APP_INTEGRATION.md`, both devlogs.

## 4. Checkpoints

One pull request each. Every checkpoint ends with a clean-context review before the next starts. Tiers as in the extension
plan (Fast: straightforward from this plan; Heavy: the tricky parts).

| # | Scope | Done when | Tests | Tier |
|---|---|---|---|---|
| 0 | Gate, not work of this plan: #82 merged | `main` has `target_s` and the ranked selection | #82's own | n/a |
| 1 | Mode plumbing with quick only: contract text, `mode` on requests and cuts, `modes` and `by_mode`, `default_mode`, `UserPolicy.cut_mode`, additive columns, watched listed as unavailable, mock backend modes, parity-matrix row | old request bodies answer exactly as before (replayed in a test); `mode:"watched"` answers the 409; settings round trip; quick cache keys unchanged (a stored row from before is still served) | `test_cuts_api.py`, `test_settings.py`, `test_db_migrations.py`, `test_emulator_mock.py` | Fast |
| 2 | Video, shots, frames, no model: `watch/video.py`, `shots.py`, `frames.py`, archive `kind=video`, limits, disk checks, scratch cleanup, archive remove hook | the synthetic clip's four cuts are found within 0.5 s; the plan obeys every cap on generated shot lists (property-style cases); a second run downloads nothing; frames are gone after the stage; over-limit and full-archive cases fail before a download; measured size and time for one real video recorded by the owner's server in the devlog | `test_watch_video.py`, `test_watch_shots.py`, `test_watch_frames.py`, `test_media_archive.py` | Heavy |
| 3 | Vision: content parts in `llm.py`, `[llm.cuts_vision]`, `describe.py` with batching, validation, repair, cache, the cloud rule; `frame_bench.py`; the model pick | mock: descriptions cached per key, one repair round, unseen marking and the 20 % rule, same-provider fallback rule; frame test run on the owner's engines for every candidate and the pick recorded with seconds per frame; if none passes, stop and report | `test_watch_describe.py`, `test_llm_parts.py`, config tests | Heavy |
| 4 | The watched build: `join.py`, `service.py`, branch in `CutService`, snap, #82 selection reused, queue slot, progress and eta, timeout, failures and `fallback`, job-report stages, admin status | end to end on the synthetic clip with the mock models: a watched request goes through every stage to a ready cut whose kept ranges include the silent part; restart mid-build resumes and reuses the caches; second preset skips stages 2 to 5; each failure row of 2.8 produces its document; the band holds after snap | `test_cuts_watched.py`, `test_watch_join.py`, `test_job_report.py` | Heavy |
| 5 | Evaluation: cutbench scene lines, three visual fixtures, `--mode`, report columns; the labelled-set runner; the gate | bench numbers for both modes recorded in `fixtures/cuts/`; gate result stated; labelled-set run recorded (numbers and a readable sample) by the owner's server | `test_cutbench.py` | Fast |
| 6 | Clients: TV picker row, follower over long builds, texts, labels, failure dialog; web UI control, progress, settings, failure offer; extension side per 2.10 | TV unit tests for the picker model and parser with the new fields; emulator run against the mock (`--cuts-watched-delay`) recorded: pick Watched, keep playing, ready announcement, Apply; failed case shows "Use Quick"; web UI tests for the control and the progress view | `UtubotCut*Test`, `test_webui.py`, emulator recipe in `docs/development.md` | Fast |
| 7 | Owner trial and switch-on: docs complete, example config, the owner's server enables watched | the owner built watched cuts for at least three videos from the TV and the phone and each finding is fixed or filed | recorded in the devlog | Fast |

Order: 1, then 2, 3, 4, 5 in sequence; 6 may run beside 2 to 5 once 1 has landed (it needs only the contract and the mock).
4 needs checkpoint 0.

## 5. Could not be verified from here

- Whether the local builds of Qwen3.6-35B-A3B and gemma-4-26B accept image input through the gateway. The gateway lists its
  discovered models as text-only by default; only the alias family the cuts use today is listed with image input, and that
  listing was read, not probed with an image.
- Every time and size figure in Part 1: seconds per frame on the local engines, the size of a 360p video-only stream, the
  download time under the gate's pacing. Checkpoints 2 and 3 measure them.
- Whether 360 lines are enough for the vision model to read slide text (frame test, checkpoint 3).
- The quality of `ffmpeg`'s scene score on screen recordings and slow fades compared with PySceneDetect (checkpoint 2 tests
  hard cuts only; the labelled set shows the rest).
- That a 360p video-only format exists for every video (the selector falls back to the smallest combined format).
- The exact answer format #82 will land; this plan follows the issue text and adapts in checkpoint 4.
- That the TV's cut parser ignores unknown fields and that `UtubotCutFollower` keeps following a request for 15 minutes
  (read, not run; checkpoint 6 tests both).
- Whether watched is better than quick at all on real videos (checkpoint 5).
