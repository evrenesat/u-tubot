import { api, upload } from "../api.js";
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
  progressBar,
  segmented,
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
  video: "getting the video copy",
  grids: "taking picture grids",
  describing: "describing the scenes",
  model: "the model is choosing the parts",
  checking: "checking the result",
  map: "reading the long video in parts",
  reduce: "choosing the final parts",
  in_line: "waiting for the other watched cut",
};
function stageText(req) {
  const label = STAGE_LABEL[req.stage] || req.stage;
  const p = req.progress;
  if (typeof p === "number") return `${label} (${Math.round(p * 100)}%)`;
  return p && req.stage === "map" ? `${label} (${p.done} of ${p.of})` : label;
}
function modeName(cut) {
  return cut && cut.mode === "watched" ? "Watched" : "Quick";
}
function etaText(req) {
  return req.eta_s ? `about ${fmtDuration(req.eta_s)} left` : "";
}
const GROUP = { waiting: 0, building: 1, needs_transcript: 1, ready: 2, failed: 3 };
const DEFAULT_SPEECH_S = 50;
let speech = null;


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

// "10", "10 min" -> minutes; "50%" -> fraction kept; "" -> no length; anything else -> false.
export function parseLength(raw) {
  const text = raw.trim().toLowerCase();
  if (!text) return {};
  const pct = text.match(/^(\d+(?:\.\d+)?)\s*%$/);
  if (pct) {
    const frac = Number(pct[1]) / 100;
    return frac >= 0.05 && frac <= 0.95 ? { length_frac: frac } : false;
  }
  const min = text.match(/^(\d+(?:\.\d+)?)\s*(?:m|min|mins|minutes?)?$/);
  return min && Number(min[1]) > 0 ? { length_min: Number(min[1]) } : false;
}

function presetLength(p) {
  if (p.length_min) return " · " + p.length_min + " min";
  if (p.length_frac) return " · " + Math.round(p.length_frac * 100) + " %";
  return "";
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
    const mode = req.mode === "watched" ? "quick" : req.mode;
    kids.push(
      button(
        req.mode === "watched" ? "Use Quick" : "Retry",
        async () => {
          const body = { ...(req.preset_id ? { preset: req.preset_id } : { prompt: req.prompt }), mode };
          const r = await api("/v1/videos/" + req.video_id + "/cuts", { method: "POST", body });
          toast(req.mode === "watched" ? "Building Quick" : "Building again");
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
      ? ", " + stageText(req)
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
      req.state === "ready" && req.cut ? pill(modeName(req.cut), "") : null,
      h("small", { class: "muted", text: fmtAgo(req.created_at) + doing }),
    ),
    req.state === "building" && req.mode === "watched" ? progressBar(req.progress) : null,
    req.state === "building" && req.mode === "watched" ? h("small", { class: "muted", text: etaText(req) }) : null,
    req.prompt ? h("small", { class: "muted", text: "“" + req.prompt + "”" }) : null,
    req.state === "ready" && req.cut ? h("div", { class: "stack inset" }, keptLine(req.cut), partsList(req.cut)) : null,
    req.error ? h("small", { class: "bad", text: req.error }) : null,
    cardActions(req, reload),
  );
}

function newCutCard(onCreated) {
  const ref = textInput("", { placeholder: "YouTube link or video id", maxlength: 500 });
  const msg = h("p", { class: "muted", text: "" });
  let mode = "quick";
  const modeControl = segmented(
    [
      ["quick", "Quick"],
      ["watched", "Watched"],
    ],
    mode,
    (value) => (mode = value),
  );
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
      const r = await api("/v1/videos/" + id + "/cuts", { method: "POST", body: { await_prompt: true, mode } });
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
    note("Paste a video, then describe the cut you want. The TV remembers it as your choice for that video and opens with it when it is ready."),
    field("Mode", modeControl, "Quick reads the transcript; Watched also looks at the picture."),
    field("Video", ref, "A link (share or copy from YouTube) or an 11-character id."),
    button("Describe this cut", start, { kind: "primary", full: true }),
    msg,
  );
}

