// Frontend tests for the Settings page (plan T4): search, staging, review, 409, chips, history.
import { test } from "node:test";
import assert from "node:assert/strict";

import "./dom-stub.mjs";
import { chipFor, clearStaged, groupSettings, matches, pageSettings, parseRest, render, stage, stagedFor, whoWhere } from "../../src/utubot/web/ui/js/pages/settings.js";

const S = (key, title, description, extra = {}) => ({
  key, title, description, group: "ai", type: "bool", default: false, phase: 1, remote: "rw", device_override: true, store: "values", ...extra,
});
const SCHEMA = {
  schema_version: 1,
  groups: [{ id: "ai", title: "AI features", order: 10 }, { id: "cuts", title: "Cuts", order: 50 }],
  settings: [
    S("ai.summary_panel", "Summary panel", "Show the side panel with a summary while you browse."),
    S("ai.auto_cuts", "Apply ready cuts", "Apply a ready director's cut.", { confirm: true, confirm_text: "Apply cuts on all your TVs?" }),
    S("cuts.cut_mode", "Default cut mode", "Quick or watched.", { group: "cuts", type: "enum", default: "quick", choices: [{ value: "quick", label: "Quick" }, { value: "watched", label: "Watched" }] }),
    S("updates.checks", "Check for app updates", "later", { phase: 2 }),
  ],
};

function* walk(n) {
  yield n;
  for (const c of n.children) yield* walk(c);
}
const find = (root, pred) => [...walk(root)].filter(pred);
const buttons = (root, text) => find(root, (n) => n.tagName === "BUTTON" && n.textContent === text);
const rows = (root) => find(root, (n) => n.className.split(/\s+/).includes("set-row"));
const settle = async () => { for (let i = 0; i < 8; i++) await new Promise((r) => setTimeout(r, 0)); };

function install({ conflict = false } = {}) {
  const calls = [];
  const state = { version: 7, values: { "ai.summary_panel": { v: false, rev: 3, from: "default" }, "ai.auto_cuts": { v: false, rev: 0, from: "default" }, "cuts.cut_mode": { v: "quick", rev: 0, from: "default" } } };
  const device = { id: "d1", device: "Den TV", syncs: true, applied_version: 7, applied_at: 1, last_sync_at: 1, overrides: [], pending: [] };
  globalThis.fetch = async (url, init = {}) => {
    const method = init.method || "GET";
    calls.push({ url, method, body: init.body ? JSON.parse(init.body) : null });
    const reply = (status, body) => ({ ok: status < 400, status, json: async () => body });
    if (url === "/v1/settings/schema") return reply(200, SCHEMA);
    if (url.startsWith("/v1/me/settings/status")) return reply(200, { version: state.version, devices: [device] });
    if (url === "/v1/me/devices/d1/settings") return reply(200, { version: state.version, settings: { "ai.summary_panel": { v: false, rev: 3, from: "user" } } });
    if (url.startsWith("/v1/me/settings/history")) return reply(200, { entries: [{ id: 1, at: 100, key: "ai.summary_panel", title: "Summary panel", old: false, new: true, via: "tv", device: "Den TV", by: "owner", outcome: "applied" }] });
    if (url === "/v1/me/settings" && method === "PUT") {
      if (conflict) { state.version = 9; state.values["ai.summary_panel"] = { v: true, rev: 9, from: "user" }; return reply(409, { error: "changed", version: 9 }); }
      return reply(200, { version: ++state.version, values: state.values });
    }
    if (url === "/v1/me/settings") return reply(200, { version: state.version, values: state.values });
    return reply(404, { error: "unexpected " + url });
  };
  return calls;
}

test("search finds a setting by title, a word of its description and its key", () => {
  const s = SCHEMA.settings[0];
  assert.ok(matches(s, "panel"));
  assert.ok(matches(s, "browse"));
  assert.ok(matches(s, "ai.summary"));
  assert.ok(matches(s, "side PANEL"));
  assert.ok(!matches(s, "captions"));
  assert.ok(matches(s, ""));
});

test("groups with no match fold away and phase 2 keys are not shown", () => {
  const values = { "ai.summary_panel": 1, "ai.auto_cuts": 1, "cuts.cut_mode": 1, "updates.checks": 1 };
  const all = pageSettings(SCHEMA, values);
  assert.equal(all.length, 3);
  const groups = groupSettings(SCHEMA, all, "quick");
  assert.deepEqual(groups.map((g) => g.group.id), ["cuts"]);
});

test("staging, undoing by returning to the saved value, and the reset marker", () => {
  const map = new Map();
  assert.equal(stage(map, "a", true, false), 1);
  assert.equal(stage(map, "a", false, false), 0);
  stage(map, "a", null, false);
  assert.equal(map.get("a"), null);
});

