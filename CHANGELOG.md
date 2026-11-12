# Changelog

Versions are `<major>.<minor>.<patch>`: `major.minor` is `utubot.version`, the patch counts the releases of that series
(`docs/development.md`). Every app change merged to `main` is released automatically. Release APKs are signed with the u·tubot
release key; the certificate SHA-256 is in each release's notes on GitHub. User-facing notes of the next release go under
`## Unreleased`; a release publishes the lines its predecessor did not carry.

## Unreleased

- App releases are numbered and published automatically (0.3.x onwards).
- Fixed: the Modern skin could show an empty screen (no grid, the sidebar and the top bar only) after the app started or a section
  loaded. The checks of the rows ran on a background thread, so the rows were put on the screen from there, which collided with the
  layout of the grid and left it empty or invisible. The rows now come out on the main thread, as the other checks do.
- Summary panel, rebuilt as a preview. It no longer takes the focus, dims anything or covers the top bar: it is a small card in the
  right strip below the top bar, and it hides when the focus leaves the cards (sidebar, another section, an empty or loading
  list), a card goes away or the player opens. Its header names the prompt and says "Long-press OK or press Info for summary
  options".
- The panel waits for the card to keep the focus (Settings, u·tubot, Summary delay: 1, 1.8, 3 or 5 seconds, 1.8 by default) and starts
  again whenever the focus moves or a key is pressed, so nothing is asked for while you scroll. It shows the title and "Waiting…",
  then a small working indicator; a result for a card you already left is dropped. The first Back hides the panel and keeps the
  focus on the card; the next Back is the app's (the sidebar). The panel mode stays on.