// A link shared from YouTube (Android's Share button) is held by the service worker; the page
// takes it once and starts a waiting request for that video, so the sheet opens right away.
//
// `serviceWorker.ready` is a promise that never settles when registration fails (Chrome with
// site data blocked, Firefox private windows, a proxy that does not pass /sw.js); it does not
// reject, so awaiting it would strand the whole Cuts queue. The timeout comes first, so the
// page moves on after 1.5 s even when the worker never arrives.
function takeSharedItem() {
  if (!("serviceWorker" in navigator)) return Promise.resolve(null);
  let timer = null;
  let timedOut = false;
  const deadline = new Promise((resolve) => {
    timer = setTimeout(() => {
      timedOut = true;
      resolve(null);
    }, 1500);
  });
  const ready = navigator.serviceWorker.ready
    .then((reg) => {
      // A worker that registers after the deadline must not take the shared link for a page
      // that has already moved on; the link stays in the cache for the next visit.
      if (timedOut) return null;
      const worker = navigator.serviceWorker.controller || reg.active;
      if (!worker) return null;
      return new Promise((resolve) => {
        const channel = new MessageChannel();
        channel.port1.onmessage = (event) => resolve((event.data && event.data.value) || null);
        worker.postMessage({ type: "take-share" }, [channel.port2]);
        setTimeout(() => resolve(null), 1500);
      });
    })
    .catch(() => null);
  return Promise.race([ready, deadline]).finally(() => clearTimeout(timer));
}

async function startSharedCut(value) {
  const id = videoIdFrom(value);
  if (!id) {
    toast("The shared item has no YouTube link; paste the link in New cut.", "bad");
    return;
  }
  try {
    const r = await api("/v1/videos/" + id + "/cuts", { method: "POST", body: { await_prompt: true } });
    location.hash = "#/cuts/" + r.request_id;
  } catch (err) {
    toast(errorText(err), "bad");
  }
}

async function queue(view) {
  const host = h("div", { class: "stack" });
  const listHost = h("div", { class: "stack" });
  const presetHost = h("div", { class: "stack" });

  function presetRow(p, reload) {
    return h(
      "div",
      { class: "row between nowrap" },
      h("span", { text: p.label + presetLength(p) }),
      button(
        "Delete",
        async () => {
          if (!window.confirm("Delete the preset " + p.label + "?")) return;
          await api("/v1/cut-presets/" + encodeURIComponent(p.id), { method: "DELETE" });
          toast("Preset deleted");
          await reload();
        },
        { kind: "danger" },
      ),
    );
  }

  async function load() {
    const [queueDoc, ownDoc] = await Promise.all([api("/v1/cut-requests"), api("/v1/cut-presets")]);
    const sorted = [...queueDoc.requests].sort((a, b) => (GROUP[a.state] ?? 9) - (GROUP[b.state] ?? 9));
    mount(listHost, sorted.length ? sorted.map((r) => cutCard(r, load)) : empty("No cuts yet. Paste a video above, or start one from the TV."));
    mount(presetHost, ownDoc.presets.length ? ownDoc.presets.map((p) => presetRow(p, load)) : empty("No saved presets yet. Save a description as one from a cut sheet."));
  }

  function draw() {
    mount(
      host,
      h("h1", { class: "page-title", text: "Cuts" }),
      newCutCard((id) => {
        location.hash = "#/cuts/" + id;
      }),
      card("Saved presets", presetHost),
      card("Your cuts", listHost),
    );
  }

  mount(view, host);
  draw();
  // Start the queue and its poller before the shared link is taken: the queue must load even
  // when the service worker is unavailable, and taking a shared link can wait up to 1.5 s.
  const stop = every(3000, () => load().catch(() => {}));
  const shared = await takeSharedItem();
  if (shared) await startSharedCut(shared);
  await load().catch(() => {});
  return stop;
}

async function loadSpeech() {
  if (speech) return;
  try {
    const me = await api("/v1/me");
    speech = me.features || {};
  } catch {
    // A transient failure is retried on the next draw instead of caching "no speech" forever.
  }
}

