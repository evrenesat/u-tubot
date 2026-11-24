# Director's cuts: quick and watched modes (plan)

Status: draft, revision 5 (revision 4 added Phase 2 at the end and the vision-model shortlist of the owner's model
research; revision 5 answers the phase 2 review and revision 6 its re-check, P.7; revision 7 adds 2.13; revision 2 made the watched mode reuse the owner's earlier scene-analysis code; revision 3
answers the plan review, section 6). Waits for the owner's decisions (Part 1). Nothing is implemented.
Scope: two ways to build a director's cut. **Quick** is today's cut, made from the transcript only, and stays the default.
**Watched** is made from what is on screen plus what is said: the server downloads a small copy of the video, turns it into
timestamped 2x2 picture grids, has a vision model describe each grid, and gives the editor model the descriptions together
with the transcript. The mode is a server default, a per-user default and a per-request choice, in the TV app and in the
browser extension.
Related: #82 (target length is not enforced), #83 (quality review of the caption-based cut), #34 (media archive), #88 and #89
(later features that shape the data model now, 2.13),
`ai/CONTRACT.md` ("Director's cuts"), `ai/BROWSER_EXTENSION_PLAN.md` (parity rule), and the `scene-analyser` directory of
the owner's public repository `evrenesat/r2t4` (the analysis engine reused here).

---

# Part 1: owner plan

## What changes for you

- The cut picker (TV, phone cut sheet, later the extension's Cut tab) gets a mode switch: **Quick (default)** and
  **Watched · about N min**. Pick a preset or describe a cut as today; the switch decides how it is built.
- Quick behaves as now: ready in seconds once a transcript exists.
- Watched runs in the background. You keep watching; the player says "Watched cut ready" with the one-press Apply it already
  has for cuts built on the phone. The phone's cut sheet shows a progress bar with the step it is on (video, grids,
  describing, editing).
- Watched can cut what quick cannot see: a demo with no talking, slides, a sponsor card on screen, "as you can see here".
- The watching part is your scene-analyser code (grid extraction, frame selection, running context, the Timed Descriptive
  Transcript), copied into the backend and adapted, not written again.
- Both modes show the cut's real length, and both hold the preset's target length once #82 is merged (that fix is a
  separate task already in work; it is shared code, not done twice, and the last two backend checkpoints wait for it).
- If a watched cut fails, the picker says why and offers Quick with one press. A quick cut that is already ready stays usable
  while the watched one builds.
- Grids stay on your own engines. A cloud vision model is not part of this plan.

## Time and space per video

**The watched times are a guess until checkpoint 3 measures them on your engines.** They are arithmetic from your
scene-analyser runs of March 2026 (a 58-minute episode on a laptop: grids for the whole
episode in 2.5 minutes; one grid described in 5.6 s by a 2B vision model and 13.8 s by Qwen3.5-35B-A3B, 21 grids each). Today's engines and
models were not measured, and one session of the same model was ten times slower. The grid counts for YouTube videos are
an estimate (see 2.2).

| | Quick | Watched, first cut of a video | Watched, another preset of the same video |
|---|---|---|---|
| 20-minute video (40 to 100 grids) | 10 to 30 s | 2 to 8 min if the big local engine does 2 to 5 s per grid as the model research expects; 5 to 25 min at the March laptop speeds | 20 to 60 s (the grids are already described) |
| 60-minute video (120 to 240 grids, capped) | 20 to 60 s | 4 to 20 min at the expected speed; 12 to 55 min at the March speeds | 30 to 90 s |
| Stored | nothing new | a 360p video-only copy, about 50 to 100 MB per 20 min (estimate), in the media archive | nothing new |

One watched job runs at a time; others wait in line and say so. The picker shows the server's own estimate, corrected from
the last finished watched jobs.

## Decisions needed from you

Decision 7 blocks checkpoint 2; the others can wait until the checkpoint that needs them.

1. **Default mode: Quick** (recommended). Watched is chosen per video, or set as your personal default in Settings.
2. **Vision model: Qwen3.6-35B-A3B, settled by a 45-minute bake-off** (changed; recommended). Your model research of
   24 Nov shortlists three models that are already installed on the big local engine: Qwen3.6-35B-A3B (8-bit, 40 GB, open
   licence, strong at reading text) as the default; Qwen3.8-Flash-Next (4-bit, 113 GB, licence not confirmed) if it is
   clearly better for at most twice the time; gemma-4-26B as a check from another model family. None of them was measured
   on pictures here. The bake-off (40 of your scene-analyser grids and 8 short clips, each model alone on the engine) is
   the first step of checkpoint 3 and needs a window in which the engine's usual big model is unloaded. Alternative: skip
   the bake-off and take the default.
3. **Cloud vision: not built now** (changed; recommended). No switch, no label. Pictures go only to the one provider you
   configure for the vision task. Alternative: build an off-by-default switch for a cloud model.
4. **Keep the small video copy in the media archive** (recommended, same rule as audio in #34: a second look with a better
   model needs no new YouTube download; the archive quota is the limit). Alternative: delete it once the grids are described.
5. **Longest video for Watched: 90 minutes** (recommended; longer ones answer "too long for Watched, use Quick" before
   anything is downloaded). Every video up to that length fits: a long or fast-cut video gets coarser grids, never a late
   refusal.
6. **When Watched fails: offer Quick with one press** (recommended). Alternative: fall back to Quick automatically and say so.
7. **Blocking: copy your scene-analyser modules into u·tubot under MIT** (recommended; the reply needed is "yes, MIT").
   `evrenesat/r2t4` is public but has no licence file, so nobody may reuse its code by default. You are the only author of
   that directory, so your word is enough: the copied files then carry a header naming their origin, and are MIT here.
   Optional and separate: add a licence to `r2t4` itself. Alternative: keep it out and write the analysis part new from the
   ideas (slower, and loses tested code).

## Next: phase 2

After the checkpoints of this plan: prime and normal users, a claim on the big local engine for prime picture work, a model
route per class (prime may use the claimed engine or the cloud, normal waits for a free local model), and an effort notch
for Watched (Keyframes, Standard, Dense). It is the last part of this file ("Phase 2"), with eleven decisions of its own
(D-P1 to D-P11), and blocks nothing above.

## Risks

