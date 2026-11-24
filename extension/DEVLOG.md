## 2026-11-24 (checkpoint 2: background core)

- `src/background/client.js` calls every endpoint of the plan's section 1 with the contract's methods, paths, query fields
  (title, channel, duration_s on insight/summary/transcribe; is_live too on cut requests), `credentials: "omit"` and
  `cache: "no-store"` on every request. `auth.js` scopes the bearer header to the stored backend's scheme, host, port and path;
  `setup.js` resolves the typed address and the setup file, with http for private hosts only; `settings.js` keeps the TV's
  defaults and keys.
- `src/background/router.js`: the two message sets of decision 6, sender checks (extension pages for the page set; YouTube or the
  test fixture for content), video id validation, and a stateless executor: connection and settings from `storage.local`, the
  verdict/summary/captions caches and the one-shot open requests in `storage.session`, no state in memory. `cache.js` clears the
  session caches on a backend or token change. `main.js` wires the router to the real API and opens the options page on install.
- `src/shared/models.js`, `meta.js`, `messages.js`: the contract's parsers and the message sets. `tests/unit/{auth,setup,client,
  messages,router}.test.js`: the ported setup and client cases, every endpoint's method/path/query, the credentials and auth
  scoping, the sender and video-id checks and a fresh router load.

# u·tubot browser extension devlog

## 2026-11-24 (checkpoint 1: mock backend controls)

- `scripts/emulator_mock_backend.py`: every control of the plan's section 8, added at once: the request log (`/__mock/requests` and
  its `clear=1`), `OPTIONS` 405 (logged), `--host` and `--user`, `/__mock/setup?backend=`, `/__mock/hold`, `/__mock/assess`
  (per-video verdict, delay, failure), the panel prompt's status and a `reason` on a failed answer, the prompt writes and
  `/v1/processed` with its `items|empty|fail` switch. The existing defaults are unchanged.
- `ai-backend/tests/test_emulator_mock.py`: one test per control plus a replay of the existing defaults, started on two loopback
  addresses with `--base`. `docs/development.md` ("Mock backend controls") lists them for the extension.

## 2026-11-24 (checkpoint 0: skeleton and CI)

- `extension/` skeleton: the base, Firefox and Chromium manifests and the five variants of `build.mjs`; `src/shared/api.js`,
  the only module touching the extension API, with the eslint rules that forbid it elsewhere and forbid `window`/`document`
  under `src/background/` and HTML string insertion everywhere; empty background and content scripts; the page and locale
  stubs; icons, `AGENTS.md` (with the licence rule), `THIRD_PARTY.md` and this devlog.
- Change classification moved from the CI workflow into `scripts/utubot_ci_changes.py` (`backend`, `app`, `release`,
  `extension`, `extension_release`), with its `parity` and `ci-green` commands; `ai-backend/tests/test_ci_changes.py` covers the
  classifier, the parity box and the green-run rule. `NON_APP` now includes `extension/`, and the backend job runs for the new
  script and the mock backend.
- `utubot-ci.yml`: the `changes` job runs the script and the new `extension` job lints, unit-tests, builds all five variants and
  runs `web-ext lint` on the Firefox variants. `.github/workflows/utubot-parity.yml`: the `parity-box` job with the
  `pull_request` triggers of the plan.
