# ai-backend rules for agents

- Python 3.12, `uv` only. Run `uv run pytest -q`, `uv run ruff check`, `uv run ruff format --check`
  before committing. Scratch in `temp/` (gitignored).
- Contract lives in `../ai/CONTRACT.md`; change code and contract together.
- No magic numbers: tunables go in `src/utubot/config.py` and `config.example.toml`.
- Never log or commit secrets. Keys come from env vars named in config. Tokens are stored only as
  sha256 hashes. Tests use the mock server in `tests/mock_openai.py`; never call real LLMs there.
- Public service: every route except health, pair and `/app/*` must depend on `current_user`
  (or `admin_user`). Video ids must pass `check_video_id` before reaching yt-dlp or the DB.
- Client IP only via `security.client_ip` (trusted proxies). Do not read X-Forwarded-For elsewhere.
- Prompt cache key = (video, prompt key, sha256 of prompt content, language); keep it that way.
- Verdicts are derived from shared per-video caches (triage, deep) plus the user's policy.
- Commit messages: `<type>/<scope>: <summary>` plus bullets; no AI attribution trailers.
- Update `DEVLOG.md` for each session.
