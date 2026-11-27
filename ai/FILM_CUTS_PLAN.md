# Film cuts: a story-aware director's cut (plan)

Status: draft 1, 2026-11-27. Nothing is implemented. Waits for the owner's decisions in Part 1.
Scope: how a cut of a film (or any long story) is built, from captions alone and from a locally "watched" film.
Related: #229 (`cut-skim-film`), #83 (cut quality review), #82/#100/#143 (target length), #95 (map/reduce), #88 (Stremio films),
`ai/CUT_MODES_PLAN.md` (quick and watched modes), `ai/CONTRACT.md` ("Director's cuts"), the vision-model research
[conduktor#141](https://github.com/evrenesat/conduktor/issues/141).

---

# Part 1: owner plan

## What went wrong with the half cut of Üç Kağıtçı (the method, more than the model)

- The model never chose what to keep. It returned the whole film as 38 scenes (91 % of the runtime) with a rank each.
  The server then dropped the lowest ranks until half was left.
- Only the top 7 ranks were real choices. After that the ranks simply follow the film's order, so "lowest rank" meant
  "latest in the film": the first quarter was kept at 86 %, the last quarter at 18 %.
- One skip is 24 min 43 s long (53:05 to 77:48). In the cut Rıfkı is never elected mayor, never loses the rain bet and
  never dreams he will die; then he says "I did not die" and resigns as mayor.
- The same happens in the middle: the trap with the real cripple, the buried gold and the bribe are all kept, and the
  scenes where they are planned are all cut. Six such pairs are listed in Part 2 (1.3).
- Nothing in the method knows what a cause is. One request, no thinking, 5.6 seconds for an 81-minute film, a task of
  one sentence ("half the size, most meaningful parts"), and nothing checked the result.

## What changes

1. **Read first.** The film is read once into a story map: scenes, beats, who is who, and which beat needs which earlier
   beat to make sense. This is kept, so a second cut of the same film is quick.
2. **Choose on purpose.** The model gets a purpose ("a first-time viewer must follow the whole story in half the time")
   and scores beats against it. Code, not the model, holds the length, and it may never keep a result without its cause.
3. **Review.** A second model reads the cut as a viewer would, scores consistency, information density and goal match,
   and names what is missing. The cut is repaired and checked again, at most twice. The scores are shown on the cut.
4. **Models per step, measured.** Each step has its own model setting. A bake-off on this film compares the current
   model (thinking off and on) with general, non-coding models; time and cost per step are recorded.
5. **Watching, locally and fast.** The existing watched mode feeds the same story map with what is on screen. It runs
   only on the local engines, with grids described in parallel. Goal: a 90-minute film watched in 10 minutes or less.
6. **Your half cut is rebuilt** by itself once the new method passes; you do not have to ask again.

## What you get first (MVP)

A paper cut of Üç Kağıtçı from captions only: kept and skipped beats, one line each, from two or three models, before
any server change. You judge it in minutes without watching; the best one goes into the server for film-length cuts.

## Time per film (estimates until measured)

| | Today | New, first cut of a film | New, another cut of the same film |
|---|---|---|---|
| Captions only | 6 s | 2 to 5 min | 30 to 90 s |
| Watched (local engines) | not usable for films | 10 min or less to watch, then as above | 30 to 90 s |

## Decisions needed from you

1. **Test films:** this film plus three you know well. Recommended: two more from the same channel and one in another
   language. You name them; the server needs their captions once.
2. **Cloud reference in the bake-off:** may one strong general cloud model read film captions, only to compare?
   Recommended: yes for the bake-off, no for watched mode ever.
3. **Skip notes:** show a one-line "skipped: ..." note at long skips? Recommended: yes on the web page first, TV later.

---

# Part 2: agent plan

## 1. Facts checked (read-only, 2026-11-27)

### 1.1 The build that failed

| Fact | Value | Source |
|---|---|---|
| Video | `evqNEHYAfDE`, 4889 s (81:29), Turkish, YouTube automatic captions uploaded by the client | `video_meta`, `transcripts` (`caption_kind=auto`, `origin=client`) |
| Input | 1597 caption segments, 926 units after `build_units`, 63 k characters of unit lines | recomputed with `build_units` at `7c9fa3ae` |
| Request | `675edfafa45f`, preset `cut-mine-09aefa8d6b9a` ("half-cut"), mode quick | `cut_requests` |
| Task text | "Create a cut of this video with the half of the original size, preserving most meaningful parts of the video, best moments etc." | `prompt_sets` |
| Model | the configured cuts alias, `reasoning_effort = "none"`, `max_tokens = 2500` | server config `[llm.cuts]` |
| Path | single pass (the transcript fits `max_input_tokens`), no map/reduce | `CutEngine.fits` |
| Wall time | 5.6 s from request to ready | `cut_requests` |
| Model answer | 38 parts covering 4427 s (91 % of the film), every part ranked, self-reported `kept_s` 2932 | `cut_requests.raw_answer` |
| Stored cut | 17 parts, 2502 s (target 2444 s) | `cuts.json` |

The same video's `cut-highlights-5` (request `a11fe7649844`, 331 s) shows the same mechanism: 15 moments proposed, the rank
trim kept 5, all from the first 44 minutes.

### 1.2 Why it failed, in the code

1. **The model segments, the server selects.** `serialize_units` asks for "a little more than the target" plus a rank and
   says "the server drops the lowest-ranked parts until the target fits". The model answered with a scene list of the whole
   film. `select_for_target` then kept ranks 1 to 19 and dropped ranks 20 to 38. Selection by rank is independent per part:
   it cannot know that part 24 ("the real cripple plan") is why part 3 ("the real cripple walks") exists.
2. **Ranks degrade into position.** Ranks 1 to 7 are the famous payoffs. Ranks 8 to 19 are all of act one. Ranks 20 to 38 are
   in strict video order. A model without thinking cannot rank 38 parts globally; the tail of the ranking is the tail of
   the film.
3. **No thinking, small answer.** `reasoning_effort = "none"` and 2500 answer tokens leave room for a list of ranges and
   nothing else: no synopsis, no reasons, no arithmetic (the model reported 2932 s for 4427 s of parts). The cap did not
   truncate this answer (about 1000 tokens); it prevents any richer one.
4. **No purpose.** `CUT_SYSTEM` says "choose units so the video plays the way the task asks". The task is one sentence.
   Nothing says who watches, what they must still understand, or that a result needs its cause.
5. **No story model.** Units are flat numbered lines. Pauses, scene changes and speakers are invisible (automatic captions
   have no speakers and spell the hero's name five ways). The answer carries a label per part and no reason.
6. **No review.** `finalize_parts` checks length and format only. Nothing reads the result.
7. **Map/reduce would be worse, not better.** It did not run here. For a longer film, or a model with a smaller input, each
   excerpt is cut "as if on its own", the reduce call sees 160 characters per candidate and is told that ranks of different
   excerpts are not comparable. Cause and effect in different excerpts cannot be linked at all.
8. **`cut-skim-film` (#229) uses the same path.** Its better task text asks for the arc, but the single pass and the rank
   trim are unchanged, so the same failure is expected.
9. **No cost record for cuts.** `feature_calls` on the server holds only triage rows; the cut calls of 26 Nov are not
   there. Checkpoint 0 finds out why (not recorded, or recorded elsewhere), because every step below must be measured.

### 1.3 Evidence: causes removed, results kept

Times are film time. "Kept" and "cut" refer to the stored half cut.

| # | Cut (the cause) | Kept (the result) | What the viewer misses |
|---|---|---|---|
| P1 | 25:09 to 27:39: the rich man blackmails the village for the mayor election; Hasan decides to make Rıfkı a rival and to raise his fame with a staged miracle | 30:05 to 32:22: the staged healing and Hasan's "our trick worked, we reach our goal" | which goal; that there is an election at all |
| P2 | 33:40 to 34:34: the opponents decide to bribe Rıfkı; his candidate speech | 35:03 to 38:15: the briber interrupts "my speech"; Rıfkı is "back on duty as candidate" | why a bribe, which speech, candidate for what |
| P3 | 38:11 to 41:02: Sabri reveals the healings are staged and plans to bring a real cripple; the doctor says only a miracle helps | 41:02 to 44:02: the real cripple walks | that it was a trap, and why it backfires |
| P4 | 44:10 to 46:36: the lost bet's aftermath and the plan to bury a tin of gold that Rıfkı must find | 47:35 to 53:05: the gold challenge | why gold is buried, who set it up |
| P5 | 53:14 to 68:28: Rıfkı becomes mayor and governs; the plot to cure his rheumatism; the lost rain bet | 79:24: "I knew the rain from my aching feet ... I resign as mayor"; the town: "we cheated people, you set us straight" | he is never mayor in the cut; none of what the town thanks him for |
| P6 | 68:37 to 77:43: the dream of his death, the announcement, coffin and helva, the countdown | 78:12: "I am sorry, I did not die" | the entire death story (9 minutes, 0 seconds kept) |

Also: a **dangling setup** (D1): the bride-price thread is opened at 7:35 to 9:16 and kept; its two later scenes (32:19 and
72:19) are cut. And **low density** at the start: quarter one is kept at 86 %, greetings and waits included.

Kept share per quarter of the runtime: 86 %, 59 %, 42 %, 18 %. Longest skip: 1483 s.

### 1.4 What exists and is reused

- `build_units`, `parse_cut_answer`, `finalize_parts`, padding, merge, guards, the cut document and cache (`cuts.py`).
- Per-task model tables (`LLMTask`), `feature_calls`/`feature_models` (per-feature alias, admin-switchable, cost columns).
- `stage_cache` (per video, stage, key) for the new story artifacts.
- Watched mode (`watch/`, `[cuts.watched]`, `video_scenes`, `scene_descriptions`, `[llm.cuts_vision]`), the media archive.
- `cutbench.py` and `scripts/cut_bench.py` (offline scorer with a supplied model callable), `tests/mock_openai.py`.
- `algo_version` on `cuts` and the repair queue (`repair`), used to rebuild old cuts.

## 2. Decisions

### 2.1 When the story method runs

New table `[cuts.story]`. The story method builds the cut when all hold: `enabled`; the cut has a target length (seconds
or fraction); and either the preset is in `presets` (default `["cut-skim-film"]`) or the video is at least
`min_duration_s = 2400` long and the story map says `kind = "story"` (2.3). Everything else keeps today's path. Removal
presets (`cut-no-filler`, `cut-answer`, `cut-demo`) never use it. `cut-highlights-5` on a story uses it with the purpose
"best moments" (closure rule relaxed to soft, 2.5).

### 2.2 Step 0: units with visible structure (code)

`build_units` as today, plus lines the model can use and cannot select:

- `--- pause 14 s ---` between units when the gap is at least `pause_mark_s = 3.0`;
- `--- music ---` for caption-only music marks (`[müzik]`, `[music]`, `♪`), which today are units;
- in watched mode, the `S` lines of `ai/CUT_MODES_PLAN.md` 2.2 and a `--- scene cut ---` line at stored scene cuts.

### 2.3 Step 1: read (model step `cuts_read`, cached per film)

Purpose-free. Input: title, channel, chapters, the unit lines. Output JSON:

```
{"kind":"story|talk|other","language":"tr","synopsis":"<= 600 chars",
 "cast":[{"id":"c1","name":"Rıfkı","aliases":["Rıfka","Rıpkı"],"role":"<= 80 chars"}],
 "scenes":[{"id":1,"from":3,"to":61,"where":"<= 40","who":["c1","c2"],
   "beats":[{"id":1,"from":3,"to":41,"what":"<= 160 chars"}]}]}
```

Rules checked by code (one repair round, then the build fails with a plain reason): scenes tile all units in order with
no gap and no overlap; beats tile their scene; ids exist; a beat is at most `beat_max_s = 240` (longer beats are split at
the largest pause). Expected size for this film: 45 to 70 scenes, 110 to 170 beats.

Long input: when the message does not fit, the film is read in **sequential** windows of `read_window_tokens = 20000`
with `read_overlap_units = 8`; each window gets the synopsis so far, the cast and the last 12 beat lines. Not parallel
map: order is the point. Answer tokens per window `read_max_tokens = 8000`.

### 2.4 Step 2: link (model step `cuts_link`, cached per film)

Purpose-free. Input: synopsis, cast, all beat cards (`B17 [25:09-25:54] scene 9: what`), no transcript. Always one call
(170 beats is about 8 k tokens). Output:

```
{"threads":[{"id":"t1","title":"<= 60","beats":[..]}],
 "beats":[{"id":17,"kind":"setup|payoff|turn|reveal|gag|connective","weight":1..5,
           "needs":[9,12],"why":"<= 100 chars"}],
 "ending":[160,161,162]}
```

`needs` are the earlier beats without which this beat is not understood (its causes, its setup, the introduction of a
person it relies on). Code rules: `needs` point only to earlier beats; at most `max_needs = 4` per beat; every `payoff`
or `reveal` has at least one `needs` or the answer is sent back once naming them; `ending` is not empty. The **story map**
is the result of steps 1 and 2, stored in `stage_cache` as stage `story_map`, key = sha256 of (transcript hash, watched
descriptions hash or empty, both step aliases, both prompt hashes, `[cuts.story]` structure settings).

### 2.5 Step 3: select (model step `cuts_select`, per purpose) and the closure rule (code)

**Purpose brief**, built by code from a template per preset family and put first in the system message:

```
Purpose: {purpose}            # e.g. "A first-time viewer follows the whole story, start to end, in half the time."
Viewer: has not seen the film. Everything you keep must be understandable from what is kept before it.
Length: {target} of {duration}. Rules: keep causes with their results; prefer dropping a whole thread to
keeping its ending alone; the ending must stay and must be earned.
```

`cut-skim-film` and fraction presets use the purpose above; a typed or saved prompt becomes `Purpose:` verbatim with the
same fixed rules after it; `cut-highlights-5` uses "the best moments, each understandable on its own".

Input: the brief, synopsis, threads, beat cards with duration, kind, weight and needs. Output:
`{"threads":[{"id":"t3","decision":"keep|compress|drop","reason":"<= 100"}],"beats":[{"id":17,"keep":0..3}]}`
(3 = must, 0 = drop). The model scores; it does not do arithmetic.

**Code then builds the cut, deterministically** (`story.py`, no model):

1. Start with the `ending` beats and all beats with keep 3.
2. **Closure:** add every beat reachable through `needs` from a kept beat. Always, without exception (for the highlights
   purpose closure is soft: a missing `needs` becomes a skip note, 2.7).
3. Under the target: add the next best beat by (keep, weight, thread decision) together with its closure, while the total
   stays within the band.
4. Over the target: remove the beat with the lowest (keep, weight) that no kept beat needs (leaves first); repeat. A beat
   in the closure of the ending is removed last. If the closure of the must-keeps alone exceeds the band, the cut is
   built over the band and marked `"over_target": true` rather than broken.
5. Balance: when a runtime quarter holds less than `min_quarter_ratio = 0.5` of the overall kept share, step 3 prefers
   beats of that quarter for the next additions and step 4 removes elsewhere.
6. Kept beats become parts over unit ids; the existing merge, padding and guards run unchanged. Parts start and end at
   beat boundaries only.

Length band for story cuts: `story.length_tolerance = 0.10`.

### 2.6 Step 4: critic and repair (model step `cuts_critic`)

A separate call, and by default a different alias from the selector. Input: the purpose brief; the cut **as the viewer
gets it** (kept unit text in order, a `--- skipped 4:12 ---` line at each seam, no summary of what was skipped); then,
below a divider, the list of skipped beat cards for naming fixes. Output:

```
{"consistency":0..10,"density":0..10,"goal":0..10,
 "problems":[{"at_beat":88,"type":"missing_cause|unknown_person|dangling_setup|filler|abrupt|goal",
              "note":"<= 120","add":[61,62],"drop":[]}]}
```

- consistency: can a first-time viewer follow every kept event; density: share of kept time that carries story, character
  or a joke; goal: purpose and length.
- Repair: code applies `add` (with closure) and `drop` (only beats nothing kept needs), re-runs steps 4 to 6 of 2.5 and the
  automatic checks, then the critic again. At most `repair_rounds = 2`.
- Accepted when consistency >= 8, density >= 7, goal >= 7 and all hard checks pass. Otherwise the best round by
  (hard checks passed, consistency, goal, density) is stored with `"review":{"passed":false,...}` and the cut page says so.

### 2.7 Seams: transitions and skip notes

- A seam is acceptable when the skipped span has no beat needed by a later kept beat (guaranteed by closure) and the
  critic raised no `abrupt` problem there.
- For an `abrupt` seam the repair first extends the earlier part by the last beat of its scene or the later part by the
  first beat of its scene, whichever is shorter and at most `seam_extend_max_s = 30`.
- Each part after a skip of at least `skip_note_min_s = 120` carries `"skipped":"<= 120 chars"`: the `what` lines of the
  skipped beats with weight >= 3, joined and trimmed by code (no extra model call). Additive field in the cut document.
  Shown in the web cut page in the MVP; TV and extension overlays are a later checkpoint (owner decision 3).

### 2.8 Automatic checks (code, on every story cut and on any stored cut given a story map)

| # | Check | Hard | Threshold |
|---|---|---|---|
| A1 | closure: every kept beat's `needs` are kept | yes | 0 violations |
| A2 | the ending beats and their closure are kept | yes | 100 % |
| A3 | kept length inside the band | yes (unless `over_target`) | target ± 10 % |
| A4 | kept share of each runtime quarter | no | >= 0.5 x overall share |
| A5 | longest skip, for targets of 40 % or more | no | <= 600 s |
| A6 | dangling setups: kept `setup` beats with no kept beat that needs them | no | <= 2 |
| A7 | kept weight share: sum of kept weight x seconds over kept seconds, against the same for the film | no | >= 1.10 x |
| A8 | parts start and end on beat boundaries | yes | all |

The results are stored in the cut document under `"checks"`. The stored half cut, checked this way, fails A1 (at least the
six pairs of 1.3), A4 (0.35) and A5 (1483 s): that is the baseline.

### 2.9 Models per step

Four new optional task tables, each falling back to `[llm.cuts]`: `[llm.cuts_read]`, `[llm.cuts_link]`,
`[llm.cuts_select]`, `[llm.cuts_critic]`. Features `cuts.read`, `cuts.link`, `cuts.select`, `cuts.critic` are recorded in
`feature_calls` (elapsed, tokens in and out, cost) and switchable through the existing feature-model admin route.

| Step | Needs | Model class | Starting setting |
|---|---|---|---|
| read | faithful, long input, structured output | fast general model; quality matters less than obedience | current cuts alias, thinking off, `max_tokens` 8000 |
| link | plot understanding, cause and effect | general reasoning model, not a coding model | bake-off winner, thinking on (low), `max_tokens` 8000 |
| select | judgement against a purpose | same class as link | bake-off winner, thinking on (low), `max_tokens` 3000 |
| critic | reading as a viewer, strictness | general model, different alias from select when one is available | bake-off runner-up, thinking on (low), `max_tokens` 2500 |
| describe (watched) | pictures | local vision alias only | `[llm.cuts_vision]` as configured |

**Bake-off** (checkpoint 1, a script, never a test): candidates are the current cuts alias with thinking off and on, the
gateway's `heavy` and `light` tiers, the largest general model installed on the big local engine, and (owner decision 2)
one general cloud model as the reference. Which general aliases the gateway serves today could not be listed from here
(5.2); checkpoint 0 lists them. Each candidate runs link, select and critic on the same story map; recorded per step:
seconds, tokens, cost, valid-JSON rate, hard-check result, the six pairs of 1.3, and the owner's paper-cut score (2.11).
The pick and the numbers go to `ai-backend/fixtures/cuts/STORY-CHOICE-<date>.md`, like `CHOICE-2026-11-20.md`.

**Watched story cuts are local in every step.** When the mode is watched, read, link, select and critic use the aliases
in `[cuts.story] watched_aliases = {read=..., link=..., select=..., critic=...}`; the build is refused with a plain reason
when one is missing. A model that is not local never sees watched descriptions. The existing class routes
(`classes.*.routes.pictures`) stay as they are.

### 2.10 The fast local watch pipeline

The watched pipeline of `ai/CUT_MODES_PLAN.md` 2.2 is kept (small video copy, scene cuts, 2x2 grids, descriptions, TDT).
Changes for films, all in `[cuts.watched]`:

| Setting | Now | Film profile (video >= `story.min_duration_s`) | Why |
|---|---|---|---|
| `max_video_minutes` | 90 | 240 | films |
| `max_grids` | 240 | 480 | 2 grids a minute on a 4-hour cap; this film: about 240 to 300 |
| describing | 1 request at a time, running context | `describe_lanes = 6`: the film is split at scene cuts into 6 contiguous stretches, each described in order with its own running context | the research expects throughput from 4 to 8 parallel grids, not from a bigger model |
| `eta_s_per_grid` | 14.0 | measured per alias from the last runs (existing `eta_window`) | honest estimate |

- Scene detection stays the ffmpeg probe at `analysis_fps = 2`, `analysis_width = 128`, on the backend host (no model).
- Audio: a film without usable captions is transcribed by the existing local speech engine chain before step 0.
- Cached artifacts, all existing: the video copy (media archive), `video_scenes` (by video hash and settings),
  `scene_descriptions` (by model, prompt hash, transcript hash). New: the story map (2.4). A second cut of a watched film
  costs select and critic only.
- How it feeds the method: step 0 lines (`S`, scene cuts, `(no speech)` units), so beats can be silent scenes; scene cuts
  are preferred beat boundaries; `who` in a scene may come from what is seen. Steps 2 to 4 do not change.
- Budget: 300 grids / 6 lanes at 4 to 10 s per grid = 3.5 to 8.5 min, plus download and grids about 3 min. Acceptance:
  a 90-minute film from request to story map in 10 minutes or less on the big local engine with nothing else loaded;
  if the measured time per grid at 6 lanes is over 12 s, the model choice goes back to the vision bake-off of
  conduktor#141 before this checkpoint is called done.

### 2.11 Evaluation

**Set.** This film plus three the owner names (decision 1). Transcripts come from the server's own store after the owner
has opened each film once; an agent never fetches from YouTube. Film captions are never committed: the repository gets
only `ai-backend/fixtures/cuts/story/<video_id>.pairs.json` (time ranges and one neutral line per pair, as in 1.3) and an
invented 12-minute story transcript for unit tests.

**Owner scoring, about 3 minutes per cut, no watching.** A paper-cut page (MVP: one static HTML file from the script;
later `/ui` cut page): the beats in order, kept ones solid, skipped ones greyed with duration, one line each. The owner
taps skipped beats that were needed ("needed") and kept beats that were not ("filler"), then gives 1 to 5 for
consistency, density and goal, and "would watch this instead of the film: yes/no". Stored in a new additive table
`cut_reviews(cut_key, user, json, created_at)`. "Needed" marks become that film's must-keep list for the scorer.

**Automatic, per run:** A1 to A8; pair score (for each pair of the film's `pairs.json`: both kept or both cut);
must-keep recall against the owner's marks; critic scores; seconds, tokens and cost per step.

### 2.12 Acceptance (MVP, captions only)

| Measure | Old half cut | Required |
|---|---|---|
| Pairs of 1.3 handled (both kept or both cut) | 0 of 6 | 6 of 6 |
| A1 closure violations | >= 6 | 0 |
| A4 lowest quarter ratio | 0.35 | >= 0.5 on 4 of 4 films |
| A5 longest skip at a half cut | 1483 s | <= 600 s |
| Kept length | 2502 s (target 2444) | target ± 10 % |
| Critic consistency / density / goal | not measured | >= 8 / 7 / 7 on 3 of 4 films |
| Owner consistency score | "really badly made" | >= 4 of 5 on 3 of 4 films, "needed" marks <= 2 per film |
| First cut of a 90-minute film, captions | 6 s | <= 5 min; another purpose on the same film <= 90 s |
| Valid answers | n/a | every step valid within one repair round on 4 of 4 films |

### 2.13 Cost and time per film (estimates; checkpoint 1 replaces them with measurements)

Sizes for this film; Turkish text is counted at about 2.7 characters per token, so the unit lines are about 23 k tokens.

| Step | Calls | Tokens in | Tokens out | Seconds (fast hosted alias) | Seconds (big local engine) |
|---|---|---|---|---|---|
| read | 1 to 2 | 25 k | 6 to 8 k | 40 to 90 | not measured |
| link | 1 | 9 k | 5 to 7 k (+ thinking) | 40 to 90 | not measured |
| select | 1 | 12 k | 2 k (+ thinking) | 15 to 40 | not measured |
| critic | 1 to 3 | 14 k each | 1 k each (+ thinking) | 15 to 40 each | not measured |
| **First cut** | 4 to 7 | 60 to 90 k | 14 to 20 k | **2 to 5 min** | measure in the bake-off |
| **Another cut, same film** | 2 to 4 | 26 to 54 k | 3 to 5 k | **30 to 90 s** | measure in the bake-off |
| Today | 1 | 23 k | 1 k | 5.6 (measured) | n/a |

The only measured number is today's: about 1000 answer tokens and 23 k input tokens in 5.6 s. The hosted price per token is
not in the repository; cost is whatever `feature_calls.cost` records, reported per film in the choice file. Watched adds
the vision time of 2.10 and no hosted cost.

## 3. Files (backend; clients only where named)

| File | Change |
|---|---|
| `src/utubot/story.py` (new) | story map types and validation, purpose brief, closure and budget selection, seams, checks A1 to A8 |
| `src/utubot/cuts.py` | route to the story method (2.1), step 0 marker lines, call steps, store `review`, `checks`, `skipped`; `CUT_BUILD_VERSION` 3 |
| `src/utubot/prompts.py` | system prompts of read, link, select, critic; purpose templates per preset family |
| `src/utubot/config.py`, `config.example.toml` | `[cuts.story]`, the four task tables, film profile in `[cuts.watched]`; every number above |
| `src/utubot/cutbench.py`, `scripts/story_cut_bench.py` (new) | story scorer, bake-off runner, paper-cut HTML |
| `src/utubot/watch/service.py`, `describe.py` | describe lanes, film profile |
| `src/utubot/db.py` | `cut_reviews` (additive) |
| `src/utubot/web/` | cut page: review scores, checks, skip notes; paper-cut scoring |
| `ai/CONTRACT.md` | additive cut-document fields `review`, `checks`, `skipped`, `over_target`, `method:"story"`; new progress stages `reading`, `linking`, `selecting`, `reviewing` |
| `docs/server.md`, `ai-backend/DEVLOG.md` | settings and the measured choice |

## 4. Checkpoints

Each ends with `uv run pytest -q`, `ruff check`, `ruff format --check`, and a pull request. Tests use
`tests/mock_openai.py` and the invented fixture; none contacts YouTube or a real model.

| # | Content | Done when |
|---|---|---|
| 0 | Facts: why cut calls are missing from `feature_calls`; list the gateway's general aliases; export this film's units from the server to a private scratch file | a short note in the checkpoint 1 pull request; a defect issue if cut calls are not recorded |
| 1 | **MVP, no server change:** `scripts/story_cut_bench.py` runs steps 0 to 4 with prompts from `prompts.py` and `story.py` (pure code, unit-tested), on this film, for each candidate; writes paper cuts and the measurement table | the owner has scored at least two paper cuts; `STORY-CHOICE-<date>.md` names the alias per step; the best candidate meets 6 of 6 pairs, A1 = 0, A5 <= 600 s |
| 2 | Server: `[cuts.story]`, task tables, routing, stages, cache, cut-document fields, contract; feature flag off by default | mocked end-to-end test builds a story cut of the invented fixture; a planted missing cause is repaired by the loop; old path byte-identical when the flag is off |
| 3 | Turn on for film-length targeted cuts; rebuild stored film cuts through the repair queue (`algo_version`); cut page shows scores and skip notes | the owner's half cut of this film is rebuilt without a request and meets 2.12; three more films scored |
| 4 | Watched for films: describe lanes, film profile, local-only aliases, story map from descriptions | 2.10 acceptance (10 minutes) measured on the local engine; a watched story cut of one film scored by the owner against its captions-only cut |
| 5 | Clients: skip notes and review badge on TV and in the extension (parity) | emulator and extension checks with the mock backend |

Tests named now: `test_story_validation.py` (tiling, needs point backwards, repair round), `test_story_select.py` (closure
never broken under add and remove; band; quarter balance; over-target case; highlights soft closure),
`test_story_checks.py` (A1 to A8 on built examples, and the six pairs of 1.3 as time ranges failing on a replica of the old
part list), `test_story_pipeline.py` (mocked four-step build, critic repair, cache hit on a second purpose, local-only
refusal in watched mode), `test_db_migrations.py` (additive table).

## 5. Verified, and not

### 5.1 Verified

Everything in 1.1 to 1.3 was read from the live database and config (read-only) and recomputed with `build_units` from
the stored segments; unit ids in the raw answer match the recomputed units (926 units, last id used 925). The code facts
of 1.2 are from `cuts.py`, `prompts.py` and `config.py` at `7c9fa3ae`.

### 5.2 Not verified

- Whether a general model fixes selection by itself. The diagnosis says the method fails before the model matters;
  the bake-off measures both.
- Which general aliases the gateway serves now, their context sizes and speeds on the local engines.
- All times and token counts in 2.13 except today's 5.6 s; the per-grid vision speed at six lanes.
- Whether automatic captions without speakers are enough for the cast list in step 1 on other films (names are spelled
  inconsistently here); if cast quality is poor in checkpoint 1, speaker-labelled captions or the local speech engine
  are tried before the method is changed.
- The owner's pairs: 1.3 is an agent's reading of the captions, not the owner's list. His "needed" marks replace it.
