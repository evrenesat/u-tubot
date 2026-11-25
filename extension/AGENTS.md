# u·tubot browser extension agent guidance

The extension brings the u·tubot AI features of the TV app to `www.youtube.com` and `m.youtube.com` with the same backend and
the same wire contract (`ai/CONTRACT.md`). The plan is `ai/BROWSER_EXTENSION_PLAN.md`; the repository-wide rules are in the
root `AGENTS.md`.

- Licence: this directory is MIT like the rest of the repository (owner decision). SponsorBlock, DeArrow, their shared library,
  Return YouTube Dislike and similar GPL-3.0 or copyleft YouTube extensions may be read to learn techniques and the facts of
  YouTube's page (element, class and event names); never copy, translate line by line or vendor their code. Code may be copied
  only from MIT, BSD or Apache-2.0 sources, with the attribution in `THIRD_PARTY.md`.
- One codebase, Manifest V3 on every browser: `manifest.base.json` plus `manifest.firefox.json` and `manifest.chromium.json`,
  merged by `build.mjs` into the variants `firefox-unlisted`, `firefox-listed`, `firefox-test`, `chromium`, `chromium-test`.
- Firefox-only keys live only in `manifest.firefox.json`; Chromium-only keys only in `manifest.chromium.json`.
- `src/shared/api.js` is the only module that touches `browser`/`chrome`. The background is written for a service worker: no DOM,
  no `window`, no state in its memory, no timer that must outlive one request.
- Network only in the background. Content scripts and pages never hold the token and never call the backend; they send named
  messages from the two sets in the plan's decision 6. There is no generic "fetch this URL" message.
- DOM is built with `textContent` only; never `innerHTML`, `outerHTML` or `insertAdjacentHTML`. The backend address, token and
  user name never enter a page-visible node, attribute or `data-*` value. Page knowledge lives in `src/content/site.js` only, and a
  failure degrades to "nothing shown", never a broken page.
- Tests never contact YouTube or any other real service: unit tests on Node; end-to-end tests in real Firefox against the
  hand-written stand-in pages under `tests/fixtures/site/` and the mock backend `scripts/emulator_mock_backend.py` on loopback,
  behind the refusing proxy. The owner alone opens real YouTube.
- Build with `npm run build:<variant>`; lint with `npm run lint`; unit tests with `npm test`; `web-ext lint` on a built variant.
  The end-to-end suite is `tests/e2e` (uv project, Selenium and the pinned Firefox and geckodriver of `tests/e2e/tools.lock`).
- Each checkpoint updates `DEVLOG.md`. Commits follow `<type>/<scope>: <imperative summary>` with no AI attribution.