test("chips: applied, waiting, own value, old app", () => {
  const base = { device: "Den TV", syncs: true, applied_at: Date.now() / 1000, last_sync_at: Date.now() / 1000, overrides: [], pending: [] };
  assert.match(chipFor(base, "k", null, String).text, /^Applied on Den TV/);
  assert.match(chipFor({ ...base, pending: ["k"] }, "k", null, String).text, /^Waiting for Den TV/);
  const own = chipFor({ ...base, overrides: ["k"] }, "k", 3, String);
  assert.ok(own.own && own.text.includes("has its own value: 3"));
  assert.match(chipFor({ ...base, syncs: false }, "k", null, String).text, /cannot sync yet \(update the app\)/);
});

test("history wording and routes", () => {
  assert.equal(whoWhere({ via: "web" }), "Web");
  assert.equal(whoWhere({ via: "tv", device: "Den TV" }), "Den TV");
  assert.equal(whoWhere({ via: "admin", by: "root" }), "Admin: root");
  assert.equal(whoWhere({ via: "migration", device: "Den TV" }), "First sync of Den TV");
  assert.deepEqual(parseRest(["ai.summary_panel"]), { tab: "my", focus: "ai.summary_panel" });
  assert.deepEqual(parseRest(["tv", "d1"]), { tab: "tv", id: "d1" });
  assert.deepEqual(parseRest(["history"]), { tab: "history" });
});

test("the page draws the schema, stages a change, reviews it and saves with the version", async () => {
  clearStaged("my");
  const calls = install();
  const view = document.createElement("div");
  const stop = await render(view, { rest: [] });
  await settle();
  assert.equal(rows(view).length, 3);
  const row = rows(view)[0];
  const box = find(row, (n) => n.tagName === "INPUT" && n.type === "checkbox")[0];
  box.checked = true;
  box.dispatch("change");
  assert.equal(stagedFor("my").get("ai.summary_panel"), true);
  assert.ok(find(view, (n) => n.tagName === "BUTTON" && /^Review 1 change$/.test(n.textContent)).length === 1);
  buttons(view, "Review 1 change")[0].dispatch("click");
  assert.ok(view.textContent.includes("Summary panel: Off → On"));
  buttons(view, "Save")[0].dispatch("click");
  await settle();
  const put = calls.find((c) => c.method === "PUT");
  assert.deepEqual(put.body, { version: 7, settings: { "ai.summary_panel": true } });
  assert.equal(stagedFor("my").size, 0);
  stop();
});

test("discard drops the staged changes", async () => {
  clearStaged("my");
  install();
  const view = document.createElement("div");
  const stop = await render(view, { rest: [] });
  await settle();
  const box = find(rows(view)[0], (n) => n.tagName === "INPUT" && n.type === "checkbox")[0];
  box.checked = true;
  box.dispatch("change");
  buttons(view, "Review 1 change")[0].dispatch("click");
  buttons(view, "Discard")[0].dispatch("click");
  await settle();
  assert.equal(stagedFor("my").size, 0);
  assert.equal(buttons(view, "Save").length, 0);
  stop();
});

test("a 409 reloads and keeps the staged changes that still apply", async () => {
  clearStaged("my");
  install({ conflict: true });
  const view = document.createElement("div");
  const stop = await render(view, { rest: [] });
  await settle();
  stagedFor("my").set("ai.summary_panel", true); // the web now says true as well: no longer a change
  stagedFor("my").set("cuts.cut_mode", "watched"); // still a change
  window.confirm = () => true;
  const box = find(rows(view)[1], (n) => n.tagName === "INPUT" && n.type === "checkbox")[0];
  box.checked = true;
  box.dispatch("change");
  buttons(view, "Review 3 changes")[0].dispatch("click");
  buttons(view, "Save")[0].dispatch("click");
  await settle();
  const map = stagedFor("my");
  assert.ok(!map.has("ai.summary_panel"));
  assert.equal(map.get("cuts.cut_mode"), "watched");
  assert.equal(map.get("ai.auto_cuts"), true);
  stop();
});

test("the TV tab and the History tab draw", async () => {
  install();
  const tv = document.createElement("div");
  let stop = await render(tv, { rest: ["tv", "d1"] });
  await settle();
  assert.ok(tv.textContent.includes("Den TV") && tv.textContent.includes("Summary panel"));
  stop();
  const hist = document.createElement("div");
  stop = await render(hist, { rest: ["history"] });
  await settle();
  assert.ok(hist.textContent.includes("Off → On") && hist.textContent.includes("Den TV"));
  stop();
});
