- [x] AI feature parity: this change works in the TV app and the browser extension, or `ai/CONTRACT.md` ("Clients") says why
      one of them does not have it. Until the extension exists: the feature's row is in `ai/BROWSER_EXTENSION_PLAN.md`.
      (Not an AI feature: tick and write "n/a".)
      Test-isolation fix plus a correctness cleanup for the Inbox badge (u-tubot #160), an AI feature whose row is the
      `inbox` row of `ai/BROWSER_EXTENSION_PLAN.md` (planned for both clients). The change unregisters the connection
      listener when the presenter is disposed and resets the u-tubot singletons between tests; it does not alter the
      feature's scope or its client coverage.
- [x] `ai/CONTRACT.md` changed together with the code that changes the wire.
      No wire change: the change is a test-isolation fix and a listener cleanup in shared `common` code, so
      `ai/CONTRACT.md` is unchanged.
- [x] No test or check contacts YouTube; no host, token or key in the tree.
      The test drives a local stub (`http://127.0.0.1:9`) with a placeholder token (`test-token`); no real host, token, or
      key is added to the tree.
