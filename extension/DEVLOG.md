# u·tubot browser extension devlog

## 2026-11-26 (error ledger, issue #206)

- `createClient(..., { reportFailures: true })` (the router) reports the extension's own transport and 5xx failures to `POST /v1/ledger`, throttled to one per message a minute and ten a minute (`createFailureThrottle`). Unit tests in `tests/unit/client.test.js`.

## 2026-11-26 (round 1 fix: the spoken cut description parity box)

- The spoken cut description (the TV's "Describe by voice…") is TV only: the extension has a keyboard and takes the description
  itself (`POST .../cuts {"prompt"}`), exactly as row 19's "Describe here". Its row in the plan's parity matrix (row 36) says so
  and points at `POST /v1/speech`, so a change to the TV-side speech feature needs no PR parity box.
- Evidence: `scripts/utubot_ci_changes.py parity` passes with the plan touched and fails without it; backend `ruff check`/`format
  --check` clean and `pytest -q` (1403 pass); `./gradlew :common:testStutubotDebugUnitTest` (the speech client, probe and WAV
  tests) and `:smarttubetv:compileStutubotDebugJavaWithJavac`; extension `npm run lint`, `npm test` (56 pass), the five builds,
  `web-ext lint` on the three Firefox variants (0 errors) and the e2e suite (4 pass) on loopback behind the refusing proxy.

## 2026-11-25 (checkpoints 0-3: third fix round, the red CI)

- Both `Install ffmpeg` steps of `.github/workflows/utubot-ci.yml` (`backend` and `extension`) skip when the runner already has
  ffmpeg and otherwise refresh the apt index first. The stale runner index asked the mirror for a removed libssh version, which
  made both jobs red before any test ran; the backend step now carries the owner's `main` fix unchanged, so a sync merges it
  cleanly, and the extension step has the same guard.
- `ai-backend/tests/test_ci_changes.py`: a test reads the workflow and requires every ffmpeg step to start with
  `command -v ffmpeg ||` and to contain `sudo apt-get update -qq`; the test fails on the old lines.
- Evidence: `ruff check`/`format --check`, `pytest tests/test_ci_changes.py` (30 pass) and `pytest tests/test_emulator_mock.py`;
  `npm run lint`, `npm test` (55 pass), all five builds, `web-ext lint` on the three Firefox variants (0 errors); the e2e suite
  (4 pass) on loopback behind the refusing proxy in the pinned Firefox. The full backend run has 1089 pass and 3 failures that
  only this host's unreadable `/var/lib/utubot/users.toml` causes in the example-config tests; the CI runner has no such path.

## 2026-11-25 (checkpoints 0-3: second review round, fixes)

- `src/shared/messages.js`: a content script may call the names both sets share (`settings.read`, `prompts.list`); only a
  non-shared page name still needs an extension page. The test fixture sender is now a parsed URL whose `hostname` is exactly
  `127.0.0.1`, so `127.0.0.10` and `127.0.0.1.evil` are refused; `messages.test.js` covers the positive and negative cases and
  `router.test.js` calls the shared page names from the content side.
- `src/shared/models.js`: parsers return plain data only; the `is*`, `allPrompts`, `first` and `find` helpers were moved to
  exported `revive*` functions (and a `revive(type, value)` map) that attach them as non-enumerable properties on the receiving
  side. The cache and the runtime message boundary now carry JSON-safe values, and `models.test.js` checks every parser through
  `structuredClone` and JSON. `router.test.js` uses structured-clone storage, so a leak of a function fails, and revives a cached
  summary after a fresh router load.
- `tests/e2e/refusing_proxy.py`: `HEAD`, `OPTIONS` and `PATCH` are recorded and refused like the other methods; the new proxy
  test covers every method.
- `scripts/utubot_ci_changes.py`: a push whose `before` is the zero SHA returns an unknown file list (`None`), so every test job
  runs instead of being skipped; `test_ci_changes.py` covers the zero-before case directly.
- Evidence: `npm run lint`, `npm test` (55 pass), the five builds; `uv run pytest -q test_refusing_proxy.py` (2 pass);
  `ruff check`/`format --check` and `pytest tests/test_ci_changes.py` (29 pass). The Selenium harness was not started here because
  the pinned Firefox and geckodriver were not downloaded in this checkout.

## 2026-11-25 (checkpoints 0-3: first review round, fixes)

- `src/background/setup.js`: `isPrivateHost`, `hostPart` (`resolveUrl`) and `originOf` strip the brackets of an IPv6 host
  literal before comparing or matching it, and put them back when the address is written into a URL, like the TV's
  `UtubotSetup.hostOf`. `[::1]:8790`, `[fd00::1]` and `[FE80::1]` are private; `[2001:db8::1]` stays public. A test covers
  `resolveUrl`, `parseSetup`, `originOf` and `requireUrl` with bracketed addresses.
- `scripts/utubot_ci_changes.py`: a failed `gh` listing no longer fails `classify`. `gh_lines_or_none` returns `None` and the
  run falls back to the inline script's defaults: both test jobs run, release only through its own decisions, and a failed
  tag listing means "no tag yet", so a version bump is not lost. `parity` needs the list, so it still fails closed with its
  own message. Tests run a failing `gh` first on `PATH` for a pull request, a push and the parity check.
- `scripts/emulator_mock_backend.py`: `do_DELETE` records the request and honours the hold with the other methods, so
  `DELETE /v1/cut-requests/<id>` shows in `/__mock/requests` and `__mock/hold` delays it. `test_emulator_mock.py` fails on the
  old code.
- `extension/assets/icons/`: the three PNGs are now rendered from `assets/brand/utubot-symbol.svg` by `assets/brand/render.py`
  (new `EXTENSION_ICONS` targets at the manifest's 48, 96 and 128), and `tests/unit/icons.test.js` decodes them to check the
  manifest paths, the square transparent canvas and the two brand colours against the symbol.
- Evidence: `npm run lint`, `npm test` (49 pass), the five builds; `ruff check`/`format --check` and
  `pytest tests/test_ci_changes.py tests/test_emulator_mock.py` (40 pass). `render.py` itself was run from a scratch venv with
  cairosvg (no system install here) and rewrote the icons identically.

## 2026-11-24 (checkpoints 0-3: review pass and fixes)

- Checked every Done When of checkpoints 0, 1, 2 and 3 against the plan on `main`. The skeleton, classifiers, mock controls,
  background core and e2e harness are the first pass of `conduktor/UTB-7`; this pass keeps them and closes the gaps found.
- `manifest.base.json`: `content_security_policy.extension_pages = "script-src 'self'; object-src 'self'"` on every variant, so
  plain-http private servers are not upgraded (decision 10). Manifest tests also assert release variants carry no fixture/loopback
  strings and that the CSP has no `upgrade-insecure-requests`.
- `src/background/client.js`: a backend-bound call without a token throws `No token` before `fetch`; `auth.js` gained
  `isUnderBackend` for the scope check. Caption files outside the backend still need no token. `tests/unit/client.test.js` covers
  both; `tests/unit/e2e.test.js` now names every `user.js` service group of section 6.
- `scripts/emulator_mock_backend.py`: removed a stray `DELETE /v1/prompts/default` branch that read an undefined body (the plan
  names only `PUT`); the mock test adds the `panel=400` answer. `ai-backend/tests/test_ci_changes.py` and `test_emulator_mock.py`
  were reformatted and the unused import removed so `ruff check` and `ruff format --check` pass in CI.
- `scripts/utubot_ci_changes.py`: the parity rule matches u-tubot code at the module root too (`common/utubot/`,
  `smarttubetv/utubot/`), as the plan's `common/**/utubot/**` says, with a unit test. `docs/development.md` runs
  `./run-offline.sh` from the e2e directory.
- Evidence: `npm run lint`, `npm test` (45 pass), all five builds, `web-ext lint` on the three Firefox variants (0 errors);
  `ruff check`/`format --check`, `pytest tests/test_ci_changes.py tests/test_emulator_mock.py` (35 pass); the e2e suite (3 pass)
  behind the refusing proxy in the pinned Firefox. A deliberate probe fetched `refused.example.invalid` through Firefox; the final
  guard failed and printed that host (probe then removed), so a host-leaking session cannot pass. `run-offline.sh` is still not
  runnable here (`unshare --net` and bubblewrap are denied, `Operation not permitted`); CI's proxy guard is the offline check and
  the namespace run stays with the owner host.

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

## 2026-11-24 (checkpoint 3: e2e harness)

- `tests/e2e/`: `fixture_server.py` (the page fixtures on `127.0.0.1`), `refusing_proxy.py` (records method and host, answers 502,
  `/__log`), `download_tools.py` with `tools.lock` (Firefox `140.4.0esr` and geckodriver `0.36.0`, source URL and SHA-256), `user.js`
  (the named service groups, the proxy and its three loopback exemptions, the auto-grant permission preference), `pyproject.toml`
  with `uv.lock`, `conftest.py` (mock on `127.0.0.2`/`127.0.0.3`, fixture server, proxy, Firefox profile and temporary add-on,
  extension UUID from the profile's `prefs.js`), `run-offline.sh` and the one trivial test of section 6's table; `tests/unit/e2e.test.js`
  checks the groups and the lock format.
- The suite: the test variant marks the `127.0.0.1` fixture, an optional permission for `http://127.0.0.2/*` is granted by a click
  with the auto-grant preference, and the background answers `health` from the mock there. `test_refusing_proxy.py` proves a request to
  a non-loopback name is recorded and refused; `test_zz_the_refusing_proxy_recorded_nothing` runs last and fails when the session
  contacted any host.
- Fixes found by the guard: the background/content bundles were ESM and content scripts may not be modules, so both are IIFE bundles
  and only page scripts stay ESM; the remote-settings dummy server must be exactly `data:,#remote-settings-dummy/v1` and Firefox's
  test mode (`MOZ_DISABLE_NONLOCAL_CONNECTIONS=1`) makes it skip. Firefox reported `content-signature-2.cdn.mozilla.net`,
  `firefox-settings-attachments.cdn.mozilla.net` and `firefox.settings.services.mozilla.com` through the proxy before the fix; after it
  the final check passes.
- `run-offline.sh` was not executed in this environment: `unshare --net`, user-namespace mapping and bubblewrap's loopback setup are
  all denied (`Operation not permitted`), and sudo needs a password. The suite itself passed locally only behind the proxy guard,
  outside the required namespace; the namespace run remains to be done where the capability exists (owner host or CI's guard).
  `.github/workflows/utubot-ci.yml`'s `extension` job now installs the e2e dependencies, downloads the pinned tools (its only network
  step) and runs the suite; `docs/development.md` has the recipe.
