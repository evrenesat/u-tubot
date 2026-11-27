import { api, ApiError, session } from "../api.js";
import { h, mount } from "../dom.js";
import { button, card, chipEditor, empty, errorText, every, fmtAgo, fmtTime, note, numberInput, pill, segmented, select, slider, switchRow, textInput, toast } from "../components.js";

// The Settings page (ai/WEB_SETTINGS_PLAN.md, section 5): every setting from the schema, the TVs' own
// values, a review before saving and the History. Nothing here names a setting: the page draws what
// GET /v1/settings/schema lists.

const POLL_MS = 5000;
const MAX_PHASE = 1;
const HISTORY_LIMIT = 100;
const SEARCHABLE = ["title", "description", "key"];
const LINKED_PAGES = { model: ["#/models", "Models"], prompt: ["#/prompts", "Prompts"] };

// Staged changes live outside the page so a tab switch or a reload keeps them. Key "my" is the user's
// own values, otherwise a TV id. A value of null means "back to the default".
const staged = new Map();

export function stagedFor(scope) {
  if (!staged.has(scope)) staged.set(scope, new Map());
  return staged.get(scope);
}

export function clearStaged(scope) {
  staged.delete(scope);
}

// ---- pure helpers (tested without a browser) -----------------------------------------------

export function matches(setting, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  return q.split(/\s+/).every((word) => SEARCHABLE.some((field) => String(setting[field] || "").toLowerCase().includes(word)));
}

export function fmtValue(setting, value) {
  if (value === null || value === undefined) return "default";
  if (setting.type === "bool") return value ? "On" : "Off";
  if (setting.type === "enum") {
    const choice = (setting.choices || []).find((c) => c.value === value);
    return choice ? choice.label : String(value);
  }
  if (setting.type === "list") return value.length ? value.join(", ") : "none";
  if (setting.type === "int" || setting.type === "float") return String(value) + (setting.unit ? " " + setting.unit : "");
  return String(value) === "" ? "default" : String(value);
}

export function sameValue(a, b) {
  return JSON.stringify(a) === JSON.stringify(b);
}

// Put a change in or out of the staged map: a value equal to what is saved is no change.
export function stage(map, key, value, base) {
  if (value !== null && sameValue(value, base)) map.delete(key);
  else map.set(key, value);
  return map.size;
}

export function pageSettings(schema, values) {
  return schema.settings.filter((s) => (s.phase || 1) <= MAX_PHASE && s.remote === "rw" && s.type !== "secret" && values && s.key in values);
}

export function groupSettings(schema, settings, query) {
  const groups = [];
  for (const g of [...schema.groups].sort((a, b) => a.order - b.order)) {
    const rows = settings.filter((s) => s.group === g.id && matches(s, query));
    if (rows.length) groups.push({ group: g, rows });
  }
  return groups;
}

// One chip per TV for a setting that a TV may hold its own value of.
export function chipFor(device, key, ownValue, fmt) {
  if (!device.syncs) return { kind: "warn", text: device.device + " cannot sync yet (update the app)" };
  if (device.overrides.includes(key)) return { kind: "", text: device.device + " has its own value: " + fmt(ownValue), own: true };
  if (device.pending.includes(key)) return { kind: "warn", text: "Waiting for " + device.device + " (last seen " + fmtAgo(device.last_sync_at) + ")" };
  return { kind: "ok", text: "Applied on " + device.device + ", " + fmtAgo(device.applied_at || device.last_sync_at) };
}

export function whoWhere(entry) {
  if (entry.via === "tv") return entry.device || "a TV";
  if (entry.via === "migration") return "First sync of " + (entry.device || "a TV");
  if (entry.via === "admin") return "Admin: " + (entry.by || "?");
  return "Web";
}

export function parseRest(rest) {
  const [first, second] = rest || [];
  if (first === "history") return { tab: "history" };
  if (first === "tv" && second) return { tab: "tv", id: second };
  if (first && first.includes(".")) return { tab: "my", focus: first };
  return { tab: "my" };
}

