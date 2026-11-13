import { ApiError, api } from "../api.js";
import { button, card, every, fmtAgo, fmtTime, note, pill, progressBar, toast } from "../components.js";
import { h, icon, mount, youtubeHref } from "../dom.js";
import { collapse, describe, fmtBytes, fmtClock, fmtOffset, fmtSecs, reasonText, stageLabel, statusIcon, statusKind, triggerText, VIA_LABELS } from "../jobtext.js";

const STATE_KIND = { ready: "ok", processing: "ok", waiting: "", failed: "bad", cancelled: "" };
const KIND_NAMES = { transcript: "Transcript from audio", captions: "HQ captions" };
const REFRESH_MS = 3000;
const IDLE_REFRESH_MS = 15000;

const active = (doc) => doc.state === "waiting" || doc.state === "processing";

function kv(rows) {
  const items = rows.filter(([, value]) => value !== null && value !== undefined && value !== "");
  return h(
    "dl",
    { class: "kv" },
    items.map(([label, value]) => h("div", {}, h("dt", { text: label }), h("dd", {}, value))),
  );
}

function downloadLink(label, href) {
  return h("a", { class: "btn sec", href, download: "" }, icon("download"), h("span", { text: label }));
}

function totalSeconds(doc) {
  const done = doc.events.find((e) => e.stage === "finished" && e.status === "ok" && e.detail && e.detail.seconds !== undefined);
  if (done) return done.detail.seconds;
  return doc.finished_at ? doc.finished_at - doc.created_at : null;
}

function headline(doc) {
  const out = doc.outputs;
  if (doc.state === "failed") {
    const failed = [...doc.events].reverse().find((e) => e.stage === "failed");
    const where = failed && failed.detail.stage ? " at " + stageLabel(failed.detail.stage).toLowerCase() : "";
    return "Failed" + where + ": " + (doc.error || "no message was recorded").replace(/[.\s]+$/, "") + ".";
  }
  if (doc.state === "cancelled") return "Cancelled before it ran.";
  if (doc.state === "waiting") {
    const wait = doc.retry_after_s ? " YouTube is holding it back, about " + fmtSecs(doc.retry_after_s) + "." : "";
    return "Waiting in the queue." + wait;
  }
  if (doc.state === "processing") {
    const last = [...doc.events].reverse().find((e) => e.stage !== "delivered");
    return "Working" + (last ? ": " + stageLabel(last.stage).toLowerCase() : "") + ", " + Math.round(doc.progress * 100) + "%.";
  }
  const took = totalSeconds(doc);
  const lead = "Ready" + (took ? " after " + fmtSecs(took) : "") + ". ";
  if (out.transcript) {
    const t = out.transcript;
    const how = t.source === "asr" ? "made from the audio" + (t.engine ? " by " + t.engine : "") : "taken from YouTube captions";
    return lead + "Transcript " + how + ", " + Number(t.chars).toLocaleString("en-US") + " characters" + (t.lang ? ", language " + t.lang : "") + ".";
  }
  if (out.captions.length) {
    const t = out.captions[0];
    return lead + "Captions track " + JSON.stringify(t.label) + " with " + t.cues + " cues.";
  }
  return lead + "No result is stored for this video any more.";
}

function deliveryLine(doc) {
  const d = doc.delivery;
  if (!d.delivered) return doc.state === "ready" ? "No client has fetched this result yet." : null;
  const who = d.clients.map((c) => c.client).join(", ");
  return "Fetched by " + who + ", " + d.count + (d.count === 1 ? " time" : " times") + ", last " + fmtAgo(d.last_ts) + ".";
}

