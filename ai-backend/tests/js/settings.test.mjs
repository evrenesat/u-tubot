// Frontend tests for the Settings page (plan T4): search, staging, review, 409, chips, history.
import { test } from "node:test";
import assert from "node:assert/strict";

import "./dom-stub.mjs";
import { chipFor, clearStaged, copyChanges, groupSettings, matches, pageSettings, parseRest, render, stage, stagedFor, tooNewFor, whoWhere } from "../../src/utubot/web/ui/js/pages/settings.js";

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
    S("secrets.token", "A secret", "later", { phase: 3 }),
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

test("groups with no match fold away and later-phase keys are not shown", () => {
  const values = { "ai.summary_panel": 1, "ai.auto_cuts": 1, "cuts.cut_mode": 1, "secrets.token": 1 };
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
  // a TV on an older schema cannot take a key that is newer than its app
  assert.match(chipFor({ ...base, schema_version: 1 }, "k", null, String, 2).text, /cannot sync yet \(update the app\)/);
  assert.match(chipFor({ ...base, schema_version: 2 }, "k", null, String, 2).text, /^Applied on Den TV/);
  assert.match(chipFor({ ...base }, "k", null, String).text, /^Applied on Den TV/);
});

const TV_SCHEMA = {
  schema_version: 2,
  groups: [{ id: "tv", title: "This TV only", order: 90 }, { id: "ai", title: "AI features", order: 10 }],
  settings: [
    S("ai.summary_panel", "Summary panel", "Side panel."),
    S("updates.checks", "Check for app updates", "Look for new versions.", { since: 2, clients: ["tv", "web"] }),
    S("updates.interval_minutes", "Update check interval", "How often.", { group: "tv", scope: "device", since: 2, clients: ["tv"], type: "enum", default: 5, choices: [{ value: 5, label: "5 minutes" }, { value: 60, label: "1 hour" }] }),
    S("ai.cut_jump", "Cut jump keys", "Which keys.", { group: "tv", scope: "device", since: 2, clients: ["tv"], type: "enum", default: "left_right", choices: [{ value: "left_right", label: "Left and right" }, { value: "off", label: "Off" }] }),
    S("secrets.token", "A secret", "later", { phase: 3, type: "secret" }),
  ],
};

test("a setting that belongs to one TV is not on My settings, an update-check switch is", () => {
  const values = Object.fromEntries(TV_SCHEMA.settings.map((s) => [s.key, 1]));
  assert.deepEqual(pageSettings(TV_SCHEMA, values).map((s) => s.key), ["ai.summary_panel", "updates.checks"]);
});

const doc = (settings) => ({ settings: Object.fromEntries(Object.entries(settings).map(([k, [v, from]]) => [k, { v, from, rev: 1 }])) });

test("copying a TV stages only the keys that differ and only keys a TV may own", () => {
  const source = doc({
    "ai.summary_panel": [true, "device"],
    "updates.checks": [true, "user"],
    "updates.interval_minutes": [60, "device"],
    "ai.cut_jump": ["left_right", "user"],
    "secrets.token": ["x", "device"],
  });
  const target = doc({
    "ai.summary_panel": [false, "user"],
    "updates.checks": [false, "device"],
    "updates.interval_minutes": [5, "user"],
    "ai.cut_jump": ["off", "device"],
    "secrets.token": ["y", "user"],
  });
  const got = copyChanges(TV_SCHEMA, source, target);
  assert.deepEqual([...got], [["ai.summary_panel", true], ["updates.checks", null], ["updates.interval_minutes", 60], ["ai.cut_jump", null]]);
  assert.equal(copyChanges(TV_SCHEMA, source, source).size, 0);
});

test("settings newer than a TV's app are listed for the note", () => {
  const old = { syncs: true, schema_version: 1 };
  assert.deepEqual(tooNewFor(TV_SCHEMA, old).map((s) => s.key), ["updates.checks", "updates.interval_minutes", "ai.cut_jump"]);
  assert.equal(tooNewFor(TV_SCHEMA, { syncs: true, schema_version: 2 }).length, 0);
  assert.equal(tooNewFor(TV_SCHEMA, { syncs: false }).length, 0);
});

