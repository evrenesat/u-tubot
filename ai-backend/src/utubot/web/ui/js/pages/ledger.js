import { api, session } from "../api.js";
import { h, mount } from "../dom.js";
import { button, card, empty, errorText, fmtAgo, fmtNumber, note, pill, select, statRow, toast } from "../components.js";

// The categories the admin may sort a flagged failure into during triage.
const CATEGORIES = [
  { value: "youtube-refused", label: "YouTube refused" },
  { value: "rate-limited", label: "Rate limited" },
  { value: "timeout", label: "Timed out" },
  { value: "network", label: "Network" },
  { value: "model-error", label: "Model error" },
  { value: "transcript", label: "Transcript" },
  { value: "config", label: "Config" },
  { value: "sync", label: "Sync" },
  { value: "bug", label: "Unexpected" },
  { value: "unknown", label: "Unsorted" },
];

const PERIODS = [7, 14, 30];

function categoryPill(entry) {
  const kind = entry.flagged ? "warn" : (
    { "youtube-refused": "bad", "rate-limited": "warn", "timeout": "warn", "network": "warn",
      "model-error": "bad", "transcript": "", "config": "warn", "sync": "", "bug": "bad", "unknown": "warn" }[entry.category] || ""
  );
  return pill(CATEGORIES.find((c) => c.value === entry.category)?.label || entry.category, kind);
}

function exampleRow(entry, reload) {
  const who = [entry.component, entry.operation].filter(Boolean).join(" · ");
  const job = entry.job_id
    ? h("a", { class: "mono", href: "#/job/" + encodeURIComponent(entry.job_id), text: entry.job_id })
    : (entry.video_id ? h("a", { href: "https://www.youtube.com/watch?v=" + entry.video_id, target: "_blank", rel: "noopener noreferrer", class: "mono", text: entry.video_id }) : null);
  const body = h("div", { class: "mono wrap", text: entry.message });
  const meta = h("small", { class: "muted", text: [who, entry.client ? "on " + entry.client : null, entry.video_id ? "video " + entry.video_id : null].filter(Boolean).join(" · ") });

  let control = h("small", { class: "muted", text: entry.flagged ? "needs triage" : "" });
  if (entry.flagged) {
    control = select(
      CATEGORIES,
      entry.category === "unknown" ? "unknown" : entry.category,
      async (next) => {
        try {
          const r = await api("/v1/admin/ledger/" + entry.id + "/categorize", { method: "POST", body: { category: next } });
          if (r.changed) toast("Classified as " + (CATEGORIES.find((c) => c.value === next)?.label || next));
          await reload();
        } catch (err) {
          toast(errorText(err), "bad");
        }
      },
    );
  }

  return h(
    "div",
    { class: "job" },
    h("div", { class: "row between nowrap" },
      h("div", { class: "row nowrap" }, categoryPill(entry), entry.flagged ? pill("flagged", "warn") : null, h("span", { class: "muted", text: fmtAgo(entry.ts) })),
      control,
    ),
    h("div", { class: "row nowrap" }, job ? h("span", { class: "muted", text: "job" }) : null, job),
    h("div", { class: "row between nowrap" }, h("strong", { text: entry.message }), h("span", { class: "muted", text: who })),
    meta,
  );
}

// A per-category/per-day cell: the day as a column header row, then counts under each category.
function countsTable(doc) {
  if (!doc.counts.length) return null;
  const days = [...new Set(doc.counts.map((c) => c.day))].sort().reverse();
  const cats = [...new Set(doc.counts.map((c) => c.category))];
  const byKey = new Map(doc.counts.map((c) => [c.day + "|" + c.category, c.count]));
  const header = h("th", {}, h("span", { text: "Category / day" }));
  const dayHeaders = days.map((day) => h("th", { class: "num", text: day }));
  const rows = cats.map((cat) => {
    const cells = days.map((day) => h("td", { class: "num", text: String(byKey.get(day + "|" + cat) || 0) }));
    const total = doc.counts.filter((c) => c.category === cat).reduce((sum, c) => sum + c.count, 0);
    return h("tr", {}, h("td", {}, pill(CATEGORIES.find((c) => c.value === cat)?.label || cat)), ...cells, h("td", { class: "num", text: fmtNumber(total) }));
  });
  const totalHeader = days.map((day) => {
    const sum = days.reduce((s, d) => s + (byKey.get(d + "|__all__") || 0), 0);
    return h("th", { class: "num", text: fmtNumber(doc.counts.filter((c) => c.day === d).reduce((s, c) => s + c.count, 0)) });
  });
  const totalRow = h("tr", {}, h("td", {}, h("strong", { text: "Total" })), ...totalHeader, h("th", { class: "num", text: fmtNumber(doc.counts.reduce((s, c) => s + c.count, 0)) }));
  return card(
    "Failures per category per day",
    h("table", {},
      h("thead", {}, h("tr", {}, header, ...dayHeaders, h("th", { class: "num", text: "Total" }))),
      h("tbody", {}, rows.concat([totalRow])),
    ),
    note("Counts over the last " + doc.period_days + " days. A flagged row is a failure whose cause is not yet sorted; triage moves it to a category."),
  );
}

function summaryCard(doc) {
  const total = doc.counts.reduce((s, c) => s + c.count, 0);
  const flagged = doc.counts.filter((c) => c.flagged).reduce((s, c) => s + c.count, 0);
  const byCategory = new Map();
  for (const c of doc.counts) byCategory.set(c.category, (byCategory.get(c.category) || 0) + c.count);
  const tiles = [...byCategory.entries()].map(([cat, n]) =>
    h("div", { class: "pill-tile" }, categoryPill({ category: cat, flagged: cat === "unknown" }), h("span", { class: "num strong", text: fmtNumber(n) })),
  );
  return card(
    "This period",
    h("div", { class: "row nowrap gap" },
      statRow("Failures", fmtNumber(total)),
      statRow("Categories", String(byCategory.size)),
      statRow("Flagged", fmtNumber(flagged), flagged ? "warn" : ""),
    ),
    h("div", { class: "pills", text: tiles.length ? tiles : empty("No failures yet.")     ),
  );
}

export async function render(view, { rest }) {
  let period = rest[1] ? Number(rest[1]) : 14;
  if (!PERIODS.includes(period)) period = 14;
  const host = h("div", { class: "stack" });

  async function load() {
    const doc = await api("/v1/admin/ledger", { query: { period_days: period, limit: 100 } });
    mount(
      host,
      h("a", { class: "back", href: "#/admin", text: "Back to admin" }),
      h("div", { class: "row between nowrap" },
        h("h1", { class: "page-title", text: "Error ledger" }),
        h("div", { class: "row" },
          select(
            PERIODS.map((p) => ({ value: String(p), label: p + " days" })),
            String(period),
            (next) => { period = Number(next); location.hash = "#/admin/ledger/" + next; },
          ),
          button("Refresh", load, { kind: "sec" }),
        ),
      ),
      note("Every failure the backend knows about and every failure the TV and the extension report. Categories are mapped from the error text; the rest is flagged for triage."),
      summaryCard(doc),
      countsTable(doc),
      card(
        "Newest failures",
        doc.recent.length ? doc.recent.map((e) => exampleRow(e, load)) : empty("No failures in this period."),
      ),
    );
  }
  mount(view, host);
  await load();
}