// ---- controls -------------------------------------------------------------------------------

function control(setting, value, onChange, disabled) {
  switch (setting.type) {
    case "bool": {
      const row = switchRow(setting.title, setting.description, value, onChange);
      row.input.disabled = !!disabled;
      return { el: row, inline: true };
    }
    case "int": {
      const input = numberInput(value, { min: setting.min, max: setting.max, step: setting.step || 1 });
      input.disabled = !!disabled;
      input.addEventListener("input", () => {
        const n = Math.round(Number(input.value));
        if (input.value !== "" && Number.isFinite(n)) onChange(Math.min(setting.max, Math.max(setting.min, n)));
      });
      const presets = (setting.presets || []).map((p) => {
        const btn = h("button", { type: "button", class: "btn sec small", text: String(p) });
        btn.disabled = !!disabled;
        btn.addEventListener("click", () => {
          input.value = p;
          onChange(p);
        });
        return btn;
      });
      const unit = setting.unit ? h("span", { class: "muted", text: setting.unit }) : null;
      return { el: h("div", { class: "row nowrap" }, input, unit), extra: presets.length ? h("div", { class: "row" }, presets) : null };
    }
    case "float": {
      const wrap = slider({ label: setting.title, value, min: setting.min, max: setting.max, step: setting.step || 0.05, format: (v) => Number(v).toFixed(2), hint: setting.description, onChange });
      return { el: wrap, inline: true };
    }
    case "enum": {
      const choices = setting.choices.map((c) => ({ value: c.value, label: c.label }));
      const sel = select(choices, value, onChange);
      sel.disabled = !!disabled;
      return { el: sel };
    }
    case "list": {
      const editor = chipEditor(value || [], { placeholder: "Add", onChange: (items) => onChange([...items]), max: setting.max_items });
      return { el: editor };
    }
    case "model":
    case "prompt": {
      const [href, label] = LINKED_PAGES[setting.type];
      return { el: h("div", { class: "row" }, h("strong", { text: String(value || "default") }), h("a", { href, text: "Change on the " + label + " page" })) };
    }
    default: {
      const input = textInput(value, { maxlength: setting.max_len });
      input.disabled = !!disabled;
      input.addEventListener("input", () => onChange(input.value));
      return { el: input };
    }
  }
}

// ---- the page -------------------------------------------------------------------------------

