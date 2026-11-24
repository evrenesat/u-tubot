import assert from "node:assert/strict";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

import { createRouter } from "../../src/background/router.js";

const BASE = "http://127.0.0.2:8790";
const PAGE = { url: "moz-extension://test/pages/options.html" };
const CONTENT = { url: "https://www.youtube.com/watch?v=abcdefghijk", tab: { id: 1 } };
const VIDEO = "abcdefghijk";

function memory() {
  const areas = { local: {}, session: {} };
  return {
    areas,
    local: {
      async get(keys) {
        if (keys === null) {
          return { ...areas.local };
        }
        const result = {};
        for (const key of keys) {
          if (key in areas.local) {
            result[key] = areas.local[key];
          }
        }
        return result;
      },
      async set(values) {
        Object.assign(areas.local, values);
      },
      async remove(keys) {
        for (const key of Array.isArray(keys) ? keys : [keys]) {
          delete areas.local[key];
        }
      },
    },
    session: {
      async get(keys) {
        if (keys === null) {
          return { ...areas.session };
        }
        const result = {};
        for (const key of keys) {
          if (key in areas.session) {
            result[key] = areas.session[key];
          }
        }
        return result;
      },
      async set(values) {
        Object.assign(areas.session, values);
      },
      async remove(keys) {
        for (const key of Array.isArray(keys) ? keys : [keys]) {
          delete areas.session[key];
        }
      },
    },
  };
}

function fakeFetch(answer = {}) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url: new URL(url), options });
    const payload = typeof answer === "string" ? answer : JSON.stringify(answer);
    return {
      ok: true,
      status: 200,
      text: async () => payload,
      arrayBuffer: async () => new TextEncoder().encode(payload),
    };
  };
  return { calls, fetchImpl };
}

function prepared(storage) {
  storage.areas.local["utubot.backend"] = BASE;
  storage.areas.local["utubot.token"] = "secret-token";
  storage.areas.local["utubot.user"] = "emu";
}

test("a page-only message from a content script is rejected", async () => {
  const storage = memory();
  prepared(storage);
  const router = createRouter({ storage, fetchImpl: fakeFetch().fetchImpl, extensionBase: "moz-extension://test/", isTest: false });
  await assert.rejects(
    () => router.handleMessage({ type: "setup.apply", payload: { setup: { backendUrl: BASE } } }, CONTENT),
    /extension page only/,
  );
});

test("a foreign sender and an unknown message are rejected", async () => {
  const storage = memory();
  const router = createRouter({ storage, fetchImpl: fakeFetch().fetchImpl, extensionBase: "moz-extension://test/", isTest: false });
  await assert.rejects(() => router.handleMessage({ type: "health", payload: {} }, { url: "https://evil.example/" }), /not allowed/);
  await assert.rejects(() => router.handleMessage({ type: "no.such", payload: {} }, PAGE), /Unknown message/);
});

test("a bad video id is rejected", async () => {
  const storage = memory();
  prepared(storage);
  const router = createRouter({ storage, fetchImpl: fakeFetch().fetchImpl, extensionBase: "moz-extension://test/", isTest: false });
  await assert.rejects(() => router.handleMessage({ type: "summary", payload: { video_id: "short" } }, CONTENT), /Bad video id/);
});

test("the test variant accepts the loopback content page", async () => {
  const storage = memory();
  prepared(storage);
  const router = createRouter({ storage, fetchImpl: fakeFetch({ status: "ready" }).fetchImpl, extensionBase: "moz-extension://test/", isTest: true });
  const answer = await router.handleMessage({ type: "summary", payload: { video_id: VIDEO, prompt: "panel" } }, { url: "http://127.0.0.1:8123/watch", tab: { id: 1 } });
  assert.equal(answer.status, "ready");
});

