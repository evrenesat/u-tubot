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