test("the TV tab stages a copy of another TV and saves it with the TV's version", async () => {
  clearStaged("d2");
  const calls = [];
  const status = { version: 4, devices: [
    { id: "d1", device: "Den TV", syncs: true, schema_version: 2, applied_version: 4, applied_at: 1, last_sync_at: 1, overrides: ["updates.interval_minutes"], pending: [] },
    { id: "d2", device: "Bedroom TV", syncs: true, schema_version: 2, applied_version: 4, applied_at: 1, last_sync_at: 1, overrides: [], pending: [] },
  ] };
  const docs = {
    d1: { version: 4, settings: { "ai.summary_panel": { v: true, rev: 1, from: "device" }, "updates.checks": { v: true, rev: 1, from: "user" }, "updates.interval_minutes": { v: 60, rev: 3, from: "device" }, "ai.cut_jump": { v: "left_right", rev: 0, from: "default" } } },
    d2: { version: 4, settings: { "ai.summary_panel": { v: false, rev: 1, from: "user" }, "updates.checks": { v: true, rev: 1, from: "user" }, "updates.interval_minutes": { v: 5, rev: 0, from: "default" }, "ai.cut_jump": { v: "left_right", rev: 0, from: "default" } } },
  };
  globalThis.fetch = async (url, init = {}) => {
    const method = init.method || "GET";
    calls.push({ url, method, body: init.body ? JSON.parse(init.body) : null });
    const reply = (code, body) => ({ ok: code < 400, status: code, json: async () => body });
    if (url === "/v1/settings/schema") return reply(200, TV_SCHEMA);
    if (url.startsWith("/v1/me/settings/status")) return reply(200, status);
    if (url === "/v1/me/devices/d1/settings") return reply(200, docs.d1);
    if (url === "/v1/me/devices/d2/settings" && method === "PUT") return reply(200, docs.d2);
    if (url === "/v1/me/devices/d2/settings") return reply(200, docs.d2);
    if (url === "/v1/me/settings") return reply(200, { version: 4, values: { "ai.summary_panel": { v: false, rev: 1, from: "default" }, "updates.checks": { v: true, rev: 1, from: "default" } } });
    return reply(404, { error: "unexpected " + url });
  };
  const view = document.createElement("div");
  const stop = await render(view, { rest: ["tv", "d2"] });
  await settle();
  assert.ok(view.textContent.includes("Copy from another TV"));
  assert.ok(view.textContent.includes("5 minutes"));
  buttons(view, "Stage the copy")[0].dispatch("click");
  await settle();
  assert.deepEqual([...stagedFor("d2")], [["ai.summary_panel", true], ["updates.interval_minutes", 60]]);
  assert.ok(find(view, (n) => n.tagName === "BUTTON" && /^Save$/.test(n.textContent)).length === 1);
  buttons(view, "Save")[0].dispatch("click");
  await settle();
  const put = calls.find((c) => c.method === "PUT");
  assert.deepEqual(put.body, { version: 4, settings: { "ai.summary_panel": true, "updates.interval_minutes": 60 } });
  stop();
});

test("a TV on an old app says which settings wait for the update", async () => {
  clearStaged("d9");
  const dev = { id: "d9", device: "Old TV", syncs: true, schema_version: 1, applied_version: 1, applied_at: 1, last_sync_at: 1, overrides: [], pending: [] };
  globalThis.fetch = async (url) => {
    const reply = (body) => ({ ok: true, status: 200, json: async () => body });
    if (url === "/v1/settings/schema") return reply(TV_SCHEMA);
    if (url.startsWith("/v1/me/settings/status")) return reply({ version: 1, devices: [dev] });
    if (url.startsWith("/v1/me/devices/")) return reply({ version: 1, settings: { "ai.summary_panel": { v: false, rev: 0, from: "user" } } });
    return reply({ version: 1, values: { "ai.summary_panel": { v: false, rev: 0, from: "default" } } });
  };
  const view = document.createElement("div");
  const stop = await render(view, { rest: ["tv", "d9"] });
  await settle();
  assert.ok(view.textContent.includes("3 settings appear here once you update it"));
  stop();
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
