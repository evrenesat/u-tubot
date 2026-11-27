// Frontend tests for the error-ledger page (persistence of the newest failures and the total row).
// Runs with `node --test` using the DOM stub; it never touches the network.
import { test } from "node:test";
import assert from "node:assert/strict";

import "./dom-stub.mjs";
import { render } from "../../src/utubot/web/ui/js/pages/ledger.js";

const PAGE_SIZE = 10;

function entry(i) {
  return {
    id: i,
    ts: 1_766_000_000 + i,
    component: "job",
    operation: "captions",
    category: i % 2 === 0 ? "rate-limited" : "unknown",
    video_id: "abcdefghijk",
    message: "failure number " + i,
    detail: i % 3 === 0 ? "job_id=" + "abcdefabcdef" : "",
    flagged: i % 2 === 1,
    client: "tv",
    job_id: i % 3 === 0 ? "abcdefabcdef" : null,
  };
}

function counts() {
  return [
    { category: "rate-limited", flagged: false, day: "2026-11-25", count: 2, total: 3 },
    { category: "rate-limited", flagged: false, day: "2026-11-26", count: 1, total: 3 },
    { category: "unknown", flagged: true, day: "2026-11-26", count: 5, total: 5 },
  ];
}

// Point fetch at a fixed ledger; page `recent` by the offset in the URL, as the backend does.
function installFetch(recent) {
  globalThis.fetch = async (url) => {
    const qs = url.includes("?") ? url.split("?", 2)[1] : "";
    const params = new URLSearchParams(qs);
    const offset = Number(params.get("offset") || 0);
    const limit = Number(params.get("limit") || 100);
    return {
      ok: true,
      status: 200,
      json: async () => ({
        period_days: 14,
        counts: counts(),
        recent: recent.slice(offset, offset + limit),
        youtube_forbidden: [],
      }),
    };
  };
}

function* walk(node) {
  yield node;
  for (const c of node.children) yield* walk(c);
}

function byClass(root, cls) {
  return [...walk(root)].filter((n) => n.className.split(/\s+/).includes(cls));
}

function buttons(root) {
  return [...walk(root)].filter((n) => n.tagName === "BUTTON");
}

async function settle() {
  for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
}

async function renderLedger(view, recent) {
  installFetch(recent);
  await render(view, { rest: [] });
  await settle();
}

test("renders the first page of ten newest failures with an Older button", async () => {
  const view = document.createElement("div");
  await renderLedger(view, Array.from({ length: 15 }, (_, i) => entry(i)));
  assert.equal(byClass(view, "job").length, PAGE_SIZE);
  assert.ok(buttons(view).some((b) => b.textContent === "Older"), "Older must be offered when more pages exist");
  assert.ok(!buttons(view).some((b) => b.textContent === "Newer"), "Newer must be hidden on the first page");
});

test("Older advances to the next page and Newer appears", async () => {
  const view = document.createElement("div");
  await renderLedger(view, Array.from({ length: 15 }, (_, i) => entry(i)));

  const older = buttons(view).find((b) => b.textContent === "Older");
  assert.ok(older, "expected an Older button on page one");
  older.dispatch("click");
  await settle();

  assert.equal(byClass(view, "job").length, 5, "the second page holds the remaining five");
  assert.ok(buttons(view).some((b) => b.textContent === "Newer"), "Newer must be offered off the last page");
  assert.ok(!buttons(view).some((b) => b.textContent === "Older"), "Older must be hidden on the last page");
});

test("Newer returns to the first page", async () => {
  const view = document.createElement("div");
  await renderLedger(view, Array.from({ length: 15 }, (_, i) => entry(i)));
  const older = buttons(view).find((b) => b.textContent === "Older");
  older.dispatch("click");
  await settle();
  const newer = buttons(view).find((b) => b.textContent === "Newer");
  assert.ok(newer, "expected a Newer button on the last page");
  newer.dispatch("click");
  await settle();
  assert.equal(byClass(view, "job").length, PAGE_SIZE);
  assert.ok(buttons(view).some((b) => b.textContent === "Older"));
  assert.ok(!buttons(view).some((b) => b.textContent === "Newer"));
});

test("shows an empty state when there are no failures", async () => {
  const view = document.createElement("div");
  await renderLedger(view, []);
  assert.equal(byClass(view, "job").length, 0);
  assert.ok(byClass(view, "empty").some((e) => e.textContent.includes("No failures")), "empty message expected");
  assert.ok(!buttons(view).some((b) => b.textContent === "Older" || b.textContent === "Newer"), "no navigation on an empty ledger");
});

test("does not offer Older when a single page exactly fills", async () => {
  const view = document.createElement("div");
  await renderLedger(view, Array.from({ length: PAGE_SIZE }, (_, i) => entry(i)));
  assert.equal(byClass(view, "job").length, PAGE_SIZE);
  assert.ok(!buttons(view).some((b) => b.textContent === "Older"), "no Older when there is no second page");
});

test("the totals row sums the day columns", async () => {
  const view = document.createElement("div");
  await renderLedger(view, Array.from({ length: 15 }, (_, i) => entry(i)));
  const table = [...walk(view)].find((n) => n.tagName === "TABLE");
  assert.ok(table, "the counts table renders");
  const totalRow = [...walk(table)].filter((n) => n.tagName === "TR").pop();
  const cells = [...walk(totalRow)].filter((n) => n.tagName === "TD").map((n) => n.textContent);
  assert.equal(cells[0], "Total");
  // The day columns are newest first: 2026-11-26 = rate-limited 1 + unknown 5 = 6, 2026-11-25 = rate-limited 2 = 2.
  assert.equal(cells[1], "6");
  assert.equal(cells[2], "2");
  assert.equal(cells[3], "8");
});