function header(doc, reload) {
  const title = doc.inputs.title || doc.inputs.video_id;
  const href = youtubeHref(doc.inputs.video_id);
  const line = deliveryLine(doc);
  const actions = [];
  if (doc.can_cancel) {
    actions.push(
      button(
        "Cancel",
        async () => {
          await api("/v1/jobs/" + doc.id + "/cancel", { method: "POST" });
          toast("Cancelled");
          await reload();
        },
        { kind: "danger" },
      ),
    );
  }
  if (doc.can_retry) {
    actions.push(
      button(
        "Retry",
        async () => {
          await api("/v1/jobs/" + doc.id + "/retry", { method: "POST" });
          toast("Queued again");
          await reload();
        },
        { kind: "primary" },
      ),
    );
  }
  if (href) actions.push(h("a", { class: "btn sec", href, target: "_blank", rel: "noopener noreferrer" }, icon("external"), h("span", { text: "YouTube" })));
  return card(
    null,
    h("div", { class: "row between nowrap" }, h("h1", { class: "job-heading", text: title }), pill(doc.state, STATE_KIND[doc.state] || "")),
    h("small", { class: "muted", text: (KIND_NAMES[doc.kind] || doc.kind) + ", " + (doc.finished_at ? "finished " + fmtAgo(doc.finished_at) : "queued " + fmtAgo(doc.created_at)) }),
    doc.state === "processing" ? progressBar(doc.progress) : null,
    h("p", { class: "headline", text: headline(doc) }),
    line ? h("p", { class: doc.delivery.delivered ? "ok" : "warn", text: line }) : null,
    actions.length ? h("div", { class: "row" }, actions) : null,
  );
}

function transcriptOutput(doc, t) {
  return h(
    "div",
    { class: "stack" },
    kv([
      ["Source", t.source === "asr" ? "Speech recognition of the audio" : "YouTube captions"],
      ["Language", t.lang],
      ["Engine", t.engine ? t.engine + (t.model ? " (" + t.model + ")" : "") : null],
      ["Size", Number(t.chars).toLocaleString("en-US") + " characters, " + t.lines + " lines" + (t.segments ? ", " + t.segments + " segments" : "")],
      ["Stored", fmtTime(t.stored_at)],
    ]),
    t.from_this_job === false ? note("Another job or source produced the transcript that is stored now.") : null,
    h("h3", { class: "sub", text: "First lines" }),
    h("pre", { class: "preview", text: t.first_lines.join("\n") }),
    h("div", { class: "row" }, downloadLink("Transcript text", t.text_url)),
  );
}

function trackOutput(track) {
  return h(
    "div",
    { class: "stack track" },
    h("div", { class: "row between nowrap" }, h("strong", { class: "job-title", text: track.label }), pill(track.lang)),
    kv([
      ["Cues", String(track.cues)],
      ["Speakers", track.speakers ? String(track.speakers) : "not labelled"],
      ["Size", fmtBytes(track.bytes)],
      ["Stored", fmtTime(track.created_at)],
    ]),
    h("h3", { class: "sub", text: "First " + track.preview.length + " cues" }),
    h(
      "ol",
      { class: "cues" },
      track.preview.map((cue) => h("li", {}, h("span", { class: "cue-time mono", text: fmtClock(cue.start) }), h("span", { text: cue.text }))),
    ),
    h("div", { class: "row" }, downloadLink(".vtt track", track.vtt_url), downloadLink("Text", track.text_url)),
  );
}

function outputsCard(doc) {
  const out = doc.outputs;
  const parts = [];
  if (out.transcript) parts.push(transcriptOutput(doc, out.transcript));
  for (const track of out.captions) parts.push(trackOutput(track));
  if (!parts.length) {
    if (doc.state === "ready") parts.push(note("Nothing is stored for this job any more."));
    else if (doc.state === "failed" || doc.state === "cancelled") parts.push(note("Nothing was produced."));
    else return null;
  }
  return card("What it produced", ...parts);
}

function deliveryCard(doc) {
  const d = doc.delivery;
  if (!d.delivered) {
    if (doc.state !== "ready") return null;
    return card(
      "Delivery",
      note("No client has fetched this result yet. A TV that fetches the captions, or a summary built from the transcript, shows up here."),
    );
  }
  return card(
    "Delivery",
    h(
      "ul",
      { class: "plain" },
      d.clients.map((c) =>
        h(
          "li",
          { class: "delivery" },
          h("strong", { text: c.client }),
          h("small", { class: "muted", text: c.via.map((v) => VIA_LABELS[v] || v).join(", ") + " · " + c.count + (c.count === 1 ? " time" : " times") + " · last " + fmtAgo(c.last_ts) }),
        ),
      ),
    ),
  );
}

