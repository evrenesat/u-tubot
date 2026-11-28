# u·tubot wire contract v1

The TV app (`stutubot` flavor) talks only to the u·tubot backend. The backend owns
all model calls (any OpenAI-compatible endpoint), downloads, ASR and per-user policy. The app stays
thin: it sends metadata, receives verdicts, renders marks, hides, dialogs and
subtitle tracks.

Base URL example: `https://utubot.example.com` or a LAN URL such as `http://10.0.0.5:8790`.
All paths below are under `/v1`. JSON, UTF-8. Times are seconds.

## Auth

`Authorization: Bearer <user token>` on every call except `GET /v1/health` (browsers may use a session cookie instead, see
[Web UI endpoints](#web-ui-endpoints)).
One token per person (owner, partner, ...). Unknown token: `401
{"error":"unauthorized"}`. Per-user policy (topics to hide, thresholds,
language) lives on the backend, so two TVs with different tokens behave
differently with the same APK.

## Common objects

`VideoMeta` (what the app knows from the card; every field but `video_id`
optional). The assess prompt judges clickbait from the title plus this
context, so a punchy headline on a subscribed creator's regular show is not
called clickbait:

```json
{"video_id":"dQw4w9WgXcQ","title":"...","channel":"...","channel_id":"UC...",
 "duration_s":754,"published":"3 days ago","upload_date":"2026-11-20","views":"1.2M views",
 "likes":12000,"dislikes":300,"is_subscribed":true,"subscriber_count":6200000,
 "channel_description":"...","channel_titles":["...","..."],
 "is_short":false,"is_live":false,"description":"..."}
```

`Flag`:

```json
{"kind":"clickbait|low_quality|inflated|topic","label":"Clickbait",
 "severity":0.0-1.0,"reason":"short human text"}
```

`Verdict`:

```json
{"video_id":"...",
 "status":"ready|pending",        // pending = still computing, ask again later
 "action":"none|mark|hide",       // backend applies the user's policy
 "mark_label":"Clickbait · 12m≈2m", // short text for the card, null if none
 "flags":[Flag],
 "title_question":"Does X work on Y?",  // null when the title asks nothing
 "answer_short":"Yes, since v3.",       // null until known
 "insight_ready":true, "captions_ready":false}
```

## Transcript status

Summaries, insights and answers are made from a real transcript only: YouTube captions (`source`
`youtube_captions`) or one the backend built from the audio (`asr`). They are **never** made from the
title, channel and description alone, so there is no `metadata_only` source any more. The responses of
`insight`, `summary` and `ask` all carry `transcript_status`, and when the transcript is the reason there
is no text they say why:

| `transcript_status` | `status` | extra fields | what the app does |
|---|---|---|---|
| `ok` | `ready` | `source` | shows the text |
| `delayed` | `pending` | `error` (user-facing, "YouTube is limiting transcript downloads; retrying in ~N min"), `retry_after_s` | shows `error`, asks again after `retry_after_s` (not before) |
| `none` | `needs_transcript` | `can_transcribe`, `message` ("No captions. Transcribe the audio in the background?", or while YouTube limits the caption API "Captions are temporarily unavailable from YouTube; transcribe the audio instead (~N s)?"), `estimate_s` (rough seconds, may be null) | shows `message`; when `can_transcribe` offers a "Transcribe in background?" action that calls `POST /v1/videos/{id}/transcribe` |
| `transcribing` | `pending` | `progress` 0.0-1.0 (finished chunks over all chunks of the speech-recognition step), `estimate_s` | shows progress, asks again later |
| `failed` | `failed` | `error`, `reason`, `can_transcribe` | shows `error`; `reason` is `private`, `members_only`, `age_restricted`, `unavailable`, `forbidden`, `too_long`, `live` (video problems), `offline` (a server in offline mode has no recorded answer for this video) or absent (a transcription job failed); offers the transcribe action again only when `can_transcribe` |
| `null` | any | none | the problem is not the transcript (model busy, generic failure) |

`delayed` means YouTube slowed the server down (HTTP 429, bot check, 403 on the watch request, network error, an incomplete answer or an open cooldown) **and the
audio cannot stand in** (see below); it is never cached, so the same request works once `retry_after_s` has passed. `none` is remembered by the backend for 3 days
(`[transcripts] no_captions_ttl_s`) and then checked again; `can_transcribe` is false for live streams and videos
longer than `[captions] max_duration_s`, or when no configured speech engine serves the video's language. The summary of a video whose transcription is queued or running answers `pending` with
`transcript_status: "transcribing"` until the transcript exists, then works normally with `source: "asr"`.

**Captions limited.** YouTube limits the caption API (timedtext) separately from the audio download. While the backend's caption breaker is
open, or waiting for its single background probe, or a caption fetch has just been refused (429, 403), a request is treated like "no
captions" instead of `delayed` whenever a speech engine can take the video (not live, within `[captions] max_duration_s`, an engine serves
its language) and the audio endpoint is healthy: the policy below starts the transcription (`pending` + `transcribing`) or the answer is
`needs_transcript` with the "Captions are temporarily unavailable ..." `message`, `can_transcribe: true` and `estimate_s`. `delayed` is
what remains when no engine is available, the video cannot be transcribed, the audio endpoint is cooling too (a bot check) or the problem
is a network error. This answer is never remembered; the transcript made from the audio has `source: "asr"` and is kept: captions that
arrive later do not replace it and it is not fetched again. After a caption cooldown the backend sends exactly one background request to
find out whether captions work again; no request of a user is ever used for that (`docs/server.md`, YouTube limits).

**Automatic transcription.** When a `summary`, `insight` or `ask` request finds no captions (or the captions are limited, see above), the user's policy decides whether the
backend asks or just does it. `auto_transcribe` (`off`, `on_open`, `on_dwell`; default `on_open`) and `auto_transcribe_max_minutes`
(default 30) are per-user settings. With `on_open` or `on_dwell` and a video up to the maximum (a length the client did not send is looked up with one paced `metadata` request when that class is healthy), the request itself queues
the transcription (no user prompt) and answers `status: "pending"`, `transcript_status: "transcribing"`, `progress`, `estimate_s`
instead of `needs_transcript`; asking again returns the progress, then the real answer. The side panel's request (`summary?prompt=panel`)
is passive: it starts a transcription only for `on_dwell`; the Summary view, `insight`, `ask` and ad-hoc summaries are explicit and start
one for `on_open` as well as `on_dwell`. Everything else keeps `needs_transcript` (policy `off`, a longer video or one whose length could not be learned, a full
per-user queue, no engine for the language) and the app shows the question as before. Explicit requests run the job at interactive
priority (claimed first, interactive engine use); a side-panel job is background work and is promoted when the user then opens the video.

## Endpoints

### `GET /v1/health` (no auth)
`{"ok":true,"version":"0.3.202611261430+a1b2c3d","commit":"a1b2c3d"}`. `version` is the real backend version, `0.<series>.<commit time>+<short sha>` from the
checkout the server runs (the series is the minor of `utubot.version`, the commit time the HEAD commit date in UTC as `YYYYMMDDHHMM`); an install without git reports the package version and no commit.
It changes with every deploy, so the TV's disk cache keyed on it starts fresh after a deploy.

### `GET /v1/me`
`{"user":"owner","policy":{...},"admin":false,"backend_version":"0.3.202611261430+a1b2c3d","prime":false,"class":"normal","settings_version":3,"features":{"assess":true,"insight":true,"captions":true}}`
`settings_version` is the version of the [settings document](#per-user-settings), a cheap way to notice a change. `prime` and `class`
say whether the caller's work is prime (`normal` otherwise).

### `POST /v1/assess`
Batch triage for one row/emission (≤ 50 videos).

Request: `{"videos":[VideoMeta],"section":"home|subscriptions|search|channel|other","wait_ms":1200}`

Response: `{"results":[Verdict]}` — same order, one per input.

Rules:
- Cached verdicts return immediately. Uncached ones run the fast title-tier
  classifier; the backend waits at most `wait_ms` (cap 3000) then returns
  `pending` for unfinished items while work continues in the background.
- The app must never block a row longer than `wait_ms` + 500 ms network slack.
  On error/timeout it shows the videos unfiltered.
- Deep (transcript) analysis may refine a verdict later; the app re-reads the
  cache-backed verdict on the next load.
- The triage classifier judges clickbait from the title plus the channel/video
  context above (subscription, subscriber count, channel description and usual
  format from recent titles, views, likes, upload date): a comedic, satirical
  or hype-framed headline on a channel the viewer subscribes to is not
  clickbait by itself, and only a clear, out-of-the-ordinary mismatch is. The
  backend can re-triage a user's recent clickbait verdicts on subscribed
  channels (`utubot assess-fixup`) so a wrong label from the title-only prompt
  disappears without the owner asking.

### `GET /v1/videos/{id}/insight?wait_ms=20000`
Optional query fields: `title`, `channel`, `duration_s` (used if the backend has
no metadata yet). Starts a job if none exists.

```json
{"video_id":"...","status":"ready|pending|failed|needs_transcript","error":null,
 "title_question":"...","answer":"2–3 sentences","answer_confidence":0.0-1.0,
 "summary":"markdown-ish plain text, ≤ 1200 chars",
 "key_points":["...","..."],
 "inflation":{"duration_s":754,"essential_s":120,"ratio":0.16},
 "source":"youtube_captions|asr",
 "transcript_status":"ok|delayed|none|transcribing|failed|null"}
```
Plus the extra fields of [Transcript status](#transcript-status) when `transcript_status` is not `ok`.

### Prompt sets (custom summary prompts)

Summaries are produced by user-chosen prompts. A prompt set is a JSON file
that can be hosted anywhere (gist, short URL, the backend itself) and
imported by URL. Format:

```json
{"tubeai_prompt_set": 1,
 "id": "my-prompts", "name": "My prompts", "version": "2026-11-12",
 "prompts": [
   {"id": "tldr", "label": "TL;DR", "default": true,
    "system": "You summarize YouTube videos for a TV viewer...",
    "template": "Title: {title}\nChannel: {channel}\nDuration: {duration}\n\nTranscript:\n{transcript}\n\nGive a 5-bullet TL;DR.",
    "max_tokens": 700, "model": null, "task": "summary"}
 ]}
```

Template variables: `{title} {channel} {duration} {description} {transcript}
{language} {question}` (`{question}` = the question the title poses as the
title triage detected it, empty when none). `model` is an optional alias
override (null = the backend's summary model). `task` is optional,
`"summary"` (default) or `"glance"`: which `[llm.*]` table runs the prompt
(`[llm.glance]` falls back to `[llm.summary]` with reasoning off). Files
without `task` stay valid. Prompt ids are unique within a set; the effective
key is `<set_id>/<prompt_id>`.

- `GET /v1/prompts` → `{"default":"builtin/tldr","panel_default":"builtin/glance","sets":[{"id","name","version","source_url","prompts":[{"id","key","label","default","panel_default"}]}]}`.
  `default` is the Summary view's prompt, `panel_default` the one for automatic side-panel summaries.
- `POST /v1/prompts/import` `{"url":"https://..."}` → the imported set (replaces a set with the same id; `source_url` remembered).
- `POST /v1/prompts/refresh` → re-fetches every set that has a `source_url`.
- `PUT /v1/prompts/sets/{set_id}` body = prompt-set JSON (direct upload/edit).
- `DELETE /v1/prompts/sets/{set_id}`
- `PUT /v1/prompts/default` `{"key":"set/prompt"}` → `{"default":"set/prompt"}`
- `PUT /v1/prompts/panel-default` `{"key":"set/prompt"}` → `{"panel_default":"set/prompt"}`; `404` for an unknown prompt.
  Unset, it follows the server's `[summary] panel_prompt` (default `builtin/glance`).

Prompt sets are per user. Built-in set `builtin` always exists: `glance`, `tldr`,
`answer-title`, `takeaways`, `worth-it`, `eli-new`.

`builtin/glance` is the panel summary: at most ~280 characters in at most 3 short lines,
plain text, in the user's language. When the title poses or implies a question or is a
curiosity gap, line 1 is `→ ` plus the direct answer from the transcript (or `→ ` plus a
few words saying the video does not answer it), then 1-2 lines with the gist. It runs on
`[llm.glance]` with a 160 token answer budget and reasoning off by default.

### `GET /v1/videos/{id}/summary?prompt=<set/prompt>&wait_ms=20000`
Also accepts the metadata query fields of `insight`. Omitted `prompt` = the
user's default. `prompt=panel` = the user's panel default (`panel_default`);
the response's `prompt` carries the resolved key. Cached per (video, prompt
key, prompt content hash), so editing a prompt invalidates only that prompt's
summaries.

With `[summary] auto_long = true` (or the user's policy field `auto_long`), a
`prompt=panel` request that ends `ready` also queues the user's `default`
prompt for the same video at background priority, so the Summary view is
usually already cached. Off by default; explicit `prompt=<key>` requests never
queue anything.

```json
{"video_id":"...","prompt":"my-prompts/tldr","status":"ready|pending|failed|needs_transcript",
 "text":"...","source":"youtube_captions|asr","error":null,
 "transcript_status":"ok|delayed|none|transcribing|failed|null"}
```
Plus the extra fields of [Transcript status](#transcript-status) when `transcript_status` is not `ok`.

`POST /v1/videos/{id}/summary` with `{"prompt_text":"...", "system":"..."}`
runs an ad-hoc prompt (not cached long-term) — for quick iteration.

### `POST /v1/videos/{id}/ask`
`{"question":"..."}` → `{"answer":"...","status":"ready|pending|failed|needs_transcript","transcript_status":"ok|delayed|none|transcribing|failed|null"}`,
plus the extra fields of [Transcript status](#transcript-status) when it is not `ok`.

### `POST /v1/videos/{id}/transcribe`
Queue a background transcription of the audio (the answer to "Transcribe in
background?"). Optional query fields `title`, `channel`, `duration_s` as for `insight`, and `force` (bool) to
build from the audio even when YouTube captions are already stored. The backend downloads the
audio (paced with every other YouTube request), runs its speech recognition and stores the text as the video's
transcript with source `asr`. Idempotent: asking again while the user's job is queued or running returns that job.
Without `force`, nothing is queued when a transcript already exists; with `force` a stored caption transcript is
replaced (an ASR transcript already there is still returned as `ready`).

```json
{"video_id":"...","job_id":"a1b2c3d4e5f6","status":"queued|running|ready",
 "transcript_status":"transcribing|ok","progress":0.0,"estimate_s":630}
```
The job is interactive (the user asked), whatever the automatic-transcription policy says. `estimate_s` is the audio download plus the
chosen speech engine's chunked recognition time.
`400` when the video cannot be transcribed (live, or longer than the configured maximum), `429` when the user
already has the maximum number of active transcriptions (`[captions] transcribe_max_active_per_user`, 5).

A transcript runs speech recognition with word times (the strongest answer), so the one run is reused by every feature that needs the audio: a
later "Prepare HQ captions" (`POST /v1/videos/{id}/captions`) finds that run in the cache and reuses it rather than recognising again, and the
captions job's `asr` stage reports `cached` and `reused_from_job` (this transcript job's id). The cache is keyed on the audio and the separation;
the result is stored under the language the audio was recognised in, so a language-detected transcript answers a later ask for that language, and
an automatic ask (no language) reuses whichever language is cached. The cache version bumps when this sharing changes.

### `POST /v1/videos/{id}/retry`
The Retry action. Forgets everything the backend remembers about a *failure* of this video, so the next request really tries again:
a failed or delayed transcript fetch, the "no captions" memory, and failed summary, insight, answer and analysis tasks. Stored successes
(transcript, summaries, captions, analyses) stay. Nothing is generated here: the client asks again right after (summary, insight, assess).
`{"ok":true,"cleared":{"fetch":2,"tasks":1,"analysis":0}}` (counts of memories dropped). Same auth and rate limits as other `/v1` routes.

Failure policy (what a client may rely on): successes are cached and versioned by their key (prompt content hash, language, model);
failures are short-lived. A busy language model (`error` = "the language model is busy, ...") is never remembered, any other model failure
for `[summary] failure_cooldown_s` (2 min), a video that cannot be read for `[transcripts] video_failure_ttl_s` (15 min). A client keeps
no failure longer than that either, and always offers Retry.

### `GET /v1/videos/{id}/transcript`
Where the transcript stands. Cheap: never contacts YouTube.

```json
{"video_id":"...","transcript_status":"ok|delayed|none|transcribing|failed|unknown",
 "source":"youtube_captions|asr","lang":"en","engine":"mac","model":"whisper-large-v3-turbo",
 "progress":0.4,"estimate_s":630,"job_id":"...",
 "can_transcribe":true,"message":"...","error":null}
```
Only the fields that apply are present (`source`/`lang` with `ok`, plus `engine`/`model` when the source is `asr`, `progress`/`estimate_s`/`job_id` with `transcribing`,
`can_transcribe`/`message`/`estimate_s` with `none`, `error`/`reason`/`can_transcribe` with `failed`,
`error`/`retry_after_s` with `delayed`). `job_id` appears only for the caller's own job, never another user's.
`unknown` (only here) means the backend has not looked yet.

### `GET /v1/jobs?limit=50`
The caller's background jobs of every kind, newest first (groundwork for a "check later" shelf). `limit` 1-200.

```json
{"jobs":[{"id":"a1b2c3d4e5f6","kind":"transcript|captions","video_id":"...","title":"...or null",
          "state":"waiting|processing|ready|failed","progress":0.0-1.0,"error":null,
          "created_at":1700000000.0,"finished_at":null,"retry_after_s":null,
          "stage":"asr_chunk","delivered":false,"delivered_at":null,
          "detail_url":"/#/jobs/a1b2c3d4e5f6","api_url":"/v1/jobs/a1b2c3d4e5f6"}]}
```
`stage` is the stage of the job's newest log event (what it is doing, or did last), `delivered`/`delivered_at` say whether a client has fetched
the result (below), `detail_url` is the web UI page of the job (relative to the server, needs a web sign-in) and `api_url` the JSON report.
`waiting` = queued (including while YouTube has the server in a cooldown; then `retry_after_s` says roughly how long),
`processing` = running, `cancelled` = the user cancelled it while it waited. `error` is a short generic message for `failed`.
A waiting job can be cancelled and a failed or cancelled one retried: `POST /v1/jobs/{id}/cancel`, `POST /v1/jobs/{id}/retry`
(`{"ok":true}`; `404` for another user's or an unknown job, `409` when the state does not allow it, `429` when a retry would exceed
`[captions] transcribe_max_active_per_user`).

### `GET /v1/jobs/{id}`
The detail report of one job: what was requested, what was done, what happened. Allowed for the job's owner and for admins; `404` for
anybody else and for an unknown id.

```json
{"id":"a1b2c3d4e5f6","kind":"transcript|captions","user":"owner","state":"waiting|processing|ready|failed|cancelled",
 "progress":1.0,"error":null,"priority":"interactive|background","class":"normal|prime","attempts":0,
 "created_at":1700000000.0,"updated_at":1700000050.0,"finished_at":1700000050.0,"retry_after_s":null,
 "detail_url":"/#/jobs/a1b2c3d4e5f6","api_url":"/v1/jobs/a1b2c3d4e5f6",
 "can_cancel":false,"can_retry":false,
 "inputs":{"video_id":"...","title":"...","channel":"...","duration_s":1740,"language":"tr","lang":"auto","translate_to":null,
           "requested":{"user":"owner","client":"Living room TV","endpoint":"POST /v1/videos/{video_id}/captions",
                        "trigger":{"kind":"explicit"},"priority":"background","class":"normal","at":1700000000.0}},
 "outputs":{"transcript":{"source":"asr","lang":"en","engine":"mac","model":"whisper-large-v3-turbo","chars":4830,"lines":6,
                          "segments":6,"stored_at":1700000050.0,"from_this_job":true,"first_lines":["[00:00] ..."],
                          "text_url":"/v1/jobs/a1b2c3d4e5f6/transcript.txt"},
            "captions":[{"lang":"tr","label":"Turkish (u·tubot)","speakers":1,"cues":612,"bytes":58120,"created_at":1700000050.0,
                         "from_this_job":true,"preview":[{"start":1.2,"text":"..."}],
                         "vtt_url":"/v1/videos/{video_id}/captions/tr.vtt","text_url":"/v1/jobs/a1b2c3d4e5f6/transcript.txt?lang=tr"}]},
 "delivery":{"delivered":true,"count":6,"last_ts":1700000900.0,
             "clients":[{"client":"Living room TV","user":"owner","count":6,"last_ts":1700000900.0,"via":["captions_status","vtt"]}]},
 "events":[{"id":1,"ts":1700000000.0,"stage":"queued","status":"ok","detail":{"user":"owner","client":"Living room TV",
            "trigger":{"kind":"explicit"},"priority":"background"}}]}
```
`outputs.transcript` is for `transcript` jobs and `outputs.captions` for `captions` jobs; both show what is stored for the video now
(`from_this_job` is false when another job made it, null for rows from before the log), with the first 10 lines or cues. `can_cancel` and
`can_retry` are true only for the job's owner. `trigger` is `{"kind":"explicit"}`, `{"via":"regen"}` (queued again by `utubot captions-regen`) or `{"kind":"auto","mode":"on_open|on_dwell",
"passive":false,"max_minutes":30}`; `client` is the name a TV was linked under, `Web UI` or `API token`.

`events` is the log in order of writing. `status` is `running`, `ok`, `warn`, `skipped`, `failed`, `info`, `cancelled` or `interrupted`;
a `running` event is followed by the `ok`/`failed`/`skipped` event of the same stage, which carries `seconds`. Stages: `queued`, `promoted`,
`started` (also `class`), `in_line` (a normal caption or transcript job waiting for prime work: `reason:"priority"`, `progress`,
`message`), `gate_wait`, `caption_recheck` (`found` carries `words` and `caption_kind` = `manual|auto`), `audio_download` (`format_id`, `track` = `original|dubbed|descriptive|unmarked`, `original`,
`language`, `bytes`, `duration_s`, `source` = `downloaded|from_archive`), `media_archive` (`bytes`, `sha256` prefix; skipped when the audio
came from the archive), `ffmpeg`, `separation` (skipped when off, the tool failed, or the ASR answer was cached), `chunking`, `asr` (`cached`
the speech recognition was reused from the cache instead of re-run, `reused_from_job` the transcript or cut job whose run it reused,
`saved_s` an estimate of the recognition seconds the reuse avoided), `asr_chunk`
(also `word_timing`, `words`, `word_mode`), `asr_wait` (`engine`, `waited_s`, `attempts`, `outcome` = `ready|gave_up`), `asr_fallback` (`reason` also `no_word_times`, `engine_unavailable`), `asr_recheck` (`start_s`, `end_s`, `reason` = comma-joined `language_mismatch|hallucination|sparse`, `action` = `forced_language|smaller_window|next_engine|dropped`, `detected`, `expected`, `outcome` = `replaced|kept|failed`, `flagged_share_before`, `flagged_share_after`; `dropped`: `dropped_segments`, `dropped_s`; `skipped` = `budget|requests`, `detected_after`; `asr` also has `rechecked_chunks`, `unresolved_chunks`, `skipped_chunks`, `recheck_requests`, `hallucination_drops`, `dropped_s`, `cache` = `not_stored_unresolved`), `stitching`,
`word_timing` (`word_timing` = `real|mixed|interpolated`, `words`, `real`, `interpolated`, `real_share`, `zero_length`, `stretched`, `squeezed`,
`nonmonotonic`, `unfixed`, `words_per_s`, `speech_s`, `silences`; `warn` with `message` when the times are estimates, `skipped` with `reason` = `no_words`),
`ref_check` (captions jobs: `reference_words`, `anchors`, `anchor_share`, `median_s`, `p10_s`, `p90_s`, `within_s`, `source` = `words|rows`, `regions` = list of `[start_s, end_s, median_s]`; `warn` when `regions` is not empty; `skipped` with `reason` = `no_reference|too_few_anchors|other_script`; changes no times), `diarization` (`reason` and `message` when skipped; only when diarization is configured), `cues`, `align` (`mode` = `silence|words|captions_timing|merge`; `words`:
`speech_cues`, `fill_cues`, `fill_from_words`, `merged_short`, `caption_cues`, `moved`, `words`; boundaries snap to silences; `captions_timing` is skipped with `reason` = `no_words|word_times_estimated`: the caption cues are kept as they are),
`sync_score` (`cues`, `speech_overlap`, `starts_in_silence`, `char_timed_cues`, `silence_share`; skipped with `reason` = `no_cues|no_audio_check|no_silences`),
`proofread` (`corrected`, `warned`, `chars_in`/`chars_out`, `cached`, `split_exact`, `split_at_pause`, `split_by_chars`, `overlong`; skipped with `reason` = `off|no_llm|translated` when a translation follows and only the translated text is proofread), `proofread_batch` (a batch that
kept its original text — length mismatch, empty text, growth or shrink beyond `proofread_max_ratio`), `text`, `translate` (`source`, `to`, `cues`, `batches`, `retried`, `split`, `untranslated`; `warn` when `untranslated` > 0, `split_exact`, `split_at_pause`, `split_by_chars`, `overlong`), `stored`, `retry`, `finished`, `failed` (`error_class`,
`message`, `stage`, `technical`) and `delivered` (`via` = `captions_status|vtt|transcript_status|summary|summary_panel|insight|answer|transcript_txt`,
`client`, `user`, `count`, `first_ts`). Details never carry a URL, token or secret. A job from before the log has one synthetic event,
`finished` (or `queued` while it waits) with `detail.synthetic: true` and the message "finished (no detailed log, created before event
logging)".

**Delivery.** Fetching a result adds (or counts up) a `delivered` event on the job that made it: `GET /v1/videos/{id}/captions` with tracks,
`GET .../captions/{lang}.vtt`, `GET /v1/videos/{id}/transcript` (source `asr`), a ready summary, insight or answer built from a transcript
that audio produced, and `GET /v1/jobs/{id}/transcript.txt`. The same client and kind within `[captions] delivery_coalesce_s` (300) only
raises `count`. This is how to see whether a TV actually downloaded a track.

### `GET /v1/jobs/{id}/transcript.txt`
`text/plain`, served as an attachment: the stored transcript of a `transcript` job, or the cue text of a `captions` job's track (query
`lang` picks the track; default the first). Same access as the report; `404` when nothing is stored.

### `POST /v1/videos/{id}/captions`
Queue high-quality captions. Body: `{"lang":"auto","translate_to":null,"force":false}`. An unset `translate_to`
follows the user's `captions_translate_to` setting, which unset follows `[captions] translate_to` (default `"en"`):
captions come out in English whatever the source language; `"off"` keeps the source language instead.
`force: true` skips the YouTube caption recheck and builds the track from the audio even when captions exist (the
caption-recheck event says `skipped` / `forced`).
→ `{"status":"queued|running|ready|failed","job_id":"...","eta_s":null}`

### `POST /v1/videos/{id}/captions/client`
Caption tracks the client already holds, so the server need not fetch them from YouTube (its yt-dlp requests are rate limited).
Body: `{"tracks":[{"lang":"en","kind":"auto|manual","name":"English","format":"json3|srv3|vtt","body":"<raw timed text>","original":true}]}`
(`name` and `original` optional; `original` marks the video's own spoken language). Optional `title`, `channel`, `duration_s`,
`is_live` query parameters like the other video routes. Limits (`[transcripts] client_max_tracks`, `client_max_track_bytes`, default 10
and 2 MiB): too many tracks or a bad language code is `400`, a track over the size `413`, a format or kind outside the lists `400`, and a
body that holds no readable timed text in any track `400`. One track is picked the way the server's own fetch picks (an authored track in
the video's language, its automatic original, any authored, any automatic) and stored exactly like a fetch (`source = youtube_captions`,
words kept for json3) but marked `origin = client`. A fresh stored copy that is manual is never replaced by an automatic upload, a
stored speech-recognition transcript is never replaced, and an upload that brings nothing better than a fresh stored copy of the same
kind is dropped; real captions clear the video's "no captions" and failure memories and end the wait of a fetch, cut or summary that
was waiting for the transcript. Every later request finds the copy in the 30-day cache, so no yt-dlp call follows.
→ `{"stored":true|false,"reason":"stored|kept_manual|kept_asr|kept_existing","lang":"en","kind":"auto|manual","tracks":1}`

### `GET /v1/videos/{id}/captions`
```json
{"status":"none|queued|running|ready|failed","progress":0.0-1.0,
 "tracks":[{"lang":"en","label":"English (u·tubot, 2 speakers)",
            "url":"/v1/videos/{id}/captions/en.vtt","speakers":2,"timing_version":1}]}
```
`timing_version` (additive, may be `null`) is the version of the timing scheme that made the track (`null`: made before it existed, or
with `[captions] timing_mode = "legacy"`); clients ignore it.

### `GET /v1/videos/{id}/captions/{lang}.vtt`
`text/vtt`. Speaker turns are prefixed `[S1] `, `[S2] ` when diarized.
Auth via header, or `?token=` for players that cannot set headers.

### `GET /v1/inbox?limit=50`
`{"items":[InboxItem],"unread":N}` (see [Inbox](#inbox-addendum-2026-11-26)); default `limit` 50,
range 1..200, `400` outside the range.

### `POST /v1/inbox/read`
Request `{"ids":[int]}` (≤ 200). `{"ok":true}`.

### `POST /v1/inbox/read-all`
`{"ok":true}`.

### `POST /v1/inbox/dismiss`
Request `{"ids":[int]}`. `{"ok":true}`.

### `POST /v1/feedback`
`{"video_id":"...","kind":"clickbait|...","correct":false,"note":null}` → `{"ok":true}`.
Stored for later threshold tuning.

### `POST /v1/ledger`
`{"operation":"GET /videos/{id}/insight","message":"HTTP 502: ...","video_id":null,"component":"client","category":null,"detail":null}` →
`{"ok":true}`. A client (TV, extension) reports a failure of its own call to the backend's error ledger. `component` outside the known
set becomes `client`; `category` is an optional hint from `youtube-refused|rate-limited|timeout|network|model-error|transcript|config|sync|bug|unknown`
(anything else is a 422), else the backend maps it from `message`, and an unmapped one is flagged for triage on the admin page
(`GET /v1/admin/ledger`, admin only). Clients report only their own transport and 5xx failures, at most one per distinct message a minute and
ten a minute overall.

## App behaviour summary

- Assess: one `POST /v1/assess` per row emission from `HiddenVideoResolver`.
  `action=hide` removes the card (unless the app's "mark only" switch is on),
  `action=mark` adds `mark_label` as a coloured card mark.
- Summary panel mode: a toggle (quick toggle + settings + context menu
  item). While on, a card that keeps the focus for the panel delay (Settings,
  default 1.8 s) gets a passive preview in the right strip of the screen
  (~35% width, below the top bar, never focused, browse stays usable) with
  the card's title and the short summary. The panel requests `prompt=panel`
  and, if the backend answers 400 or 404, the first prompt of `GET /v1/prompts`; its header label is the label of
  `panel_default`. The Summary view (Info key or the context menu item "u·tubot summary") is a focused view with the
  prompt list and the long summary of the user's `default` prompt, which the user changes by moving through
  the list. The first Back hides the panel and keeps the focus on the card; the toggle turns the mode off.
- Context menu: "AI answer" (shows `answer_short` in the item label when
  known), "Summary panel on/off", "Prepare HQ captions".
- Summary panel and Summary view: handle `transcript_status`. `delayed`: show the `error` text and a "Retrying in N s" countdown, and retry after
  `retry_after_s` (1 s at least, 10 min at most) while the card or view is shown. `none` (`status: "needs_transcript"`): show
  `message` and, when `can_transcribe`, a "Transcribe in background?" action that calls `POST /v1/videos/{id}/transcribe`;
  afterwards the view follows `GET /v1/videos/{id}/transcript` (every 4 s; the passive panel every 20 s, no faster than it
  polled a `pending` summary, one long poll) until the transcript is `ok`, then asks for the summary again.
  `transcribing`: "Transcribing… N% (~M min)" (the `estimate_s` when given) and the same follow-up, with nothing to press when the
  server started the job itself. `failed`: show `error`; offer the action again only with
  `can_transcribe`, and no Retry when `reason` is present. None of these answers is kept by the app. Retry (the user's action, not the
  countdown of a `delayed` answer) first calls `POST /v1/videos/{id}/retry`, whatever it answers, then asks again. The app keeps only ready
  verdicts and summaries on disk, per backend address, token and backend version (`version` of `GET /v1/health`) for 3 days, and drops them with
  a prompt import, refresh or default change; a summary request that was in flight then is shown but not stored again. The AI answer shows
  the same states for an insight, counts a delay down and follows a running transcription like the view does (the transcription the user
  starts is started from the Summary view of the video). `message` is shown as the server wrote it in the panel, the view and the answer;
  the app's own wording is only the fallback. Every `insight`, `summary` and `transcribe` call carries `title`, `channel` and `duration_s`.
- Settings → AI features → Prompts: list sets, "Import from URL", "Refresh all",
  choose default.
- Player: when `captions_ready`, offer the u·tubot track(s) in the subtitle
  picker ("u·tubot: <label>"); optionally auto-select. The app asks `GET /v1/videos/{id}/captions` when a video starts and, while the
  answer is `queued` or `running`, every 10 s while the video plays; ready captions are added to the playing video, selected and
  announced. It downloads each ready track once (`GET .../captions/{lang}.vtt`, `Authorization` header) into its own storage and keeps
  it for good: the backend is not asked again for a video whose captions are stored, and a track never changes once stored.
- Settings: Import setup (first item), enable switches, mark-only switch, pairing, test button.
  Backend URL and token are under Advanced. Private builds can bake defaults
  (`-PutubotUrl=… -PutubotToken=…`); public builds ship with none.
- Browse sections (Home, Subscriptions, the feeds and grids, u-tubot#65) are cached on the TV, never on this backend: a focus
  shows the last loaded cards at once from memory or the disk cache, then refreshes in the background only after the named
  "Browse refresh" minutes (5, 10, 20, 30 or 60; 10 by default); "Refresh section" reloads immediately. An account or locale
  change clears the cache. No request of this contract is added: the cache is local to the app.

## Clients

Two clients speak this contract: the TV app (`stutubot` flavor) and the browser extension (`extension/`, Firefox first, planned in
`ai/BROWSER_EXTENSION_PLAN.md`; until it is built, that plan's parity matrix is its side of a feature). A feature of this
contract is built for both. Exceptions, each with its reason:

- The QR sheet of "Describe on phone…": TV only. The extension has a keyboard, takes the description itself
  (`POST /v1/videos/{id}/cuts {"prompt"}`) and opens the cut sheet (`/cuts/{request_id}`) in a tab.
- The TV's "Describe by voice…": TV only. It records the TV's microphone and uploads the recording (`POST /v1/speech`, a
  `recording.wav`, with the TV's UI language as the optional `language` hint); the extension has a keyboard and takes the
  description itself, as the QR sheet does. The endpoint is client-agnostic; only the recording UI is TV-only.
- The sponsor-segment merge of a cut jump and turning SponsorBlock fully off while a cut is applied: TV only. The browser has
  no built-in sponsor skip, so neither the merge of the cut's jump past the sponsor segments nor the suppression of the sponsor
  skip over the cut's ranges applies; it comes back when the cut is off or the video has no active cut.
- The browse cache: TV only. YouTube's site owns its own loading.
- The 3-day disk cache of ready verdicts and summaries: TV only. It is scoped to the backend version; the extension
  keeps its caches in `storage.session`, which ends with the browser session, and does not keep failures either.
- Caption upload (`POST /v1/videos/{id}/captions/client`): TV only for now. The TV player is handed YouTube's caption tracks with
  the stream; the extension only draws HQ captions and reads no caption track of YouTube's page yet. Its row is in the plan's parity
  matrix; the extension sends the same body when it reads the page's own tracks.
- Content extraction cache (one speech-recognition run serves every feature: "Prepare HQ captions", cuts and watched cuts reuse a
  transcript's run instead of recognising again; the `asr` stage of a job reports `cached`/`reused_from_job`/`saved_s`): TV + backend
  only. The extension does no extraction and has no jobs UI, so it shows no job-stage details; these fields are backend metadata the web
  UI job detail page renders. Its row is in the plan's parity matrix.
- Voice control (consent, history, the live socket, the Talk page): TV app, phone page and phone app first; the extension's intended
  role (the playing tab as a screen, a Talk button in the panel) waits for the background-socket check of the plan's checkpoint 12,
  and until then its row `voice-control` in the parity matrix is the exception. The live server is the plan's `realtime/`.
- `GET /app/update.json`: TV only. Firefox updates extensions itself.
- Update interval and development mode (offering the install at once when idle): TV only, the extension is updated by Firefox.
- "What's new" after an app update: TV only (the extension's own version history is the add-on's). The two lists of `GET /v1/changelog`
  (app versions, backend deploys) are in the extension options page too; until the options page exists, that is row `whats-new` of the
  plan's parity matrix.

The extension sends the bearer token from its background context only, to the backend's own origin, with no cookies
(`credentials: "omit"`) and never as `?token=`. It needs no CORS headers from the backend.

## Addendum (backend implementation, 2026-11-12)

- Public endpoints (no token): `GET /setup.json`, `GET /v1/health`, `POST /v1/pair`,
  `GET /app/update.json`, `GET /app/info.json`, `GET /app/<file>.apk`, `GET /app/latest/<abi>.apk`, and for the web UI `GET /`, `GET /ui/*`
   (static files, no data), `POST /v1/auth/login`, `POST /v1/auth/logout`, `GET /web-login/<token>`. Everything else needs a bearer token or a session cookie. Rate limits return `429
   {"error":"rate limited"}` with `Retry-After`. Bodies over 256 KiB return 413.
- A user's own daily cost budget (`[usage] user_budget_usd`, `0` = unlimited) is checked before each of their calls; a call past it is refused with
  `429 {"error": ...}` and a `Retry-After` (seconds to the next UTC day). `[usage] user_requests_per_min` (`0` = follow the global limit) caps their
  requests the same way. A user's own upstream (see `/v1/me/provider`) is where their calls run; without one they use the server default.
- Video ids must match `^[A-Za-z0-9_-]{11}$`, else `400`.
- `POST /v1/pair` `{"code":"123456","device":"Living room TV"}` -> `{"token":"utb_...","user":"owner"}`.
  Codes are single use, valid 15 minutes, created by `utubot user pair NAME` or the admin UI.
  Wrong codes: `403`; lockout after repeated failures: `429`. Each device gets its own token.
- `GET /v1/me` `features` also lists `"transcribe": true` (the endpoints above exist).
- `GET /v1/me` also returns `"admin": bool`. `PUT /v1/me/policy` patches the caller's policy.
- Admin only (user with `admin = true`, else `403 {"error":"forbidden"}`):
  `POST /v1/admin/pair {"user"}` -> `{"code","expires_in_s"}`, `GET /v1/admin/users`,
  `DELETE /v1/admin/devices/{id}`, `PUT /v1/admin/users/{name}/policy`.
- One-time web sign-in link (issue 203): the TV's "u·tubot web admin" entry asks for a link that
  opens the web UI on the same device, signed in, instead of a QR. `POST /v1/web-login` (a bearer
  token, i.e. any authenticated user — a paired TV has its device token) -> `{"token":"wtl_...","expires_in_s":60}`.
  The client opens `GET /web-login/<token>` (public, no auth) in a browser: the backend spends the
  link once, makes a cookie session for that user (the session's `agent` records the device that
  asked for the link, so the sign-in is attributable), and `302`s to `/#/home`. The link is single
  use and lives `security.web_login_ttl_s` (60 s by default); an already-used, expired or unknown
  link answers `400 {"error":"This sign-in link is invalid or expired"}`. The request is rate
  limited per address (`security.web_login_attempts_per_ip_per_min`). The QR of "Describe on phone…"
  stays the fallback only when no browser is installed on the device.
- `GET /v1/me` policy also carries `auto_long` (`null` = follow the config).
- Extra read endpoints: `GET /v1/prompts/sets/{set_id}` (raw set JSON), `GET /v1/captions/jobs`.
- A prompt's `model` is an alias or `provider:model` naming a configured provider.
- Prompt-set format key stays `tubeai_prompt_set` for compatibility.
- `GET /app/update.json` serves the file published by `utubot app publish` (Electric Eel format).
  Per-architecture keys `downloadUrlList_<abi>` (`arm64-v8a`, `armeabi-v7a`, `x86`, `x86_64`, `universal`)
  win over `downloadUrlList` for the device's primary ABI. `GET /app/latest/<abi>.apk` answers
  `302` to the versioned APK of the latest release. `GET /app/info.json` returns the latest version,
  per-ABI file names, sizes, sha256 and the configured Downloader codes, for the landing page.

## Director's cuts (addendum, 2026-11-20)

A cut is a model-picked list of parts to keep; the TV skips the rest with its sponsor-skip
engine. Cuts exist only when the backend config names an explicit model (`[llm.cuts]`); without
it the build routes (`POST /v1/videos/{id}/cuts`, `PUT /v1/cut-requests/{id}`) answer
`409 {"error":"Cuts are not configured on this server (no [llm.cuts] model)."}`, the read
routes answer `200` with `"configured": false`, and `GET /v1/me` features carries `"cuts": false`.

Refused download (addendum, 2026-11-26, issue #205): when YouTube answers the server's download with HTTP 403 the server retries with
the next `[youtube] player_clients` entry after `forbidden_backoff_s`. If that fails too, a cut waits up to `[cuts] client_captions_wait_s`
for the TV to upload its captions (`POST /v1/videos/{id}/captions/client`) instead of failing: the request stays `needs_transcript` with
`error` = "YouTube refused the server; using the TV's captions…" (the TV's cut picker shows it in place of "Needs a transcript"), then
builds as soon as the captions arrive, or fails once the wait ends. Each such refusal adds one to the `youtube_forbidden` metric of the
day (`usage_daily`). Only the TV uploads captions, so the extension's cut fails after the wait (see "Clients").

Channel defaults (addendum, 2026-11-26): the owner can store a cut mode per channel, from the
TV's cut sheet or the web UI. A channel is the YouTube `channel_id` the client sends with the video
facts (at most 64 characters). An omitted mode resolves in order: the owner's default for the
video's channel, else the user's `cuts.cut_mode`, else `[cuts] default_mode`; the rule that
decided is `mode_rule` (`request`, `channel`, `user` or `server`). A default `watched` while it is
unavailable still reports its rule but runs `quick`.

- `GET /v1/cut-channels` -> `{"channels":[{"channel_id","channel_name"?,"mode":"quick"|"watched"|
  null,"updated_at"?}]}`, by channel name then id. A channel the owner has cut but not given a
  default appears with `"mode": null`.
- `PUT /v1/cut-channels/{channel_id}` body `{"mode":"quick"|"watched"|null,"channel_name"?}` ->
  the stored row. `mode: null` clears the default. Storing `watched` while it is unavailable
  answers `409`. `DELETE /v1/cut-channels/{channel_id}` -> `{"ok":true}`, idempotent.
- Channel defaults belong to their owner. The optional `channel_id` query param rides next to the
  other video facts on `GET /v1/videos/{id}/cuts`, `POST /v1/videos/{id}/cuts` and
  `PUT /v1/cut-requests/{id}`; the picker answer adds `default_mode`, `mode_rule`, `channel_id`,
  `channel_name` and `channel_mode` (the owner's stored override, or `null`).

- `GET /v1/videos/{id}/cuts` -> `{"configured":bool,"presets":[{"id","label","state",
  "request_id"?,"error"?,"cut"?}],"selection":{...}|null}`. State is `none` | `waiting` | `building` |
  `needs_transcript` | `ready` | `failed` for this video; `ready` carries the cut document.
  `selection` is what the video opens with: the viewer's choice for this video (a preset, a typed
  request, or `off`), else the preset they used last when it has a ready cut here; `null` when
  neither does, so a client offers the ready cuts instead of picking one. Fields:
  `{"source":"chosen"|"last"|"off","off":bool,"preset_id"?,"request_id"?,"state","cut"?}`;
  `cut` rides once the selection is ready.
- `GET /v1/videos/{id}/cuts` also carries a strong ETag (`etag`, echoed in the body and the `ETag` header; a hash of the whole answer, so it changes when a preset's state, a ready cut, the selection or the modes change) and `Cache-Control: max-age` (the backend's `[cuts] cache_max_age_s`, 900 s). A client that serves the menu from a local cache re-validates it with `If-None-Match` and gets `304` (carrying the same `ETag`) when nothing changed, so the menu opens instantly from that cache while the backend is slow or down and refreshes in the background; the cut document on the wire is unchanged, so this is backward with earlier backends (offline-first, issue 146).
- `POST /v1/videos/{id}/cuts` body `{"preset":"<preset id>"}` | `{"prompt":"<what to keep>"}` |
  `{"await_prompt":true}` -> `{"request_id","state"}`. `preset`/`prompt` are mutually exclusive
  (sending both answers `400`); `await_prompt` creates a `waiting` request the phone fills (the
  TV's "Describe on phone…").
  A preset or a typed description is also remembered as the viewer's choice for the video (a
  preset also becomes the preset used last for the user); filling a waiting request remembers it too.
  The caller's known video facts ride as query params (`title`, `channel`, `duration_s`,
  `is_live`) so the phone queue can show them before the backend learns them itself.
  Optional `"force":true` rebuilds the cut even when one is stored; it reuses the stored transcript
  (captions the server fetched, the TV uploaded, or speech-to-text). Optional `"refetch":true` also drops the stored
  captions and builds the transcript from the audio, as `force` does for transcribe and captions. Neither is echoed in the
  request document, and a forced or refetching request never joins a request of another kind. Transcripts the TV uploaded
  (`captions/client`) and speech-to-text ones never expire. When YouTube refuses the download (HTTP 403, "Requested
  format is not available", "try again later") the server tries the next player client, then the cut waits for the TV's captions and says so
  in `error`; removed, private or members-only videos fail at once.
  Duplicate active requests (same video + preset/prompt/waiting) return the existing row; a
  `failed` row never blocks a new request, so asking for the same preset again starts a fresh
  build and keeps the failure in the history. A per-user cap on concurrent builds answers `429`.
- `PUT /v1/videos/{id}/cut-choice` body `{"preset":"<preset id>"}` | `{"request":"<request id>"}` |
  `{"off":true}` -> `{"ok":true}`. Remembers what the viewer chose for the video; exactly one kind
  (otherwise `400`). A preset also becomes the preset used last for the user. `off` is the
  explicit choice to play uncut and is kept for that video.
- `GET /v1/cuts/{request_id}?wait_ms=3000` long-polls (default `cuts.default_wait_ms` 3000 ms,
  cap 20000 ms, omit `wait_ms` to take the default) while `waiting`/`building` and returns the
  request document below.
- `GET /v1/cut-requests` -> `{"requests":[...]}` newest first (max 100), the phone queue.
- `PUT /v1/cut-requests/{id}` `{"prompt"}` fills a `waiting` request and starts the build
  (`409` when it is not waiting any more). `DELETE /v1/cut-requests/{id}` dismisses a request
  (a building one is stopped); dismissed requests leave the queue.
- `GET /cuts/{request_id}` (no auth): `302` to `/#/cuts/{request_id}`, the QR target that opens
  the request's cut sheet in the web UI.

Request document (both the queue cards and the single request):
`{"id","video_id","state","source","mode_rule","preset_id","prompt","error","created_at","updated_at",
"title"?,"channel"?,"channel_id"?,"duration_s"?,"stage"?,"progress"?,"cut"?,"job_id"?,"instruction"?,"raw_answer"?}`.
`stage` (`transcript`|`model`|`checking`, `in_line` while a normal build waits for prime work, and for a video too long for one request `map`|`reduce`;
clients show an unknown stage as its name) rides while building; `progress` (`{"done","of"}`,
additive) rides during `map` and counts the excerpts answered; `cut` once ready; `job_id`
opens the build report in the jobs API; `raw_answer` is the model's answer, trimmed. A video whose
transcript does not fit one model request (`[cuts] max_input_tokens`) is cut by map/reduce: excerpts
on chapter boundaries apply the task to their own text, one final call picks the cut with the same
length selection; no video is refused for being long. A cut with no target length (a removal
preset, a saved preset with no length) is limited on that path to `[cuts] map_max_keep_frac`
(default 0.90) of the video, keeping the highest-ranked parts; the model still chooses them.
Each `map` event carries the excerpt's `kept_s`, `removed_s` and `parts`, and the `reduce` event
carries `kept_s` and `target_s` or `cap_s` (additive; older clients ignore them).

The cut document (`cut`): `{"version","video_id","transcript_hash","duration_ms","label",
"summary","parts":[{"label","start_ms","end_ms"}],"skip_ranges_ms":[[from,to]...],"kept_ms",
"kept_s"?,"target_s"?,"source","preset_id","model","built_at"}`. `kept_s` is `kept_ms` in seconds
(one decimal) and `target_s` the preset's target length in seconds, `null` for typed prompts, saved
presets and videos already short enough (both additive; older cuts lack them, clients read `kept_ms`). All times are milliseconds of the video the cut was
built for (`duration_ms`); a client does not apply a cut whose video length differs by more than
2 s. `transcript_hash` identifies the transcript the cut was built from; clients carry it and do not
compare it (they hold no transcript). `skip_ranges_ms` is the sorted,
non-overlapping complement of `parts`.
`source` is the transcript's origin (`youtube_captions` or `asr`) on YouTube cuts. A cut of another
source (a film or episode, see "Cuts of films and episodes") may carry it as `{"kind","key","release_key"?,
"release_duration_ms"?}` instead; a client that ignores it reads the YouTube `video_id` as today.
A cut may also carry optional `transitions` (`[{"after_part","type","duration_ms","asset":{"ref",
"sha256"?},"engine","engine_version","status"}]`, status `none|pending|ready|failed`) from the later
feature that generates them. Both fields are additive: `parts` and `skip_ranges_ms` never depend on
them, old cuts lack them, and a client that cannot show transitions skips as today.

Build rules (mirrored from the backend config, `[cuts]`): caption fragments are merged into
numbered sentence-like units (new unit on a pause over 0.6 s or sentence punctuation, 15 s
cap; only an auto-caption fragment's repeated tail is dropped (an authored caption or ASR
text keeps a genuine repeat); the model answers JSON with kept unit id ranges (`from`/`to`), a label per part, a
one-line summary and `kept_s`; ids are validated (must exist, sorted, never overlapping) with
one repair round; kept parts are merged (gaps under 2 s) and short parts (under 4 s) dropped
on the model's boundaries clamped to the video first, then the kept boundaries are padded 0.3 s
before and 0.5 s after.
Keeping under 10 % of the video ("this would remove almost everything") is refused, except
for a cut with a target length and for the presets that keep a small part by design (`[cuts]
short_presets`: just the answer, the demo, the highlights). Keeping over 95 % ("nothing to cut")
is refused only for a typed prompt without a target: a named preset has no upper guard, because
a removal preset that keeps nearly all of the video is a valid answer. The removal presets report the result in `summary` ("Removed 1:12
of filler, 2 % of the video"); when nothing at all is removed that summary is "No filler found"
(or "Nothing was removed") and the cut is `ready`, not failed. A missing timed transcript
queues a transcript job (`needs_transcript`) and the build waits for it (15 min); live streams
are refused. Builds run
as their own async tasks (never in the caption worker's queue) with a per-user cap, and one
finished cut is shared per (video, preset or prompt, model, transcript) cache key — two requests
with the same key that are in flight together share the model call too.

Target length (addendum, 2026-11-24): a built-in preset can have a target length (`[cuts]
preset_target_s`, today `cut-highlights-5` = 300 s) and a tolerance (`length_tolerance`, default
0.15 = +/- 15 %). The model is told the target, asked to keep about `over_ask_frac` (0.2) more and to
give every part a `rank` (1 = most important; optional, an answer without ranks counts in video
order). The server takes parts by rank until the target is reached, trims the last one at a unit
boundary so the total stays inside the band, and returns them in video order. The selection charges
the merged, padded, video-clamped length (a gap under `merge_gap_s` is part of the cut it
counts) and never selects a part under `min_part_s` on its model boundaries, so the parts it
counts survive `finalize_parts` inside the band. An answer below the
band gets one retry that names the measured length; a second short answer fails the request
("The model kept only N s of the T s this cut aims for"). A preset with a target skips the keep
fraction guard; a video no longer than the band's top is cut without a target. Clients show the real
length (`kept_ms`) next to the preset label, for example "Highlights in 5 min · 5:02" (TV picker; the
browser extension's cut checkpoints show the same, plan section 3).

A built-in preset can also target a fraction of the video instead of a fixed length (`[cuts]
preset_target_frac`, a `0 < f < 1` fraction; `cut-skim-film` defaults to `0.5`). Its target is
`duration_s * f`, applied after `preset_target_s` and only when the video is long enough to fall
outside the band, so `target_s` in the cut document is the effective fraction target. `cut-skim-film`
("Skim the film") keeps the story beat by beat — the scene's best moments, in order, no cut mid-shot
or mid-sentence — to about half the film's length; it has no description (the preset infers the story
from the scenes). It runs in either mode: `quick` from the timed transcript, or `watched` when the
viewer picks it for the vision pass. It is offered like the other built-in presets (`GET
/v1/videos/{id}/cuts`), and it is a film-length cut: for a film too long for one request the map/reduce
path limits it to `[cuts] map_max_keep_frac` of the video (the model still picks).

Length of saved presets and typed prompts (addendum, 2026-11-24): the same band and rank selection
apply to any cut that has a target. The target is, in order: a built-in preset's `preset_target_s`;
a saved preset's explicit `length_min` / `length_frac` (a fraction needs the video's duration); the
length the description asks for, read by a small English parser (`half`, `a third`, `a quarter`,
`N %`, `N minutes`, `N min`, `under N minutes`, `shorter by half`; "the first half", "skip the first
5 minutes" or two different lengths give no target). Built-in presets' own wording is never read. The
cache version includes the target and the band settings (`length_tolerance`, `over_ask_frac`), so a
cut built before this rebuilds once and changing either setting rebuilds targeted cuts;
`target_s` in the cut document is the effective target (`null` without one).

### Cut modes: Quick and Watched (addendum, 2026-11-24)

Every cuts route keeps its Quick behaviour, and the new fields are additive: a client that
ignores them sees the caller's default mode exactly as before. Quick is the transcript-only
engine above. Watched is opt-in picture analysis: it stores a small video copy, describes 2x2
frame grids with `[llm.cuts_vision]`, joins those descriptions to the same transcript units,
and asks `[llm.cuts]` for the timeline. It is available only when `[llm.cuts_vision]` is set,
the `watched` Python extra (Pillow) is installed, `[cuts.watched] enabled` is true, and the
video is not live or longer than `[cuts.watched] max_video_minutes` (90 by default).

- `GET /v1/me` features gains `"cuts_watched": bool` (whether Watched could run on this server;
  watched availability per video also answers `409` with its plain reason).
- `GET /v1/videos/{id}/cuts` adds `"default_mode":"quick"|"watched"` and
  `"modes":[{"id","label","default":bool,"available":bool,"reason"?,"eta_s"?}]`. A preset keeps
  its existing top-level state fields for the caller's default mode and adds
  `"by_mode":{"quick":{...},"watched":{...}}` with the same state fields as the top level.
- `POST /v1/videos/{id}/cuts` and `PUT /v1/cut-requests/{id}` accept optional `"mode"`; without
  it the request takes the user's `cut_mode` (below). Unavailable Watched answers
  `409 {"error":"<the modes reason>"}` before a request is queued.
- The request document gains `"mode"` (always present, `quick` for old rows), and while
  `building` also `"progress"` (0 to 1) and `"eta_s"` (remaining estimate, integer seconds).
  A failed Watched request gains `"fallback"`: the Quick state (`none`/`ready`/...) of the same
  preset or description, which the client offers with one press. Quick requests never carry it.
- Request/build stages gain `"video"`, `"grids"`, `"describing"` and the queue stage `"in_line"`.
  The visible sequence for Watched is `transcript` -> `video` -> `grids` -> `describing` ->
  `model` -> `checking`; cached stages report `skipped`.
- The cut document gains `"mode":"quick"|"watched"`. Watched also adds
  `"watched":{"grids":int,"model":"<vision alias>","partial":bool,"coarse":bool}`. `version`
  stays 1; Quick documents keep every existing field.
- `GET /v1/processed`: each cut entry gains `"mode"` (`quick` for old rows), so a tile can
  label a Watched cut.

The per-user setting `cut_mode` (`"quick"` default or `"watched"`) is the viewer's default, in the
`cuts` section of `GET/PUT /v1/me/settings` and `GET /v1/me`. Its choices are
`["quick","watched"]`; the server-wide default is `[cuts] default_mode`. Changing it does not
start a build. Watched is still chosen per request on the TV and phone, and the choice holds for
that picker session.

Build rules for Watched: a failure never turns into a dead Quick job. If more than 20 % of
scenes stay unseen (`max_unseen_frac`), the vision model stays busy/unavailable, the stored
video exceeds 90 minutes or 1 GiB, free disk falls below the configured floor, a describe
estimate exceeds `describe_s_per_grid_max` per grid, or the 1-hour build deadline passes, the
request goes `failed` with a plain reason and the Quick `fallback`. One Watched build runs at a
time per server (`[cuts.watched] max_concurrent`, default 1): a second request emits `in_line`
and waits its turn. A request waiting for its transcript holds no slot: the transcript comes
first, then the slot. The video copy and scene/grid caches are per video and video description;
grids are per preset's description and removed after the build unless `keep_grids`.

Admin: `GET /v1/admin/videos/{id}/tdt` returns the newest stored TDT for debugging a watched
build (`{"cache_key","tdt"}`; `404` when none). `DELETE /v1/admin/archive/{video_id}` also drops
that video's watched scene, description and label caches.

No-target long videos (repair, 2026-11-25): a map/reduce cut with no target length is capped at
`map_max_keep_frac` of the video (default 0.90), keeping the highest-ranked parts; a one-pass cut is
unchanged and a named preset may still keep nearly all of a short video. Cuts built before this
algorithm (`cuts.algo_version` older than the current build) that kept over `repair_near_full_frac`
on the map/reduce path are superseded once, on server start or by `utubot cuts repair`, and the same
user, video and preset or prompt is queued again; the wire documents do not change.

## Cuts of films and episodes (addendum, 2026-11-28, issue 295)

A film or an episode playing in the TV's main player is cut like a YouTube video, from its subtitles. The cut routes are the same
(`GET/POST /v1/videos/{id}/cuts`, `PUT .../cut-choice`, `GET /v1/cuts/{id}`, the queue); what differs is the id and the facts the TV states.

- **The id** is derived, never guessed: `f` plus the first ten hex digits of the SHA-256 of `{source_key}|{release_key}` (eleven characters,
  so every route keyed by a video id works). The release is the stream file, so cuts, the cut choice and the stored subtitles are per
  release. A request whose id does not match its source and release is `400`.
- **The facts**, as query parameters on the cut list and the cut request: `source_kind=film`, `source_key` (`imdb:tt0111161`, or
  `imdb:tt0944947:S1E2` for an episode), `release_key` (the stream's name and size), `release_duration_ms` (the player's length; the details
  screen sends the length it last saw or the catalogue runtime), `file_name`, `stream_size`, `stream_fps` (when the player opened the file),
  `sub_lang` (the viewer's subtitle language, two letters), `title` and `poster` (a public image address; stored only when its origin is in
  `[films] poster_origins`). The server keeps them with the video facts, so a phone request for the same id needs none. The stream address
  is never sent.
- **The transcript** is a subtitle file from a Stremio subtitles add-on (`[films] subtitles_url`, OpenSubtitles v3 by default), asked by IMDb
  id (`/subtitles/{movie|series}/{tt..[:season:episode]}/filename=..&videoSize=..`). Only the IMDb id, season, episode, file name and size
  leave the server. The candidate in the viewer's language (else English) whose release name best matches the file name is tried first (token
  overlap, release group, hash match). It is used only when its timing fits the release: enough cues, the last cue before the stream's end plus
  a margin, reaching at least `min_last_cue_frac` of it, covering `min_cover_frac` of it, and the subtitle's and the stream's frame rates
  agreeing (`fps_tolerance`) when both are known. The first failure is the reason told: the request fails with plain words
  ("The subtitles end at 4 min but this stream is 126 min, so they belong to a different cut of the film."), shown as the preset's error.
  A stored transcript (an earlier fetch, or captions the TV sent through `POST /v1/videos/{id}/captions/client` from the file's own tracks)
  is used first and never refetched.
- **Modes**: films are Quick only. `modes[watched]` is `available: false` with a reason, a request for `watched` is `409`, the default is
  `quick`.
- **Columns**: `cut_requests` and `cuts` keep `source_kind` `film`, `source_key`, `release_key`, `release_duration_ms`; the cut document's
  `source` is `{"kind":"film","key","release_key","release_duration_ms"}`.
- **Other releases**: a cut built for another release of the same title is offered for this one (its `video_id` rewritten to this release's,
  plus `shared_from_video_id`) only when both lengths are known and agree within `[cuts] release_duration_tolerance_ms`.
- **Applying**: a TV applies a film cut whose length is within `[films] apply_tolerance_ms` (30 s; subtitle sync is not frame exact), not the
  2 s of a YouTube video.
- The queue card and the inbox carry `title`, `thumbnail` (the poster) and `source_kind`; the phone page shows the poster and no YouTube link.
- Clients: TV only. Films play in the TV app; the extension has no film player. Its row is in the plan's parity matrix.

## Voice prompts (addendum, 2026-11-21)

The phone's spoken cut description becomes text through modelgate only: this backend posts the
audio to modelgate `POST /v1/audio/transcriptions` (`[speech] alias`, EVR-464). The audio is not
stored: no file, no transcript row, and the server log records only the client, alias, bytes and
duration. The multipart form is closed after the read, so a spooled temp file is unlinked before
the response leaves. Without `[speech] alias` (or without the named provider in `[llm.providers]`)
the route answers `503 {"error":"Speech is not configured on this server; type the cut instead."}`
and `GET /v1/me` features carries `"speech": false`.

- `POST /v1/speech`: `multipart/form-data` with one recording in the field `audio` (the field
  name `file` is accepted too) and an optional `language` hint (the caller's language; it overrides
  `[speech] language` for that request). Authenticated like every `/v1` route. It has its own body cap,
  `[speech] max_upload_bytes` (default 4 MiB) — `413 {"error":"request too large"}` before the
  form is read; `security.max_body_bytes` (256 KiB) stays for every other route. A per-user
  rate limit, `[speech] per_user_per_min` (default 10), answers `429 {"error":"rate limited"}`
  with `Retry-After`.
- `200 -> {"text":"<transcribed text>"}`. The text is returned as it came; the phone puts it in
  the description box and keeps it editable, never sending it itself.
- Plain errors: `"Speech service is busy, try again or type it."` (`429`/`503`/`504` upstream,
  timeouts, and transport failures such as modelgate being unreachable), `"Speech could not be
  transcribed, try again or type it."` (other upstream refusals), `"The recording was empty; try
  again or type it."` (empty upload, `400`), `"The recording is too long or too large; try again
  or type it."` (upstream `413`).
- The forwarded file part keeps a decoder-friendly extension: the phone sends `recording.webm` or
  `recording.m4a`, the TV `recording.wav` (16 kHz mono PCM muxed on the device), and a bare client filename gets an extension from the content type.
- `GET /v1/me` features adds `"speech":bool` and `"speech_max_s":int` (default 50), the phone's
  recording limit. The modelgate route's engine refuses a chunk over about 55 s (EVR-524), so the
  default stays below it; a longer description takes several Speak taps, each appended to the
  box.

## Saved cut presets and the phone share target (addendum, 2026-11-21)

The owner can save a description from the cut sheet as his own preset. Saved presets are rows of
the user's prompt set `cut-presets` (`task:"cuts"`), so `GET /v1/videos/{id}/cuts` lists them
beside the built-ins and a save/delete changes both views. That set never appears in
`GET /v1/prompts` (summary defaults and the prompt pickers exclude cut tasks); managing saved
presets is phone-only in v1. A saved preset's id is `cut-mine-<12 hex>` (a hash of its name and
description), so saving the same name and description replaces the earlier copy. A built-in
preset cannot be deleted from this list, and a user may keep at most 20 saved presets. A built
cut carries the saved label (`label` in the cut document), not the id.

- `GET /v1/cut-presets` -> `{"presets":[{"id","label","length_min"?,"length_frac"?}]}` in saved
  order, the owner's own only.
- `POST /v1/cut-presets` `{"label","prompt","length_min"?,"length_frac"?}` ->
  `{"preset":{"id","label","length_min"?,"length_frac"?}}`. `length_min` (0.5..600 minutes kept) or
  `length_frac` (0.05..0.95 of the video kept), not both; `0`/absent means none (see Target length,
  "Length of saved presets and typed prompts"). The label is 1..60
  characters, the description 1..2000 (the same cap as a typed prompt); empty or too long
  answers `400 {"error":"<plain reason>"}`. The description becomes the preset's task text.
- `DELETE /v1/cut-presets/{preset_id}` -> `{"ok":true}`; `404` for an unknown id (a built-in id
  is unknown here). The last saved preset deletes the set.

The web UI is a PWA (manifest at `/manifest.webmanifest`, icon, standalone) and takes Android's
Share target: YouTube -> Share -> u·tubot. Nothing on the server receives the shared POST.

- The manifest's `share_target` is `{"action":"/shared","method":"POST",
  "enctype":"multipart/form-data","params":{"title":"title","text":"text","url":"url"}}`.
- `/sw.js` (public static, `Service-Worker-Allowed: /`) handles `POST /shared`: it keeps the
  newest shared `url` (else `text`) in the Cache API under `/__shared-item` with its timestamp,
  then answers `303` to `/#/cuts`. Items older than 10 minutes are dropped when taken.
- The Cuts page asks the worker for the item once (`take-share`), deletes it, and starts a
  `{"await_prompt":true}` request for the URL's video id; the sheet opens. A shared item without
  a YouTube link says "paste the link in New cut" and starts nothing.
- `/manifest.webmanifest` and `/sw.js` are public like `/` and `/ui`; CSP allows `manifest-src
  'self'` and the site's own worker, and `Permissions-Policy` allows the microphone for self
  (the Speak button), with camera and geolocation still off.

## Processed videos (addendum, 2026-11-23)

The TV's *Processed* section asks for the videos a user recently processed. This is a read-only
view: it combines the caller's caption jobs (`jobs`, kind `captions`), the caller's cut requests
(`cut_requests`) and the shared `summaries` table. No new storage is written.

`GET /v1/processed?limit=50` (auth required; default 50, 1..200, `400` outside the range)
returns `{"videos":[...]}`, one item per video id, newest last change first. `limit` counts
videos, not caption or cut entries; a video with several jobs still is one item. A video is
listed when the caller has at least one caption job or non-dismissed cut request for it. Only
the caller's rows are combined; another user's caption jobs and cuts never appear. Dismissed
cut requests are not listed, and a video with only dismissed requests does not appear.

Item:

```json
{"video_id":"dQw4w9WgXcQ",
 "title":"...",              // cached metadata title, else the newest caption job's title; null if neither
 "thumbnail":"https://i.ytimg.com/vi/dQw4w9WgXcQ/mqdefault.jpg", // metadata thumbnail_url/thumbnail, else this standard URL
 "duration_s":633.0,         // cached metadata duration in seconds; null when unknown
 "updated_at":1763900000.0,  // newest updated_at among the item's caption jobs and cut requests
 "summary":true,             // any stored summary for this video (summaries are shared per video)
 "captions":[{"job_id":"...","lang":"en","translate_to":"en",
              "state":"waiting|processing|ready|failed|cancelled",
              "progress":1.0,"error":null,"created_at":1763899900.0,"updated_at":1763900000.0}],
 "cuts":[{"request_id":"...","state":"waiting|building|needs_transcript|ready|failed",
          "preset_id":"cut-demo","preset_label":"Only the demo","prompt":null,"error":null,
          "created_at":1763899800.0,"updated_at":1763899900.0}]}
```

Captions and cuts are newest first. `state` for caption jobs is the client-facing job state used
by `GET /v1/jobs` (raw `queued` is `waiting`, `running` is `processing`). A cut's `preset_label`
is the built-in or saved preset label; it is null for a prompt request, whose text rides in
`prompt`. Empty history is `{"videos":[]}`.

## Inbox (addendum, 2026-11-26)

The TV's *Inbox* is one item per ready AI result: a ready cut, a requested summary/TL;DR, a
research/insight answer, or a ready HQ caption. Unlike [Processed](#processed-videos-addendum),
this is **new storage**: each result writes one row, so the viewer can come back to a result after
leaving the video.

`GET /v1/inbox?limit=50` (auth required; default 50, 1..200, `400` outside the range) returns
`{"items":[...],"unread":N}` — newest first, unread count for the caller.

```json
{"items":[{"id":1,"video_id":"dQw4w9WgXcQ","kind":"cut|summary|research|captions",
           "result_id":"...","prompt_key":"...",
           "title":"...","length_s":754,"label":"Only the demo","created_at":1763900000.0,
           "read":false}],
 "unread":3}
```

- `kind` is one of `cut`, `summary`, `research`, `captions`.
- `result_id` is the item's dedup identity with `kind`/`video_id`: the cut's `request_id`, the
  summary's `prompt_key`, the research's language, the caption's `lang`. A result reported ready
  again (a re-ready, or a client polling) does not make a second item, and the first `created_at`
  is kept.
- `prompt_key` is the summary's prompt key (null for other kinds).
- `title`/`length_s`/`label` come from the result: a cut's title/length/label, a summary's prompt
  title/length, the research's metadata title/length, the caption's label. `label` is null for
  research and captions (the client derives it from `kind` + `result_id`).
- `read` is derived from `read_at` (null = unread). Read state is **per user and global**: any
  client (phone, extension, TV) for that user can mark an item read or unread, so the state is
  shared across devices.

`POST /v1/inbox/read` `{"ids":[...]}` (≤ 200) marks those items read (`{"ok":true}`); `POST
/v1/inbox/read-all` marks all the caller's items read; `POST /v1/inbox/dismiss` `{"ids":[...]}`
(`{"ok":true}`) hides them (a read-only flag — the item can be created again later). All three
affect only the caller's items; another user's rows are untouched.

## Voice control (addendum, 2026-11-26)

Backend half of `ai/VOICE_CONTROL_PLAN.md` (checkpoint 1: consent, history, retention). Everything here is additive and
exists only when the server has `[voice] enabled = true` (default `false`). With it off every route below answers
`404 {"error":"voice is not enabled on this server"}` (after authentication), `GET /v1/me` has `"features":{"voice":false}` and no
other new key, and `/setup.json` is unchanged: a client that predates voice sees nothing different, and one that knows voice
reads `features.voice`.

- `GET /v1/me` (voice on): `features.voice` is `true`, plus `"device":{"id","name"}|null` (the paired device behind the token;
  `null` for a config token or a browser session) and `"voice":{"enabled","listen_mode":"push"|"wake","speak","retention_days"}`.
  `voice.enabled` is that device's own consent (off until switched on). The live server calls it with the device's token and
  may cache it for 60 s, so a switch-off reaches it within a minute.
- `GET /setup.json` (voice on) gains `realtime_url`: `server.public_base_url` + `[voice] realtime_path` (default `/rt`),
  with the scheme of the base address. Clients open the WebSocket on it (`wss`/`ws` equivalents of `https`/`http`).
- `GET /v1/me/voice` -> `{"enabled":true,"retention_days","default_retention_days","consent":{"version":1,"text":[...]},
  "devices":[{"id","device","enabled","listen_mode","speak","consented_at"}]}` (every paired device of the caller, off ones
  included). The consent text is the server's, so every client shows the same words.
- `PUT /v1/me/devices/{id}/voice` `{"enabled"?,"listen_mode"?:"push"|"wake","speak"?,"consent_version"?}` -> the device's
  `{"enabled","listen_mode","speak","consented_at"}`. Switching a device on needs `consent_version` equal to the
  current `consent.version` (`400` otherwise: show the text first). `404` for a device the caller does not own.
- `PUT /v1/me/voice` `{"retention_days"?:0..365,"all_off"?:true}` -> the overview. `all_off` switches every device of the
  caller off (switching one on again asks for consent again). A shorter retention deletes older records at once; `0` keeps nothing.
- `POST /v1/voice/commands` `{"text","tool","args":{},"outcome":"ok|failed|cancelled|refused|clarify|none","marks":{"stt_ms":410}}`
  -> `{"stored":true,"id"}` (`{"stored":false,"id":null}` when retention is 0). The live server files one record when a
  command ends, with the token of the device that spoke; a paired device that has not switched voice on gets `403`. `text` is
  at most `[voice] max_text_chars` (`413`), `args` at most `max_args_bytes`, `marks` at most 16 names of milliseconds. Rate limited
  per user (`commands_per_min`, `429`). No audio is ever part of a record.
- `GET /v1/voice/commands?limit=50` (1..`history_page_max`, `400` outside) -> `{"retention_days","commands":[{"id","at","device_id",
  "device","text","tool","args","outcome","marks"}]}`, newest first, expired records already gone. `DELETE /v1/voice/commands/{id}`
  -> `{"ok":true}` (`404` for an unknown or foreign id); `DELETE /v1/voice/commands` -> `{"deleted":N}`. All of them touch the caller's
  records only.
- Web UI: TVs page, "Voice control" card (a switch per device with the consent text, spoken replies, hands-free, retention, all-off)
  and a "Voice" page (the history, delete one or all). Both appear only when `features.voice` is true.
- Clients: the TV app is the screen and, later, a controller; this checkpoint adds no TV code (it ignores the new keys). The
  extension's row is `voice-control` in the plan's parity matrix.

## Live server (addendum, 2026-11-27)

The real-time half of `ai/VOICE_CONTROL_PLAN.md` (checkpoint 2): the Go service in `realtime/` (`utubot-rt`). Not the Python backend: its
own process, reached at `realtime_url` from `/setup.json` (`<public base>/rt`). Nothing here exists until the owner deploys it; without
`realtime_url` a client has no voice, and every other feature is unchanged. This checkpoint has no speech engine and no model: `say`
is understood by the phrase matcher only, and `listen` answers "Speech is not available on this server".

Routes (under the path, default `/rt`): `GET /rt/v1/ws` (WebSocket), `GET /rt/v1/health` (`{"ok":true}`, no auth),
`GET /rt/v1/stats` (`Authorization: Bearer <admin token>` from `UTUBOT_RT_ADMIN_TOKEN`; `404` when none is set, `401` otherwise wrong): the last
1,000 commands as `{"count","window","outcomes","hops":{hop:{"n","p50_ms","p90_ms","p99_ms","max_ms"}},"families":{family:{hop:...}}}` with
hops `server`, `push_ack`, `act`, `total`, `queue` and families `player`, `cut`, `captions`, `view`, `ask`, `other`.

Frames are JSON text, every one has `"t"`; unknown types and fields are ignored. Binary frames are audio of an open `listen`. A frame over
64 KiB closes the socket. Sides: D = device, S = server.

- D to S `hello` (first, within 5 s): `{"t":"hello","v":1,"token","roles":["screen"|"controller"],"client","name","tools":[...],"mic","speaker"}`.
  The token is a device token as for the backend (`utb_` prefix, at most 128 characters; anything else is refused as `unauthorized` without asking the
  backend) and rides in the frame. S checks it with `GET /v1/me` and re-checks every 30 s with a 15 s cache, so a revoked device or a voice switch-off
  closes the socket within the 60 s window. `tools` is what a screen can run (names of the plan's tool table); a screen only receives those.
  A browser's `Origin` must match the allow-list (`origins`, host patterns); a native client sends none.
  Protection of the backend's sign-in budget: upgrade attempts are limited per client address (30 a minute; the address is the last entry of
  `X-Forwarded-For`, which the proxy must set), at most 64 sockets may be waiting for their hello, and every `/v1/me` call of the live server carries
  `X-Utubot-Client: realtime` and `X-Utubot-Realtime-Secret: <secret>` (the secret is `UTUBOT_RT_BACKEND_SECRET` on the live server and `UTUBOT_REALTIME_SECRET`
  on the backend, same value) so the backend can count them apart from users' own addresses. **The backend counts a request carrying both in its own, larger
  bucket** (`[security] rate_per_ip_per_min_realtime`, 6000 a minute by default, keyed apart from the `ip:` bucket of the proxy address). The header alone
  grants nothing: without the matching secret a request stays in the users' bucket, and with no secret configured on the backend there is no separate bucket.
  A 429 on it refuses only the live server's own checks, never a user, so a flood of well-formed junk tokens cannot starve the users behind that address.
  A device that cannot be re-checked (backend unreachable or rate limited) keeps its socket for 10 minutes, then closes with `not_verified`.
- S to D `welcome`: `{"t":"welcome","device_id","user","voice":{"enabled","listen_mode","speak","retention_days"},"peers":[{"device_id","name",
  "roles","client","focus"?}],"server_time_ms"}`. `focus` is the screen's last `focus` frame as sent (left out when it is over 8 KiB). Or `error` and close: `unauthorized`,
  `voice_off` (the server's `features.voice` is false, or this device has not switched voice on), `too_many` (8 sockets per user),
  `bad_hello`, `unsupported_version`, `hello_timeout`, `backend_unavailable`, `shutdown` (a hello that arrives while the server stops). A second socket of the
  same device replaces the first: the older one gets `replaced`, which is **terminal**, a client must not reconnect on its own after it (two copies
  of the app would otherwise replace each other forever). After `revoked`, `voice_off`, `not_verified`, `unauthorized` a client reconnects only after the user acts;
  after `shutdown`, `idle_timeout` or a plain close it reconnects with backoff.
- S to D `peers` `{"peers":[...]}` whenever another device joins or leaves, or a screen's video, screen, playing state, cut state or view changes (not its position).
- D (screen) to S `focus`: `{"t":"focus","seq","screen":"player|browse|menu|search|other","video":{"id","title","channel","duration_s"}|null,
  "position_s","playing","rate","cut":{"active","label","part","parts","preset_id"|"request_id"}|null,"captions":{"track"}|null,
  "view":"summary|answer|cuts|none","at_ms"}`. The server keeps the latest per screen (a lower `seq` is ignored) and times it by its own clock (`at_ms` is informational). A screen that has not
  reported for 15 s no longer counts as playing. The understanding stage is given the focus with `playing` aged that way and the position extrapolated
  from the time the frame was received, `playing` and `rate`. Send on change (debounced 300 ms) and every 5 s while playing.
- D (controller) to S `say`: `{"t":"say","id","text","target"?}` (text up to 2,000 characters; `target` pins a screen by device id; a `say` id seen from the same device in the last 2 minutes is ignored, so a frame resent
  after a reconnect does not run twice). `listen`:
  `{"t":"listen","id","state":"start|end|cancel","format","target"?}` followed by binary frames; limits 30 s, 2 MiB, one utterance per
  controller at a time, 20 utterances a minute and 30 minutes a day per user (`error` codes `busy`, `too_long`, `rate_limited`,
  `daily_audio_limit`, `no_listen`). Audio is counted and dropped; the server never writes it anywhere. Elapsed time is charged to the day's audio on every way an utterance ends (end, cancel,
  too long, the server's own 30 s timer, a disconnect), and every device of the user is sent `heard` `failed` when it ends, so no screen keeps its microphone
  indicator on. The limits belong to the user and survive reconnecting. A refused frame answers `error` with one of `not_screen`, `not_controller`,
  `bad_frame` (unknown screen or view, empty text), `too_long`, `rate_limited`, `busy`, `no_listen`, `daily_audio_limit`. A screen too slow to take its queue is closed with `slow_consumer`.
- S to every device of the user `heard`: `{"t":"heard","id","state":"listening|transcribing|understood|failed","text"?,"tool"?,"message"?}`;
  `reply`: `{"t":"reply","id","text","more":false,"speak":false}` (a refusal or failure in words: "The TV is not connected", "Focus a video first");
  `outcome`: `{"t":"outcome","id","command_id"?,"tool","state","message"?}` with `state` one of `ok`, `failed`, `refused`, `timeout`, `expired`,
  `busy`, `cancelled`, `offline`, `none`, `clarify`, `rate_limited` (told to the user, but not filed in the history and not counted in the statistics). `id` is the `say` or `listen` id.
- S to the target screen `command`: `{"t":"command","id","tool","args","origin":{"device_id","kind":"text|voice"},"expires_ms","confirm":{"text","eta_s"?}|null}`.
  `id` is the server's own (`c<n>`), `expires_ms` is a time on the server's clock (`welcome.server_time_ms`, `pong.server_ms`), 10 s after the
  command was made. A command is sent once, never replayed after a reconnect, and a screen must ignore one past `expires_ms` and one it
  already saw. The target is the pinned screen, else the only connected one that lists the tool, else the one that is playing, else the
  one whose focus changed last within 10 minutes; two playing screens and no pin give an `ask` frame.
- D (screen) to S `ack`: `{"t":"ack","id","state":"received|confirm_shown|started|done|failed|refused","message"?,"data"?}`. `received` first
  (within 2 s, or the command is dead and the controller is told "The TV did not answer"), then `done`/`started`/`failed`/`refused` (within
  30 s). A screen handles one command at a time; up to 3 wait behind it (each expiring at 10 s), more are refused as `busy`. The `message` of
  a `failed`/`refused` is shown to the user as the reply.
- S to D `revoke` `{"id","reason"}`: the screen drops that command or its confirmation (no `received` in time, no answer to a confirmation).
- Confirmation is decided by the server from its tool table and the focus (`research`; a `watched` cut; HQ captions of a video over 30
  minutes). The screen shows the text, sends `confirm_shown`, and then the user answers on the TV (the screen acks `started` or `refused`) or by
  voice/another device: `answer` `{"id","option":"yes|no"}` from a controller (or `say` "yes"/"no") is forwarded to the screen as `answer`.
  Unanswered for 15 s the command is cancelled (`revoke`, outcome `cancelled`).
- S to D `ask` `{"id","text","options":[...],"expires_ms"}`: a question (which screen, or a clarifying question of the model), kept 30 s. The answer to a
  clarifying question is read as the user's next command. Any device answers with `answer`
  `{"id","option"}` (an option label) or by saying the option (or "the first"/"the second"); an unrelated utterance drops the question.
- `ping`/`pong`: either side sends `{"t":"ping","ts"}` and the other answers `{"t":"pong","ts"(echoed),"server_ms"}`; a device answers the server's
  ping (every 20 s) with `{"t":"pong","ts":<its clock ms>}`, from which the server keeps the clock offset. A socket silent for 45 s is dropped
  (`idle_timeout`).
- A device whose token is revoked, or whose voice switch is turned off, is closed within the cache window (`revoked`, `voice_off`). The server
  shutting down closes with `shutdown`; clients reconnect with backoff (1 s to 30 s, jitter). A backend that cannot be reached does not
  close sockets: the last good answer stays in use.
- After a command ends the server files one record with `POST /v1/voice/commands` using the speaker's own token (outcome mapped to the
  route's vocabulary, `marks` of `server_ms`, `push_ack_ms`, `act_ms`, `total_ms`, `queue_ms`). Best effort: filing goes through a bounded queue and a record is dropped when it is full, a failure is logged only. The `queue`/`server` hops stop when the frame is queued for the socket's writer, not when it is written.
- Clients: the TV app is the screen (checkpoint 3), the phone page, the phone app and later the extension are controllers. Server only in this
  checkpoint: no client speaks this protocol yet, so the parity matrix row `voice-control` is unchanged.

## Setup file (`GET /setup.json`)

Public, rate limited like `/v1/health`. The app's "Import setup" fetches it so nothing is typed
but a short address.

```json
{"utubot_setup":1,
 "name":"Family server",
 "backend_url":"https://utubot.example.com",
 "update_url":"https://utubot.example.com/app/update.json",
 "pairing":true,
 "defaults":{"assess":true,"mark_only":false,"answer_in_menu":true,
             "summary_panel":false,"auto_captions":true},
 "prompt_set_urls":["https://example.com/my-prompts.json"]}
```

- `utubot_setup` (required): format version, `1`.
- `backend_url` (required) and `update_url` (optional): `https`, or `http` for private
  addresses only (loopback, RFC1918, link-local, CGNAT/tailnet, `.local`, single-label names). With
  no `update_url` the app never checks for updates. The backend builds both from
  `server.public_base_url`.
- `name`: shown after the import. `pairing`: when true the app opens the 6-digit pairing dialog next.
- `defaults`: the app's switches; missing keys leave the current value. The backend takes
  them from `[setup.defaults]`.
- `prompt_set_urls` (optional): imported after pairing succeeds.

The app builds the address to fetch from what the user types: a bare host
(`utubot.example.com`, `host:port`) becomes `https://<host>/setup.json` (`http` for a bare private
address, which cannot hold a certificate); a full URL is fetched as typed.

## Web UI endpoints

The phone web UI (`GET /`, static files under `/ui/`) uses the same API as the app. Its additions:

### Sign-in for browsers

- `POST /v1/auth/login` `{"username":"owner","password":"..."}` or `{"token":"utb_..."}` ->
  `{"user":"owner","admin":true,"csrf":"<64 hex>","expires_in_s":2592000}` and `Set-Cookie: utubot_session=...; HttpOnly; SameSite=Lax;
  Path=/; Max-Age=2592000` (`Secure` when the browser reached the server over HTTPS, directly or through a trusted proxy that sends
  `X-Forwarded-Proto: https`). `401 {"error":"invalid username or password"}` (an unknown user and a wrong password are identical),
  `429` with `Retry-After` once the address, the account or the server is locked out after repeated failures, `403` for a
  cross-origin `Origin`.
- `GET /v1/auth/session` -> `{"user","admin","via":"cookie|token","csrf":"..."|null,"has_password":true}`.
  With `[auth] tailscale_identity` on, a safe request (`GET`, `HEAD`, `OPTIONS`) from a loopback peer carrying a mapped
  `Tailscale-User-Login` (Tailscale Serve) creates the session here; `via` is `cookie` and `csrf` is set, as for any other sign-in.
- `POST /v1/auth/logout` -> `{"ok":true}`, ends the session and clears the cookie.
- `PUT /v1/me/password` `{"current_password":"...","new_password":"..."}` -> `{"ok":true,"csrf":"..."|null}`. `current_password` is
  required when a password exists. At least 10 characters. Ends the user's other sessions.
- A session lasts 30 days from the last use. `POST`, `PUT` and `DELETE` authenticated by the cookie must send `X-CSRF-Token` with the
  value from login or `GET /v1/auth/session` (else `403 {"error":"csrf token missing or wrong"}`), and an `Origin` header, when present,
  must name this server. Bearer-token calls need neither.

### Per-user settings

`GET /v1/me/settings` (admins: `GET /v1/users/{name}/settings`):

```json
{"user":"owner","version":3,"updated_at":1700000000.0,
 "settings":{
   "models":{"glance":"llama3.2:3b","summary":"llama3.1:8b","answer":"llama3.1:8b","triage":"llama3.2:3b","analysis":"llama3.1:8b"},
   "prompts":{"default":"builtin/tldr","panel_default":"builtin/glance"},
   "filtering":{"hide_topics":[],"mark_topics":[],"hide_clickbait_above":0.9,"mark_clickbait_above":0.6,
                "hide_low_quality_above":0.9,"mark_low_quality_above":0.65,"mark_inflated_ratio_below":0.35,
                "inflated_min_duration_s":300,"answer_in_label":false,"mark_only":false},
   "summaries":{"language":"en","auto_long":false},
   "transcripts":{"auto_transcribe":"on_open","auto_transcribe_max_minutes":30,"captions_translate_to":"en"},
   "tv":{"summary_delay_ms":1800,"summary_panel":false,"auto_captions":true,"update_checks":true}},
 "overrides":{"models":{"glance":"llama3.2:3b"}},
 "defaults":{ "...": "the same shape: what applies with no override" },
 "choices":{"tasks":["glance","summary","answer","triage","analysis"],"auto_transcribe":["off","on_dwell","on_open"]}}
```

`settings` is what applies (a TV reads this); `overrides` only what the user changed; `defaults` what a reset returns to. The
precedence (override, `[users.policy]`, `[default_policy]`, built-in, then the server setting an unset field follows) is in
[docs/server.md](../docs/server.md#per-user-settings). `version` rises by one on every change, also through `PUT /v1/me/policy` and
the prompt-default calls. `auto_transcribe` is `off`, `on_dwell` or `on_open`; the TV settings are `summary_delay_ms` (0-10000),
`summary_panel`, `auto_captions`, `update_checks`; thresholds are 0-1.01; at most 50 topics of at most 80 characters.

`PUT /v1/me/settings` (admins: `PUT /v1/users/{name}/settings`) takes a partial document and returns the new one:

```json
{"version":3,"allow_unlisted_models":false,
 "settings":{"models":{"summary":"qwen3:14b","glance":null},"filtering":{"hide_topics":["asmr"]},"tv":{"summary_delay_ms":1000}}}
```

`null` removes the user's override of that setting. `version` is required from a browser session (`428
{"error":"send the settings version you loaded with the change","version":3}` without it) and optional for bearer-token callers;
when given and stale the answer is `409 {"error":"settings changed since you loaded them; reload","version":4}` (the write is a
compare-and-set, so of two writers from the same version only one succeeds). Errors are `400 {"error":"..."}` naming the field
(`unknown setting filtering.nope`, `invalid settings: auto_transcribe: Input should be 'off', 'on_dwell' or 'on_open'`). A task model
must appear in `GET /v1/models` unless an admin sends `allow_unlisted_models: true` (`400` with `"unlisted":"<model>"` otherwise; `403`
when a non-admin sends the flag). `PUT /v1/me/policy` answers `403` to a non-admin that sets `models`.

### Web settings (`[settings_sync] enabled`, default off)

Plan: [`ai/WEB_SETTINGS_PLAN.md`](WEB_SETTINGS_PLAN.md). With the switch off every route below answers `404` after authentication,
`GET /v1/me` has no `features.settings_sync` and the settings document has no `values`, so an old client sees nothing new. All routes
are additive and need a signed-in caller.

- `GET /v1/settings/schema` -> the file `ai/settings/schema.json` (`schema_version`, `groups`, `settings`); `ETag` is the
  `schema_version`. A setting is named only there. Per setting: `key` (`ai.summary_panel`), `group`, `title` (at most 60 characters),
  `description` (at most 160), `type` (`bool`, `int`, `float`, `enum`, `string`, `list`, `model`, `prompt`, `secret`), `default`, the range
  (`min`, `max`, `step`, `presets`, `choices`, `max_items`, `max_len`), `scope` (`user` or `device`), `device_override` (one TV may hold
  its own value), `remote` (`rw`, `ro`, `none`), `confirm`, `clients` (`tv`, `extension`, `web`), `since`, `phase`, `store`, `tv_pref`.
  A client sends its schema version and ignores keys it does not know; the server never sends a key with a higher `since`.
- `GET /v1/device/settings?have=<version>&schema=<n>&wait_ms=<ms>` (a paired device's token; a browser session or config token gets `400`) ->
  `{"version":41,"schema_version":2,"settings":{"ai.summary_panel":{"v":true,"rev":39,"from":"user"}}}`, every key this client may see,
  resolved for this device (`from`: `device`, `user`, `default`). `have` is the version the TV has applied; the server records it.
  When `have` equals the current version the answer is `{"version":41,"unchanged":true}` (under 300 bytes). `Cache-Control: no-store`.
  **Long poll (schema 2):** with `have` and `wait_ms` (capped by `[settings_sync] long_poll_max_ms`, default 20000) an `unchanged` answer
  is held until the user's settings version differs from `have` or the wait ends; a change answers at once with the full document, and
  the wait ends `unchanged` when nothing moved. Without `have`, or with `wait_ms` 0 or absent, nothing changes. A server older than this
  ignores `wait_ms` and answers at once; a client takes an `unchanged` that came back in under half the wait as "this server does not
  hold requests" and polls on a timer instead.
- `POST /v1/device/settings` `{"schema_version","app_version","applied_version","initial":false,
  "changes":[{"key","value","base_rev"}],"report":{...}}` -> the same document plus `"results":[{"key","outcome"}]` with `outcome`
  `applied`, `superseded`, `invalid` or `not_remote`. At most 200 changes and 64 KiB. A TV change lands as that TV's own value, never as
  the user's (the web page offers "Use for all my TVs"). `base_rev` is the `rev` the TV last saw: equal to the key's current `rev`
  -> applied; different -> `superseded`, the server's value stays (the arrival order decides, never a device clock) and the lost value
  stays in the history. **First sync** (`initial: true`, once per device): each change may carry `"user_set": true` (the value was
  chosen on the TV). For every key the server compares the TV's value with the value it would give; equal -> nothing stored;
  different and `user_set` -> the TV's value becomes this TV's own value (`via: migration`), so the TV keeps what it chose;
  different and not `user_set` (an untouched default) -> checked against `base_rev` like any change, so it never replaces a newer
  web value. A second `initial` is a normal sync, except after an app update that brought new keys (schema 2): the TV then sends
  `"initial": true` with `"from_schema": <the schema it had synced at>` and only the keys newer than that; those keys take its
  own `user_set` values as above (`via: migration`) and every older key stays a normal base-checked sync. `report` keeps at most 20 short scalar entries; a body over 64 KiB is `413`.
- The routes below this one (status, history, a TV's document and `PUT`) are for a browser session or config token: a paired TV's token gets `403`, so a TV cannot read or change its sibling TVs.
- **Schema 2** (per-TV settings): `updates.checks` (user value, a TV may override; `tv_pref` `update_checks`) and the keys of scope
  `device`: `ai.auto_scroll_speed`, `ai.cut_jump`, `updates.interval_minutes`, `updates.development_mode`, `browse.refresh_minutes`.
  They have `since: 2`, so a client that sends `schema=1` never receives them and the web page shows "update the app" for that TV. A key of
  scope `device` has no user-level value: it is not in `GET /v1/me/settings` `values` and a `PUT` of it there is `400`; it is set per TV
  (`PUT /v1/me/devices/{id}/settings`, `400` for a key the TV's reported schema is too old for). The numeric choices (scroll speed,
  update interval, browse refresh) are `enum` keys with number values, the exact set the app accepts; `ai.cut_jump` values are
  `left_right`, `up_down`, `off`.
- **Secrets** (checkpoint 6; the schema's `secret` keys `secrets.films_rd_token` and `secrets.films_addon_url`, `deliver: tv`). Stored in
  `user_secrets`, AES-256-GCM, a fresh nonce per write, the user and the key name as associated data. The master key is 32 random bytes
  (base64) in the environment variable named by `[security] secrets_key_env` (default `UTUBOT_SECRETS_KEY`), never in the config file,
  the database or git. Without it every secret route answers `503 {"error":"secret storage is not set up on this server"}` and nothing
  is stored.
  `GET /v1/me/secrets` (browser) -> `{"available":bool,"secrets":[{"key":"films_rd_token","set":true,"last4":"4f2a","updated_at",
  "delivered_to":[{"id","device","at"}]}]}` (`last4` is the last 4 characters of a token, only the host of an address);
  `PUT /v1/me/secrets/{name}` `{"value"}` (`400` for a bad value: a token is one word of 8 to 1000 characters, an address is https, or
  http for a private host) and `DELETE` answer for a browser; a device token gets `403`. No route returns a value to a browser.
  `GET /v1/device/secrets?have=<rev>` (a paired TV only; `no-store`) -> `{"rev","secrets":{name:value},"set":[name]}`, or
  `{"rev","unchanged":true,"set":[...]}` when `have` is the current revision; it records that this TV was given them. The settings
  answer carries `"secrets_rev"` (0 without any), and a TV asks only when it changed. `PUT /v1/device/secrets/{name}` `{"value"}` lets a
  TV keep its own value on the server (decision D2: only after its owner agreed on the TV); `409` when the server has one (the server
  wins). A removal on the web removes the value on the next fetch. The audit and the History keep only the words `set` and `cleared`.
  `utubot user secret set <user> <name>` reads the value from stdin; `utubot secrets check` and `utubot secrets rotate
  --new-key-env VAR` print counts only. The per-user AI provider key (`PUT /v1/me/provider`) uses the same store (name
  `provider.api_key`, never delivered to a TV); at the first start with a master key every clear-text key moves in, the old column is
  blanked after the new row decrypts back to the same value, and the database file is rewritten (`VACUUM`) so no clear copy stays;
  `key_sha256` is unchanged. Without a master key the provider key stays in its column as before.
- The owner's Stremio auth key (`films_stremio_auth`, set by `POST /v1/films/stremio/login` from the Stremio login) uses the same store but
  is server-side only: it is not in the schema, is never delivered to a TV and never returned by the secret routes. The import runs on the
  server, so the key never leaves it; see [Stremio library import](#stremio-library-import-addendum-2026-11-28-issue-308).
- `GET /v1/me/settings/status` -> `{"version","now","devices":[{"id","device","last_used","syncs","applied_version","applied_at",
  "last_sync_at","schema_version","app_version","migrated","report","overrides":[key],"pending":[key]}]}`; `pending` is every key whose `rev`
  is above the TV's `applied_version` among the keys that TV's schema may see.
- `GET /v1/me/devices/{id}/settings` -> the device document with `device` (state). `PUT /v1/me/devices/{id}/settings`
  `{"version","settings":{key:value|null}}` sets or (`null`) removes a TV's own values; `version` is required (`428`, `409` as for the
  document).
- `GET /v1/me/settings/history?limit=50&key=&device=` -> `{"entries":[{"id","at","key","title","device_id","device","old","new","by","via",
  "actor","outcome"}]}`, newest first; `via` is `web`, `tv`, `admin` or `migration`; `outcome` is `applied` or `superseded`. Kept 180 days
  and 5,000 entries per user.
- `PUT /v1/me/settings` also takes the schema's dotted keys (`{"settings":{"ai.assess":false}}`, `null` resets) beside the old
  sections, and `GET` adds `values` (`{key:{"v","rev","from"}}` for every user-level key). `rev` is the settings `version` at which the
  key last changed; the version still rises by one on every change.
- Known value mismatch, decided: `ai.panel_delay_ms` (server `tv.summary_delay_ms`) now defaults to 1800 ms (the TV's value), range
  0-10000. `ai.mark_only` is one key backed by `filtering.mark_only`: today only the TV acts on it (hide or mark a card); the server
  never reads it when it answers, and `/setup.json` only carries the starting value.

### Models

- `GET /v1/models` -> `{"fetched_at":1700000000.0,"cache_ttl_s":300,"refreshed":false,"providers":[{"name":"local","default":true,
  "key":"configured|missing|not needed","ok":true,"error":null,"stale":false,"fetched_at":1700000000.0,"added":["qwen3:14b"],
  "models":[{"id":"qwen3:14b","value":"qwen3:14b","new":true}]}]}`. Each provider's `/models` is cached for 5 minutes. `value` is
  what a task takes (`provider:id` for a provider other than the default). `new` marks models that appeared since the previous list
  (for 3 days); `added` those found by the latest fetch. A provider that fails is `ok:false` with a short `error` (and `stale:true`
  while an older list is kept). Admins also get `base_url` (no credentials). API keys are never returned.
- `POST /v1/models/refresh` fetches again now (at most every 10 s; `refreshed:false` when it was too soon).

### Status and updates

- `GET /v1/status` -> `{"version","uptime_s","youtube":{"state":"closed|half_open|open","healthy":true,"cooldown_remaining_s":0,
  "background_waiting":0,"classes":{"captions|metadata|media":{"state":"closed|half_open|open","cooldown_remaining_s":0,"strikes":0}}},
  "asr":{"engines":[{"name","kind","model","enabled","healthy","unhealthy_for_s","languages","priority","max_parallel","background_only","word_times"}]},"usage":{"day":"2026-11-12","llm":{"calls","errors","prompt_tokens","completion_tokens"},
  "transcripts":{"youtube_captions","asr"},"analyses":{"used","cap"}},"jobs":{"waiting","processing","failed"}}` (counts of the caller's jobs; usage
  is for the current UTC day). `youtube.state`, `healthy` and `cooldown_remaining_s` summarise the three endpoint classes (open if any is open, the longest
  cooldown); `classes` has each one, because a limit on one does not stop the others. Engine entries never carry URLs or keys.
- `GET /v1/updates` -> `{"channel":{"published":true,"version_name","version_code","changelog","files":{"arm64-v8a":{"file","size"}},
  "published_at"},"github":{"configured":true,"repo","checked_at","latest":{"tag","version","published_at","url"}|"error":"..."},
  "behind":true,"last_sync":{"checked_at","status","version_name","error"}|null,"update_url"}`. `last_sync` is the last real
  `utubot app sync-github` run. `POST /v1/updates/refresh` asks GitHub again (cached otherwise for 10 minutes).

- `GET /v1/changelog?kind=app|backend&limit=50` (any signed-in user; `kind` defaults to `backend`) -> `{"kind","current":"<backend version>"|null,
  "entries":[{"kind","version","at":<epoch s>,"commit":"<sha>"|"","changes":[{"group":"features|fixes|other","text","pr":<number>|null}]}]}`,
  newest first. `backend` entries are deploys: written at server start when the running commit differs from the last recorded
  one (never twice for a restart), `changes` are the merged first-parent commit subjects between the two commits in plain words
  (`type/scope: summary (#n)` becomes "Scope: summary" under New or Fixed; docs, test, chore, ci and refactor commits are left out). `app` entries are
  the app releases the release sync saw: `version` is the app version name, `at` its GitHub release time, `changes` the lines of
  its `release.json` changelog (older releases: the bullets of the release body), all in group `other`.
  The TV shows both lists as text under Settings, Updates, What's new (no QR code); the web UI shows them under Updates.

### Crash reports and player logs (addendum, 2026-11-28, issue 301)

- `POST /v1/device/reports` (paired TV token only; a config token or browser session is refused with 400), body gzip (`Content-Encoding:
  gzip`) or plain JSON, at most `[reports] max_report_bytes` (default 2 MiB, also once unpacked, 413 past it) -> `{"id":"<n>"}`.
- The report is a JSON object: `{"schema":1,"app":{"version","code","flavor"},"device":{"model","sdk"},"failures":[...],"events":["MM-dd
  HH:mm:ss.SSS name detail",...]}`. `failures` are the TV's player failure records (kinds `crash`, `anr`, `*_error`, `stall`...; a crash holds
  its stack, the screen and the last 60 events) and `events` the player event log (open stream, format, decoder, state, seek, track changes,
  errors, Back, activity lifecycle). The TV redacts before it sends: URL queries and user info, opaque path segments (Real-Debrid tokens
  sit in an add-on address), values after token/key/secret/password/authorization, bearer and device tokens, the token and add-on
  address the TV holds, IP and email addresses. The server stores the report as it came and never logs its content.
- Stored in `device_reports` per user and device (name, app version, crash, ANR and error counts), kept `[reports] keep_days` (30) and at
  most `max_bytes_per_user` (50 MiB, oldest first). CLI: `utubot reports list [--user U] [--limit N]`, `utubot reports show ID`.
- `GET /v1/status` also has `"reports":{"days":7,"reports","crashes","anrs"}` (the whole server for an admin, else the caller's own).
- The TV sends (`ReportUploader`) only while nothing plays: a minute after the app starts, 30 s after the player closes and every 6 hours,
  with a doubling wait (1 min up to 1 h) after a failure; what the server confirmed is deleted on the TV. Clients: TV only; the browser
  extension has no player to log (`ai/BROWSER_EXTENSION_PLAN.md`, parity matrix).

### Subtitle picker of a film (addendum, 2026-11-28, issue 300)

- `GET /v1/films/subtitles?source_key=imdb:tt..[:S1E2]&file_name=<stream file>&size=<bytes>&lang=<viewer language>` -> `{"subtitles":[{"id",
  "lang","name","score","hash_match","best"?}]}`: the add-on's subtitles in the viewer's language, then English, each best release match first
  (`best` marks the first); other languages are not listed. 400 for a bad key, 404 when none, 502 when the add-on fails. Signed-in users only.
- `GET /v1/films/subtitles/{id}.vtt?source_key=&file_name=&size=` -> the listed subtitle as WebVTT (`text/vtt`). The TV names it by the
  id of the list, never by an address; the server looks the id up in its own list of that stream and downloads it with the same guarded client
  as the film cuts. The add-on's lists and files are cached in memory for an hour (64 entries), shared with the cut builder.
- The TV (`UtubotFilmSubtitlesController`) side-loads the file as a text track merged with the stream, applies the viewer's delay by shifting
  the cues of its copy, and keeps the choice and the delay per title on the TV. Clients: TV only (no film player in the browser extension).

### Stremio library import (addendum, 2026-11-28, issue 308)

The owner's Stremio watch state is copied into the per-user films store (the **My list** and **Continue watching** rows the TV reads). Import
only; a two-way sync is a later investigation. The owner signs in once on the web; the server keeps only the Stremio auth key (encrypted in the
secret store as `films_stremio_auth`, server-side only, never delivered to a TV and never the password).

- `POST /v1/films/stremio/login` `{"email","password"}` (signed-in users only) -> `{"ok":true}`. Logs in to Stremio (`POST https://stremio.com/api/auth`,
  `{"event":"login","payload":{"email","password"}}`), keeps the returned `auth` key, forgets the password. `400` for a bad email/password or a Stremio
  auth failure (`{"error": message}`), `502` when Stremio answers in an unreadable shape.
- `POST /v1/films/stremio/import` (signed-in users only) -> `{"watchlist","resume","watched","unmapped","items":[{id,type,title_id,name,poster,season,episode,position_ms,watched,last_watched}]}`. Reads the library with the stored key (`GET https://lib.stremio.com/api/datastoreGet`, `payload` = base64 of
  `{"op":"read","key":"libraryItem"}`), maps it, and writes the films store. `400 {"error":"connect your Stremio account first"}` when no key is stored,
  `502` on a Stremio error. A movie maps to one film entry (id = IMDb id, `timeOffset` seconds as `position_ms`, not watched); a series episode maps to an
  entry (id = `imdb:season:episode`, watched when the fraction is ≥ `WATCHED_SHARE` (0.9) or in `watchedAnyway`), and the series also gets a resume entry
  (id = the IMDb id, `position_ms` from its `timeOffset`). A key that is not an IMDb movie or episode is counted in `unmapped`.
- `GET /v1/films/stremio/status` (signed-in users only) -> `{"set":true|false}`: whether the account is connected.
- Clients: TV + web UI + backend. The browser extension shows no films section (a watchlist is IMDb titles, not a YouTube video), so it has no row; see
  the parity matrix in `ai/STREMIO_PLAN.md` and the contract's "Clients" section.

### Devices, prompts, videos

- Voice control additions to the web UI: see [Voice control](#voice-control-addendum-2026-11-26).
- `GET /v1/me/devices` -> `{"devices":[{"id","user","device","created_at","last_used"}]}`, `DELETE /v1/me/devices/{id}` (own devices
  only), `POST /v1/me/pair` -> `{"user","code","expires_in_s"}` (a one-time pairing code for the caller).
- `GET /v1/me/provider` -> the caller's own upstream as `{"host","key_sha256"}` (a short key fingerprint, never the key) or
  `{"configured": false}`; `PUT /v1/me/provider` `{"base_url","api_key"}` stores it and returns that plus `"configured": true`
  (`400` for a base url without a scheme or an empty key); `DELETE /v1/me/provider` clears it (`404` when none) and returns the
  server default for the caller's next calls. The key is stored on the server, never returned.
- `POST /v1/prompts/validate` with a prompt set -> `{"ok":true,"id","name","prompts":2}` or `400` with the validator's messages.
- `POST /v1/videos/resolve` `{"text":"https://youtu.be/..."}` -> `{"video_id":"..."}` (an id, or a watch, shorts, live, embed or
  youtu.be link; `400` otherwise; nothing is fetched).

### User administration (admin only)

`GET /v1/users` -> `{"users":[{"name","admin","prime","class","has_password","has_token","devices","sessions","admin_editable","usage","provider"}]}`;
`POST /v1/users` `{"name","admin":false,"prime":false,"password":null}` (a user without a token; `409` if it exists, `400` for a bad name or a short
password); `PUT /v1/users/{name}` `{"admin":true,"prime":true}` (either field optional; `409` for a user declared in `config.toml` or for your own `admin` flag);
`PUT /v1/users/{name}/password` `{"password"}`; `GET/PUT /v1/users/{name}/settings` as above. The older `GET /v1/admin/users`,
`POST /v1/admin/pair`, `DELETE /v1/admin/devices/{id}` and `PUT /v1/admin/users/{name}/policy` stay. Each user also carries `usage`
(`{"cost","calls","day"}`, the caller's own cost and calls for the UTC day) and `provider` (`{"host","key_sha256"}` or `{"configured": false}`);
neither carries a key.

### Media archive (admin only)

Every media file a pipeline downloads from YouTube is kept once, content-addressed by its sha256 under `[archive] path`
(empty: `<data dir>/archive`), with one `media_archive` row per video: `video_id`, `sha256`, `kind` (`audio`, later `video`),
`format_id`, `codec`, `bitrate_kbps`, `language`, `original`, `size`, `ext`, `path` (relative), `fetched_at`, `job_id`. Pipelines
read from the archive first and download only when the media is missing, so a video is never fetched twice.

- `GET /v1/admin/archive?video_id=&limit=` -> `{"files","usage_bytes","quota_bytes","state":"ok|warn|full","entries":[...rows...]}`.
- `DELETE /v1/admin/archive/{video_id}` -> `{"ok":true,"removed","bytes_freed","stage_cache_rows_removed"}`; `404` when nothing is stored for it.
  Without eviction this is the only cleanup: nothing in the archive is deleted automatically. At `quota_bytes` (0: no limit) new
  downloads are refused (the job fails with "The media archive is full...") until an admin removes entries; at `warn_frac` (0.9) a
  warning is logged.
- `[archive] eviction` (`never`, the default, or `lru`) and `evict_protect_s` (default `3600`): with `lru` a download that would start
  at or past `quota_bytes` first frees the least recently used entries (a lookup hit stamps the row's use; an entry never read counts
  from its `fetched_at`) until the usage fits; a stored file that leaves the archive over the quota frees what it can, never itself.
  Entries used within `evict_protect_s` and the file just stored are never evicted; when that is not enough the download is refused as
  without eviction.
- `GET /v1/admin/videos/{video_id}/artifacts` -> `{"video_id","artifacts":[{"kind","rows","bytes","newest_at"}],"total_bytes"}`
  (per kind: `metadata`, `transcript`, `captions`, `triage`, `analysis`, `summary`, `condensed`, `insight`, `pipeline`, `verdict`,
  `archive`).
- `DELETE /v1/admin/videos/{video_id}/artifacts?kind=summary&kind=...` -> `{"ok":true,"removed":{kind:rows}}` (`400` for an unknown
  kind). With no `kind` it removes every kind but the media archive; `kind=archive` removes the archived media, as the archive delete
  above.
- `GET /v1/admin/status` also carries `"archive":{"files","usage_bytes","quota_bytes","state"}`.

### Feature models (admin only)

Each feature a pipeline runs through (`FEATURE_KEYS`: `glance`, `summary`, `answer`, `triage`, `analysis`, `captions`,
`cuts`, `cuts_vision`; a feature with no `[llm.<task>]` table — `cuts`, `cuts_vision` — is listed once configured) runs on a
modelgate alias. A call resolves the model as an explicit one (a per-user `models` entry or a prompt's `model`) first, else the
admin's per-feature override, else the `[llm.<task>]` default in `config.toml`; the override only replaces the default, so a call
that names a model is routed exactly as before. The choice is server-wide, stored in a `feature_models` row and effective on the
next call (no restart); it is logged in `feature_audit`. Cost is not billed by this server — modelgate reports a real per-alias cost
(EVR-560, modelgate#18/#20) and, without that gateway, cost is estimated from the call's tokens and an optional per-alias price
(`[usage] price_usd_per_million`, dollars per 1M prompt+completion tokens; an alias with no price reports an unknown cost, never a
guessed one). Every model call records its feature, alias, wall time and tokens in `feature_calls`.

- `GET /v1/admin/features` -> `{"features":[...], "aliases":[...], "window_days":7}`. `aliases` is the list the switch is
  validated against: the live model values `GET /v1/models` shows plus every alias this server already knows from its config
  (each feature's model and fallback, and the speech alias), so a choice is offered even before the catalog is fetched.
- Each feature row is `{"feature","alias","fallback":[...],"overridden":bool,"changes":[{"from","to","by","at"}],"usage":{...}}`:
  the alias in force (override or default), its configured fallback, whether an admin override is set, the last 20 audit rows
  (`from`/`to` may be null on a reset), and the `usage` for the alias in force over the last `window_days`
  (`{"calls","prompt_tokens","completion_tokens","tokens","cost","median_ms","p90_ms","samples"}`; both time values null with no
  sample, `cost` null without a price).
- `PUT /v1/admin/features/{feature}` `{"alias"}` -> the feature row; `400` for an unknown `feature`, an empty alias, or an alias
  not in the `aliases` list (refused, nothing applied).
- `DELETE /v1/admin/features/{feature}` -> the feature row with `alias` back on the config default and `overridden` false; `404`
  when there is no override to reset, `400` for an unknown `feature`.

Per-feature runs also carry their cost and wall time on the result: the insight, summary, ask and cut answers gain `cost_usd`
(rounded to 5 dp) and `elapsed_s`. The schema is additive — `feature_models(feature PK, alias, changed_at, changed_by)`,
`feature_calls(id PK AUTOINCREMENT, feature, alias, ts, elapsed_ms, prompt_tokens, completion_tokens, cost)` with a
`feature_calls_feature` index, and `feature_audit(id PK AUTOINCREMENT, feature, from_alias, to_alias, changed_by, at)` (both alias
columns nullable: a fresh override has no `from`, a reset has no `to`).

Every response carries `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
`Referrer-Policy: no-referrer`; `/v1/*` answers are `Cache-Control: no-store`.