- The panel asks for the short glance summary (`prompt=panel`; a server that doesn't know it gets the first prompt of its list) and shows
  about three lines; a first line that starts with "→ " is the answer to the title's question and is shown in bold.
- Summary view: Info on a card (or "u·tubot summary" in the video menu) opens a focused view with the prompts on the left and the
  summary on the right. Up and Down move through the prompts (the summary follows after a short rest), OK keeps a prompt for the
  session, Right enters the text, Up and Down scroll it by pages, Left goes back, Back closes the view and the focus returns to
  the same card. The title, the source, the indicator and Retry are on top. The AI answer dialog scrolls and has the indicator and Retry too.
- A small animated indicator and a badge at the top right of every screen but the player show while u·tubot is working.
- Videos without captions: the panel says "No captions — press Info to transcribe"; the Summary view offers "Transcribe in
  background (~N min)", which starts the job on the server and shows "Transcribing… N%" until the summary is ready. When YouTube slows
  the server down the message is shown and the request is repeated after the time the server gives, while the card or view is still
  shown. These states are never kept in the app.
- Automatic updates: the app checks for a new version shortly after it starts and then at most every 6 hours, with Electric Eel's
  update dialog and installer (Settings, Updates, Notify about updates turns it off). A backend typed in Advanced on 0.2.0, which
  never stored an update address, now uses `<backend>/app/update.json` for both the automatic and the manual "Check for updates".
- Backend: `utubot app sync-github` publishes the newest GitHub Release into the update channel after checking each APK's SHA-256
  and signing certificate, so a server follows new app releases on its own.

Backend (`ai-backend/`) changes in this release:

- New phone-first web UI at `/` to steer u·tubot from a phone instead of the TV remote: Home (version, health, the YouTube gate with its
  cooldown, today's model and transcript counters), Models (a model per task from the live provider list, new models marked), Prompts
  (defaults, import, JSON editor with validation messages, try a prompt on a video link), Filters (topic chips, threshold sliders,
  mark-only), Captions (automatic-transcription policy, jobs with cancel and retry, transcribe from a link), TVs (link a TV with a big
  one-time code, revoke, TV settings), Updates (channel, newest GitHub release, last sync) and Admin (users, passwords, per-user settings).
  Plain HTML/CSS/JS, no build step; a strict Content-Security-Policy, no inline script, no markup built from text.
- Web sign-in with a username and password (`utubot user passwd NAME`, scrypt N=2^17, older hashes upgraded at sign-in) next to the old token sign-in. Browsers get an HttpOnly
  `SameSite=Lax` session cookie (30 days, sliding, `Secure` behind HTTPS), writes need a CSRF header, failed sign-ins lock out per
  address, account and server. Bearer tokens and TV device tokens work as before. Behind two proxies in a row, `[security] client_ip_header`
  with a shared secret names the real client so the per-IP limits do not collapse into one bucket.
- Per-user settings document: `GET/PUT /v1/me/settings` (admins: `/v1/users/{name}/settings`), versioned, with models per task, prompt
  defaults, hide/mark policy, `auto_long`, transcript policy (`auto_transcribe` off, on_dwell or on_open, default on_open;
  `auto_transcribe_max_minutes`, default 30) and the TV settings (summary delay, panel default, auto captions, update checks) the TV will
  read in a later release. Defaults come from `[default_policy]`, `[users.policy]`, `[summary]` and `[setup.defaults]`; a user's own
  choices override them (`docs/server.md`, Per-user settings). A per-task model now really applies to summaries, answers, insights,
  triage and deep analysis.
- `GET /v1/models` lists every configured provider's models (cached 5 minutes, refresh button, newcomers marked new; keys never
  returned); `GET /v1/status`, `GET /v1/updates`, `POST /v1/jobs/{id}/cancel|retry` (jobs gain the state `cancelled`),
  `POST /v1/videos/resolve`, `POST /v1/prompts/validate`, `/v1/me/devices`, `/v1/me/pair` and `/v1/users` for admins.

- YouTube rate limits (HTTP 429) after a burst of caption downloads no longer leave junk behind. Every request that reaches
  YouTube (metadata, caption text, audio) goes through one gate: one at a time, at least 3 s plus jitter apart, interactive before
  background (`[youtube] max_concurrent`, `min_interval_s`, `jitter_s`). A 429, 403 or bot check opens a circuit breaker that
  honours `Retry-After` or backs off from 5 to 60 minutes; background work pauses and resumes instead of failing.
- Summaries, insights and answers are never generated from the title alone any more (`source: "metadata_only"` is gone; rows made
  that way are deleted on first start). A transient YouTube problem answers `status: "pending"`, `transcript_status: "delayed"`,
  an `error` such as "YouTube is limiting transcript downloads; retrying in ~5 min" and `retry_after_s`, and is never cached.
  A video without captions answers `status: "needs_transcript"` (`transcript_status: "none"`, `can_transcribe`, `message`,
  `estimate_s`), remembered for 3 days (`[transcripts] no_captions_ttl_s`) but only from a complete YouTube answer. Problems of one
  video (private, members-only, age-gated, unavailable, a 403/410 on its caption or media URL, too long, live) answer
  `transcript_status: "failed"` with a `reason` and never trip the circuit breaker.
- New `POST /v1/videos/{id}/transcribe` queues a background transcription of the audio (stored as the transcript with source
  `asr`; idempotent), `GET /v1/videos/{id}/transcript` shows its progress, and `GET /v1/jobs` lists your caption and transcript
  jobs (`waiting|processing|ready|failed`; jobs retry at most 3 times). The TV app offers "Transcribe in background?" for
  `needs_transcript`. Audio downloads hold the YouTube gate only until they start; ASR never replaces YouTube captions.
- Fewer YouTube fetches: tier-2 analysis defaults to 30 per user per day (was 40, example config 100), runs only for videos with a
  title question or a clickbait score above the threshold, and only while YouTube is healthy; `[transcripts] max_concurrency` is
  replaced by `[youtube] max_concurrent`.
- New built-in prompt `builtin/glance` for the side panel: at most about 280 characters in 3 short lines. When the title poses
  a question or teases a reveal ("you won't believe", "the truth about", "why ...") the first line is `→ ` plus the answer from
  the transcript. It uses a 160 token budget with reasoning off, on the optional `[llm.glance]` model (falls back to
  `[llm.summary]`).
- `GET /v1/prompts` returns `panel_default` (default `builtin/glance`, config `[summary] panel_prompt`) next to `default`
  (still `builtin/tldr`). Change it with `PUT /v1/prompts/panel-default` or in the web UI. `GET /v1/videos/{id}/summary?prompt=panel`
  uses it. The app's panel asks for it (`prompt=panel`); the Summary view uses `default`.
- `[summary] auto_long = false`: when true (or the policy field `auto_long`), a panel summary also queues the user's default
  long summary in the background (at most `auto_long_max_concurrent = 2` at a time). Opening the long summary yourself takes over
  from the background job, and a background failure never fails your request.
- `builtin/answer-title` answers the title's question or curiosity gap first; the transcript condense step keeps the passage that
  answers it. Prompts accept an optional `task` (`summary` or `glance`); existing prompt-set files are unchanged.

## 0.2.2 (2026-11-12)

Security fixes for backend addresses and tokens. Updates 0.2.1 in place.

- A backend address typed in Advanced follows the same rules as an imported one (https, or http for local network addresses) and
  is refused with a message otherwise. The update address is derived from the validated address: its origin and path plus
  `/app/update.json`, without query or fragment.
- Changing the backend host in Advanced drops the stored token, so it is never sent to another host; pair again afterwards.
- The import log no longer records the query string of the address.
- Importing the same setup again on a paired device keeps the pairing and doesn't open the pairing dialog; it opens only when
  there is no token or the backend changed.

## 0.2.1 (2026-11-12)

Fixes for Import setup and pairing. Updates 0.2.0 in place.

- Import setup now works: the fetch failed on every server with an empty "null" error (the setup file was read with a byte
  count longer than the file), so nothing was imported and nothing was shown.
- Settings, u·tubot lists Import setup and Pair with code first, then the switches, Prompts, Test connection and Advanced.
- The address and pairing code fields submit on OK and on the keyboard's Go, Done, Next, Send or Search key; Back hides the
  keyboard without closing the dialog; an empty value shows a message.
- Import shows "Fetching the setup…", then the server name or the reason it failed (address not found, TLS, timeout,
  connection refused, HTTP status, not a setup file). Each step is logged with the tag `Utubot` (no tokens or codes).
- After an import the pairing dialog opens; once paired the app tests the connection and shows "Paired as <user>".
- The first-launch prompt (Import setup, Not now, Don't ask again) comes back on every launch until the app is set up,
  unless you pick Don't ask again.
- A backend address typed in Advanced also sets the update address (`<backend>/app/update.json`) when none is stored.

## 0.2.0 (2026-11-12)

First signed release.

- **Uninstall 0.1.0 first.** 0.1.0 was a debug build signed with a different (debug) key, so Android refuses to update it
  with 0.2.0. Uninstall it once, install 0.2.0; later releases update in place.
- Import setup: Settings, u·tubot, Import setup. Type your server's address (for example `utubot.example.com`); the app
  fetches the setup from the server, then opens the 6-digit pairing dialog. The first launch offers it.
- The app no longer ships with any backend address. Without an imported setup there are no AI features and no update checks.
- Updates come from the update URL in the imported setup. One APK per architecture: arm64-v8a, armeabi-v7a, x86 and universal.
- Backend: `/setup.json`, `utubot app publish` with several APKs, stable `/app/latest/<abi>.apk` links, a public download page.

## 0.1.0

Debug build, not published.