test("the router answers from storage after the module is loaded afresh", async () => {
  const storage = memory();
  prepared(storage);
  const fake = fakeFetch({ status: "ready", text: "T" });
  const extensionBase = "moz-extension://test/";
  const first = createRouter({ storage, fetchImpl: fake.fetchImpl, extensionBase, isTest: false });
  const firstAnswer = await first.handleMessage({ type: "summary", payload: { video_id: VIDEO, prompt: "panel" } }, CONTENT);
  const freshUrl = pathToFileURL(new URL("../../src/background/router.js?fresh=2", import.meta.url).pathname).href;
  const fresh = await import(freshUrl);
  const second = fresh.createRouter({ storage, fetchImpl: fake.fetchImpl, extensionBase, isTest: false });
  const secondAnswer = await second.handleMessage({ type: "summary", payload: { video_id: VIDEO, prompt: "panel" } }, CONTENT);
  assert.deepEqual(secondAnswer, firstAnswer);
});

test("setup.fetch parses the setup from the given address without a token", async () => {
  const storage = memory();
  const fake = fakeFetch({ utubot_setup: 1, backend_url: BASE, defaults: { assess: true } });
  const router = createRouter({ storage, fetchImpl: fake.fetchImpl, extensionBase: "moz-extension://test/", isTest: false });
  const setup = await router.handleMessage({ type: "setup.fetch", payload: { url: `${BASE}/setup.json` } }, PAGE);
  assert.equal(setup.backendUrl, BASE);
  assert.equal(fake.calls[0].options.credentials, "omit");
  assert.equal(fake.calls[0].options.headers?.Authorization ?? undefined, undefined);
});

test("settings.read returns the TV's defaults and settings.write keeps the switches", async () => {
  const storage = memory();
  const router = createRouter({ storage, fetchImpl: fakeFetch().fetchImpl, extensionBase: "moz-extension://test/", isTest: false });
  const defaults = await router.handleMessage({ type: "settings.read", payload: {} }, PAGE);
  assert.equal(defaults.assess, true);
  assert.equal(defaults.mark_only, false);
  assert.equal(defaults.summary_panel, false);
  assert.equal(defaults.auto_captions, true);
  assert.equal(defaults.auto_cuts, false);
  assert.equal(defaults.panel_delay_ms, 1800);
  const written = await router.handleMessage({ type: "settings.write", payload: { settings: { summary_panel: true, panel_delay_ms: 3000 } } }, PAGE);
  assert.equal(written.summary_panel, true);
  assert.equal(written.panel_delay_ms, 3000);
  assert.equal(written.assess, true);
});

test("a backend change drops the token when the origin changes and clears the session caches", async () => {
  const storage = memory();
  prepared(storage);
  storage.areas.session["utubot.cache.summaries"] = [{ key: "abcdefghijk|panel", value: { status: "ready" }, at: 1 }];
  const router = createRouter({ storage, fetchImpl: fakeFetch().fetchImpl, extensionBase: "moz-extension://test/", isTest: false });
  await router.handleMessage({ type: "backend.set", payload: { url: "http://127.0.0.3:8790" } }, PAGE);
  assert.equal(storage.areas.local["utubot.backend"], "http://127.0.0.3:8790");
  assert.equal(storage.areas.local["utubot.token"], "");
  assert.equal(storage.areas.session["utubot.cache.summaries"], undefined);
});

test("open.set writes a one-shot request and open.take removes it", async () => {
  const storage = memory();
  const router = createRouter({ storage, fetchImpl: fakeFetch().fetchImpl, extensionBase: "moz-extension://test/", isTest: false });
  await router.handleMessage({ type: "open.set", payload: { video_id: VIDEO, request: { kind: "captions" } } }, PAGE);
  const taken = await router.handleMessage({ type: "open.take", payload: { video_id: VIDEO } }, CONTENT);
  assert.deepEqual(taken, { kind: "captions" });
  assert.equal(await router.handleMessage({ type: "open.take", payload: { video_id: VIDEO } }, CONTENT), null);
});
