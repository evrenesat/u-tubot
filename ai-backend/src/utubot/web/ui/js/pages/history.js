import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { button, card, empty, fmtAgo, fmtNumber, note, pill, toast } from "../components.js";

const HISTORY_LIMIT = 100;
const OUTCOME_KIND = { ok: "ok", failed: "bad", refused: "bad", cancelled: "warn", clarify: "warn", none: "" };
const MARK_LABELS = { stt_ms: "speech", intent_ms: "intent", ack_ms: "TV", total_ms: "total" };

function argsText(args) {
  const parts = Object.entries(args || {}).map(([k, v]) => k + ": " + (typeof v === "string" ? v : JSON.stringify(v)));
  return parts.join(", ");
}

function marksText(marks) {
  const parts = Object.entries(marks || {}).map(([k, v]) => (MARK_LABELS[k] || k) + " " + fmtNumber(Math.round(v)) + " ms");
  return parts.join(" · ");
}

// The text of each spoken command and what it did, kept for the retention the user chose (never audio).
export async function render(view) {
  const host = h("div", { class: "stack" });

  async function load() {
    const { commands, retention_days: days } = await api("/v1/voice/commands", { query: { limit: HISTORY_LIMIT } });
    draw(commands, days);
  }

  function entry(c) {
    const detail = [c.tool, argsText(c.args)].filter(Boolean).join(" · ");
    return h(
      "div",
      { class: "job" },
      h(
        "div",
        { class: "row between nowrap" },
        h("strong", { class: "job-title", text: c.text ? "“" + c.text + "”" : "(no text)" }),
        button(
          "Delete",
          async () => {
            await api("/v1/voice/commands/" + c.id, { method: "DELETE" });
            toast("Deleted");
            await load();
          },
          { kind: "danger" },
        ),
      ),
      h("div", { class: "row" }, pill(c.outcome, OUTCOME_KIND[c.outcome] || ""), h("small", { class: "muted", text: detail })),
      h("small", { class: "muted", text: [fmtAgo(c.at), c.device, marksText(c.marks)].filter(Boolean).join(" · ") }),
    );
  }

  function draw(commands, days) {
    const keeps = days ? "Kept for " + days + (days === 1 ? " day" : " days") + "." : "Nothing is kept (retention is 0 days).";
    mount(
      host,
      h("h1", { class: "page-title", text: "Voice history" }),
      card(
        "What you said",
        note(keeps + " Text only: no audio is stored anywhere. Change the retention under TVs, Voice control."),
        commands.length ? commands.map(entry) : empty("Nothing here yet."),
        commands.length
          ? button(
              "Delete all",
              async () => {
                if (!window.confirm("Delete the whole voice history?")) return;
                await api("/v1/voice/commands", { method: "DELETE" });
                toast("History deleted");
                await load();
              },
              { kind: "danger", full: true },
            )
          : null,
      ),
    );
  }

  mount(view, host);
  await load();
}
