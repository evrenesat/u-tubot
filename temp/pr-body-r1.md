## UTB-256 r1: parity box for the Real-Debrid film spike

The Real-Debrid film spike (UTB-226 r0) plays Stremio addon streams in the u·tubot player through the existing progressive ExoPlayer path
(`ExoMediaSourceFactory.fromProgressiveUrl` / `ExoPlayerController.openProgressiveUrl` next to `openUrlList`). It touches `common/.../utubot/`
without an `extension/` file or a browser-extension plan row, so the `parity-box` check failed. This round adds the parity box to the pull
request description so the check passes; the spike code itself is unchanged.

- [x] AI feature parity: this change works in the TV app and the browser extension, or `ai/CONTRACT.md` ("Clients") says why one of them does not have it. Until the extension exists: the feature's row is in `ai/BROWSER_EXTENSION_PLAN.md`.
      (Not an AI feature: tick and write "n/a".)
  — n/a. The Real-Debrid film spike is a TV-only media-playback feature: a progressive ExoPlayer path fed by a Stremio stream addon, not an AI feature. It has no browser-extension counterpart and no parity row.
- [x] `ai/CONTRACT.md` changed together with the code that changes the wire.
  — no u·tubot backend wire change: `ai/CONTRACT.md` is unchanged. `UtubotRealDebridClient` talks to a user-configured Stremio addon (Torrentio / Comet / MediaFusion) over HTTP, not to the u·tubot backend contract.
- [x] No test or check contacts YouTube; no host, token or key in the tree.
  — the Real-Debrid client and the `RealDebridHarnessActivity` never contact YouTube; the unit tests (`UtubotRealDebridClientTest`, `UtubotRealDebridSkipsTest`) use a local `TinyHttpServer` and mock JSON only. The Real-Debrid token is entered on the TV via the device flow and is never committed.
