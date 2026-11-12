# Changelog

Versions follow `versionName` in `smarttubetv/build.gradle` (flavor `stutubot`). Release APKs are signed with the u·tubot
release key; the certificate SHA-256 is in each release's notes on GitHub.

## Unreleased

Backend (`ai-backend/`) only; no app build changes yet.

- New built-in prompt `builtin/glance` for the side panel: at most about 280 characters in 3 short lines. When the title poses
  a question or teases a reveal ("you won't believe", "the truth about", "why ...") the first line is `→ ` plus the answer from
  the transcript. It uses a 160 token budget with reasoning off, on the optional `[llm.glance]` model (falls back to
  `[llm.summary]`).
- `GET /v1/prompts` returns `panel_default` (default `builtin/glance`, config `[summary] panel_prompt`) next to `default`
  (still `builtin/tldr`). Change it with `PUT /v1/prompts/panel-default` or in the web UI. `GET /v1/videos/{id}/summary?prompt=panel`
  uses it. The app keeps showing `default` in the panel until it adopts `panel_default`.
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