- Watched is slow at the only speeds that were measured (March, a laptop): tens of minutes for a long video. The model
  research expects several times faster on today's engine; nothing confirms that before the bake-off. The plan caps the number
  of grids, shares the descriptions between presets, and measures a faster model on at least 100 grids; if that is still too slow for you, the
  answer is a smaller vision model (decision 2's alternative), not a different design.
- scene-analyser was tuned on a drama episode. Talking heads and screen recordings have few cuts; the plan adds one rule for
  them (long quiet stretches share a grid) that the earlier code did not have and that checkpoint 2 must prove.
- Watched may not beat Quick on ordinary talking videos. Checkpoint 5 measures both; if Watched is not better where the screen
  matters, it stays behind a server switch that is off.
- Each watched cut is one more media download through the YouTube gate. It shares the gate's pacing and breakers, so a blocked
  media class makes Watched unavailable, not Quick.

---

# Part 2: agent plan

## 1. Facts checked

### 1.1 u·tubot (repository state at `7868a34a`)

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
  `max_tokens`. Priorities `INTERACTIVE` and `BACKGROUND` exist. The backend runs Python 3.12 (`>=3.12,<3.13`).
- Offline rule: `[youtube] offline` answers from caches and cassettes; cassettes hold no media ("recorded media is large and
  belongs in the media archive"). `tests/conftest.py` blocks YouTube for every test.
- Clients: TV picker `UtubotMenu.showCuts`, player side `UtubotCutController`, `UtubotCutFollower` (long-polls a request with
  `wait_ms` 10000), `UtubotCutSkipper`, `UtubotCutSeekBar`; phone cut sheet `web/ui/js/pages/cuts.js`; mock
  `scripts/emulator_mock_backend.py`; the extension does not exist yet (its cut picker is checkpoint 16 of the extension plan,
  cut playback checkpoint 8).

### 1.2 scene-analyser (`evrenesat/r2t4`, directory `scene-analyser`, at `29075554`)

What it is: a local pipeline that turns a film or episode into a validated "Timed Descriptive Transcript" (TDT), built for a
player that skips uncomfortable scenes. Three stages, read in full with its README, ARCHITECTURE, DEVLOG, plan, config, tests
and the recorded run data.

| Module | What it does | Use here |
|---|---|---|
| `frame_selector.py` (661 lines) | One low-resolution grey `ffmpeg` pass (2 fps, 128 px wide): per-frame motion, novelty (difference hash), sharpness, black-frame test; thresholds derived per video from percentiles; adaptive chunks between 4 and 15 s that respect scene cuts; four frames per chunk chosen by score with a minimum distance; a low-variation flag per chunk; a diagnostics summary | Copied, adapted (2.2) |
| `extractor_v1.py` (509) | `ffmpeg` scene-cut probe cached by file hash, cut merging, full-resolution extraction of the chosen frames, 2x2 grid stitching (cells at most 512 px), `manifest.jsonl` (chunk window, the four timestamps and scores, activity class, the source cut times), `diagnostics.json` with phase timings | Functions copied (probe, merge, extract, grid, manifest record); the CLI and run directories are not |
| `context_strategies.py` (387), `scene_memory.py` (278) | Four prompt strategies for one sequential vision request per grid: image only; image with all subtitles so far; image with a bounded memory (older subtitles summarised, exact lines for the last three windows, a carry-forward state from earlier answers); image with a summary precomputed by a stronger model | The bounded strategy is copied and fed from u·tubot's transcript; the others are not |
| `tdt_format.py` (225) | TDT schema and validator: segments aligned exactly to the chunk windows, sorted, typed fields, subtitle indexes that must exist, label vocabularies | Validator copied and slimmed (2.2) |
| `artifact_runner.py` (438), `artifact_prompts.md` | A stronger model rewrites all scene answers plus subtitles into one TDT, with validation retries | Not copied: the editor model is the stronger model here and reads segments and units directly (2.2) |
| `openai_compatible_client.py`, `pipeline_config.py`, `pipeline_runner.py`, `inference_runner.py`, `subtitle_ingestion.py`, `subtitle_summary_precompute.py`, `research_context.py` | urllib client with JSON repair, TOML roles and aliases, orchestration, subtitle file parsing, summary precompute, optional research | Not copied: `llm.py`, `config.py`, `CutService` and the transcript store do these jobs; the per-request records (timing, raw text, retry count, error) and the role idea are kept |
| `netflix-firefox-extension/`, film labels (mood, tension, threat, discomfort, warnings) | Capture of streaming assets; labels for skipping uncomfortable scenes | Out of scope |
| `tests/` (10 files, 35 cases) | Config, strategies, memory, inference orchestration, TDT validation, artifact retries | The cases for the copied modules are ported |

Measured in its recorded run (March 2026, one 58.4-minute episode, a laptop with a local model server):

- Extraction, preset `balanced` (scene threshold 0.4, 2 fps analysis, chunks 4 to 15 s): 318 grids, 5.4 per video minute;
  chunk length median 13.8 s, mean 11.0 s; 48 chunks flagged low-variation; grids 1024 px wide, about 60 KB each, 19 MB in
  total. Phase times: cut probe 3.7 s, low-resolution analysis 52.3 s, full-resolution extraction 77.3 s, grid writing
  19.0 s; 153 s in all.
- Vision, one grid per request, JSON answer:
  - Qwen3.5-35B-A3B (4-bit), image plus subtitles so far, first 3 minutes: 21 of 21 answered, 13.8 s average, 17.1 s worst.
  - The same model, image only, first 10 minutes, in an earlier session: 25 answered at a median of 118 s and 12 timed out
    at 180 s. The engine was unstable in that session; the per-grid time is not a property of the model.
  - Qwen3.5-2B, image plus subtitles so far, first 3 minutes: 21 of 21, 5.6 s average.
  - Qwen3.5-2B, whole episode, subtitles so far: 114 answered, then all 204 remaining requests refused with HTTP 400, from
    the grid at 20 minutes on. At that point the prompt carried 344 subtitle events, about 10,300 characters, and grew with
    every grid. The cause was not recorded: a context limit of that model load is the likely one, not a shown one. The
    bounded and precomputed strategies were written the day after.
  - Qwen3.5-0.8B: a single answer recorded (5.4 s). No conclusion.
- Not in the data: any quality score, a comparison of grids with single frames, a run of the models named in its current
  config, a completed whole-title run with the bounded strategy.

Licence: the repository is public and has no licence file (GitHub reports none; the root README says "Private project - see
LICENSE file", which does not exist). Unlicensed public code may be read but not copied. Every commit under `scene-analyser`
is the owner's, so he alone can allow the copy (owner decision 7). Its own dependencies are Pillow (MIT-CMU, permissive)
and `json-repair` (MIT); `ffmpeg` is used as an external program.

### 1.3 Other earlier design reused (ideas only)

From the owner's private film-editing design, which has no application code: shot boundaries are technical observations and
not scenes; every editorial claim cites supplied ids; unknown visual content stays unknown; a text-only model never invents
what was on screen; pictures go only to an endpoint the owner enabled; model output is untrusted JSON validated against
supplied ids; caches are keyed by model, prompt and input fingerprints.

## 2. Decisions (all made, owner decisions of Part 1 assumed as recommended)

### 2.0 How scene-analyser is reused

**Copied into the backend and adapted** (`ai-backend/src/utubot/watch/`), with attribution. Not a package dependency and
not a sidecar:

- Dependency: it is not a package (`[tool.uv] package = false`, flat top-level module names), it requires Python 3.14 while
  the backend is pinned to 3.12, it has no licence and no release, and its entry points are command-line scripts that write
  run directories.
- Sidecar: a second process would need its own model configuration and client (losing the backend's provider limits,
  priorities, back-pressure and job events), its own deployment, and a file hand-over for every job.
- Copy: the reusable part is about 1,400 lines of pure functions (`frame_selector.py`, five functions of `extractor_v1.py`,
  the bounded strategy and memory, the TDT validator) that need only `ffmpeg` and Pillow. They are adapted to the backend's
  rules: tunables into `config.py` (no module constants), paths from the scratch directory, typed dataclasses kept. Their
  `ffmpeg` calls stay blocking `subprocess` calls (the low-resolution pass reads raw grey frames from the child's stdout,
  the cut probe parses its stderr; the backend's `run_ffmpeg` discards stdout and cannot do either) behind a new small
  module `watch/ffmpeg.py`: argument arrays only, a cancel event that terminates the child, `-threads` from
  `[cuts.watched] ffmpeg_threads = 2`, stderr trimmed and free of paths in errors. The whole grid stage runs in one worker
  thread per build (`asyncio.to_thread`), never on the event loop that serves the long polls; one watched build at a time
  means one such thread.

Rules for the copy: each copied file starts with a comment naming `evrenesat/r2t4`, `scene-analyser/<file>` and the commit
`29075554`; `ai-backend/THIRD_PARTY.md` (new) lists them with "by the repository owner, contributed under MIT" and the date
of his decision, and the `AGENTS.md` licence sentence gains that file; no file is copied before decision 7 is answered yes. With a no, checkpoints 2 and 3 are written from the
behaviour described in 1.2 instead, without the code, and take longer.

New Python dependency: Pillow, in an optional extra `watched` (like `asr`); without it watched is unavailable with the
reason "not installed". numpy (an optional accelerator in scene-analyser) is not added; the pure-Python path is used and
its speed measured in checkpoint 2.

### 2.1 Modes and how one is chosen

1. Two mode ids: `quick` and `watched`. A cut, a request and a cache row each carry one.
2. Server default: `[cuts] default_mode = "quick"`. Watched exists only when `[llm.cuts_vision]` is configured, the
   `watched` extra is installed and `[cuts.watched] enabled = true`; otherwise it is listed as unavailable with a reason and
   a build request for it answers `409 {"error":"Watched cuts are not configured on this server."}`.
3. Per-user default: `UserPolicy.cut_mode` (`null` follows the server; `"quick"`; `"watched"`), with the usual settings
   plumbing (`settings.py` `SECTION_FIELDS`, docs, contract, a test). A user default of `watched` on a server without it
   resolves to `quick`.
4. Per request: `POST /v1/videos/{id}/cuts` and `PUT /v1/cut-requests/{id}` take an optional `"mode"`. Omitted means the
   caller's resolved default. Unknown value: `400`.
5. The duplicate-request rule and the per-user build cap count a request by (video, preset or prompt, mode).

### 2.2 The watched pipeline

Stages, in order, each a job-report stage through `captions/events.py`. Transcript and video are fetched concurrently.

| # | Stage (`stage` value) | What it does | From scene-analyser | Cached by |
|---|---|---|---|---|
| 1 | `transcript` | As today (`_ensure_transcript`). A video with no speech at all is allowed in watched mode | no | transcript store |
| 2 | `video` | Archive lookup `(video_id, KIND_VIDEO)`, else one download through the gate, stored in the archive | no | archive row |
| 3 | `grids` | Cut probe, low-resolution analysis, adaptive chunks, four frames per chunk, 2x2 grids into scratch, the manifest | `frame_selector.py`, `extractor_v1.py` | manifest in `video_scenes`; grids are scratch |
| 4 | `describing` | One vision request per grid, in order, with bounded running context; `progress` counts grids done | bounded strategy, `scene_memory.py`, request records | `scene_descriptions` row (the TDT) |
| 5 | `model` | TDT segments and transcript units joined into one document; `[llm.cuts]` picks unit ranges | TDT shape | `cuts` row |
| 6 | `checking` | Validation, target-length selection (#82), boundary snap, padding and merge, guards | no | part of the `cuts` row |

**Video download.** A new `download_video` next to `download_audio`, same gate call (`run_started`, class `media`,
`BACKGROUND` priority, key `video:<id>`), same failure classification, no URL in any log. Video only, no audio. Selector
`[cuts.watched] video_format = "bestvideo[height<=360][ext=mp4]/bestvideo[height<=360]/best[height<=360]/worst"`,
`video_max_bytes = 1073741824`, `max_video_minutes = 90` (checked from the known length before any download; unknown length
is asked through `ensure_length` first). `archive.require_room()` before the download. Offline mode: archive only, else the
existing offline answer. 360 lines fit the grid: scene-analyser scales every frame down to a cell of at most 512 px, so a
640x360 source loses little (the measured runs started from a larger film file; legibility is checked in 2.11).

**Grids.** scene-analyser's `balanced` preset as the starting values, all in `[cuts.watched]`: `scene_threshold = 0.4`,
`analysis_fps = 2.0`, `analysis_width = 128`, `min_chunk_s = 4.0`, `max_chunk_s = 15.0`, `cut_merge_s = 1.5`,
`min_frame_distance = 6`, `black_frame_luma = 18.0`, `grid_cell_max_px = 512`, 2x2. The scene-cut probe result is cached by
the archive's sha256 (scene-analyser hashed the file itself). Two additions for YouTube material, both new and both proven
in checkpoint 2:

- **Quiet stretches share a grid.** Consecutive chunks that `frame_selector` flags as low-variation are joined up to
  `low_variation_max_chunk_s = 45.0`; the four frames are chosen over the joined window. A talking head then costs about
  1.3 grids a minute instead of 4. Chunk ends follow `frame_selector`'s own rule (a busy cut, else a calm cut near the
  maximum, else the maximum); cuts inside a chunk stay listed in its record.
- **A cap that always fits.** `max_grids = 240`. When the chunk list is longer, the chunks are rebuilt with all three
  lengths raised together (`min_chunk_s`, `max_chunk_s`, `low_variation_max_chunk_s`, factor 1.25 per step, at most four
  steps). Still over the cap, the last step is a budget split: chunks of `duration / max_grids` seconds, each end moved to
  a scene cut when one lies within `cut_merge_s`. So every video within `max_video_minutes` gets at most 240 grids (at 90
  minutes: one grid per 22.5 s, one frame per 5.6 s) and the cap never refuses a video; the only length refusal is the
  duration check before the download. Deterministic for a given video and settings; the step used is in the manifest and
  the job report, and the cut document says `"coarse": true` when the budget split was used.

Expected grids per video minute: 1.3 (still picture) to 5.4 (the measured drama); the tables in Part 1 assume 2 to 5.
The manifest keeps scene-analyser's record: chunk window, the four timestamps and scores, activity class, low-variation
flag, and the source cut times inside the chunk.

Why grids and not single frames: one picture carries four moments in order, so the model sees change within the chunk
(what the earlier project was built around), and the number of requests is a quarter of one-frame-per-request at the same
coverage. The cost side is measured (5.4 requests per minute instead of about 22); the quality side was never compared,
so checkpoint 3 measures one thing about it: whether text on a slide is still read inside a 512 px cell (2.11).

**Vision model.** A new task table `[llm.cuts_vision]` (same fields as other tasks; no default, like `[llm.cuts]`).
The shortlist of the owner's model research (24 Nov 2026), all three installed on the big local engine and served by its
current engine software, which stays (no other engine showed a gain for this job):

| # | Model (build) | Size | Expected s per grid | Role | Note |
|---|---|---|---|---|---|
| 1 | Qwen3.6-35B-A3B, 8-bit | 40 GB | 2 to 5 | default | Apache-2.0; the best document-reading score found; takes video natively; successor of the measured Qwen3.5-35B-A3B |
| 2 | Qwen3.8-Flash-Next, 4-bit | 113 GB | 4 to 10 | wins only if clearly better | licence not confirmed; leaves less memory for parallel requests. The gateway's `fast` alias serves the same family from another engine and is not this build |
| 3 | gemma-4-26B-A4B, 8-bit | 30 GB | 2 to 5 | cross-family check | Apache-2.0; weaker document-reading score |

The speeds are the research's estimates, not measurements. The gateway serves 1 and 3 today as discovered aliases
(`qwen3.6-35b-a3b-oq8e-mtp`, `gemma-4-26b-a4b-it-oq8e-mtp`) declared without image input; the winner gets a curated alias
with the right capability in the gateway's own configuration (outside this repository). The pick is recorded in
`ai-backend/fixtures/cuts/VISION-CHOICE-<date>.md`. The Qwen3.5 models that scene-analyser measured are not installed and
are not candidates.
`llm.py` gains message content parts (`[{"type":"text"},{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,..."}}]`),
OpenAI-compatible, nothing provider-specific. JSON answers go through the existing `chat_json` and `extract_json`;
`json-repair` is not added.

**Describing.** One grid per request, in video order, `describe_concurrency = 1`, `BACKGROUND` priority, as in the measured
runs. The user message is scene-analyser's bounded-memory template, fed from u·tubot's data:

- the chunk's start and end;
- the transcript text spoken inside the chunk;
- exact transcript lines of the previous `recent_window_count = 3` chunks;
- the carry-forward state: the last `carry_forward_scenes = 2` visual summaries and their kinds;
- no text older than that, and a hard limit `describe_context_chars = 4000` (the earlier whole-episode run with growing
  context ended in HTTP 400 for every later grid; whatever the exact limit was, a prompt that grows with the video is not
  an option); over the limit the oldest recent lines are dropped first. An HTTP 400 on a grid is retried once with the
  context halved, and checkpoint 3 records the real limit of the chosen model.

No stronger-model summary of the older transcript is precomputed: a cut needs what a chunk shows, not the plot so far, and
the pass would cost one more model call per grid.

System prompt, adapted from scene-analyser's (describe the four frames as one continuous moment, never mention the grid,
brief and factual, the picture is the primary evidence, transcript only as context, say `unknown` when unsure). Answer JSON:
`{"visual_summary","kind","on_screen_text","same_as_previous"}` with `kind` one of `talking_head`, `screen`, `slide`, `demo`,
`broll`, `title_card`, `sponsor_card`, `other` (these replace the film labels); `visual_summary` at most 240 characters,
`on_screen_text` at most 160. One retry per grid on an invalid answer, then the segment is marked `not_seen`. More than
`max_unseen_frac = 0.2` unseen segments fails the watched build; less proceeds and the cut says `"partial": true`. Every
request keeps scene-analyser's record: duration, raw text, retry count, error.

**The TDT and how it maps to cut units.** The stored result of stage 4 is a Timed Descriptive Transcript in a slim
u·tubot form (`"format":"tdt"`, `"format_version":"1.0-utubot"`), assembled by code, not authored by a model:

| scene-analyser TDT field | u·tubot TDT | Source |
|---|---|---|
| `segment_id`, `start`, `end`, `grid_filename` | `segment_id`, `start`, `end`, `timestamps` (the four frame times) | manifest; segments equal the chunk windows exactly |
| `visual_summary` | `visual_summary` | vision answer |
| `labels` (mood, tension, threat, discomfort, setting, warnings) | `labels: {"kind","on_screen_text","same_as_previous"}` | vision answer |
| `subtitle_event_indexes` | `unit_ids` | computed: the cut units that overlap the segment, a unit counted to the segment it overlaps most |
| `dialogue_summary`, `combined_narrative` | not stored | the units themselves are the dialogue; the editor model does the combining |
| `carry_forward_state` | not stored | prompt-time only |
| `analysis_provenance` | `provenance: {"model","prompt_version","retry_count","seen"}` | request record |
| top level `source`, `inputs`, `generation` | `video_sha256`, `settings_key`, `model`, `prompt_hash`, `scene_cuts` | pipeline |

The copied validator keeps its rules (segments sorted, not overlapping, aligned to the windows, ids must exist, known
labels) and runs before the TDT is stored. `labels` is an open object so the earlier project's tension and discomfort
labels can be added later for other presets without a format change; they are not part of this plan.

Units in watched mode come from a builder that shares `build_units`:

- speech units as today;
- a gap without speech longer than `silent_unit_min_s = 4.0` becomes `(no speech)` units, split at segment boundaries and at
  `unit_max_s`, numbered in the same sequence (so a silent demo can be kept by id like anything else);
- each TDT segment is written as one `S` line before its first unit; consecutive segments with the same `kind` and
  `same_as_previous` collapse into one line over the whole range.

```
Scenes and transcript (lines starting with S are what is on screen, lines starting with # are units you can keep):
S7 [03:10-03:55] screen: a terminal, a build runs and stops; text: "error: linker failed"
#41 [03:10-03:18] so when I run it you can see it fails
#42 [03:18-03:31] (no speech)
```

On-screen text is untrusted data. It reaches only the editor model, whose answer is unit ids validated against the supplied
units, so the worst outcome of a hostile picture is a poor cut.

**Editorial call.** The text model `[llm.cuts]`, the same presets and instructions as quick, the same answer format (the one
#82 lands: ranked parts with a reason). The system prompt gains two sentences for watched mode (S lines are evidence, only
`#` ids can be kept). `[cuts.watched] max_input_tokens = 48000`; over it, `visual_summary` is dropped from collapsed
`talking_head` runs first, then the build is refused with the existing "too long" message.

**Boundary snap.** After the #82 selection and before padding: a part's start moves back to a scene cut (the manifest's
source cut times, not chunk edges), and its end forward to one, when the cut is within `snap_s = 1.0` and no speech unit lies
in between. Never inward, never across speech.

### 2.3 Target length (#82) in both modes

- #82 lands first for quick. Its selection (`target_s`, tolerance, ranks, trim at a unit boundary, one re-ask with the
  measured length) lives after `parse_cut_answer`, on units, so watched uses it unchanged; `(no speech)` units are ordinary
  units to it.
- The band is checked on the final document's `kept_ms` (after snap, padding and merge) in both modes.
- The real length is shown next to the label in both modes ("Highlights · 5:02", with "· Watched" when it is).
- Owner and place of #82: it is its own task and pull request, in work on the Heavy tier outside this plan (labels
  `bug`, `tier:heavy`); this plan does not implement it. Checkpoints 4 and 5 wait for its merge to `main`; checkpoints 1, 2,
  3 and 6 do not.