export async function render(view, { rest = [] } = {}) {
  const where = parseRest(rest);
  const S = { schema: null, doc: null, status: null, devDocs: {}, history: null, query: "", signature: "" };
  const host = h("div", { class: "stack" });
  const bar = h("div", { class: "stage-host" });
  let stopPoll = null;
  let reviewOpen = false;

  const deviceName = (id) => (S.status.devices.find((d) => d.id === id) || {}).device || "this TV";
  const scopeKey = () => (where.tab === "tv" ? where.id : "my");

  async function loadAll() {
    const [schema, doc, status] = await Promise.all([api("/v1/settings/schema"), api("/v1/me/settings"), api("/v1/me/settings/status")]);
    S.schema = schema;
    S.doc = doc;
    S.status = status;
    S.devDocs = {};
    await Promise.all(
      status.devices.map(async (d) => {
        try {
          S.devDocs[d.id] = await api("/v1/me/devices/" + encodeURIComponent(d.id) + "/settings");
        } catch {
          /* a TV that vanished meanwhile */
        }
      }),
    );
    S.signature = signatureOf(status);
  }

  function signatureOf(status) {
    return JSON.stringify([status.version, status.devices.map((d) => [d.id, d.applied_version, d.applied_at, d.last_sync_at, d.overrides, d.pending])]);
  }

  function setting(key) {
    return S.schema.settings.find((s) => s.key === key);
  }

  // ---- rows
  function row(s, { base, from, scope, disabled }) {
    const map = stagedFor(scope);
    const isStaged = map.has(s.key);
    const shown = isStaged && map.get(s.key) !== null ? map.get(s.key) : base;
    const metaHost = h("div", { class: "set-meta" });
    const onChange = (v) => {
      stage(map, s.key, v, base);
      drawBar();
      drawMeta();
    };
    function drawMeta() {
      const resetting = map.has(s.key) && map.get(s.key) === null;
      mount(
        metaHost,
        s.default !== undefined && s.default !== "" ? h("small", { class: "muted", text: "Default: " + fmtValue(s, s.default) }) : null,
        resetting ? pill("Back to default when saved", "warn") : null,
        scope === "my" && from === "user" && !resetting && s.store !== undefined
          ? h("button", { type: "button", class: "linklike", text: "Reset", onClick: () => (stage(map, s.key, null, base), draw()) })
          : null,
        scope !== "my" && from === "device" && !resetting
          ? h("button", { type: "button", class: "linklike", text: "Use my default", onClick: () => (stage(map, s.key, null, base), draw()) })
          : null,
        resetting ? h("button", { type: "button", class: "linklike", text: "Undo", onClick: () => (map.delete(s.key), draw()) }) : null,
      );
    }
    const c = control(s, shown, onChange, disabled || (isStaged && map.get(s.key) === null));
    drawMeta();
    const el = h(
      "div",
      { class: "set-row" + (where.focus === s.key ? " focus" : ""), id: "set-" + s.key, dataset: { key: s.key } },
      c.inline ? null : h("div", { class: "set-head" }, h("strong", { text: s.title }), s.advanced ? pill("Advanced") : null, h("small", { class: "muted", text: s.description })),
      c.el,
      c.extra,
      metaHost,
    );
    if (scope === "my" && s.device_override) {
      const chips = h("div", { class: "chips-row" });
      for (const d of S.status.devices) {
        const own = (S.devDocs[d.id] || { settings: {} }).settings[s.key];
        const chip = chipFor(d, s.key, own ? own.v : null, (v) => fmtValue(s, v));
        chips.appendChild(
          h(
            "span",
            { class: "sync-chip" },
            pill(chip.text, chip.kind),
            chip.own ? h("button", { type: "button", class: "linklike", text: "Use my default", onClick: () => useDefaultOn(d.id, s) }) : null,
            chip.own ? h("button", { type: "button", class: "linklike", text: "Use for all my TVs", onClick: () => promote(d.id, s, own.v) }) : null,
          ),
        );
      }
      if (chips.children.length) el.appendChild(chips);
    }
    return el;
  }

  async function useDefaultOn(deviceId, s) {
    await api("/v1/me/devices/" + encodeURIComponent(deviceId) + "/settings", { method: "PUT", body: { version: S.status.version, settings: { [s.key]: null } } });
    toast(deviceName(deviceId) + " now follows your default");
    await refresh();
  }

  async function promote(deviceId, s, value) {
    const doc = await api("/v1/me/settings", { method: "PUT", body: { version: S.doc.version, settings: { [s.key]: value } } });
    await api("/v1/me/devices/" + encodeURIComponent(deviceId) + "/settings", { method: "PUT", body: { version: doc.version, settings: { [s.key]: null } } });
    toast(s.title + " is now the same on all your TVs");
    await refresh();
  }

  // ---- the review bar
  function changesOf(scope) {
    const out = [];
    for (const [key, value] of stagedFor(scope)) {
      const s = setting(key);
      if (!s) continue;
      const baseDoc = scope === "my" ? S.doc.values[key] : (S.devDocs[scope] || { settings: {} }).settings[key];
      const old = baseDoc ? baseDoc.v : null;
      out.push({ s, key, old, next: value });
    }
    return out;
  }

  function drawBar() {
    const scope = scopeKey();
    const changes = where.tab === "history" ? [] : changesOf(scope);
    if (!changes.length) {
      reviewOpen = false;
      mount(bar);
      return;
    }
    const label = "Review " + changes.length + " change" + (changes.length === 1 ? "" : "s");
    const where_ = scope === "my" ? "your settings" : deviceName(scope);
    mount(
      bar,
      h(
        "div",
        { class: "stage-bar" },
        reviewOpen
          ? h(
              "div",
              { class: "review" },
              h("strong", { text: "Saving to " + where_ }),
              h(
                "ul",
                { class: "plain" },
                changes.map((c) =>
                  h("li", {}, h("span", { text: c.s.title + ": " }), h("span", { class: "muted", text: fmtValue(c.s, c.old) }), h("span", { text: " → " }), h("strong", { text: c.next === null ? "default" : fmtValue(c.s, c.next) })),
                ),
              ),
              h("div", { class: "row" }, button("Save", () => save(scope, changes), { kind: "primary" }), button("Discard", () => discard(scope), { kind: "sec" })),
            )
          : null,
        reviewOpen ? null : button(label, () => ((reviewOpen = true), drawBar()), { kind: "primary", full: true }),
      ),
    );
  }

  function discard(scope) {
    clearStaged(scope);
    reviewOpen = false;
    draw();
  }

  async function save(scope, changes) {
    for (const c of changes) {
      if (c.s.confirm && c.next !== c.old && !window.confirm(c.s.confirm_text || "Change " + c.s.title + "?")) return;
    }
    const settings = {};
    for (const c of changes) settings[c.key] = c.next;
    const path = scope === "my" ? "/v1/me/settings" : "/v1/me/devices/" + encodeURIComponent(scope) + "/settings";
    const version = scope === "my" ? S.doc.version : S.devDocs[scope].version;
    try {
      await api(path, { method: "PUT", body: { version, settings } });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        await refresh();
        for (const c of changes) {
          const now = (scope === "my" ? S.doc.values[c.key] : (S.devDocs[scope] || { settings: {} }).settings[c.key]) || { v: null };
          if (c.next !== null && sameValue(now.v, c.next)) stagedFor(scope).delete(c.key);
        }
        reviewOpen = true;
        draw();
        toast("Settings changed elsewhere. Your changes are kept; review them again.", "bad");
        return;
      }
      throw err;
    }
    clearStaged(scope);
    reviewOpen = false;
    toast(scope === "my" ? "Saved. Your TVs get it within about 30 seconds." : "Saved for " + deviceName(scope) + ".");
    await refresh();
  }

  async function refresh() {
    await loadAll();
    draw();
  }

  // ---- tabs and bodies
  function tabs() {
    const items = [["#/settings", "My settings", where.tab === "my"]];
    for (const d of S.status.devices) items.push(["#/settings/tv/" + encodeURIComponent(d.id), d.device, where.tab === "tv" && where.id === d.id]);
    items.push(["#/settings/history", "History", where.tab === "history"]);
    return h("nav", { class: "tabs", "aria-label": "Settings sections" }, items.map(([href, label, on]) => h("a", { href, class: "tab" + (on ? " on" : ""), "aria-current": on ? "page" : null, text: label })));
  }

  function searchBox() {
    const input = h("input", { type: "search", placeholder: "Search settings", "aria-label": "Search settings", autocomplete: "off", spellcheck: "false" });
    input.value = S.query;
    input.addEventListener("input", () => {
      S.query = input.value;
      drawBody();
    });
    return input;
  }

  const body = h("div", { class: "stack" });

  function myBody() {
    const settings = pageSettings(S.schema, S.doc.values);
    const groups = groupSettings(S.schema, settings, S.query);
    if (!groups.length) return [empty("No setting matches \"" + S.query + "\".")];
    return groups.map(({ group, rows }) =>
      card(
        group.title,
        rows.map((s) => row(s, { base: S.doc.values[s.key].v, from: S.doc.values[s.key].from, scope: "my" })),
      ),
    );
  }

  function tvBody() {
    const dev = S.status.devices.find((d) => d.id === where.id);
    const doc = S.devDocs[where.id];
    if (!dev || !doc) return [empty("This TV is not linked any more.")];
    const synced = S.schema.settings.filter((s) => doc.settings[s.key] && matches(s, S.query));
    const facts = card(
      dev.device,
      dev.syncs ? null : note("This TV cannot sync yet. Update the app on it, then it shows up here.", "warn"),
      h(
        "dl",
        { class: "kv" },
        fact("App version", dev.app_version || "unknown"),
        fact("Last sync", dev.syncs ? fmtAgo(dev.last_sync_at) : "never"),
        fact("Applied version", dev.syncs ? String(dev.applied_version) : "none"),
        fact("Own values", dev.overrides.length ? String(dev.overrides.length) : "none"),
        dev.report && dev.report.caption_store_bytes !== undefined ? fact("Caption storage", Math.round(dev.report.caption_store_bytes / 1024) + " KiB") : null,
      ),
    );
    const groups = S.schema.groups
      .slice()
      .sort((a, b) => a.order - b.order)
      .map((g) => ({ g, rows: synced.filter((s) => s.group === g.id) }))
      .filter((x) => x.rows.length);
    if (!groups.length) return [facts, empty("No setting matches \"" + S.query + "\".")];
    return [
      facts,
      ...groups.map(({ g, rows }) =>
        card(
          g.title,
          rows.map((s) => row(s, { base: doc.settings[s.key].v, from: doc.settings[s.key].from, scope: where.id })),
        ),
      ),
    ];
  }

  function fact(label, value) {
    return h("div", {}, h("dt", { text: label }), h("dd", { text: value }));
  }

  async function historyBody() {
    if (!S.history) S.history = (await api("/v1/me/settings/history", { query: { limit: HISTORY_LIMIT } })).entries;
    if (!S.history.length) return [card("History", empty("Nothing has changed yet."))];
    return [
      card(
        "History",
        S.history.map((e) =>
          h(
            "div",
            { class: "job" },
            h("div", { class: "row between nowrap" }, h("strong", { class: "job-title", text: e.title }), e.outcome === "superseded" ? pill("Not applied", "warn") : null),
            h("span", {}, h("span", { class: "muted", text: fmtHist(e, e.old) }), h("span", { text: " → " }), h("strong", { text: fmtHist(e, e.new) })),
            h("small", { class: "muted", text: whoWhere(e) + " · " + fmtTime(e.at) + (e.outcome === "superseded" ? " · the web value was newer" : "") }),
          ),
        ),
      ),
    ];
  }

  function fmtHist(e, value) {
    const s = setting(e.key);
    return s ? fmtValue(s, value) : String(value);
  }

  async function drawBody() {
    const kids = where.tab === "history" ? await historyBody() : where.tab === "tv" ? tvBody() : myBody();
    mount(body, kids);
    if (where.focus && typeof document.getElementById === "function") {
      const el = document.getElementById("set-" + where.focus);
      if (el && el.scrollIntoView) el.scrollIntoView({ block: "center" });
    }
  }

  function draw() {
    mount(
      host,
      h("h1", { class: "page-title", text: "Settings" }),
      tabs(),
      where.tab === "history" ? null : searchBox(),
      body,
    );
    drawBar();
    return drawBody();
  }

  await loadAll();
  mount(view, host, bar);
  await draw();

  stopPoll = every(POLL_MS, async () => {
    try {
      const status = await api("/v1/me/settings/status");
      if (signatureOf(status) === S.signature) return;
      S.history = null;
      await refresh();
    } catch {
      /* the page keeps what it has until the server answers again */
    }
  });
  return () => {
    if (stopPoll) stopPoll();
  };
}

export { errorText, session };
