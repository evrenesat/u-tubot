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
optional):

```json
{"video_id":"dQw4w9WgXcQ","title":"...","channel":"...","channel_id":"UC...",
 "duration_s":754,"published":"3 days ago","views":"1.2M views",
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
(default 30) are per-user settings. With `on_open` or `on_dwell` and a video of known length up to the maximum, the request itself queues
the transcription (no user prompt) and answers `status: "pending"`, `transcript_status: "transcribing"`, `progress`, `estimate_s`
instead of `needs_transcript`; asking again returns the progress, then the real answer. The side panel's request (`summary?prompt=panel`)
is passive: it starts a transcription only for `on_dwell`; the Summary view, `insight`, `ask` and ad-hoc summaries are explicit and start
one for `on_open` as well as `on_dwell`. Everything else keeps `needs_transcript` (policy `off`, a longer or unknown-length video, a full
per-user queue, no engine for the language) and the app shows the question as before. Explicit requests run the job at interactive
priority (claimed first, interactive engine use); a side-panel job is background work and is promoted when the user then opens the video.

## Endpoints

### `GET /v1/health` (no auth)
`{"ok":true,"version":"0.1.0"}`

### `GET /v1/me`
`{"user":"owner","policy":{...},"settings_version":3,"features":{"assess":true,"insight":true,"captions":true}}`
`settings_version` is the version of the [settings document](#per-user-settings), a cheap way to notice a change.

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
Queue a background transcription of the audio for a video without captions (the answer to "Transcribe in
background?"). Optional query fields `title`, `channel`, `duration_s` as for `insight`. The backend downloads the
audio (paced with every other YouTube request), runs its speech recognition and stores the text as the video's
transcript with source `asr`. Idempotent: asking again while the user's job is queued or running returns that job.
Nothing is queued when a transcript already exists.

```json
{"video_id":"...","job_id":"a1b2c3d4e5f6","status":"queued|running|ready",
 "transcript_status":"transcribing|ok","progress":0.0,"estimate_s":630}
```
The job is interactive (the user asked), whatever the automatic-transcription policy says. `estimate_s` is the audio download plus the
chosen speech engine's chunked recognition time.
`400` when the video cannot be transcribed (live, or longer than the configured maximum), `429` when the user
already has the maximum number of active transcriptions (`[captions] transcribe_max_active_per_user`, 5).

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
 "progress":1.0,"error":null,"priority":"interactive|background","attempts":0,
 "created_at":1700000000.0,"updated_at":1700000050.0,"finished_at":1700000050.0,"retry_after_s":null,
 "detail_url":"/#/jobs/a1b2c3d4e5f6","api_url":"/v1/jobs/a1b2c3d4e5f6",
 "can_cancel":false,"can_retry":false,
 "inputs":{"video_id":"...","title":"...","channel":"...","duration_s":1740,"language":"tr","lang":"auto","translate_to":null,
           "requested":{"user":"owner","client":"Living room TV","endpoint":"POST /v1/videos/{video_id}/captions",
                        "trigger":{"kind":"explicit"},"priority":"background","at":1700000000.0}},
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
`can_retry` are true only for the job's owner. `trigger` is `{"kind":"explicit"}` or `{"kind":"auto","mode":"on_open|on_dwell",
"passive":false,"max_minutes":30}`; `client` is the name a TV was linked under, `Web UI` or `API token`.

`events` is the log in order of writing. `status` is `running`, `ok`, `warn`, `skipped`, `failed`, `info`, `cancelled` or `interrupted`;
a `running` event is followed by the `ok`/`failed`/`skipped` event of the same stage, which carries `seconds`. Stages: `queued`, `promoted`,
`started`, `gate_wait`, `caption_recheck`, `audio_download` (`format_id`, `track` = `original|dubbed|descriptive|unmarked`, `original`,
`language`, `bytes`, `duration_s`, `source` = `downloaded|from_archive`), `media_archive` (`bytes`, `sha256` prefix; skipped when the audio
came from the archive), `ffmpeg`, `separation` (skipped when off, the tool failed, or the ASR answer was cached), `chunking`, `asr`, `asr_chunk`, `asr_fallback`, `stitching`,
`diarization` (`reason` and `message` when skipped; only when diarization is configured), `cues`, `align` (`mode` = `silence|merge`; boundaries move outward only),
`proofread` (`corrected`, `warned`, `chars_in`/`chars_out`, `cached`; skipped with `reason` = `off|no_llm`), `proofread_batch` (a batch that
kept its original text — length mismatch, empty text, growth or shrink beyond `proofread_max_ratio`), `text`, `translate`, `stored`, `retry`, `finished`, `failed` (`error_class`,
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
Queue high-quality captions. Body: `{"lang":"auto","translate_to":null}`. An unset `translate_to`
follows `[captions] translate_to` (default `"en"`): captions come out in English whatever the
source language; `"off"` keeps the source language instead.
→ `{"status":"queued|running|ready|failed","job_id":"...","eta_s":null}`

### `GET /v1/videos/{id}/captions`
```json
{"status":"none|queued|running|ready|failed","progress":0.0-1.0,
 "tracks":[{"lang":"en","label":"English (u·tubot, 2 speakers)",
            "url":"/v1/videos/{id}/captions/en.vtt","speakers":2}]}
