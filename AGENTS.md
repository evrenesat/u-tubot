# u·tubot agent guidance

u·tubot = Electric Eel (SmartTube fork) + an AI layer. Stylize the name "u·tubot" (U+00B7); identifiers use `utubot` / `u-tubot`.

- Read `ai/FORK_SURVEY.md` (why this base), `ai/CONTRACT.md` (wire contract and setup file), `ai/APP_INTEGRATION.md` (every touched upstream file, merge guide), `docs/development.md` (build and test), `DEVLOG-utubot.md`.
- The Android build needs two sibling checkouts next to this repo: `SharedModules` and `MediaServiceCore` (cygnusx-1-org, see `.github/workflows/utubot-release.yml` for the pinned commits).
- Android: flavor `stutubot`, app id `dev.utubot.tv`. `./gradlew :smarttubetv:assembleStutubotDebug :common:testStutubotDebugUnitTest` with a JDK 25 and the Android SDK (`JAVA_HOME`, `ANDROID_HOME` or `local.properties`).
- AI code lives in `...common.utubot` / `...tv.utubot`; keep hooks in upstream files small and listed in `ai/APP_INTEGRATION.md`.
- Backend: `ai-backend/` (own `AGENTS.md`, `README.md`, `DEVLOG.md`).
- The app ships no backend address: users import a setup from their own server. Never bake a personal host, token or key into the tree; `-PutubotUrl` / `utubot.properties` are for private builds only.
- Release signing key: never commit it. It is read from `UTUBOT_KEYSTORE`, `UTUBOT_KEYSTORE_PASSWORD`, `UTUBOT_KEY_ALIAS`, `UTUBOT_KEY_PASSWORD` or a gitignored `keystore.properties`. An update signed with another key will not install over the current one.
- Branches: `master` mirrors Electric Eel; work lands on `feat/ai-layer`. Remotes: `electriceel` (base), `smarttube` (upstream). Sync: merge `electriceel/master` into `master`, then into `feat/ai-layer`. Prefer guarding inherited upstream workflows with `if: github.repository == ...` over editing them, to keep syncs clean.
- Commits `<type>/<scope>: <imperative summary>` + bullets, no AI attribution. No secrets in git. Keep docs generic: placeholders like `utubot.example.com`, `127.0.0.1`.
