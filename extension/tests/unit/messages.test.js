import assert from "node:assert/strict";
import { test } from "node:test";

import { checkMessage, CONTENT, PAGE_ONLY } from "../../src/shared/messages.js";

const BASE = "moz-extension://test/";
const PAGE = { url: `${BASE}pages/popup.html` };
const YOUTUBE = { url: "https://www.youtube.com/watch?v=abcdefghijk", tab: { id: 1 } };

test("the two sets keep the page messages apart from the content ones", () => {
  for (const type of ["setup.fetch", "setup.apply", "pair", "backend.set", "token.set", "health", "me", "prompts.list",
    "prompts.import", "prompts.refresh", "prompts.default", "settings.read", "settings.write", "processed", "open.set", "diagnostics.read"]) {
    assert.equal(PAGE_ONLY.has(type), true, type);
  }
  for (const type of ["assess", "summary", "insight", "transcribe", "transcript", "prompts.list", "captions.status",
    "captions.prepare", "captions.file", "cuts.list", "cuts.request", "cuts.follow", "settings.read", "open.take", "diagnostics.report"]) {
    assert.equal(CONTENT.has(type), true, type);
  }
});

test("a page may call both sets and a YouTube page only the content set", () => {
  assert.deepEqual(checkMessage({ type: "health", payload: {} }, PAGE, BASE, false), { page: true, payload: {} });
  assert.deepEqual(checkMessage({ type: "summary", payload: { video_id: "abcdefghijk" } }, YOUTUBE, BASE, false), {
    page: false,
    payload: { video_id: "abcdefghijk" },
  });
  assert.deepEqual(checkMessage({ type: "summary", payload: { video_id: "abcdefghijk" } }, PAGE, BASE, false), {
    page: true,
    payload: { video_id: "abcdefghijk" },
  });
  assert.throws(() => checkMessage({ type: "health", payload: {} }, YOUTUBE, BASE, false), /extension page only/);
});

test("the test variant accepts the fixture page and nothing else", () => {
  const fixture = { url: "http://127.0.0.1:8123/watch", tab: { id: 1 } };
  assert.equal(checkMessage({ type: "summary", payload: { video_id: "abcdefghijk" } }, fixture, BASE, true).page, false);
  assert.throws(() => checkMessage({ type: "summary", payload: { video_id: "abcdefghijk" } }, fixture, BASE, false), /not allowed/);
  assert.throws(() => checkMessage({ type: "summary", payload: { video_id: "abcdefghijk" } }, { url: "http://127.0.0.2:8790/" }, BASE, true), /not allowed/);
});
