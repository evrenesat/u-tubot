import { api, session } from "../api.js";
import { h, mount } from "../dom.js";
import { button, card, empty, errorText, field, fmtAgo, note, pill, textInput, toast } from "../components.js";

export const TASKS = [
  ["glance", "Glance", "The short side-panel summary shown while you browse."],
  ["summary", "Summary", "The long summary view and prompt-set summaries."],
  ["answer", "Answer", "Questions you ask about a video."],
  ["triage", "Triage", "Batch title scoring behind hide and mark."],
  ["analysis", "Analysis", "Insights and the deep inflation check."],
];
const CUSTOM = "\u0000custom";
const DEFAULT = "";

function flatModels(catalog) {
  const out = [];
  for (const p of catalog.providers) for (const m of p.models) out.push({ ...m, provider: p.name });
  return out;
}

// Per-task model pickers. `settingsPath` is /v1/me/settings or /v1/users/NAME/settings.
export async function modelsForm(settingsPath, doc, catalog, onUpdate) {
  const known = flatModels(catalog);
  const picks = {};
  const customs = {};
  const rows = h("div", { class: "stack" });
  let allowUnlisted = false;
  const msg = h("p", { class: "bad", text: "" });

  function optionsFor(task) {
    const def = doc.defaults.models[task];
    const opts = [{ value: DEFAULT, label: "Server default (" + def + ")" }];
    for (const p of catalog.providers) {
      for (const m of p.models) opts.push({ value: m.value, label: (p.default ? "" : p.name + " / ") + m.id + (m.new ? "  (new)" : ""), group: p.name });
    }
    opts.push({ value: CUSTOM, label: "Other model name..." });
    return opts;
  }

  for (const [task, label, hint] of TASKS) {
    const override = (doc.overrides.models || {})[task] || "";
    const inList = !override || known.some((m) => m.value === override);
    picks[task] = override ? (inList ? override : CUSTOM) : DEFAULT;
    customs[task] = inList ? "" : override;
    const sel = h("select", {});
    let grouped = null;
    for (const opt of optionsFor(task)) {
      const o = h("option", { value: opt.value, text: opt.label });
      if (opt.value === picks[task]) o.selected = true;
      if (opt.group && catalog.providers.length > 1) {
        if (!grouped || grouped.label !== opt.group) {
          grouped = h("optgroup", { label: opt.group });
          sel.appendChild(grouped);
        }
        grouped.appendChild(o);
      } else {
        grouped = null;
        sel.appendChild(o);
      }
    }
    const custom = textInput(customs[task], { placeholder: "provider:model or model name", maxlength: 200 });
    custom.hidden = picks[task] !== CUSTOM;
    sel.addEventListener("change", () => {
      picks[task] = sel.value;
      custom.hidden = sel.value !== CUSTOM;
      if (!custom.hidden) custom.focus();
    });
    custom.addEventListener("input", () => (customs[task] = custom.value.trim()));
    const effective = doc.settings.models[task];
    rows.appendChild(
      h("div", { class: "task-row" }, field(label, sel, hint), custom, h("small", { class: "muted", text: "Running now: " + effective })),
    );
  }

  function patch() {
    const models = {};
    for (const [task] of TASKS) {
      const chosen = picks[task];
      const current = (doc.overrides.models || {})[task] || "";
      const next = chosen === CUSTOM ? customs[task] : chosen;
      if (next !== current) models[task] = next || null;
    }
    return models;
  }

  async function save() {
    msg.textContent = "";
    const models = patch();
    if (!Object.keys(models).length) {
      toast("Nothing changed");
      return;
    }
    try {
      const next = await api(settingsPath, { method: "PUT", body: { version: doc.version, allow_unlisted_models: allowUnlisted, settings: { models } } });
      toast("Models saved");
      onUpdate(next);
    } catch (err) {
      msg.textContent = errorText(err);
      if (err.body && err.body.unlisted && session.admin) {
        msg.appendChild(document.createTextNode(" "));
        msg.appendChild(
          button(
            "Use it anyway",
            async () => {
              allowUnlisted = true;
              await save();
              allowUnlisted = false;
            },
            { kind: "sec" },
          ),
        );
      }
    }
  }

  return h("div", { class: "stack" }, rows, msg, button("Save models", save, { kind: "primary", full: true }));
}

function providerLine(p) {
  const bits = [p.name + (p.default ? " (default)" : ""), p.models.length + " models"];
  if (p.key === "configured") bits.push("key configured");
  else if (p.key === "missing") bits.push("key missing");
  return h(
    "div",
    { class: "provider" },
    h("div", { class: "row between" }, h("strong", { text: bits[0] }), p.ok ? pill("ok", "ok") : pill(p.stale ? "stale" : "unavailable", "bad")),
    h("small", { class: "muted", text: bits.slice(1).join(", ") }),
    p.error ? h("small", { class: "bad", text: p.error }) : null,
    p.added && p.added.length ? h("small", { class: "ok", text: "New: " + p.added.join(", ") }) : null,
  );
}

export async function render(view) {
  let doc = await api("/v1/me/settings");
  let catalog = await api("/v1/models");
  const host = h("div", { class: "stack" });

  async function refresh() {
    catalog = await api("/v1/models/refresh", { method: "POST" });
    toast(catalog.refreshed ? "Model list refreshed" : "Refreshed a moment ago; showing the cached list");
    await draw();
  }

  async function draw() {
    const form = await modelsForm("/v1/me/settings", doc, catalog, (next) => {
      doc = next;
      draw();
    });
    const newCount = catalog.providers.reduce((n, p) => n + p.models.filter((m) => m.new).length, 0);
    mount(
      host,
      h("h1", { class: "page-title", text: "Models" }),
      note("Pick the model each task runs on. Without a choice a task uses the server's configured model."),
      card(
        "Task models",
        form,
      ),
      card(
        "Model list",
        h(
          "div",
          { class: "row between" },
          h("small", { class: "muted", text: "Updated " + fmtAgo(catalog.fetched_at) + (newCount ? ", " + newCount + " new" : "") }),
          button("Refresh", refresh, { kind: "sec" }),
        ),
        catalog.providers.length ? catalog.providers.map(providerLine) : empty("No provider is configured."),
        note("The list is cached for " + Math.round(catalog.cache_ttl_s / 60) + " minutes. Models that appeared recently are marked new. Provider keys never leave the server."),
      ),
    );
  }

  mount(view, host);
  await draw();
}