function timelineCard(doc) {
  const rows = collapse(doc.events);
  const first = doc.events.length ? doc.events[0].ts : doc.created_at;
  const items = rows.map((row) => {
    const text = describe({ stage: row.stage, status: row.status, detail: row.detail });
    const label = row.child ? (row.stage === "asr_chunk" ? "Chunk" : "Fallback") : stageLabel(row.stage);
    const technical = row.detail.technical;
    return h(
      "li",
      { class: "tl-row" + (row.child ? " child" : "") },
      h("span", { class: "tl-icon " + statusKind(row.status), title: row.status }, icon(statusIcon(row.status))),
      h(
        "div",
        { class: "tl-main" },
        h(
          "div",
          { class: "tl-head" },
          h("span", { class: "tl-label", text: label }),
          h("span", { class: "tl-meta", text: [row.seconds ? fmtSecs(row.seconds) : null, fmtOffset(row.ts - first)].filter(Boolean).join(" · ") }),
        ),
        text ? h("div", { class: "tl-text", text }) : null,
        technical ? h("div", { class: "tl-text muted mono", text: technical }) : null,
      ),
    );
  });
  return card("What happened", h("ol", { class: "timeline" }, items.length ? items : [note("No events were recorded.")]), h("small", { class: "muted", text: "Times are from the moment the job was queued." }));
}

function inputsCard(doc) {
  const i = doc.inputs;
  const r = i.requested;
  const href = youtubeHref(i.video_id);
  return card(
    "What was requested",
    kv([
      ["Video", href ? h("a", { href, target: "_blank", rel: "noopener noreferrer", text: i.video_id }) : i.video_id],
      ["Title", i.title],
      ["Channel", i.channel],
      ["Length", i.duration_s ? fmtClock(i.duration_s) : null],
      ["Spoken language", i.language],
      ["Job", KIND_NAMES[doc.kind] || doc.kind],
      ["Language asked", doc.kind === "captions" ? i.lang + (i.translate_to ? " translated to " + i.translate_to : "") : null],
      ["Requested by", r.user + (r.client ? " on " + r.client : "")],
      ["How", r.trigger ? triggerText(r.trigger) : null],
      ["Endpoint", r.endpoint],
      ["Priority", r.priority],
      ["Queued", fmtTime(r.at)],
      ["Attempts", doc.attempts ? String(doc.attempts) : null],
    ]),
  );
}

function errorCard(doc) {
  if (doc.state !== "failed") return null;
  const failed = [...doc.events].reverse().find((e) => e.stage === "failed");
  const d = failed ? failed.detail : {};
  return card(
    "Error",
    h("p", { class: "bad", text: doc.error || d.message || "The job failed." }),
    kv([
      ["Failed in", d.stage ? stageLabel(d.stage) : null],
      ["Cause", d.error_class ? reasonText(d.error_class) + " (" + d.error_class + ")" : null],
      ["Technical", d.technical],
    ]),
  );
}

function draw(host, doc, reload) {
  const back = h("a", { class: "back back-icon", href: "#/captions" }, icon("back"), h("span", { text: " Captions" }));
  // A failure is read from the log first; a finished job is read from its result and who fetched it.
  const order =
    doc.state === "failed"
      ? [errorCard(doc), timelineCard(doc), outputsCard(doc), inputsCard(doc)]
      : [outputsCard(doc), deliveryCard(doc), timelineCard(doc), inputsCard(doc)];
  mount(host, back, header(doc, reload), order);
}

export async function render(view, { rest }) {
  const id = encodeURIComponent(rest[0] || "");
  const host = h("div", { class: "stack" });
  let doc = null;
  let loadedAt = 0;
  let loading = false;

  async function load() {
    if (loading) return;
    loading = true;
    try {
      const next = await api("/v1/jobs/" + id);
      loadedAt = Date.now();
      const changed = JSON.stringify(next) !== JSON.stringify(doc);
      doc = next;
      if (changed) draw(host, doc, load);
    } finally {
      loading = false;
    }
  }

  mount(view, host);
  try {
    await load();
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      mount(host, h("a", { class: "back back-icon", href: "#/captions" }, icon("back"), h("span", { text: " Captions" })), card("Job not found", note("This job does not exist, or it belongs to someone else.")));
      return null;
    }
    throw err;
  }
  return every(REFRESH_MS, () => {
    if (doc && (active(doc) || Date.now() - loadedAt >= IDLE_REFRESH_MS)) load().catch(() => {});
  });
}