- What this plan needs from #82, whatever its final answer format: the selection runs in the server after
  `parse_cut_answer`, on parts made of unit ids, and the band is checked on the finished cut. If #82 lands like that with
  other field names, checkpoint 4 uses them as they are. If it lands differently (selection only by prompt, or not on
  units), checkpoint 4 begins with a short amendment of this section, reviewed before any code.
- If #82 slips: checkpoints 1, 2, 3 and 6 still land. The real length is shown in both modes anyway, because it is the
  cut document's existing `kept_ms`; only holding the target waits, and watched is not switched on (checkpoint 7) before
  it.

### 2.4 Caching

- Video file: archive, one per video (`kind = "video"`).
- `video_scenes`: key `(video_sha256, settings key)` where the settings key hashes the grid settings and
  `GRID_PLAN_VERSION`; the scene cuts and the manifest as JSON.
- `scene_descriptions`: key `sha256(video_sha256 | settings key | vision model | describe prompt hash | transcript_hash)`;
  the TDT. The transcript is part of the key because it is part of the describe prompt. Shared by every preset, prompt and
  user. This is the expensive part and is paid once per video.
- `cuts`: the quick key stays byte-for-byte as it is (existing rows stay valid). The watched key is
  `sha256(video | version | model | transcript_hash | "watched" | descriptions key)`. New column `cuts.mode`.
- The preset list (`by_mode`) reads the cache once per preset and mode, two lookups per preset instead of one; both are
  indexed reads of `cuts`.
- In-flight sharing (`_inflight`) is per key as today; a second watched request for the same video waits on the same
  describing work through a per-video lock.
- Describing is resumable: finished segments are written to the row as they complete, so a restart continues at the next
  grid (scene-analyser appended one result row per grid for the same reason).
- `DELETE /v1/admin/archive/{video_id}` also removes the video's `video_scenes` and `scene_descriptions` rows and counts
  them in its answer.

### 2.5 Budget, queue and what the user is told

- `[cuts.watched] max_concurrent = 1` server-wide; waiting requests are `building` with `stage = "in_line"` (not `queued`: that
  name is a job event `_last_stage` filters out, and `waiting` is already a request state).
- Request documents gain `mode`, `progress` (0 to 1; weights video 0.05, grids 0.1, describing 0.75, model 0.1) and `eta_s`.
- `eta_s` before the build: expected grids (`eta_grids_per_minute = 3.5` x minutes until the manifest exists, then the real
  count) x seconds per grid, plus `eta_grid_stage_s_per_minute = 3.0` x minutes (153 s for 58.4 minutes was measured) and a
  fixed part. Seconds per grid is the median of the last `eta_window = 20` finished watched jobs; until there are any,
  `eta_s_per_grid = 14.0`, a placeholder from the 21-grid run that checkpoint 3 replaces with the median of its 100-grid
  run. During the build it is recomputed from the grids left.
- `describe_timeout_s = 60` per grid, also a placeholder: checkpoint 3 sets it to three times the 95th percentile of its
  100-grid run. `build_timeout_s = 3600` for the whole build.
- Ready while you watch something else: the follower follows the video that is playing, so a cut that becomes ready
  for another video is not announced there. It shows as ready in that video's picker, on the phone's Cuts tab and in the
  Processed list ("Cut ready"), and is offered when the video is opened again, as ready cuts are today.
- Texts: picker "Watched · about 12 min"; on start "Watched cut is being prepared, about 12 min. Keep watching."; ready, as
  today, "Cut ready" with Apply.

### 2.6 Storage and cleanup

- Video: kept in the archive under its quota (owner decision 4). `keep_video = true`; with `false` the file and its archive
  row are removed when the TDT is stored.
- Grids and extracted frames: scratch under the media scratch directory, `watched/<request id>/`, removed when describing
  ends (success or failure). About 60 KB per grid was measured, so at most about 15 MB per build. `keep_grids = false`
  exists for debugging. The existing scratch sweep removes leftovers after a crash.
- Before a watched build: free space on the archive and scratch filesystems must exceed `min_free_bytes = 2147483648` plus
  the expected size, or the build fails with a clear message before any download.
- Nothing visual is stored in the database: the TDT is text.

### 2.7 Privacy

- Grids are sent only to the provider of `[llm.cuts_vision]`, together with the transcript lines of the bounded context.
  `docs/privacy.md` gains this, the stored video copy, and the TDT.
- No cloud switch (owner decision 3). `fallback` entries of `[llm.cuts_vision]` must be on the same provider (config
  validation error otherwise), and the docs tell the admin to give that provider a gateway key that is not allowed to
  reach cloud engines (modelgate: a client without `allow_cloud`), so a re-routed alias is refused by the gateway and the
  watched build fails over to the Quick offer instead of sending pictures out. The backend cannot see where an alias is
  routed; the guarantee is the gateway key, and the docs say so.
