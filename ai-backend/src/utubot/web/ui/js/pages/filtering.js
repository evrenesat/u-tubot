import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { button, card, chipEditor, errorText, note, numberInput, field, slider, switchRow, toast } from "../components.js";

const NEVER = 1.01;
const SLIDER_MAX = 1.05;
const fmtScore = (v) => (v > 1 ? "never" : v.toFixed(2));
const toScore = (v) => (v > 1 ? NEVER : Math.round(v * 100) / 100);

const THRESHOLDS = [
  ["hide_clickbait_above", "Hide clickbait at or above", "How clickbaity a title must be before the card disappears."],
  ["mark_clickbait_above", "Mark clickbait at or above", "Adds the Clickbait mark."],
  ["hide_low_quality_above", "Hide low quality at or above", "AI-narration slop, spam and filler."],
  ["mark_low_quality_above", "Mark low quality at or above", "Adds the Low quality mark."],
];

// Hide/mark rules. `settingsPath` is /v1/me/settings or /v1/users/NAME/settings.
export function filteringForm(settingsPath, doc, onUpdate) {
  const current = doc.settings.filtering;
  const draft = { ...current };
  const msg = h("p", { class: "bad", text: "" });

  const hideTopics = chipEditor(current.hide_topics, { placeholder: "e.g. reaction videos", onChange: (v) => (draft.hide_topics = [...v]) });
  const markTopics = chipEditor(current.mark_topics, { placeholder: "e.g. celebrity gossip", onChange: (v) => (draft.mark_topics = [...v]) });
  const sliders = THRESHOLDS.map(([key, label, hint]) =>
    slider({ label, hint, value: Math.min(current[key], SLIDER_MAX), min: 0, max: SLIDER_MAX, step: 0.05, format: fmtScore, onChange: (v) => (draft[key] = toScore(v)) }),
  );
  const inflated = slider({
    label: "Mark inflated when real content is at most",
    hint: "Share of the runtime that carries information, from the deep analysis.",
    value: current.mark_inflated_ratio_below,
    min: 0,
    max: 1,
    step: 0.05,
    format: (v) => Math.round(v * 100) + "%",
    onChange: (v) => (draft.mark_inflated_ratio_below = Math.round(v * 100) / 100),
  });
  const minutes = numberInput(Math.round(current.inflated_min_duration_s / 60), { min: 0, max: 1440, step: 1 });
  minutes.addEventListener("input", () => (draft.inflated_min_duration_s = Math.max(0, Math.round(Number(minutes.value) || 0)) * 60));
  const markOnly = switchRow("Mark only, never hide", "On the TV, cards that would be hidden show a mark instead.", current.mark_only, (v) => (draft.mark_only = v));
  const answer = switchRow("Show the answer in the mark", "Appends the short answer to a card's label when it is known.", current.answer_in_label, (v) => (draft.answer_in_label = v));

  async function save() {
    msg.textContent = "";
    const changes = {};
    for (const key of Object.keys(draft)) {
      if (JSON.stringify(draft[key]) !== JSON.stringify(current[key])) changes[key] = draft[key];
    }
    if (!Object.keys(changes).length) {
      toast("Nothing changed");
      return;
    }
    try {
      const next = await api(settingsPath, { method: "PUT", body: { version: doc.version, settings: { filtering: changes } } });
      toast("Filtering saved");
      onUpdate(next);
    } catch (err) {
      msg.textContent = errorText(err);
    }
  }

  async function reset() {
    const keys = Object.keys((doc.overrides || {}).filtering || {});
    if (!keys.length) {
      toast("Already using the defaults");
      return;
    }
    const filtering = Object.fromEntries(keys.map((k) => [k, null]));
    onUpdate(await api(settingsPath, { method: "PUT", body: { version: doc.version, settings: { filtering } } }));
    toast("Back to the defaults");
  }

  return h(
    "div",
    { class: "stack" },
    card("Hide these topics", note("Videos that clearly belong to a topic are removed. Short, concrete phrases work best."), hideTopics),
    card("Mark these topics", note("Videos get a mark with the topic name instead."), markTopics),
    card("Thresholds", h("div", { class: "stack" }, sliders, inflated, field("Ignore videos shorter than (minutes) for the inflated mark", minutes))),
    card("Behaviour", markOnly, answer),
    msg,
    h("div", { class: "row" }, button("Save filtering", save, { kind: "primary" }), button("Reset to defaults", reset, { kind: "sec" })),
  );
}

export async function render(view) {
  let doc = await api("/v1/me/settings");
  const host = h("div", { class: "stack" });
  function draw() {
    mount(
      host,
      h("h1", { class: "page-title", text: "Filters" }),
      note("What gets hidden or marked on your TV. Changes apply to the next row you open."),
      filteringForm("/v1/me/settings", doc, (next) => {
        doc = next;
        draw();
      }),
    );
  }
  mount(view, host);
  draw();
}
