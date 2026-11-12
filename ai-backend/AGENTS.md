# ai-backend rules for agents

- Python 3.12, `uv` only. Run `uv run pytest -q`, `uv run ruff check`, `uv run ruff format --check`
  before committing. Scratch in `temp/` (gitignored).
- Contract lives in `../ai/CONTRACT.md`; change code and contract together.
- No magic numbers: tunables go in `src/utubot/config.py` and `config.example.toml`.
- Never log or commit secrets. Keys come from env vars named in config. Tokens are stored only as
  sha256 hashes. Tests use the mock server in `tests/mock_openai.py`; never call real LLMs there.
- Public service: every route except health, pair, `/app/*`, `/setup.json`, `/`, `/ui/*` and `/v1/auth/login|logout` must depend on
  `current_user` (or `admin_user`); `tests/test_webui.py` enumerates the routes and fails for an unauthenticated one. Video ids must
  pass `check_video_id` before reaching yt-dlp or the DB.
- Web UI (`src/utubot/web/`): plain HTML/CSS/ES modules, no build step, no npm, no inline script or style (CSP `'self'`), no
  `innerHTML`/`eval` (build DOM with `h()` and `textContent`; a test greps for it), no data in the static files. Cookie sessions need the
  CSRF header on writes; never put a token in page storage. API responses never carry provider keys, token hashes or password hashes.
- Per-user settings have one store each (`policy_overrides` row for everything in `UserPolicy`, `user_default`/`user_panel_default`
  for prompt defaults); the settings document is a view. A new setting goes into `UserPolicy` with its default, `settings.py`
  `SECTION_FIELDS`, the docs (`docs/server.md`, `docs/policy.md`, `ai/CONTRACT.md`) and a test.
- Client IP only via `security.client_ip` (trusted proxies; the optional `client_ip_header` counts only with the proxy secret), HTTPS detection only via `security.is_https`. Do not read X-Forwarded-For/-Proto or the client-IP header elsewhere.
- Prompt cache key = (video, prompt key, sha256 of prompt content, language); keep it that way.
- Verdicts are derived from shared per-video caches (triage, deep) plus the user's policy.
- Anything that reaches YouTube (yt-dlp, timedtext, audio) runs through `YoutubeGate.run` / `run_started` (`youtube.py`); never call YouTube
  directly. Never put a URL (they carry signed tokens) into a log line or exception message: classify failures with
  `classify_failure` / `classify_status` and raise `... from None`. Name the endpoint class of the request (`captions`, `metadata`,
  `media`; `klass=` on the classifiers, `classes=` on the gate): breakers are per class, pacing is shared. Never gate audio on caption state.
- Speech to text goes through the engine chain (`captions/engines.py`, `[[captions.asr_engines]]`); chunking and stitching live in
  `captions/chunking.py`, the audio format pick in `captions/formats.py`. Never hardcode an engine, URL or key. Transcripts made from
  audio keep their segments, engine and model (`TranscriptService.store_asr`).
- The automatic-transcription policy (`auto_transcribe`, `auto_transcribe_max_minutes`) is acted on only in `Transcription.auto`; keep
  explicit (summary view, insight, ask) and passive (side panel) triggers apart.
- No summary, insight or answer is ever generated from the title/channel/description alone. Without a transcript return
  `pending` + `transcript_status` (`delayed`) or `needs_transcript`; never cache those.
- Commit messages: `<type>/<scope>: <summary>` plus bullets; no AI attribution trailers.
- Update `DEVLOG.md` for each session.