- The admin TDT route returns on-screen text of a video to admins only; `docs/privacy.md` names it.
- The TDT text does reach `[llm.cuts]` (as transcripts do today).

### 2.8 Failures and fallbacks

| Failure | Result |
|---|---|
| Watched not configured or not installed, video too long, live stream | refused at request time (`409`), nothing queued |
| Video refused by YouTube, media class blocked, archive full, disk reserve | request `failed`, plain reason |
| Vision model unavailable, gateway refusal, over 20 % segments unseen, timeout | request `failed`, plain reason |
| Editor model failure | as today |

A failed watched request document carries `"fallback":{"mode":"quick","state","request_id"?,"cut"?}` (the quick state of the
same preset or prompt). Clients show the reason and one action: "Use Quick" (applies a ready quick cut or posts the same
request with `"mode":"quick"`). `auto_fallback = false`; with `true` the server queues the quick request itself and the
request document says so. A partial watched cut (`"partial": true`) is applied normally and labelled "Watched (partly seen)".

### 2.9 Contract changes (all additive; `ai/CONTRACT.md`, "Director's cuts")

- `GET /v1/me` features: `"cuts_watched": bool`.
- `GET /v1/videos/{id}/cuts`: adds `"default_mode"`, `"modes":[{"id","label","default":bool,"available":bool,"reason"?,
  "eta_s"?}]`; each preset adds `"by_mode":{"quick":{state fields},"watched":{state fields}}`. The preset's existing
  top-level `state`, `request_id`, `error`, `cut` keep describing the caller's default mode, so a client that ignores the new
  fields behaves as today.
- `POST /v1/videos/{id}/cuts`, `PUT /v1/cut-requests/{id}`: optional `"mode"`.
- Request document: `mode`, `progress`, `eta_s`, `fallback`; `stage` gains `in_line`, `video`, `grids`, `describing`.
- Cut document: `"mode"`, and for watched `"watched":{"grids":n,"model":"<alias>","partial":bool,"coarse":bool}`. `version` stays 1.
- `GET /v1/processed`: each cut entry gains `mode`.
- Settings document: `cut_mode`.
- Admin: `GET /v1/admin/videos/{id}/tdt` returns the stored TDT (for the job page and for debugging); admin only.
- Source columns, the optional `source` and `transitions` fields of the cut document and the table `scene_labels`: 2.13.
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

