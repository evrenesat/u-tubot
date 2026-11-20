import { api } from "../api.js";
import { h, icon, mount } from "../dom.js";
import {
  button,
  card,
  empty,
  errorText,
  every,
  field,
  fmtAgo,
  fmtDuration,
  note,
  pill,
  textInput,
  toast,
} from "../components.js";
import { youtubeHref } from "../dom.js";

// Director's cuts: the Cuts tab is the phone queue; #/cuts/{id} is the cut sheet a TV request
// opens on (the QR code points here). A card never shows a bare video id: the thumbnail comes
// straight from the id, the title and channel follow when the server knows them.

const STATE_KIND = {
  waiting: "warn",
  building: "",
  needs_transcript: "",
  ready: "ok",
  failed: "bad",
};
const STATE_LABEL = {
  waiting: "waiting for your description",
  building: "building",
  needs_transcript: "needs a transcript",
  ready: "ready",
  failed: "failed",
};
const STAGE_LABEL = {
  transcript: "finding the transcript",
  model: "the model is choosing the parts",
  checking: "checking the result",
};
const GROUP = { waiting: 0, building: 1, needs_transcript: 1, ready: 2, failed: 3 };

export function videoIdFrom(text) {
  const t = (text || "").trim();
  const m = t.match(/(?:v=|\/shorts\/|youtu\.be\/|\/embed\/|\/live\/)([A-Za-z0-9_-]{11})/);
  if (m) return m[1];
  return /^[A-Za-z0-9_-]{11}$/.test(t) ? t : null;
}

function thumb(videoId) {
  if (!/^[A-Za-z0-9_-]{11}$/.test(videoId || "")) return null;
  const img = h("img", {
    class: "thumb",
    src: "https://i.ytimg.com/vi/" + videoId + "/mqdefault.jpg",
    alt: "",
    loading: "lazy",
  });
  img.addEventListener("error", () => img.remove());
  return img;
}

function ms(msValue) {
  return fmtDuration((msValue || 0) / 1000);
}

function sourceLine(req) {
  const at = new Date((req.created_at || 0) * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  return "from " + (req.source || "the phone") + ", " + at;
}

function cutHeadline(req) {
  const title = req.title || "Looking up the video…";
  const meta = [req.channel, req.duration_s ? fmtDuration(req.duration_s) : null]
    .filter(Boolean)
    .join(" · ");
  return h(
    "div",
    { class: "cut-head" },
    h("a", { class: "cut-title", href: "#/cuts/" + req.id, text: title }),
    meta ? h("small", { class: "muted", text: meta }) : null,
  );
}

function keptLine(cut) {
  const kept = ms(cut.kept_ms) + " kept of " + ms(cut.duration_ms);
  return h("small", { class: "ok", text: kept });
}

function partsList(cut) {
  return h(
    "ul",
    { class: "plain parts" },
    (cut.parts || []).map((part) =>
      h(
        "li",
        {},
        h("span", { class: "cue-time", text: ms(part.start_ms) + " – " + ms(part.end_ms) }),
        h("span", { text: part.label }),
      ),
    ),
  );
}

function cardActions(req, reload) {
  const kids = [h("a", { class: "btn sec", href: "#/cuts/" + req.id }, h("span", { text: "Open" }), icon("chevron"))];
  if (req.state === "failed") {
    kids.push(
      button(
        "Retry",
        async () => {
          const body = req.preset_id ? { preset: req.preset_id } : { prompt: req.prompt };
          const r = await api("/v1/videos/" + req.video_id + "/cuts", { method: "POST", body });
          toast("Building again");
          location.hash = "#/cuts/" + r.request_id;
          await reload();
        },
        { kind: "sec" },
      ),
    );
  }
  kids.push(
    button(
      "Dismiss",
      async () => {
        await api("/v1/cut-requests/" + req.id, { method: "DELETE" });
        await reload();
      },
      { kind: "sec" },
    ),
  );
  return h("div", { class: "row" }, ...kids);
}

function cutCard(req, reload) {
  const doing =
    req.state === "building" && req.stage
      ? ", " + (STAGE_LABEL[req.stage] || req.stage)
      : req.state === "needs_transcript"
        ? ", a transcript job is queued"
        : "";
  return h(
    "div",
    { class: "cut" },
    h("div", { class: "row nowrap" }, thumb(req.video_id), h("div", { class: "cut-text" }, cutHeadline(req), h("small", { class: "muted", text: sourceLine(req) }))),
    h(
      "div",
      { class: "row between nowrap" },
      pill(STATE_LABEL[req.state] || req.state, STATE_KIND[req.state] || ""),
      h("small", { class: "muted", text: fmtAgo(req.created_at) + doing }),
    ),
    req.prompt ? h("small", { class: "muted", text: "“" + req.prompt + "”" }) : null,
    req.state === "ready" && req.cut ? h("div", { class: "stack inset" }, keptLine(req.cut), partsList(req.cut)) : null,
    req.error ? h("small", { class: "bad", text: req.error }) : null,
    cardActions(req, reload),
  );
}

function newCutCard(onCreated) {
  const ref = textInput("", { placeholder: "YouTube link or video id", maxlength: 500 });
  const msg = h("p", { class: "muted", text: "" });
  async function start() {
    msg.className = "muted";
    msg.textContent = "";
    const id = videoIdFrom(ref.value);
    if (!id) {
      msg.className = "bad";
      msg.textContent = "That does not look like a YouTube link or video id.";
      return;
    }
    try {
      const r = await api("/v1/videos/" + id + "/cuts", { method: "POST", body: { await_prompt: true } });
      ref.value = "";
      onCreated(r.request_id);
    } catch (err) {
      msg.className = "bad";
      msg.textContent = errorText(err);
    }
  }
  ref.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      start();
    }
  });
  return card(
    "New cut",
    note("Paste a video, then describe the cut you want. The TV offers the finished cut when you open the video there."),
    field("Video", ref, "A link (share or copy from YouTube) or an 11-character id."),
    button("Describe this cut", start, { kind: "primary", full: true }),
    msg,
  );
}

