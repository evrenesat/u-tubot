# Privacy

u·tubot has three parties: the TV app, your backend, and the services the backend calls. There is no u·tubot cloud: nothing is sent
to the authors.

## What leaves the TV

To **your backend** only, over the address in the imported setup:

- For each row shown: video id, title, channel, duration, publish text, view text, short/live flags and a short description snippet
  (`POST /v1/assess`). Section name (home, search, ...).
- When you open or focus a video with the panel on, or choose a menu item: the video id (and title, channel, duration), the prompt
  you picked, your question.
- Pairing: the 6-digit code and the device model name.
- The access token, in an `Authorization` header, only to the backend host.

The app does **not** send your YouTube account, cookies or watch history to the backend, and never talks to any LLM itself. If the
backend is unreachable, rows show unfiltered.

The app itself (Electric Eel / SmartTube) talks to YouTube as before and checks for updates at the address from your setup (and
fetches `setup.json` once when you import it). With no setup imported it contacts no u·tubot server.

## What the server stores

In `data_dir` (SQLite and `users.toml`):

- user names, SHA-256 hashes of tokens, pairing codes (hashed) and failed-pairing records (IP and time), device names and
  last-use times;
- per-video caches shared between users: title analysis, transcripts (text), deep analysis, captions (VTT);
- per-user: policy overrides, prompt sets, summaries, feedback you submitted, caption jobs;
- no audio after a caption or transcription job finishes (unless `keep_media = true`), no YouTube credentials;
- whether YouTube has captions for a video (3 days), and the state of the YouTube request gate (a cooldown end time).

Logs may contain client IPs, video ids and errors. Tokens are never logged. Client IPs are used in memory for rate limits.

## What goes to the LLM provider

Whatever provider you configure receives: titles, channel names and short descriptions (triage), transcripts and your prompt text
(summaries, analysis, answers), caption text (translation). Your topic lists are part of the triage request. Use a local model if this
matters; a cloud provider's own retention and training policy applies otherwise. API keys stay in the server's environment.

The ASR backend `openai` receives the audio of videos you prepare captions for or transcribe in the background; `faster_whisper` keeps it local. Diarization downloads
a model from Hugging Face with your token; audio stays local.

The server also fetches from YouTube (yt-dlp: metadata, captions, audio) from its own IP, and fetches prompt-set URLs you import
(guarded against private addresses).

## Public exposure

The landing page, `/setup.json`, `/v1/health`, `/v1/pair` and `/app/*` need no token; everything else does. Rate limits and a
pairing lockout apply. Keep the server current, use TLS, and revoke lost devices (`utubot user revoke`).
