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
{"video_id":"...","status":"ready|pending|failed","error":null,
 "title_question":"...","answer":"2–3 sentences","answer_confidence":0.0-1.0,
 "summary":"markdown-ish plain text, ≤ 1200 chars",
 "key_points":["...","..."],
 "inflation":{"duration_s":754,"essential_s":120,"ratio":0.16},
 "source":"youtube_captions|asr|metadata_only"}
```

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
{"video_id":"...","prompt":"my-prompts/tldr","status":"ready|pending|failed",
 "text":"...","source":"youtube_captions|asr|metadata_only","error":null}
```

`POST /v1/videos/{id}/summary` with `{"prompt_text":"...", "system":"..."}`
runs an ad-hoc prompt (not cached long-term) — for quick iteration.

### `POST /v1/videos/{id}/ask`
`{"question":"..."}` → `{"answer":"...","status":"ready|pending"}`

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
  item). While on, focusing a card for ~700 ms opens/updates a side overlay
  panel (right side, ~35% width, browse stays usable) with the summary for
  that video, a prompt select box (the panel default preselected; D-pad
  reachable) and a status line. The panel requests `prompt=panel` (or the
  `panel_default` key from `GET /v1/prompts`), not `default`. Changing the
  prompt reloads the panel. Back closes the panel
  focus, toggle turns the mode off.
- Context menu: "AI answer" (shows `answer_short` in the item label when
  known), "Summary panel on/off", "Prepare HQ captions".
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
