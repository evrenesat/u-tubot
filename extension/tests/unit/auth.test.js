import assert from "node:assert/strict";
import { test } from "node:test";

import { authorizationFor, stripTrailingSlash } from "../../src/background/auth.js";

test("the token goes only to the same scheme, host, port and a path under the backend", () => {
  const token = "secret-token";
  assert.equal(authorizationFor("https://host:8443/", token, "https://host:8443/v1/x.vtt"), "Bearer secret-token");
  assert.equal(authorizationFor("https://host:8443", token, "https://host:8443/v1/x.vtt"), "Bearer secret-token");
  assert.equal(authorizationFor("https://host:8443", token, "https://other/x.vtt"), null);
  assert.equal(authorizationFor("https://host:8443", token, "https://host:8444/v1/x.vtt"), null);
  assert.equal(authorizationFor("https://host:8443", token, "http://host:8443/v1/x.vtt"), null);
  assert.equal(authorizationFor("https://host", token, "https://host:443/v1/x.vtt"), "Bearer secret-token");
  assert.equal(authorizationFor("https://host", "", "https://host/v1/x.vtt"), null);
  assert.equal(authorizationFor("https://host", token, null), null);
  assert.equal(authorizationFor("", token, "https://host/v1/x.vtt"), null);
});

test("a host that only starts like the backend gets no token", () => {
  const token = "secret-token";
  const base = "https://u.example.com";
  assert.equal(authorizationFor(base, token, "https://u.example.com.evil.net/x"), null);
  assert.equal(authorizationFor(base, token, "https://u.example.comevil.net/x"), null);
  assert.equal(authorizationFor(base, token, "https://u.example.com@evil.net/x"), null);
  assert.equal(authorizationFor(base, token, "https://evil.net/https://u.example.com/x"), null);
  assert.equal(authorizationFor(base, token, "https://evil.net/x?u=https://u.example.com/"), null);
  assert.equal(authorizationFor("https://U.Example.com/", token, "HTTPS://u.example.COM/v1/x.vtt"), "Bearer secret-token");
  assert.equal(authorizationFor(base, token, "ftp://u.example.com/x.vtt"), null);
  assert.equal(authorizationFor(base, token, "file:///data/x.vtt"), null);
  assert.equal(authorizationFor(base, token, "/v1/x.vtt"), null);
});

test("a backend under a path vouches for its own path only", () => {
  const token = "secret-token";
  const base = "https://u.example.com/ai/";
  assert.equal(authorizationFor(base, token, "https://u.example.com/ai/v1/x.vtt"), "Bearer secret-token");
  assert.equal(authorizationFor(base, token, "https://u.example.com/ai"), "Bearer secret-token");
  assert.equal(authorizationFor(base, token, "https://u.example.com/other/v1/x.vtt"), null);
  assert.equal(authorizationFor(base, token, "https://u.example.com/aiother/v1/x.vtt"), null);
  assert.equal(authorizationFor(base, token, "https://u.example.com/"), null);
  assert.equal(authorizationFor(base, token, "https://u.example.com/ai/../other/x.vtt"), null);
  assert.equal(authorizationFor(base, token, "https://u.example.com/ai/%2e%2e/other/x.vtt"), null);
});

test("stripTrailingSlash trims one slash", () => {
  assert.equal(stripTrailingSlash("https://host/"), "https://host");
  assert.equal(stripTrailingSlash(" https://host "), "https://host");
  assert.equal(stripTrailingSlash(null), "");
});
