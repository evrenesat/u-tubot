## UTB-278 r3: parity box for the Real-Debrid film spike

This round re-submits the Real-Debrid film spike (UTB-226 r0: "spike to play Real-Debrid film streams" and "tick the parity box") so the `parity-box` check passes against the current pull request body. The spike plays Stremio addon streams (Torrentio / Comet / MediaFusion) in the u·tubot player through the existing progressive ExoPlayer path (`ExoMediaSourceFactory.fromProgressiveUrl` / `ExoPlayerController.openProgressiveUrl`, next to `openUrlList`), feeding `SponsorBlockController` a hand-written skip list to prove cut playback. It touches `common/.../utubot/` without an `extension/` file or a browser-extension plan row, so the `parity-box` check requires the parity box to be ticked in the pull request description.

- [x] AI feature parity: this change works in the TV app and the browser extension, or `ai/CONTRACT.md` ("Clients") says why one of them does not have it. Until the extension exists: the feature's row is in `ai/BROWSER_EXTENSION_PLAN.md`.
  — n/a. The Real-Debrid film spike is a TV-only media-playback feature: a progressive ExoPlayer path fed by a Stremio stream addon, not an AI feature. It has no browser-extension counterpart and no parity row.
- [x] `ai/CONTRACT.md` changed together with the code that changes the wire.
  — no u·tubot backend wire change: `ai/CONTRACT.md` is unchanged. `UtubotRealDebridClient` talks to a user-configured Stremio addon (Torrentio / Comet / MediaFusion) over HTTP, not to the u·tubot backend contract.
- [x] No test or check contacts YouTube; no host, token or key in the tree.
  — the Real-Debrid client and the debug-only `RealDebridHarnessActivity` never contact YouTube; the unit tests (`UtubotRealDebridClientTest`, `UtubotRealDebridSkipsTest`) use a local `TinyHttpServer` and mock JSON only. The Real-Debrid token is entered on the TV via the device flow and is never committed or logged.
