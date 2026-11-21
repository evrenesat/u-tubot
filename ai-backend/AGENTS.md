# ai-backend rules for agents

- Python 3.12, `uv` only. Run `uv run pytest -q`, `uv run ruff check`, `uv run ruff format --check`
  before committing. Scratch in `temp/` (gitignored).
- Contract lives in `../ai/CONTRACT.md`; change code and contract together.
- Database changes are additive (new tables, nullable or defaulted columns) so a rollback to the previous revision needs no database step;
  `tests/test_db_migrations.py` enforces it (`docs/server.md`, Updating and rolling back).
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
  The caption class is probed after a cooldown by exactly one background request (`YoutubeGate.interactive_ok`, `TranscriptService.probe_captions`);
  never send an interactive caption request while `interactive_ok` is false, and cap its escalation with `captions_cooldown_max_s`.
- While captions are limited (breaker open or probing, or a fetch just got 429/403) and the audio can stand in (`media` healthy, an engine
  takes the video) the answer is the "no captions" one (`Transcription.audio_fallback`, then `auto`), never `delayed`; the first stored
  transcript stays (captions never replace `asr`, `asr` never replaces captions).
- Speech to text goes through the engine chain (`captions/engines.py`, `[[captions.asr_engines]]`); chunking and stitching live in
  `captions/chunking.py`, the audio format pick in `captions/formats.py`. Never hardcode an engine, URL or key. Transcripts made from
  audio keep their segments, engine and model (`TranscriptService.store_asr`).
- The automatic-transcription policy (`auto_transcribe`, `auto_transcribe_max_minutes`) is acted on only in `Transcription.auto`; keep
  explicit (summary view, insight, ask) and passive (side panel) triggers apart.
- No summary, insight or answer is ever generated from the title/channel/description alone. Without a transcript return
  `pending` + `transcript_status` (`delayed`) or `needs_transcript`; never cache those.
- Job events: every stage of a transcript or captions job is logged through `captions/events.py` (`stage`, `emit`, `note`); never put a URL,
  token, cookie or raw exception text in a detail (`events.clean` / `events.technical` filter it, but do not rely on that). Routes that can
  queue a job call `mark_origin`; routes that hand a stored result to a client call the `record_*_delivery` helpers (`JobQueue`). The detail
  page lives in `web/ui/js/pages/job.js` + `jobtext.js`; document stages in `docs/server.md` (Job details) and `ai/CONTRACT.md`.
- Tests and demos never reach YouTube (owner rule): `tests/conftest.py` `block_youtube()` makes real yt-dlp, httpx and DNS-resolved
  requests to YouTube hosts fail (an autouse fixture, so every test is covered). Use the fake fetcher/downloader or a stand-in
  `yt_dlp.YoutubeDL`; `tests/webui_demo.py` is the same. The offline dev-proxy mode (`[youtube] offline = true`) is the same rule for a
  running backend: it refuses every YouTube request and answers from caches and recorded fixtures (`youtube_fixtures.py`, cassettes in
  `fixtures/youtube/`; unknown videos answer `offline`). Recording a cassette (`utubot youtube-record`) is the one command that reaches
  YouTube and belongs to the owner: never run it from tests, CI or an agent's verification runs — it refuses under pytest, in CI and
  with an offline config, and committed cassettes must carry no URL at all (signatures can sit in URL paths); the recorder replaces
  every URL with a `<url>` placeholder.
- Word times: every `Word` carries its provenance (`timing`); engine words are cached raw (`ASR_CACHE_VERSION`) and repaired per job
  (`captions/wordtimes.py`); cues come from the words (`align.cues_from_words`), the caption track only fills wordless gaps. Never present
  interpolated times as real: a result without real word times is flagged (`word_timing` event) and not cached. `timing_mode = "legacy"`
  is the rollback switch. Measure changes with `tests/test_sync_metric.py` and `utubot captions-score`.
  YouTube's own word starts (`transcripts.words`, `caption_kind`) are a reference, never the clock: `captions/reference.py` only measures
  (`ref_check`, no times change); they time the fill cues of gaps the engine did not hear (`align.word_cues`, `TIMING_REFERENCE`, not counted
  as engine words) except for manual tracks. `captions-score` forces the base language of the transcript (`hi-orig` is `hi`).
- Chunk review: `captions/sanity.py` (pure rules) + `AsrRouter._review` re-listen to wrong-language / hallucinated / sparse chunks (language forced,
  smaller windows, next engine) and drop what is still not speech, per chunk, after all first answers are in (never inside an engine's first-request lock).
  The expected language is a hint (metadata) that yields to the audio majority. `captions-score` references skip it unless `--review`. Thresholds: `halluc_*`, `sparse_*`.
- Commit messages: `<type>/<scope>: <summary>` plus bullets; no AI attribution trailers.
- Update `DEVLOG.md` for each session.