function pickMime() {
  if (!window.MediaRecorder) return "";
  for (const type of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/aac"]) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return "";
}

// Tap to start, tap to stop. The audio goes to POST /v1/speech; the text lands in the box and
// stays editable (nothing is sent automatically). The recording is dropped after the upload.
//
// The sheet creates this button once and reuses it across redraws, so a redraw cannot leave a
// recorder running without its Stop. `cancel()` is called when the sheet goes away or leaves the
// waiting state; it stops the recorder without uploading and releases the microphone.
function micButton(box) {
  const btn = h("button", { type: "button", class: "btn sec mic", text: "Speak" });
  let recorder = null;
  let chunks = [];
  let stream = null;
  let limitTimer = null;
  let canceled = false;
  // True while getUserMedia is still being acquired (the first-use permission prompt can take
  // seconds). The button is disabled then, so a second tap cannot start another acquisition, and
  // cancel() marks the attempt dead so the stream that arrives late is stopped, not recorded.
  let starting = false;
  // True while the recording is on its way to /v1/speech. A tap is refused then, so a cancel
  // during the upload cannot reset the button for a new recording while the old request's
  // finally would wipe that new recorder's chunks.
  let uploading = false;
  // Each recording is one attempt; cancel() moves to the next one, so a late `stop` event from
  // an abandoned recorder cannot upload after a new attempt has begun.
  let attempt = 0;

  function resetButton() {
    btn.textContent = starting ? "Listening…" : uploading ? "Uploading…" : "Speak";
    btn.classList.remove("on");
    btn.disabled = starting || uploading;
  }

  function releaseStream() {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      stream = null;
    }
  }

  function stopRecording() {
    if (limitTimer) {
      clearTimeout(limitTimer);
      limitTimer = null;
    }
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }

  function cancel() {
    canceled = true;
    attempt += 1; // a stop event from the abandoned attempt is ignored from now on
    stopRecording();
    releaseStream();
    resetButton();
  }

  async function sendRecording() {
    uploading = true;
    resetButton();
    const type = (recorder && recorder.mimeType) || (chunks[0] && chunks[0].type) || "audio/webm";
    const blob = new Blob(chunks, { type });
    releaseStream();
    try {
      if (!blob.size) {
        toast("No speech heard; try again or type it.", "bad");
        return;
      }
      // The extension lets OpenAI-compatible STT servers pick the decoder from the name,
      // even when the content type is already right.
      const ext = /mp4|aac/.test(type) ? "m4a" : /ogg/.test(type) ? "ogg" : /wav/.test(type) ? "wav" : "webm";
      const form = new FormData();
      form.append("audio", blob, "recording." + ext);
      const r = await upload("/v1/speech", form);
      const text = ((r && r.text) || "").trim();
      if (!text) {
        toast("No speech heard; try again or type it.", "bad");
        return;
      }
      const old = box.value.trim();
      box.value = old ? old + " " + text : text;
      box.focus();
      const end = box.value.length;
      box.setSelectionRange(end, end);
      toast("Speech added; edit it if needed.");
    } catch (err) {
      toast(errorText(err), "bad");
    } finally {
      uploading = false;
      resetButton();
      recorder = null;
      chunks = [];
    }
  }

  async function startRecording() {
    if (!speech || !speech.speech) {
      toast("Speech is not configured on this server; type the cut instead.", "bad");
      return;
    }
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      toast("This browser cannot record sound; type the cut instead.", "bad");
      return;
    }
    if (starting || uploading) return;
    starting = true;
    canceled = false;
    const myAttempt = ++attempt;
    btn.disabled = true;
    btn.textContent = "Listening…";
    let got;
    try {
      got = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      starting = false;
      resetButton();
      toast("Microphone not available; type it instead.", "bad");
      return;
    }
    if (canceled) {
      // The sheet left (Build, Dismiss, Back, error) while the permission prompt was open:
      // release the stream that just arrived instead of recording on a detached button.
      got.getTracks().forEach((track) => track.stop());
      starting = false;
      resetButton();
      return;
    }
    stream = got;
    try {
      const mime = pickMime();
      recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
    } catch {
      releaseStream();
      starting = false;
      resetButton();
      toast("This browser cannot record sound; type the cut instead.", "bad");
      return;
    }
    chunks = [];
    recorder.addEventListener("dataavailable", (event) => {
      // A new attempt owns the shared `chunks` list; an abandoned recorder's last chunk must not
      // ride along in the new recording.
      if (myAttempt !== attempt) return;
      if (event.data && event.data.size) chunks.push(event.data);
    });
    recorder.addEventListener("stop", () => {
      // A new attempt (the owner tapped Speak again after a cancel) owns the globals now; this
      // abandoned attempt must not upload its chunks or clear the new recorder.
      if (myAttempt !== attempt) return;
      if (canceled) {
        resetButton();
        recorder = null;
        chunks = [];
        return;
      }
      void sendRecording();
    });
    recorder.start();
    starting = false;
    btn.textContent = "Stop";
    btn.classList.add("on");
    btn.disabled = false;
    const maxS = Number(speech.speech_max_s) || DEFAULT_SPEECH_S;
    limitTimer = setTimeout(() => {
      toast("The recording reached its " + maxS + " s limit.");
      stopRecording();
    }, maxS * 1000);
  }

  btn.addEventListener("click", () => {
    if (!btn.disabled) {
      if (recorder && recorder.state === "recording") stopRecording();
      else void startRecording();
    }
  });
  return { btn, cancel };
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
  // One mic button per sheet, reused across redraws like the box; `cancel()` ties the recorder
  // and the microphone to the sheet's lifecycle.
  let mic = null;
  // The preset name field also lives across redraws, so a name typed while the metadata arrives
  // survives the poll.
  let nameBox = null;
  let lengthBox = null;
  // The mode picked on this sheet; null follows the request's own mode.
  let sheetMode = null;

  function stopMic() {
    if (mic) {
      mic.cancel();
      mic = null;
    }
  }

  // Cancel the live recorder but keep the instance: a failed Build/Dismiss leaves the sheet on
  // the same box and DOM, so the button must stay tied to this sheet's lifecycle.
  function cancelMic() {
    if (mic) mic.cancel();
  }

  async function loadPresets(videoId) {
    if (presets || !videoId) return;
    try {
      presets = await api("/v1/videos/" + videoId + "/cuts");
    } catch {
      presets = { configured: true, presets: [] };
    }
  }

  function selectedMode(req) {
    return sheetMode || req.mode || "quick";
  }

  function modeControl(req) {
    const list = (presets && presets.modes) || [
      { id: "quick", label: "Quick", available: true, default: true },
      { id: "watched", label: "Watched", available: true },
    ];
    const choices = list
      .filter((m) => m.available !== false)
      .map((m) => [m.id, m.label + (m.default ? " (default)" : "")]);
    const chosen = selectedMode(req);
    return segmented(choices, choices.some((c) => c[0] === chosen) ? chosen : choices[0][0], (v) => (sheetMode = v));
  }

  async function buildWithPreset(req, presetId) {
    // Start the preset build first; the waiting request is dismissed only once that worked,
    // so a failed POST (a full per-user cap, say) cannot leave the QR code pointing at nothing.
    const body = { preset: presetId, mode: selectedMode(req) };
    const r = await api("/v1/videos/" + req.video_id + "/cuts", { method: "POST", body });
    await api("/v1/cut-requests/" + req.id, { method: "DELETE" }).catch(() => {});
    location.hash = "#/cuts/" + r.request_id;
  }

  async function fill(req, box) {
    cancelMic();
    try {
      await api("/v1/cut-requests/" + req.id, { method: "PUT", body: { prompt: box.value, mode: selectedMode(req) } });
      toast("Building the cut");
      await draw();
    } catch (err) {
      toast(errorText(err), "bad");
    }
  }

  async function savePreset() {
    const text = (box && box.value || "").trim();
    const label = (nameBox && nameBox.value || "").trim();
    if (!text) {
      toast("Describe the cut in the box first; the preset saves that description.", "bad");
      return;
    }
    if (!label) {
      toast("Name the preset first.", "bad");
      return;
    }
    const length = parseLength((lengthBox && lengthBox.value) || "");
    if (length === false) {
      toast("Length: a number of minutes (10) or a percentage (50%), 5 to 95 %.", "bad");
      return;
    }
    try {
      await api("/v1/cut-presets", { method: "POST", body: { label, prompt: text, ...length } });
      presets = null;
      waitingSig = null;
      nameBox.value = "";
      if (lengthBox) lengthBox.value = "";
      toast("Saved; it is a chip on this sheet now.");
      await draw();
    } catch (err) {
      toast(errorText(err), "bad");
    }
  }

  async function dismissAndLeave(req) {
    cancelMic();
    try {
      await api("/v1/cut-requests/" + req.id, { method: "DELETE" });
      location.hash = "#/cuts";
    } catch (err) {
      toast(errorText(err), "bad");
    }
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
      // Reset the redraw signature so the next successful poll replaces the error card instead
      // of hitting the "same sheet" early return forever.
      box = null;
      nameBox = null;
    lengthBox = null;
      waitingSig = null;
      stopMic();
      mount(host, h("h1", { class: "page-title", text: "Cut" }), card(null, note(errorText(err), "bad"), h("a", { class: "btn sec", href: "#/cuts" }, h("span", { text: "Back to the queue" }))));
      return;
    }
    await loadPresets(req.video_id);
    await loadSpeech();
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
          field(
            "Mode",
            modeControl(req),
            ((presets && presets.modes) || []).some((m) => m.id === "watched" && m.available === false)
              ? "Watched is not available: " +
                (((presets && presets.modes) || []).find((m) => m.id === "watched") || {}).reason
              : "Quick reads the transcript; Watched also looks at the picture.",
          ),
          chips,
          field(
            "Your description",
            box,
            speech && speech.speech
              ? "Speak or type; the recording limit is set on the server."
              : "Type the cut; voice needs a speech engine on the server.",
          ),
          field(
            "Save this description as a preset",
            nameBox || (nameBox = textInput("", { placeholder: "Preset name", maxlength: 60 })),
            "Only you see the saved preset, and only on the phone; it becomes a chip here.",
          ),
          field(
            "Length of the preset (optional)",
            lengthBox || (lengthBox = textInput("", { placeholder: "10 min or 50%", maxlength: 12 })),
            "Minutes kept, or the share of the video kept. Empty: read from the description (half, 10 minutes ...).",
          ),
          button("Save as preset", () => savePreset(), { kind: "sec", full: true }),
          sheetActions(
            req,
            speech && speech.speech ? (mic || (mic = micButton(box))).btn : null,
            button("Build cut", () => fill(req, box), { kind: "primary" }),
          ),
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
    nameBox = null;
    lengthBox = null;
    waitingSig = null;
    stopMic();
    if (req.state === "building" || req.state === "needs_transcript") {
      const stage = req.state === "needs_transcript" ? "needs a transcript" : stageText(req) || "working";
      kids.push(
        card(
          null,
          head,
          h("div", { class: "row" }, pill("building", ""), h("span", { class: "muted", text: stage })),
          req.mode === "watched" ? progressBar(req.progress) : null,
          req.mode === "watched" && req.eta_s ? note(etaText(req)) : null,
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
          h("div", { class: "row between nowrap" }, h("strong", { text: cut.label || "Cut" }), pill("ready", "ok"), pill(modeName(cut), "")),
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
            req.mode === "watched"
              ? button(
                  "Use Quick",
                  async () => {
                    const body = { ...(req.preset_id ? { preset: req.preset_id } : { prompt: req.prompt }), mode: "quick" };
                    const r = await api("/v1/videos/" + req.video_id + "/cuts", { method: "POST", body });
                    location.hash = "#/cuts/" + r.request_id;
                  },
                  { kind: "primary" },
                )
              : button(
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
    stopMic();
    if (pollStop) pollStop();
  };
}

export async function render(view, { rest }) {
  if (rest && rest[0]) return sheet(view, rest[0]);
  return queue(view);
}