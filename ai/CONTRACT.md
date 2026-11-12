# u·tubot wire contract v1

The TV app (`stutubot` flavor) talks only to the u·tubot backend. The backend owns
all model calls (any OpenAI-compatible endpoint), downloads, ASR and per-user policy. The app stays
thin: it sends metadata, receives verdicts, renders marks, hides, dialogs and
subtitle tracks.

Base URL example: `https://utubot.example.com` or a LAN URL such as `http://10.0.0.5:8790`.
All paths below are under `/v1`. JSON, UTF-8. Times are seconds.

## Auth

`Authorization: Bearer <user token>` on every call except `GET /v1/health`.
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
| `none` | `needs_transcript` | `can_transcribe`, `message` ("No captions. Transcribe the audio in the background?"), `estimate_s` (rough seconds, may be null) | shows `message`; when `can_transcribe` offers a "Transcribe in background?" action that calls `POST /v1/videos/{id}/transcribe` |
| `transcribing` | `pending` | `progress` 0.0-1.0, `estimate_s` | shows progress, asks again later |
| `failed` | `failed` | `error`, `reason`, `can_transcribe` | shows `error`; `reason` is `private`, `members_only`, `age_restricted`, `unavailable`, `forbidden`, `too_long`, `live` (video problems) or absent (a transcription job failed); offers the transcribe action again only when `can_transcribe` |
| `null` | any | none | the problem is not the transcript (model busy, generic failure) |

`delayed` means YouTube slowed the server down (HTTP 429, bot check, 403 on the watch request, network error, an incomplete answer or an open cooldown); it is never
cached, so the same request works once `retry_after_s` has passed. `none` is remembered by the backend for 3 days
(`[transcripts] no_captions_ttl_s`) and then checked again; `can_transcribe` is false for live streams and videos
longer than `[captions] max_duration_s`. The summary of a video whose transcription is queued or running answers `pending` with
`transcript_status: "transcribing"` until the transcript exists, then works normally with `source: "asr"`.

## Endpoints

### `GET /v1/health` (no auth)
`{"ok":true,"version":"0.1.0"}`

### `GET /v1/me`
`{"user":"owner","policy":{...},"features":{"assess":true,"insight":true,"captions":true}}`

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
`400` when the video cannot be transcribed (live, or longer than the configured maximum), `429` when the user
already has the maximum number of active transcriptions (`[captions] transcribe_max_active_per_user`, 5).

### `GET /v1/videos/{id}/transcript`
Where the transcript stands. Cheap: never contacts YouTube.

```json
{"video_id":"...","transcript_status":"ok|delayed|none|transcribing|failed|unknown",
 "source":"youtube_captions|asr","lang":"en",
 "progress":0.4,"estimate_s":630,"job_id":"...",
 "can_transcribe":true,"message":"...","error":null}
```
Only the fields that apply are present (`source`/`lang` with `ok`, `progress`/`estimate_s`/`job_id` with `transcribing`,
`can_transcribe`/`message`/`estimate_s` with `none`, `error`/`reason`/`can_transcribe` with `failed`,
`error`/`retry_after_s` with `delayed`). `job_id` appears only for the caller's own job, never another user's.
`unknown` (only here) means the backend has not looked yet.

### `GET /v1/jobs?limit=50`
The caller's background jobs of every kind, newest first (groundwork for a "check later" shelf). `limit` 1-200.

```json
{"jobs":[{"id":"a1b2c3d4e5f6","kind":"transcript|captions","video_id":"...","title":"...or null",
          "state":"waiting|processing|ready|failed","progress":0.0-1.0,"error":null,
          "created_at":1700000000.0,"finished_at":null,"retry_after_s":null}]}
```
`waiting` = queued (including while YouTube has the server in a cooldown; then `retry_after_s` says roughly how long),
`processing` = running. `error` is a short generic message for `failed`.

### `POST /v1/videos/{id}/captions`
Queue high-quality captions. Body: `{"lang":"auto","translate_to":null}`.
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
- Summary panel and Summary view: handle `transcript_status`. `delayed`: show the `error` text and retry after
  `retry_after_s` (1 s at least, 10 min at most) while the card or view is shown. `none` (`status: "needs_transcript"`): show
  `message` and, when `can_transcribe`, a "Transcribe in background?" action that calls `POST /v1/videos/{id}/transcribe`;
  afterwards the view follows `GET /v1/videos/{id}/transcript` (every 4 s; the passive panel every 20 s, no faster than it
  polled a `pending` summary, one long poll) until the transcript is `ok`, then asks for the summary again.
  `transcribing`: "Transcribing… N%" and the same follow-up. `failed`: show `error`; offer the action again only with
  `can_transcribe`, and no Retry when `reason` is present. None of these answers is kept by the app. The AI answer shows
  the same states for an insight (Retry; the transcription is started from the Summary view of the video).
- Settings → u·tubot → Prompts: list sets, "Import from URL", "Refresh all",
  choose default.
- Player: when `captions_ready`, offer the u·tubot track(s) in the subtitle
  picker; optionally auto-select.
- Settings: Import setup (first item), enable switches, mark-only switch, pairing, test button.
  Backend URL and token are under Advanced. Private builds can bake defaults
  (`-PutubotUrl=… -PutubotToken=…`); public builds ship with none.

## Addendum (backend implementation, 2026-11-12)

- Public endpoints (no token): `GET /setup.json`, `GET /v1/health`, `POST /v1/pair`,
  `GET /app/update.json`, `GET /app/info.json`, `GET /app/<file>.apk`, `GET /app/latest/<abi>.apk`. Everything else needs a bearer token. Rate limits return `429
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