```

### `GET /v1/videos/{id}/captions/{lang}.vtt`
`text/vtt`. Speaker turns are prefixed `[S1] `, `[S2] ` when diarized.
Auth via header, or `?token=` for players that cannot set headers.

### `POST /v1/feedback`
`{"video_id":"...","kind":"clickbait|...","correct":false,"note":null}` → `{"ok":true}`.
Stored for later threshold tuning.

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
  `can_transcribe`, and no Retry when `reason` is present. None of these answers is kept by the app. The AI answer shows
  the same states for an insight, counts a delay down and follows a running transcription like the view does (the transcription the user
  starts is started from the Summary view of the video). `message` is shown as the server wrote it in the panel, the view and the answer;
  the app's own wording is only the fallback. Every `insight`, `summary` and `transcribe` call carries `title`, `channel` and `duration_s`.
- Settings → u·tubot → Prompts: list sets, "Import from URL", "Refresh all",
  choose default.
- Player: when `captions_ready`, offer the u·tubot track(s) in the subtitle
  picker ("u·tubot: <label>"); optionally auto-select. The app asks `GET /v1/videos/{id}/captions` when a video starts and, while the
  answer is `queued` or `running`, every 10 s while the video plays; ready captions are added to the playing video, selected and
  announced. It downloads each ready track once (`GET .../captions/{lang}.vtt`, `Authorization` header) into its own storage and keeps
  it for good: the backend is not asked again for a video whose captions are stored, and a track never changes once stored.
- Settings: Import setup (first item), enable switches, mark-only switch, pairing, test button.
  Backend URL and token are under Advanced. Private builds can bake defaults
  (`-PutubotUrl=… -PutubotToken=…`); public builds ship with none.

## Addendum (backend implementation, 2026-11-12)

- Public endpoints (no token): `GET /setup.json`, `GET /v1/health`, `POST /v1/pair`,
  `GET /app/update.json`, `GET /app/info.json`, `GET /app/<file>.apk`, `GET /app/latest/<abi>.apk`, and for the web UI `GET /`, `GET /ui/*`
  (static files, no data), `POST /v1/auth/login`, `POST /v1/auth/logout`. Everything else needs a bearer token or a session cookie. Rate limits return `429
  {"error":"rate limited"}` with `Retry-After`. Bodies over 256 KiB return 413.
- Video ids must match `^[A-Za-z0-9_-]{11}$`, else `400`.
- `POST /v1/pair` `{"code":"123456","device":"Living room TV"}` -> `{"token":"utb_...","user":"owner"}`.
  Codes are single use, valid 15 minutes, created by `utubot user pair NAME` or the admin UI.
  Wrong codes: `403`; lockout after repeated failures: `429`. Each device gets its own token.
- `GET /v1/me` `features` also lists `"transcribe": true` (the endpoints above exist).
- `GET /v1/me` also returns `"admin": bool`. `PUT /v1/me/policy` patches the caller's policy.
- Admin only (user with `admin = true`, else `403 {"error":"forbidden"}`):
  `POST /v1/admin/pair {"user"}` -> `{"code","expires_in_s"}`, `GET /v1/admin/users`,
  `DELETE /v1/admin/devices/{id}`, `PUT /v1/admin/users/{name}/policy`.
- `GET /v1/me` policy also carries `auto_long` (`null` = follow the config).
- Extra read endpoints: `GET /v1/prompts/sets/{set_id}` (raw set JSON), `GET /v1/captions/jobs`.
- A prompt's `model` is an alias or `provider:model` naming a configured provider.
- Prompt-set format key stays `tubeai_prompt_set` for compatibility.
- `GET /app/update.json` serves the file published by `utubot app publish` (Electric Eel format).
  Per-architecture keys `downloadUrlList_<abi>` (`arm64-v8a`, `armeabi-v7a`, `x86`, `x86_64`, `universal`)
  win over `downloadUrlList` for the device's primary ABI. `GET /app/latest/<abi>.apk` answers
  `302` to the versioned APK of the latest release. `GET /app/info.json` returns the latest version,
  per-ABI file names, sizes, sha256 and the configured Downloader codes, for the landing page.

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
   "transcripts":{"auto_transcribe":"on_open","auto_transcribe_max_minutes":30},
   "tv":{"summary_delay_ms":700,"summary_panel":false,"auto_captions":true,"update_checks":true}},
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
  "asr":{"engines":[{"name","kind","model","enabled","healthy","unhealthy_for_s","languages","priority","max_parallel","background_only"}]},"usage":{"day":"2026-11-12","llm":{"calls","errors","prompt_tokens","completion_tokens"},
  "transcripts":{"youtube_captions","asr"},"analyses":{"used","cap"}},"jobs":{"waiting","processing","failed"}}` (counts of the caller's jobs; usage
  is for the current UTC day). `youtube.state`, `healthy` and `cooldown_remaining_s` summarise the three endpoint classes (open if any is open, the longest
  cooldown); `classes` has each one, because a limit on one does not stop the others. Engine entries never carry URLs or keys.
- `GET /v1/updates` -> `{"channel":{"published":true,"version_name","version_code","changelog","files":{"arm64-v8a":{"file","size"}},
  "published_at"},"github":{"configured":true,"repo","checked_at","latest":{"tag","version","published_at","url"}|"error":"..."},
  "behind":true,"last_sync":{"checked_at","status","version_name","error"}|null,"update_url"}`. `last_sync` is the last real
  `utubot app sync-github` run. `POST /v1/updates/refresh` asks GitHub again (cached otherwise for 10 minutes).

### Devices, prompts, videos

- `GET /v1/me/devices` -> `{"devices":[{"id","user","device","created_at","last_used"}]}`, `DELETE /v1/me/devices/{id}` (own devices
  only), `POST /v1/me/pair` -> `{"user","code","expires_in_s"}` (a one-time pairing code for the caller).
- `POST /v1/prompts/validate` with a prompt set -> `{"ok":true,"id","name","prompts":2}` or `400` with the validator's messages.
- `POST /v1/videos/resolve` `{"text":"https://youtu.be/..."}` -> `{"video_id":"..."}` (an id, or a watch, shorts, live, embed or
  youtu.be link; `400` otherwise; nothing is fetched).

### User administration (admin only)

`GET /v1/users` -> `{"users":[{"name","admin","has_password","has_token","devices","sessions","admin_editable"}]}`;
`POST /v1/users` `{"name","admin":false,"password":null}` (a user without a token; `409` if it exists, `400` for a bad name or a short
password); `PUT /v1/users/{name}` `{"admin":true}` (`409` for a user declared in `config.toml` or for your own flag);
`PUT /v1/users/{name}/password` `{"password"}`; `GET/PUT /v1/users/{name}/settings` as above. The older `GET /v1/admin/users`,
`POST /v1/admin/pair`, `DELETE /v1/admin/devices/{id}` and `PUT /v1/admin/users/{name}/policy` stay.

### Media archive (admin only)

Every media file a pipeline downloads from YouTube is kept once, content-addressed by its sha256 under `[archive] path`
(empty: `<data dir>/archive`), with one `media_archive` row per video: `video_id`, `sha256`, `kind` (`audio`, later `video`),
`format_id`, `codec`, `bitrate_kbps`, `language`, `original`, `size`, `ext`, `path` (relative), `fetched_at`, `job_id`. Pipelines
read from the archive first and download only when the media is missing, so a video is never fetched twice.

- `GET /v1/admin/archive?video_id=&limit=` -> `{"files","usage_bytes","quota_bytes","state":"ok|warn|full","entries":[...rows...]}`.
- `DELETE /v1/admin/archive/{video_id}` -> `{"ok":true,"removed","bytes_freed","stage_cache_rows_removed"}`; `404` when nothing is stored for it. This is the
  only cleanup: nothing in the archive is ever deleted automatically. At `quota_bytes` (0: no limit) new downloads are refused
  (the job fails with "The media archive is full...") until an admin removes entries; at `warn_frac` (0.9) a warning is logged.
- `GET /v1/admin/status` also carries `"archive":{"files","usage_bytes","quota_bytes","state"}`.

Every response carries `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
`Referrer-Policy: no-referrer`; `/v1/*` answers are `Cache-Control: no-store`.
