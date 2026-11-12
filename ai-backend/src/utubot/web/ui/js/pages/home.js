import { api, session } from "../api.js";
import { h, mount } from "../dom.js";
import { card, every, fmtDuration, fmtNumber, pill, progressBar, statRow } from "../components.js";

const GATE_TEXT = {
  closed: ["Healthy", "ok", "Requests to YouTube flow normally."],
  half_open: ["Probing", "warn", "The cooldown ended; the next request tests whether YouTube is happy again."],
  open: ["Cooling down", "bad", "YouTube limited this server. Background work waits, interactive requests answer later."],
};

export async function render(view) {
  let status = null;
  let fetchedAt = 0;
  const host = h("div", { class: "stack" });
  const countdowns = [];

  async function load() {
    status = await api("/v1/status");
    fetchedAt = Date.now();
    draw();
  }

  function remaining() {
    return Math.max(0, status.youtube.cooldown_remaining_s - Math.round((Date.now() - fetchedAt) / 1000));
  }

  function draw() {
    countdowns.length = 0;
    const gate = GATE_TEXT[status.youtube.state] || GATE_TEXT.closed;
    const left = h("strong", { text: "" });
    const showLeft = () => {
      left.textContent = status.youtube.state === "open" ? fmtDuration(remaining()) + " left" : "";
    };
    showLeft();
    countdowns.push(showLeft);
    const u = status.usage;
    mount(
      host,
      h("h1", { class: "page-title", text: "Hello, " + session.user }),
      card(
        "Server",
        statRow("Status", "online", "ok"),
        statRow("Version", status.version),
        statRow("Uptime", fmtDuration(status.uptime_s)),
      ),
      card(
        "YouTube gate",
        h("div", { class: "row between" }, pill(gate[0], gate[1]), left),
        h("p", { class: "muted", text: gate[2] }),
        statRow("Gate state", status.youtube.state),
        status.youtube.background_waiting ? statRow("Background fetches waiting", status.youtube.background_waiting) : null,
      ),
      card(
        "Today (UTC)",
        statRow("Model calls", fmtNumber(u.llm.calls)),
        statRow("Model errors", fmtNumber(u.llm.errors), u.llm.errors ? "bad" : ""),
        statRow("Tokens in / out", fmtNumber(u.llm.prompt_tokens) + " / " + fmtNumber(u.llm.completion_tokens)),
        statRow("Transcripts from captions", fmtNumber(u.transcripts.youtube_captions)),
        statRow("Transcripts by speech recognition", fmtNumber(u.transcripts.asr)),
        h("div", { class: "stat" }, h("span", { class: "muted", text: "Deep analyses (yours)" }), h("strong", { text: u.analyses.used + " / " + u.analyses.cap })),
        progressBar(u.analyses.cap ? u.analyses.used / u.analyses.cap : 0),
      ),
      card(
        "Your background jobs",
        h(
          "div",
          { class: "row" },
          pill(status.jobs.waiting + " waiting"),
          pill(status.jobs.processing + " running", status.jobs.processing ? "ok" : ""),
          pill(status.jobs.failed + " failed", status.jobs.failed ? "bad" : ""),
        ),
        h("a", { class: "btn sec", href: "#/captions", text: "Open jobs" }),
      ),
      card(
        "TV",
        h("p", { class: "muted", text: "Link a TV with a one-time code, no typing on the remote beyond the code." }),
        h("a", { class: "btn primary", href: "#/tvs", text: "Link a TV" }),
      ),
    );
  }

  mount(view, host);
  await load();
  const stopPoll = every(10000, () => load().catch(() => {}));
  const stopTick = every(1000, () => countdowns.forEach((fn) => fn()));
  return () => {
    stopPoll();
    stopTick();
  };
}