- **Grid test** (`scripts/grid_bench.py`, run by hand against a real endpoint, never in CI), three steps:
  1. *Bake-off* (the first step of checkpoint 3; about 45 minutes of engine time, each candidate loaded alone, so it needs
     a window in which the engine's usual big model is unloaded: by hand until phase 2 exists, by an engine claim after).
     Inputs, on the owner's machine only and never in this repository: 40 grids from the recorded scene-analyser run, picked
     by kind (10 with on-screen text, 10 dialogue, 10 action, 10 dark), and 8 clips of 8 to 15 s of the same kinds. Per
     candidate: the 40 grids at one request at a time and at six in parallel, then the 8 clips as native video input; the
     scene-analyser JSON prompt, temperature 0, thinking off. Recorded: seconds per grid at both levels, tokens in and out,
     valid-JSON rate, peak memory, load time. Quality: a short reference line per grid (visible text, people, main action)
     written from the frames, each answer judged 0 to 2 on text, who and what, and action, plus a count of invented names
     or text. Pass bar: valid JSON at least 98 %, text read right on at least 80 % of the on-screen-text grids. A candidate
     that does not answer pictures at all fails here. Pick: candidate 1 unless candidate 2 is clearly better on quality
     for at most twice the time; candidate 3 only if both Qwen models fail the bar. If none passes, the plan stops and the
     owner decides (another model, or the alternative of decision 3).
  2. *Scores*, for the pick and the runner-up: grids built by the real grid code from clips rendered with `ffmpeg` from
     known content (text slides at three sizes, a terminal-like text block, colour scenes, a title card, a change between
     the first and the last cell). On-screen text recall, `kind` accuracy, valid JSON rate; and the same content sent as
     four single frames, once, to put a number on what the grid costs in legibility.
  3. *Long run*, for the pick: at least 100 consecutive grids of one real video from the archive (offline
     mode, imported as in 2.12), with the real describe prompt at its full bounded context. Recorded: answered and failed
     counts, median and 95th percentile seconds per grid, the largest prompt sent, any HTTP 400. `eta_s_per_grid` and
     `describe_timeout_s` are set from it.
  The pick of step 1 stands unless the long run answers under 95 % in valid form or its median is over
  `describe_s_per_grid_max = 20.0`; then the runner-up takes its place and the long run is repeated.
  Parallel describing: if six in parallel gave at least twice the throughput in step 1, `describe_concurrency` is set
  to what was measured as best and the carry-forward state is dropped from the prompt (it needs strict order); the
  transcript context stays. Until then it is 1. Native video input is measured in step 1 for later use only; this plan
  sends grids.
- **cutbench, watched mode**: every fixture gains a hand-written TDT (no video, no vision model: this measures the join and
  the editor). Three new fixtures where the transcript alone misleads: a silent demo (the must-keep span has no speech), a
  walkthrough where the talk refers to the screen ("as you can see here") and the screen decides relevance, and a sponsor
  card shown while the talk sounds on-topic. `scripts/cut_bench.py --mode quick|watched|both`; the report adds per-mode
  columns, #82's length-accuracy column, and `visual keep` (recall on spans marked as screen-only).
- **Labelled set** (owner's server, never CI, never in the repository): six real videos the owner chose (two talking, two
  screen recordings, two with demonstrations), two presets each, hand-marked keep and skip ranges in a small JSON file under
  `[cutbench] labelled_dir`. The cassettes are recorded by the owner (`utubot youtube-record`); the video files reach the
  archive either through his normal production use or through `utubot media import` (2.12). The run uses offline mode. Reports both modes side by side with a readable sample of the kept parts, the grid count per
  minute for each video, and the measured stage times.
- **Gate** (checkpoint 5): on the three visual fixtures watched scores at least 0.15 higher than quick; on the other
  fixtures it is no more than 0.03 lower; length accuracy inside #82's band in both. If the gate fails, `[cuts.watched]
  enabled` stays `false` in the example config and the finding is filed as an issue.

### 2.12 Tests (never YouTube, never a real model)

- Ported from scene-analyser with their modules: the cases of `test_scene_memory.py`, `test_context_strategies.py` (bounded
  strategy), `test_tdt_format.py`, and the orchestration cases of `test_inference_runner.py` that still apply (sequential
  order, per-grid failure record, state update after a success). `frame_selector.py` and the grid functions have no tests
  there; checkpoint 2 writes them.
- Synthetic video: `tests/synth_video.py` builds a 60 s clip with `ffmpeg` (`lavfi` sources, four hard cuts, drawn text, a
  30 s still stretch), as `synth_speech.py` does for audio. Tests needing `ffmpeg` or Pillow skip without them, like the
  existing media tests; CI installs the `watched` extra.
- `tests/mock_openai.py` accepts image content parts and answers the describe format (plus modes: invalid JSON once, HTTP
  400, timeout).
- The fake downloader pattern of `test_media_archive.py` supplies the video; `block_youtube()` stays autouse.
- **Media import** (new, checkpoint 2): `utubot media import <video_id> <file> [--kind video|audio]`, an owner command
  that puts a local file into the media archive through `MediaArchive.store` (`check_video_id`, quota check, no network,
  works with `[youtube] offline`). It is how the long run of checkpoint 3 and the labelled set of checkpoint 5 get their
  videos without any request to YouTube from a test, an agent or a bench run. Its test imports the synthetic clip and
  builds grids from it in offline mode.
- The mock's HTTP 400 case covers the halved-context retry.
- Per checkpoint, see the table.

### 2.13 Data model ready for #88 and #89

Two later features shape the tables now; neither is built here. #88: director's cuts for films and episodes watched in
another player (skip lists per title, content filters by category, promptable per title, the same scene analysis). #89:
generated transitions between kept scenes. Everything below is additive, and nothing a current client reads changes.

**A cut belongs to a source, not to a YouTube id.**

- `source_kind TEXT NOT NULL DEFAULT 'youtube'`, `source_key TEXT`, `release_key TEXT`, `release_duration_ms INTEGER` on
  `cut_requests` and `cuts` (checkpoint 1) and, from their creation, on `video_scenes` (checkpoint 2) and
  `scene_descriptions` (checkpoint 3).
- `source_key` is one canonical string: `youtube:<video id>`, or for a title `<scheme>:<id>[:s<season>e<episode>]`
  (`imdb:tt0123456:s01e03`). `release_key` tells releases of the same title apart (a fingerprint of the file the analysis
  was made from, or `dur:<ms>` when there is none); it is null for YouTube. A row with `source_key` null is read as
  `youtube:<video_id>`, so old rows need no rewrite. `video_id` stays, filled as today.
- Matching a cut to what is playing: same `source_key`, and the playing length within
  `[cuts] release_duration_tolerance_ms = 2000` of `release_duration_ms` (the 2 s rule clients already apply to
  `duration_ms`); with a `release_key`, that must match too.
- Cache keys: the YouTube keys stay byte-for-byte as they are. Keys of other sources use `source_key|release_key` where
  `video` stands today. One helper, `source_ref(row)`, is the only place that reads these columns.
- The cut document gains an optional `"source":{"kind","key","release_key"?,"release_duration_ms"?}`; absent means the
  YouTube `video_id` as today.

**Scene labels, so a filter is a query.**

- A TDT segment's `labels` object (2.2, already open) gets an optional list
  `"content":[{"category","intensity","confidence"}]`: `category` from a versioned vocabulary (`LABEL_VOCAB_VERSION`;
  first set: `violence`, `gore`, `sex`, `nudity`, `language`, `drugs`, `frightening`, `flashing`, taken from
  scene-analyser's warnings and the usual rating symbols), `intensity` 0 to 3, `confidence` 0 to 1. The validator
  accepts the list and checks its values; the phase 1 describe prompt does not ask for it, so YouTube TDTs carry none.
- A table `scene_labels(descriptions_key, source_key, release_key, segment_id, start_ms, end_ms, category, intensity,
  confidence, vocab_version)`, indexed by `(source_key, release_key, category)`, written from the TDT whenever one is
  stored (checkpoint 3). A content filter is then
  `SELECT start_ms, end_ms ... WHERE category IN (...) AND intensity >= ? AND confidence >= ?` turned into skip ranges
  by the existing `skip_ranges_ms`: no model call, and a new filter needs no new analysis.
- The TDT stays the record; `scene_labels` can be rebuilt from it (a test does).

**A transition slot per boundary.**

- The cut document gains an optional `"transitions":[{"after_part":<index>,"type","duration_ms","asset":{"ref",
  "sha256"?},"engine","engine_version","status"}]`, `status` one of `none`, `pending`, `ready`, `failed`. One entry per
  boundary between two kept parts at most; `asset.ref` is an opaque server-side reference, never a URL with a token.
- It lives inside the stored cut JSON, so no column is needed; `CUT_DOC_VERSION` stays 1. `skip_ranges_ms` and `parts`
  never depend on it. `ai/CONTRACT.md` says: a client that cannot show transitions ignores the field and skips as
  today.

**Where it lands and how it is tested.** Checkpoint 1 adds the source columns, `source_ref`, the two optional document
fields and the contract text; checkpoints 2 and 3 create their tables with the source columns, and 3 adds `scene_labels`
and the label list. Tests: a database made by the schema of `main` with stored cuts, requests and their rows is opened by
the new code and every old row reads and is served exactly as before (same JSON, same cache hit); a cut document with
`source` and `transitions` passes the TV's cut parser and the web UI unchanged (parser test in checkpoint 1); a stored
TDT with a `content` list fills `scene_labels`, and one without fills nothing.

## 3. New and changed files (backend)

- `src/utubot/watch/__init__.py`; `watch/video.py` (download, archive); `watch/ffmpeg.py` (blocking calls with cancel,
  used from the worker thread); `watch/frame_selector.py` and `watch/grids.py`
  (copied and adapted: analysis, chunks, selection, cut probe, extraction, stitching, manifest; plus the quiet-stretch rule
  and the cap); `watch/memory.py` (copied: bounded context, carry-forward state); `watch/describe.py` (prompt, sequential
  requests, records, resume); `watch/tdt.py` (copied validator, slim format, assembly); `watch/join.py` (silent units,
  S lines, snap); `watch/service.py` (the stage runner, queue slot, progress, eta).
- `ai-backend/THIRD_PARTY.md` (new): the copied files and their origin.
- `cuts.py` (mode on requests, key, branch in `_run_build`, fallback field), `llm.py` (content parts), `config.py` and
  `config.example.toml` (`[llm.cuts_vision]`, `[cuts] default_mode`, `[cuts.watched]`, `UserPolicy.cut_mode`),
  `pyproject.toml` (extra `watched = ["pillow>=12.1.1"]`, the version scene-analyser ran with), `db.py`, `media_archive.py` (remove hook), `settings.py`,
  `processed.py`, `cli.py` (`media import`), `cutbench.py`, `prompts.py` (describe prompt, watched sentences), `web/ui/js/pages/cuts.js`, the settings
  page, `job.js`/`jobtext.js` (new stages).
- CI: `.github/workflows/utubot-ci.yml` installs the `watched` extra for the backend job (ffmpeg is already there) and its
  path filter covers `ai-backend/THIRD_PARTY.md`.
- Docs: `AGENTS.md` (the licence sentence names `ai-backend/THIRD_PARTY.md`), `ai/CONTRACT.md`, `docs/server.md` ("Director's cuts", "Job details"), `docs/privacy.md`, `docs/llm-providers.md`,
  `ai/APP_INTEGRATION.md`, both devlogs.

## 4. Checkpoints

One pull request each. Every checkpoint ends with a clean-context review before the next starts. Tiers as in the extension
plan (Fast: straightforward from this plan; Heavy: the tricky parts).

| # | Scope | Done when | Tests | Tier |
|---|---|---|---|---|
| 0 | Gates, not work of this plan: owner decision 7 answered (needed by 2); #82 merged (its own Heavy-tier task; needed by 4 and 5, see 2.3) | the decision is recorded in this plan; `main` has the server-side length selection | #82's own | n/a |
| 1 | Mode plumbing with quick only: the source columns and the two optional cut-document fields of 2.13 (old rows read unchanged, tested against a database made by the schema of `main`; the TV parser ignores `source` and `transitions`); contract text, `mode` on requests and cuts, `modes` and `by_mode`, `default_mode`, `UserPolicy.cut_mode`, additive columns, watched listed as unavailable, mock backend modes, parity-matrix row | old request bodies answer exactly as before (replayed in a test); `mode:"watched"` answers the 409; settings round trip; quick cache keys unchanged (a stored row from before is still served) | `test_cuts_api.py`, `test_settings.py`, `test_db_migrations.py`, `test_emulator_mock.py` | Fast |
| 2 | Video and grids, no model: `video_scenes` created with the source columns of 2.13; `watch/video.py`; `frame_selector.py` and `grids.py` copied with headers and `THIRD_PARTY.md`, adapted to config; `watch/ffmpeg.py` and the worker thread; the quiet-stretch rule and the cap with its budget split; `utubot media import`; archive `kind=video`, limits, disk checks, scratch cleanup, archive remove hook | on the synthetic clip: every hard cut is a chunk end or in that chunk's cut list within 0.5 s, every chunk is 4 to 15 s except the joined still stretch (one grid for 30 s), each grid is 2x2 with cells of at most 512 px, the manifest matches scene-analyser's record; the cap holds on generated chunk lists including a 90-minute one with a cut every 4 s (budget split, 240 grids); a long poll answers within its `wait_ms` while the grid stage runs; cancelling a build ends the child `ffmpeg`; `media import` works offline; a second run downloads nothing and reuses the manifest; grids are gone after the stage; over-limit and full-archive cases fail before a download. Recorded by the owner's server for one talking video and one screen recording: grids per minute, stage time, video size | `test_watch_video.py`, `test_watch_selector.py`, `test_watch_grids.py`, `test_media_archive.py`, `test_cli_media.py` | Heavy |
| 3 | First step: the bake-off of 2.11 for the three shortlisted models (owner's machine, engine window needed), result and pick recorded before anything else is built. Then: `scene_descriptions` with the source columns, `scene_labels` and the optional label list of 2.13 (filled from a TDT with labels, rebuilt from the TDT in a test); content parts in `llm.py`, `[llm.cuts_vision]`, `memory.py` and `tdt.py` copied with their ported tests, `describe.py` (sequential, bounded context, records, resume, timeout), the cloud rule; `grid_bench.py`; the model pick | mock: one request per grid in order, context never over the limit on a two-hour transcript, one retry then `not_seen`, HTTP 400 retried once with half the context, the 20 % rule, resume after a restart at the next grid, TDT validated and cached per key, same-provider fallback rule; on the owner's engines: the bake-off table, the scores of step 2, the long run of at least 100 grids at full context, the pick, the eta and timeout values and the model's real prompt limit recorded; if none passes, stop and report | `test_watch_describe.py`, `test_watch_memory.py`, `test_watch_tdt.py`, `test_llm_parts.py`, config tests | Heavy |
| 4 | The watched build: `join.py`, `service.py`, branch in `CutService`, snap, #82 selection reused, queue slot, progress and eta, timeouts, failures and `fallback`, job-report stages, admin TDT route and status | end to end on the synthetic clip with the mock models: a watched request goes through every stage to a ready cut whose kept ranges include the silent part; restart mid-build resumes and reuses the caches; second preset skips stages 2 to 4; each failure row of 2.8 produces its document; the band holds after snap | `test_cuts_watched.py`, `test_watch_join.py`, `test_job_report.py` | Heavy |
| 5 | Evaluation: cutbench TDTs, three visual fixtures, `--mode`, report columns; the labelled-set runner; the gate | bench numbers for both modes recorded in `fixtures/cuts/`; gate result stated; labelled-set run recorded (numbers, grids per minute, times, a readable sample) by the owner's server | `test_cutbench.py` | Fast |
| 6 | Clients: TV picker row, follower over long builds, texts, labels, failure dialog; web UI control, progress, settings, failure offer; extension side per 2.10 | TV unit tests for the picker model and parser with the new fields; emulator run against the mock (`--cuts-watched-delay`) recorded: pick Watched, keep playing, ready announcement, Apply; failed case shows "Use Quick"; web UI tests for the control and the progress view | `UtubotCut*Test`, `test_webui.py`, emulator recipe in `docs/development.md` | Fast |
| 7 | Owner trial and switch-on: docs complete, example config, the owner's server enables watched | the owner built watched cuts for at least three videos from the TV and the phone and each finding is fixed or filed | recorded in the devlog | Fast |

Order: 1, then 2, 3, 4, 5 in sequence; 6 may run beside 2 to 5 once 1 has landed (it needs only the contract and the mock).
2 needs decision 7; 4 and 5 need #82 merged; 7 needs both.

## 5. Verified, and not

### 5.1 Verified (read or measured, sources in section 1)

- scene-analyser's grid extraction works on a full episode and its cost: 153 s for 58.4 minutes, 5.4 grids per minute,
  about 60 KB per grid.
- A 35B-class local Qwen vision model answers a 2x2 grid with transcript context in valid JSON at about 14 s per grid, and
  a 2B model at about 5.6 s (21 grids each).
- A run whose prompt grew with the video ended in HTTP 400 for every grid after the 114th (about 10,300 characters of
  subtitles at that point). The cause is not in the data.
- The reusable modules need only `ffmpeg` and Pillow; all commits to them are the owner's; the repository has no licence.
- The gateway's model list, as read: `fast` and its family are listed with image input; `qwen3.6-35b-a3b-oq8e-mtp` and
  `gemma-4-26b-a4b-it-oq8e-mtp` are served and listed without it.
- The five copied modules compile under Python 3.12 (the plan review checked this); the 3.14 requirement is a declared
  floor, not used syntax.

### 5.2 Could not be verified from here

- Whether any shortlisted model answers a picture through the gateway, and how well: nothing was sent to them. The
  research found them registered as vision models on the engine; the gateway declares the discovered ones without image
  input. Their speeds are estimates and their benchmark scores are the model authors' own. The bake-off is the first
  step of checkpoint 3.
- Whether parallel requests help, and whether dropping the carry-forward state for them costs quality.
- Why the growing-context run failed, and the real prompt limit of any candidate.
- Speed on today's engines. The per-grid times are from a laptop in March 2026 with older models, 21 grids each from the
  first three minutes, with little context; one session of the same model was ten times slower. Every time in Part 1, the
  eta default and the timeout follow from them until the 100-grid run replaces them.
- Description quality. scene-analyser recorded no score; nothing shows how good the summaries were, and nothing compares
  grids with single frames. The grid test and checkpoint 5 are the first measurements.
- Grids per minute on YouTube material, and the quiet-stretch rule and the budget split, which are new. The 1.3 to 5.4 range is arithmetic from
  the settings and one drama episode.
- The speed of `frame_selector.py` without numpy on the server, and on a 360p source (the measured source was a film file).
- The size of a 360p video-only stream and the download time under the gate's pacing; that a 360p video-only format exists
  for every video (the selector falls back to the smallest combined format).
- Whether a 512 px cell keeps slide text readable for the vision model.
- The exact answer format #82 will land; this plan follows the issue text and adapts in checkpoint 4.
- That the TV's cut parser ignores unknown fields and that `UtubotCutFollower` keeps following a request for an hour
  (read, not run; checkpoint 6 tests both).
- Whether watched is better than quick at all on real videos (checkpoint 5).

## 6. Review response

Plan review of revision 2 (clean context, verdict: approve with changes; no high findings).

| # | Finding | Answer |
|---|---|---|
| M1 | The #82 gate has no owner, order or fallback; its answer format is unknown | 2.3 and checkpoint 0: #82 is its own Heavy-tier task; checkpoints 4 and 5 wait for its merge; what the plan needs from it and what happens if the format differs or it slips; Part 1 reworded |
| M2 | The recommended vision model is unprobed and the candidates are unnamed | 2.2: three named candidates (since replaced by the shortlist of the owner's model research); 2.11 and checkpoint 3: a bake-off is the first step, with a pass bar and a pick rule; decision 2 says none was measured here |
| M3 | Speed rests on 21-grid runs with little context | 2.11 step 3 and checkpoint 3: a run of at least 100 grids at full context; the eta default and the timeout are placeholders set from it; Part 1 says the times are a guess |
| M4 | The 10,000-character cause was stated as shown | 1.2, 2.2, 5.1, 5.2: the observed evidence only, cause unverified; HTTP 400 retried with half the context; the real limit recorded in checkpoint 3 |
| M5 | The grid cap can contradict the 90-minute limit, after a paid download | 2.2: the cap raises `min_chunk_s` too and ends in a budget split, so every video within the limit fits; the only length refusal is before the download; decision 5 kept, failure row removed |
| M6 | `run_ffmpeg` cannot stream frames or return stderr; analysis must be off the event loop | 2.0, section 3, checkpoint 2: `watch/ffmpeg.py` with blocking calls and cancel, the whole grid stage in one worker thread, tests for long-poll latency and cancel |
| M7 | No way to put media into the archive for offline runs | 2.12, 2.11, checkpoint 2: the owner command `utubot media import` |
| M8 | The stage name `queued` collides with the job-event filter | 2.5, 2.9: the stage is `in_line` |
| L | Owner part long; cloud switch for a case nobody asked for | Decision 3 is now "not built"; the switch, the label and the status line are gone. The table and the risks are kept: they carry the time and the main doubts |
| L | Decision 7 is a gate, not just "new" | Marked blocking, with the reply needed |
| L | `THIRD_PARTY.md` and the `AGENTS.md` sentence | 2.0 and section 3 |
| L | CI workflow missing from the file list | Section 3 |
| L | Pillow pin | `pillow>=12.1.1` |
| L | `by_mode` doubles the cache lookups | Noted in 2.4; the quick-key test is in checkpoint 1 |
| L | Admin TDT route and privacy | 2.7 |
| L | Same-provider rule is config-level only | Unchanged; 2.7 says the guarantee is the gateway key |
| L | Ready announcement while on another video | 2.5 |
| L | 5.1 and 5.2 read as contradictory on the gateway's list | Reworded: what the list says (5.1), what was never probed (5.2) |
| - | Review note: a hard cut does not always end a chunk in `frame_selector` | Found while answering M5; 2.2 and checkpoint 2 corrected |

---

# Phase 2: priority classes and engine claims

Added 24 Nov 2026 (evening) on the owner's request; revised after its review and its re-check (P.7). It comes after the checkpoints
above and blocks none of them. What it adds: two classes of user, a way for a priority request to get the big local
engine to itself, a model route per class, and an effort notch for watched cuts. Infrastructure outside this repository
is described here only as far as this backend sees it; the companion plan `plans/engine-claims.md` in the owner's private
`conduktor` repository holds the rest (the claim service, the gateway's mode switch in the private `evreniops`
repository, the gateway configuration).

Decisions are numbered D-P1 to D-P11, checkpoints P0 to P9.

## P.1 Owner part

What changes for you:

- **Prime users.** One checkbox per u·tubot user in the web UI's user list. Your user is prime; a child's user is normal.
  On the TV each YouTube account can be paired with its own u·tubot user, so the class follows whoever is signed in. An
  account that is not paired, or that the app cannot identify, always uses the device's user, which should be a normal one
  (the web UI warns when it is not).
- **Prime work goes first.** A prime request for demanding work (a watched cut, HQ captions) is next in every line.
  Normal requests never slow it: they wait and say "waiting for a priority job"; a normal watched build that is already
  running pauses after the grid it is on (at most a minute) and continues afterwards.
- **The big engine on demand, within limits.** When a prime request needs picture analysis, the backend claims the big
  local engine. Nothing running there is stopped, paused or switched to another model: new agent work starts on its cloud
  replacement at once, and the claim waits for the agent runs that are already on the engine to finish. You see "waiting
  for the engine, N min left". **A claim is not instant**, and with long agent runs under way it often will not come in
  time.
- **If the engine is not free within 10 minutes**, the watched request ends with the reason (for example "the engine is
  in use by the owner") and the one-press Quick offer of phase 1. It never waits without end and never sends pictures to
  the cloud. Grids that were already described stay stored, so asking again later continues where it stopped; the same
  holds for a long Dense build that reaches the 2-hour claim limit.
- **While a claim lasts, normal users' requests that need a model on that engine wait**, up to the length of the claim.
  The example config therefore gives the normal class a text model on another engine.
- **Cloud is a choice per class.** Prime text work (summaries, answers, the cut editor) may use the cloud when the local
  model is busy. Normal users use local models when they are free and wait otherwise; the server refuses to start if their
  route could reach the cloud.
- **Effort notch.** Watched gets three levels: Keyframes (one grid a minute), Standard (phase 1) and Dense. Normal users
  default to Quick and may use Watched at Keyframes; prime defaults to Standard.

Decisions (each with the recommendation):

| # | Decision | Recommended | Alternative |
|---|---|---|---|
| D-P1 | Where the claim lives | The conductor owns the claim (page control, API, audit, limits, expiry) and switches the gateway with the existing mode switch | A claim feature inside the gateway itself; revisit if claims pass about 20 a day |
| D-P2 | Vision model under a claim | Decided by the bake-off only. The plan assumes the bake-off winner is loaded in place of the usual big model for the length of the claim (minutes each way). The usual model is bake-off entry 4; if it passes the bar, no model change is needed and that is used instead | Skip entry 4 and always swap |
| D-P3 | The engine cannot be claimed in time (D-P11) | The request ends with the reason and offers Quick | Send the pictures to a cloud model, labelled "Watched (cloud)" (reopens phase 1 decision 3) |
| D-P4 | Text tasks for prime | Local first; the cloud only when the local model has not started answering within 5 s | Cloud always, as the server is set up today |
| D-P5 | Normal users and Watched | Allowed at Keyframes only; default Quick | Not allowed at all |
| D-P6 | A running normal build when prime work arrives | Pause after the current grid, resume after | Let it finish first |
| D-P7 | Users on the TV | Each YouTube account can pair with its own u·tubot user, with that user's own pairing code; unknown or unpaired accounts use the device's user | One user per device as today (a child on your TV would then be prime) |
| D-P8 | Claim limits | 30 minutes, renewed while the job runs, 2 hours at most per claim, then a 10-minute pause for the same claimer; at most 4 hours of claims a day for the backend as one claimer (all prime users share it), with an alert when a limit is hit. Claims you make by hand are outside the pause and the daily limit | Other numbers |
| D-P9 | The engine is in video mode | A claim is refused; the request gets the Quick offer at once. Video mode is only left by hand | A claim ends video mode |
| D-P10 | "Automatic" claims | The backend claims by itself when a prime job needs it, and releases after; no click | Also time windows or rules on the conductor |
| D-P11 | Agent runs already using the engine when a claim comes | The claim waits for them to finish, at most 10 minutes, then fails with the Quick offer. New agent work goes to the cloud replacement for its whole run. Nothing is ever frozen, stopped or switched in mid-conversation | A longer wait; or switch those runs to the cloud model in mid-conversation and mark them |

## P.2 Facts checked for this phase

- Users: `UserConfig` has `name`, `token_sha256`, `admin`, `policy`; `admin` is flipped in `users.toml` by
  `set_user_admin` and through `PUT /v1/users/{name}`; a user cannot change it for itself. There is no class or priority
  on a user. Pairing codes are created by the signed-in user for itself (`POST` behind "Pair my TV") or by an admin for a
  named user.
- The TV keeps one backend address and token "shared by every account" (`UtubotSettings`), so today every YouTube account
  on a device is the same u·tubot user.
- Priorities: `llm.py` has `INTERACTIVE` and `BACKGROUND` and a `PriorityLimiter` per provider (`max_concurrent`,
  `reserved_interactive`); `JobQueue` claims jobs `ORDER BY priority, created_at`; the YouTube gate takes the same
  priority; cut builds run as their own tasks with a per-user cap. Nothing distinguishes users.
- Providers: every task table names a model and optionally a provider and fallbacks; a provider has one key
  (`api_key_env`). The route cannot depend on the caller today.
- The gateway (modelgate) decides per client key whether cloud engines may be reached (`allow_cloud`) and refuses
  otherwise with `403 cloud_not_allowed`. It has no claim or hold feature.
- The owner's infrastructure already has a mode switch that repoints the gateway's coding aliases to a cloud model while
  the big local engine does other work, and back. It is driven by hand today. The engine has a memory guard that refuses
  to load a model that does not fit; the gateway then serves an alias from its fallback when it has one (this happened in
  the conductor's own history). Read, not run, for this plan.

## P.3 Decisions (backend and clients)

### P.3.1 Classes

- `UserConfig.prime: bool = False`, stored like `admin`: `users.toml`, `set_user_prime`, `utubot user prime NAME on|off`,
  `PUT /v1/users/{name}` `{"prime":bool}` (admin only; a user declared in `config.toml` answers `409` as for `admin`).
  `GET /v1/me` and the user list carry `"class":"prime"|"normal"`. It is not part of `UserPolicy`. The class is read from
  the authenticated user on the server for every request; no header, query or body field can state it.
- Everything a request starts inherits the class of the user who asked: `jobs.klass` and `cut_requests.klass`
  (`TEXT NOT NULL DEFAULT 'normal'`, additive).
- Shared builds (same cache key): the build's class is the highest class among the requests **waiting** on it, and it only
  ever rises. A normal request that joins a prime build does not change it; a normal request can never raise a build. A
  normal user who asks for something a prime build already made gets the stored cut: the class limits compute, not
  content.
- Order everywhere is (class, then today's priority, then age): `JobQueue`, `PriorityLimiter` (prime waiters first;
  `reserved_prime = 1` slot per provider that normal work cannot take), the YouTube gate, the watched slot.
- "Demanding work" is a named set: watched builds, caption and transcription jobs. While a prime demanding job is running
  or waiting, no normal demanding job starts (stage `in_line`, reason `priority`), and a running normal one yields at its
  next safe point: a watched build after the current grid (at most `describe_timeout_s`; describing is resumable per grid,
  2.4), a caption job after the current ASR chunk. The paused request shows `in_line` with the reason and its progress
  so far. Small interactive calls of normal users are not held; they queue behind prime in the limiter.
- Per-class defaults in config, `[classes.prime]` and `[classes.normal]`: `cut_mode`, `watched_effort`,
  `watched_max_effort`, `max_active_cuts`, `routes` (P.3.2). `UserPolicy` values still apply within what the class allows.

### P.3.2 Routes per class

A route is a named way to reach a model; a class lists the routes it may use, in order, per kind of work.

| Route | Meaning | Key |
|---|---|---|
| `local` | The shared local models | a gateway key that cannot reach cloud engines |
| `claimed` | The big local engine while this backend holds a claim on it (P.3.3) | its own key, also unable to reach cloud engines, and different from the `local` key so the gateway can tell the claimer's requests from everyone else's |
| `cloud` | A provider that may reach cloud engines | a different key |

- Providers gain `route = "local"|"claimed"|"cloud"`. Each task table gains
  `by_route = { local = "<alias>", claimed = "<alias>", cloud = "<alias>" }`; a missing entry means the task cannot use
  that route. Precedence: with `[classes]` configured, `by_route` is the only source and a task without it is a startup
  error; without `[classes]`, `model` is used exactly as today and `by_route` is ignored.
- `[classes.<class>.routes]`: `text = [...]`, `pictures = [...]`, `speech = [...]`. Defaults: prime
  `text = ["local","cloud"]`, `pictures = ["claimed"]`, `speech = ["local"]`; normal `["local"]` for all three. A config
  that gives normal a `cloud` route, or pictures a `cloud` route without D-P3's alternative being switched on, is a
  startup error.
- **Startup validation** (the server does not start with `[classes]` configured unless all hold):
  1. the `local`, `claimed` and `cloud` providers have three different `api_key_env` names and three different key
     values;
  2. each `local` and `claimed` provider passes the cloud check: one request for `[llm] cloud_check_alias` (an alias the
     admin names that is served only by a cloud engine) must be refused by the gateway with its "cloud not allowed"
     answer. Any other answer, including a success, stops the start with a message naming the provider;
  3. the `claimed` aliases have no `fallback` in this config.
  The check is repeated every `route_check_every_s = 3600`; a failure disables classes' model calls on that provider and
  raises an admin-status error (requests then wait, they do not move to the cloud).
- Trying the next route: a refusal moves on at once; a busy local model moves on after `cloud_after_s = 5.0` without a
  first streamed byte (prime text only, D-P4), and the local request is then cancelled, so one answer is used and one
  cloud call is paid. When the list is exhausted a text or speech request waits and retries its first route
  (back-pressure as today); it never fails for being normal. Pictures follow P.3.3.
- The `claimed` route never falls through to anything: any answer other than a success (refusal, not found, engine or
  memory-guard error, a claim that ended while the request was running) fails that request, and the job goes back to
  the claim logic of P.3.3. A request cannot be answered by another model, because the alias has one target and no
  fallback on both sides (this config and the gateway's, P4).
- `GET /v1/admin/status` shows the routes per class, which one served the last request of each task, the last route
  check, and the current claim (held or not, seconds left, the service's own link when it sends one).

### P.3.3 Engine claims, as this backend sees them

The backend speaks a small HTTP contract to a claim service; it does not know what stands behind it. Without
`[engine_claim]` the route `claimed` is unavailable. **The contract is frozen first**, as `ai/ENGINE_CLAIM_CONTRACT.md`
(checkpoint P0), and both plans refer to that file; the text below is its draft.

- `[engine_claim] url`, `token_env`, `engine = "<name>"`, `ttl_s = 1800`, `renew_every_s = 300`, `renew_retry_s = 20`,
  `claim_wait_max_s = 900`, `release_idle_s = 60`, `claim_retry_max = 1`.
- `POST <url>` `{"engine","reason","ttl_s","client_ref"}` -> `201 {"id","state":"draining"|"active","expires_at",
  "max_expires_at","ready_by","waiting_for"?,"link"?}`. `ready_by` is the time by which the service will have made the
  claim `active` or failed it; `waiting_for` says what it waits for (`runs`, `idle`, `model`). `reason` carries this
  backend's job id, nothing about the user. The holder is whoever the token belongs to; `client_ref` is an opaque string this backend
  chooses (its instance id) so it can find its own claim again. `409 {"reason","holder_kind"?}` with `reason` one of `held`
  (`holder_kind` `owner` or `other`), `other_mode`, `engine_down`, `actuator_failed`, `runs_busy`, `drain_timeout`,
  `max_reached`, `cooldown`, `budget`. A `draining` claim that the service gives up ends as `failed` with one of the same
  reasons.
  `POST <url>/<id>/renew` -> `200 {"expires_at"}` or `409` (`max_reached`, or the claim is gone).
  `DELETE <url>/<id>` -> `200`. `GET <url>?engine=&client_ref=` -> the caller's open claim or `404`.
  `GET <url>/<id>` -> its state (`draining`, `active`, `released`, `expired`, `failed`).
- Times: only the service's `expires_at` counts; the backend never computes an expiry from its own clock and `ttl_s`.
- Getting a claim: the backend asks when a prime job needs the `claimed` route and polls the claim while it is
  `draining`. The service owns the waiting time: it waits for what has to finish and fails the claim itself at
  `ready_by`. The request shows "waiting for the engine, N min left" from `ready_by`. `claim_wait_max_s` is only this
  backend's outer guard and must be larger than the service's longest wait (checked against the first `ready_by`; a
  smaller value is a logged configuration error and `ready_by` is used). A `409` on asking ends the wait at once.
- Giving up: whenever the backend stops waiting (the claim failed, the guard ran out, the user dismissed the request, the
  job was cancelled) it sends `DELETE` for the claim, so the engine is never held for nobody.
- The sentence shown comes from the reason: `held` by the owner reads "The engine is in use by the owner right now.",
  `runs_busy` "Other work on the engine did not finish in time.", and so on; none of them reads like a fault of the
  video. The request then carries the `fallback` to Quick of 2.8.
- Under any claim `describe_concurrency` is 1 until a memory budget for parallel requests has been measured (companion
  plan).
- Holding it: renewal runs on its own timer every `renew_every_s`, independent of the describing loop (a slow grid cannot
  stall it). A renewal that fails in transport is retried every `renew_retry_s` until 60 s before `expires_at`; a `409`
  or reaching that point means the claim is lost.
- A lost claim, or any failure on the `claimed` route (P.3.2), ends the current grid's request as failed and stops the
  job at that grid. The backend releases what it holds, then asks once more (`claim_retry_max`), with the same wait limit.
  A second loss or failure in the same build ends it with the Quick offer; the grids already described stay cached, so
  a later request (after a `cooldown`, for example) continues from them. A
  memory-guard refusal is such a failure: it is never retried in a loop.
- Release: when no prime job needs the route any more, after `release_idle_s` (two cuts in a row share one claim), and on
  shutdown. On start the backend looks up its claim by `client_ref` and continues it if a prime job is waiting, else
  releases it. A killed backend releases nothing: the service's expiry ends the claim.
- Only prime-class jobs reach this code; there is no claim call on any path a normal user's request takes.
- The job report gains the stage `claim` (asked, waited, state, reason, lost). No address or token of the service is
  logged. The token comes from `token_env` only.

### P.3.4 Effort

- Three levels, `keyframes`, `standard`, `dense`, as named grid settings in `[cuts.watched.effort.<level>]`:
  - `keyframes`: the budget split of 2.2 from the start, one grid per `keyframes_grid_s = 60` (four frames a minute, taken
    at scene cuts where there are any), `max_grids = 90`. That equals the 90-minute limit, so within it the level is never
    coarser than one grid a minute; an admin who raises `max_video_minutes` gets a coarser split above 90 minutes, and the
    cut says `"coarse": true`;
  - `standard`: the phase 1 settings;
  - `dense`: scene-analyser's `high_recall` preset (threshold 0.34, 2.5 fps analysis, chunks 3.5 to 12 s), at most 480
    grids. Its parallel requests under a claim are limited by the measured memory budget of the companion plan.
- Contract (additive): optional `"effort"` beside `"mode"` on the build routes; `modes[]` entry of `watched` gains
  `"efforts":[{"id","label","default":bool,"available":bool,"eta_s"}]`; the cut document's `watched` object gains
  `"effort"`. An effort above the class's `watched_max_effort` answers `403` with a plain sentence.
- Caching: the effort is part of the grid settings key, so each level has its own manifest and TDT. A request is served
  from a stored TDT of the same or a higher level when one exists. A normal user can so receive a cut made from a Dense
  description that a prime user paid for; the limit is on what a class may start, not on what it may be given.
- Expected first-cut time at `keyframes` for a 20-minute video: 20 grids, under 2 minutes at the expected 2 to 5 s per
  grid, 2 to 5 minutes at the March speeds. Estimates, like the phase 1 table.
- Clients: a second row under the mode switch, "Effort: Keyframes / Standard / Dense", the default marked, levels above
  the user's maximum not shown. TV, phone and extension alike; the parity-matrix row of phase 1 is extended.

### P.3.5 Users on the TV and in the extension

- TV: the token store becomes per YouTube account with the device token as fallback. Settings gain "Pair this account".
- **Fail closed.** The token for a request is chosen at the moment the request is made, from the account the app reports
  as signed in right then. Unknown, unresolved, signed out or mid-switch: the device token. The last-used account's token
  is never reused for another account. An account switch drops the per-user caches and cancels requests in flight, as a
  token change does today.
- **Pairing needs the target user.** An account is paired with a code that only the target u·tubot user (or an admin) can
  create, as device pairing works today, so a child cannot attach an account to your user without a code from you.
  Account tokens are kept in the app's private storage in the same form as the device token; `pair` requests carry
  `"scope":"device"|"account"` so the server knows which kind a token is.
- The web UI's device list shows the scope, and warns the user and the admin when a prime user is some device's default
  ("everyone on that TV is prime").
- Extension: one u·tubot user per browser profile, as planned; no change. `ai/CONTRACT.md` "Clients" gains the per-account
  pairing as a TV-only item with this reason (a browser profile already is one person). Requests from the extension get
  the class of its user like any other.
- Web UI: the user list shows and edits the class; Settings shows your class and what it allows.

## P.4 Checkpoints

Repositories: **u-tubot** (this one), **modelgate** (the gateway), and the owner's private **conduktor** and
**evreniops**; the steps in the last three are specified in the companion plan and only named here.

| # | Repo | Scope | Done when (tests never contact YouTube or a real engine unless marked "drill") | Tier |
|---|---|---|---|---|
| P0 | u-tubot | `ai/ENGINE_CLAIM_CONTRACT.md`: the frozen contract of P.3.3 (requests, answers, every `409` reason, times, `client_ref`), reviewed against the companion plan | both plans link to the merged file; P2, P5 and P6 do not start before it | Fast |
| P1 | u-tubot | Classes: `prime` flag, CLI, API, web UI checkbox, `klass` columns, ordering in queue, limiter, gate and cut cap, normal demanding work waits and yields, shared-build rule | unit: a normal job queued first starts after a prime one queued later; with a prime watched build active a normal one stays `in_line` with reason `priority`; a running normal build stops after its current grid and finishes later with the same TDT; a build's class rises when a prime request joins and never through a normal one; every route is called as a normal user with `prime`, `class` and `klass` in headers, query and body and the class stays normal (the route list is enumerated as in `test_webui.py`); `GET /v1/me` reports the stored class only; a job made with an extension-style token has its user's class; migrations additive | Heavy |
| P2 | u-tubot | Routes: `route` on providers, `by_route`, `[classes.*.routes]`, startup validation and the repeated cloud check, next-route rules, status | startup fails for each of: any two of the three routes sharing a key env or a key value, a local provider whose cloud check is answered, a `claimed` alias with a fallback, a normal class with a cloud route; mock gateway with two keys: no request of a normal user carries the cloud key (asserted on every recorded request); a "cloud not allowed" answer makes a normal request wait and retry, not fail; prime text moves to cloud after `cloud_after_s` measured to the first streamed byte, the local call is cancelled, and a local answer arriving at 5.1 s is not used twice; a non-success on `claimed` is never retried on another route; servers without classes behave as before (replayed requests) | Heavy |
| P3 | evreniops | The mode switch gains `claim` and `release` with its own cap and expiry timer; the claim map covers every alias that targets the big engine | companion plan; tests against a fake gateway admin API | Fast |
| P4 | modelgate | The usual big model as bake-off entry 4; in-flight counts per alias and client readable by the claim service; the fallback-free picture alias; two no-cloud client keys (one for `local`, one for `claimed`) | companion plan; production-config test | Fast |
| P5 | conduktor | Claim API per the frozen contract, scoped token, limits and budget, new agent work pinned to the replacement, the bounded wait for running work and the idle check, expiry, audit, the page control | companion plan; pytest with a stub actuator | Heavy |
| P6 | u-tubot | Claim client: `[engine_claim]`, wait limit, timer renewal, lost claim, restart lookup, job-report stage, the Quick offer | `tests/mock_claims.py`: a prime watched build claims before its first grid and renews on the timer while one grid takes longer than `renew_every_s`; two prime builds in a row share one claim and it is released `release_idle_s` after the second; each `409` reason and each failed-claim reason gives its sentence (`held` by the owner reads as in use, not as a fault) and the request ends with `fallback` to Quick; the remaining minutes shown come from `ready_by`; a `DELETE` is sent on every way of giving up (failed claim, guard, dismissed request, cancelled job); a claim that expires on the service's clock while the backend's clock runs slow is treated as lost; a guard-style error on the claimed alias releases, asks once more, then ends with the Quick offer and keeps the described grids; the backend is killed while holding a claim, the mock expires it, the restarted backend finds nothing by `client_ref` and asks again; restarted while the claim is alive, it continues it; no claim call is made for a normal user on any route | Heavy |
| P7 | u-tubot | Effort: settings, contract, cache rule, class limits, mock backend, the three clients | synthetic clip: `keyframes` yields one grid per 60 s, `dense` more grids than `standard`; a 90-minute generated chunk list gives 90 grids at `keyframes`; a stored `standard` TDT serves a `keyframes` request without a vision call; a normal user asking for `standard` gets the `403`; TV and web UI tests for the notch; emulator recipe with the mock | Fast |
| P8 | u-tubot (app) | Per-account pairing on the TV, fail closed | unit tests for the token store: account A paired with a prime user, then account B unpaired, then signed out, then an unresolved account: A's token is used only for A; a switch cancels requests in flight and clears caches; `scope` sent on pairing; emulator run against the mock with two mock users and no real YouTube account, recorded | Fast |
| P9 | all | Owner drill on the real machines, with the backend in offline mode and an imported video; needs P4's picture alias | recorded: a prime watched cut asks for the engine while one agent run is on it, new agent work answers from the replacement, the claim becomes active when that run has ended, the grids are described locally, the claim is released, the aliases are back; a second try with a run that outlasts the wait ends in the Quick offer with nothing changed; a normal request made meanwhile waited; a claim asked during video mode gave the Quick offer | Fast |

Order: P0 first. P1 can start once phase 1 checkpoint 1 has landed; P2 after P0 (it tests against mocks; the real
no-cloud key comes with P4). P3, P4, P5 are outside this repository; P5 after P0. P6 needs P2 and P5. P7 needs phase 1
checkpoint 4. P8 needs P1. P9 needs all.

## P.5 Tests without YouTube

- Everything in this repository runs against mocks: `tests/mock_openai.py` grows a second key, the gateway's refusal
  answers, a streamed first byte with a settable delay, and a memory-guard style error; a new `tests/mock_claims.py` plays
  the claim service with a settable clock (grant, drain, refuse with each reason, expire, lose). Users of both classes
  come from the test config. Watched cases use the synthetic clip and the fake downloader of phase 1.
- `scripts/emulator_mock_backend.py` gains `class` on `/v1/me`, `efforts`, the `in_line` reason and two users, so the TV
  and the extension are checked without a server and without a real account.
- The drill (P9) is the only step on real engines. It uses `[youtube] offline` and `utubot media import`, so it makes no
  request to YouTube either.

## P.6 Not verified for this phase

- Whether the usual big model answers pictures (the gateway declares it without image input; the model research did not
  check it). D-P2 is decided by bake-off entry 4, not before.
- How long a model change takes in both directions, and what memory it needs. The swap path is not allowed before the
  companion plan's measured memory budget and its engine-side state for a loaded vision model exist.
- How often the engine becomes free within 10 minutes when agent work is under way; the drill and the first weeks of use
  show it, and D-P11's wait is a config value on the service.
- Whether the gateway exposes in-flight request counts (P4 adds them per alias and client). Use of the engine that does
  not go through the gateway is invisible to the idle check and is out of scope.
- Whether every alias the coding agents use is covered by the mode switch (the companion plan makes it a test).
- The 5 s first-byte threshold for prime text, and the keyframes level's quality (the labelled set of 2.11 gets an effort
  column).
- How the TV learns which YouTube account is active at the moment a request is made (the account code is upstream's; read
  only at `UtubotSettings`). P8 is written fail closed because of this.
- Whether the app's private storage for tokens is encrypted on every device the app supports.

## P.7 Review response (phase 2)

Review of the first phase 2 text (clean context, verdict: needs changes, five high and eight medium findings).

| # | Finding | Answer |
|---|---|---|
| H1 | A refused claim left a prime watched build waiting without end | P.3.3: a bounded wait (first 3 minutes, now the service's `ready_by`, see the re-check), then the Quick offer; some reasons end the wait at once. D-P3 is the owner's choice between that and labelled cloud pictures |
| H2 | Key isolation rested on choosing the right key | P.3.2: startup validation (separate keys, a cloud check that must be refused, no fallback on claimed aliases), repeated hourly; `claimed` uses a no-cloud key and never falls through |
| H3 | Drain was a fixed 10 s; runs in mid-conversation undecided | D-P11 and the companion plan: an idle check on the engine, agent runs parked between requests and resumed (parking was dropped in the re-check below), new agent work on the replacement for its whole life, the claim fails after 2 minutes without idle and changes nothing; a model change only after idle |
| H4 | The engine's memory guard was not handled | P.3.2, P.3.3: one target and no fallback on the picture alias on both sides (tested in P2 and P4), a guard refusal is a claim failure with one new attempt, no loop; the swap path waits for a measured memory budget (companion plan) |
| H5 | Claim authority was thin | Companion plan: token scoped to claims on one engine, per-claim cap enforced by the service and by the switch, cooldown, daily budget with alert, a private-network-only route with a source check, token from the vault and rotated. P.3.1: class cannot be stated by a client; shared builds rise one way only |
| M1 | An agent alias missing from the claim map | Companion plan: a test that every alias targeting the big engine is in the map, the opposite check for the conductor's own alias, and a drill step |
| M2 | "No model change" presented as likely | D-P2 reworded: the bake-off decides, the plan assumes a swap, P.1 says a claim is not instant; the replacement lane is never a picture route (P.3.2 startup rule) |
| M3 | Contract not frozen; `holder`; repository names; P9 and the alias | P0 freezes `ai/ENGINE_CLAIM_CONTRACT.md`; the holder is the token's owner, `client_ref` replaces the body field; repositories named; P9 needs P4 |
| M4 | Expiry and renewal edges | P.3.3: the service's `expires_at` only, renewal on a timer with retries, lookup by `client_ref`, a lost claim fails the running request; the cloud budget during a claim is in the companion plan |
| M5 | The engine-side watchdog could reload the usual model over a vision model | Companion plan: a third engine-side state, specified before the swap path is allowed; P.6 |
| M6 | TV pairing could hand a child the prime token | P.3.5: fail closed, the target user's own code, scope on tokens, a warning for a prime device default; P8's A-then-B test |
| M7 | Missing tests | P1 (class spoofing on every route, extension token), P6 (killed backend, restart, two builds sharing a claim) |
| M8 | Keyframes cap against long videos; higher-level TDT for normal users | P.3.4: the cap equals the 90-minute limit; the limit is on compute, not content |
| L | Names, precedence of `by_route`, first-byte case, status, paused state, emulator account, decision numbering | P.4 header, P.3.2, P2's test, P.3.2 status line, P.3.1, P8, D-P numbering |

Re-check of that revision (verdict: needs changes; one new high on parking, four mediums). The owner's side simplified
instead of patching: parking is dropped.

| # | Finding | Answer |
|---|---|---|
| N1 | Freezing agent runs is unsafe | Dropped. D-P11: new agent work goes to the replacement for its whole run, the claim waits for running work with a limit, then fails with the Quick offer; nothing is frozen, stopped or switched |
| N2 | Pinned runs, the cloud budget, other aliases of a run | Companion plan: the pin is a whole run profile (every model of the run), shown on the page; at the cloud cap pinned runs fail as provider errors and are retried on the local model |
| N3 | In-flight counter and whose requests count | P.3.2: the `claimed` route has its own key; companion plan: counts per alias and client, leak-proof, engine use outside the gateway documented as out of scope; P.1 states that normal requests on that engine wait during a claim |
| N4 | A 3-minute wait did not fit drain and a model change | P.3.3: the service owns the wait and sends `ready_by`; the backend's guard is larger; `DELETE` on every give-up; a sentence per reason, `held` by the owner included |
| N5 | Limits in two places | Companion plan: one tested inequality between the switch's cap and the service's limits, the owner's own claims outside pause and daily budget, the service is the source of truth and the switch the safety net. P.1 and P.3.3: a build that hits a limit continues from its stored grids later |
| L | Parallel requests under a claim; job id in the reason | P.3.3 |

