# Changelog

Versions follow `versionName` in `smarttubetv/build.gradle` (flavor `stutubot`). Release APKs are signed with the u·tubot
release key; the certificate SHA-256 is in each release's notes on GitHub.

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
