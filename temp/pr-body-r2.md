- [x] AI feature parity: this change works in the TV app and the browser extension, or `ai/CONTRACT.md` ("Clients") says why
      one of them does not have it. Until the extension exists: the feature's row is in `ai/BROWSER_EXTENSION_PLAN.md`.
      (Not an AI feature: tick and write "n/a".) — TV-only refinement of the existing "Describe on phone…" (cut-qr)
      feature: the tablet now types the cut description on device (or opens the cut sheet in the browser) instead of
      scanning a QR, and pairing adds an "Open in browser" option. The extension is unchanged — it already types the
      description itself and opens the cut sheet in a tab; the QR sheet is TV only, as `ai/CONTRACT.md` ("Clients")
      says. The feature's row is in `ai/BROWSER_EXTENSION_PLAN.md` (cut-qr).
- [x] `ai/CONTRACT.md` changed together with the code that changes the wire. — No wire change: the tablet calls the
      already-documented `PUT /v1/cut-requests/{id}` (`{"prompt"}` fills a waiting request and starts the build) and
      opens the existing `#/tvs` admin page; no new endpoint or payload is introduced.
- [x] No test or check contacts YouTube; no host, token or key in the tree. — The new unit test (`UtubotCutsClientTest`)
      uses the local `TinyHttpServer` mock; no YouTube access, and no host, token or key was added to the tree.