async function queue(view) {
  const host = h("div", { class: "stack" });
  const listHost = h("div", { class: "stack" });

  async function load() {
    const { requests } = await api("/v1/cut-requests");
    const sorted = [...requests].sort((a, b) => (GROUP[a.state] ?? 9) - (GROUP[b.state] ?? 9));
    mount(listHost, sorted.length ? sorted.map((r) => cutCard(r, load)) : empty("No cuts yet. Paste a video above, or start one from the TV."));
  }

  function draw() {
    mount(
      host,
      h("h1", { class: "page-title", text: "Cuts" }),
      newCutCard((id) => {
        location.hash = "#/cuts/" + id;
      }),
      card("Your cuts", listHost),
    );
  }

  mount(view, host);
  draw();
  await load().catch(() => {});
  return every(3000, () => load().catch(() => {}));
}

async function sheet(view, requestId) {
  const host = h("div", { class: "stack" });
  mount(view, host);
  let presets = null;
  let stopped = false;
  let pollStop = null;
  // The description box lives across redraws: the poll redraws the sheet every 2.5 s, and a
  // fresh empty textarea would erase what the owner is typing (and its focus).
  let box = null;
  let waitingSig = null;

  async function loadPresets(videoId) {
    if (presets || !videoId) return;
    try {
      presets = await api("/v1/videos/" + videoId + "/cuts");
    } catch {
      presets = { configured: true, presets: [] };
    }
  }

  async function buildWithPreset(req, presetId) {
    // Start the preset build first; the waiting request is dismissed only once that worked,
    // so a failed POST (a full per-user cap, say) cannot leave the QR code pointing at nothing.
    const r = await api("/v1/videos/" + req.video_id + "/cuts", { method: "POST", body: { preset: presetId } });
    await api("/v1/cut-requests/" + req.id, { method: "DELETE" }).catch(() => {});
    location.hash = "#/cuts/" + r.request_id;
  }

  async function fill(req, box) {
    await api("/v1/cut-requests/" + req.id, { method: "PUT", body: { prompt: box.value } });
    toast("Building the cut");
    await draw();
  }

  async function dismissAndLeave(req) {
    await api("/v1/cut-requests/" + req.id, { method: "DELETE" });
    location.hash = "#/cuts";
  }

  function sheetActions(req, ...primary) {
    return h(
      "div",
      { class: "row" },
      ...primary,
      button("Dismiss", () => dismissAndLeave(req), { kind: "sec" }),
    );
  }

  async function draw() {
    if (stopped) return;
    let req;
    try {
      req = await api("/v1/cuts/" + requestId, { query: { wait_ms: 800 } });
    } catch (err) {
      mount(host, h("h1", { class: "page-title", text: "Cut" }), card(null, note(errorText(err), "bad"), h("a", { class: "btn sec", href: "#/cuts" }, h("span", { text: "Back to the queue" }))));
      return;
    }
    await loadPresets(req.video_id);
    const kids = [
      h("a", { class: "back back-icon", href: "#/cuts" }, icon("back"), h("span", { text: "Cuts" })),
      h("h1", { class: "page-title", text: req.title || "Looking up the video…" }),
    ];
    const head = h(
      "div",
      { class: "row nowrap" },
      thumb(req.video_id),
      h(
        "div",
        { class: "cut-text" },
        req.channel ? h("small", { class: "muted", text: req.channel }) : null,
        req.duration_s ? h("small", { class: "muted", text: fmtDuration(req.duration_s) }) : null,
        h("small", { class: "muted", text: sourceLine(req) }),
      ),
    );
    const yt = youtubeHref(req.video_id);

    if (req.state === "waiting") {
      // Redraw only when something visible changed (metadata arriving); while it has not, keep
      // the DOM as it is so typing and focus survive the poll. Even on a real redraw the same
      // textarea element is reused, with focus and caret put back.
      const sig = [req.title || "", req.channel || "", req.duration_s || 0].join("|");
      if (box && sig === waitingSig) return;
      waitingSig = sig;
      if (!box) box = h("textarea", { placeholder: "Describe the cut: what should stay, what should go…", maxlength: 2000 });
      const hadFocus = document.activeElement === box;
      const caret = hadFocus ? [box.selectionStart, box.selectionEnd] : null;
      const chips = h(
        "div",
        { class: "chips" },
        ((presets && presets.presets) || []).map((p) =>
          h("button", { type: "button", class: "chip chip-btn", onclick: () => buildWithPreset(req, p.id).catch((err) => toast(errorText(err))) }, h("span", { class: "chip-text", text: p.label })),
        ),
      );
      kids.push(
        card(
          null,
          head,
          note("Describe the cut, or pick a preset."),
          chips,
          field("Your description", box),
          sheetActions(req, button("Build cut", () => fill(req, box), { kind: "primary" })),
        ),
      );
      mount(host, ...kids);
      if (hadFocus) {
        box.focus();
        box.setSelectionRange(caret[0], caret[1]);
      }
      return;
    }
    box = null;
    waitingSig = null;
    if (req.state === "building" || req.state === "needs_transcript") {
      const stage = req.state === "needs_transcript" ? "needs a transcript" : STAGE_LABEL[req.stage] || req.stage || "working";
      kids.push(
        card(
          null,
          head,
          h("div", { class: "row" }, pill("building", ""), h("span", { class: "muted", text: stage })),
          note("This can take a few minutes. You can leave the page; the cut lands in the queue."),
          req.prompt ? h("small", { class: "muted", text: "“" + req.prompt + "”" }) : null,
          sheetActions(req),
        ),
      );
    } else if (req.state === "ready") {
      const cut = req.cut || {};
      kids.push(
        card(
          null,
          head,
          h("div", { class: "row between nowrap" }, h("strong", { text: cut.label || "Cut" }), pill("ready", "ok")),
          cut.summary ? note(cut.summary) : null,
          keptLine(cut),
          partsList(cut),
          note("The TV offers this cut when you open the video there.", "muted"),
          yt ? h("a", { href: yt, target: "_blank", rel: "noopener noreferrer" }, "Open on YouTube") : null,
          sheetActions(req),
        ),
      );
    } else if (req.state === "failed") {
      kids.push(
        card(
          null,
          head,
          h("div", { class: "row" }, pill("failed", "bad")),
          note(req.error || "The cut could not be built.", "bad"),
          req.prompt ? h("small", { class: "muted", text: "“" + req.prompt + "”" }) : null,
          sheetActions(
            req,
            button(
              "Try again",
              async () => {
                const body = req.preset_id ? { preset: req.preset_id } : { prompt: req.prompt };
                const r = await api("/v1/videos/" + req.video_id + "/cuts", { method: "POST", body });
                location.hash = "#/cuts/" + r.request_id;
              },
              { kind: "primary" },
            ),
          ),
        ),
      );
    } else {
      kids.push(card(null, head, pill(STATE_LABEL[req.state] || req.state, STATE_KIND[req.state] || "")));
    }
    mount(host, ...kids);
  }

  await draw();
  pollStop = every(2500, () => draw().catch(() => {}));
  return () => {
    stopped = true;
    if (pollStop) pollStop();
  };
}

export async function render(view, { rest }) {
  if (rest && rest[0]) return sheet(view, rest[0]);
  return queue(view);
}