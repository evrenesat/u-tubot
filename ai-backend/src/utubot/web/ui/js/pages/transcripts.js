import { api } from "../api.js";
import { h, mount } from "../dom.js";
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
  slider,
  textInput,
  toast,
} from "../components.js";
import { youtubeHref } from "../dom.js";

const MODES = [
  ["off", "Off"],
  ["on_dwell", "On dwell"],
  ["on_open", "On open"],
];
const MODE_HELP = {
  off: "Never transcribes by itself. You choose videos here or from the TV.",
  on_dwell: "Starts when you rest on a card that has no captions.",
  on_open: "Starts when you open a video that has no captions.",
};
const STATE_KIND = { ready: "ok", processing: "ok", waiting: "", failed: "bad", cancelled: "" };

// Automatic transcription policy; `settingsPath` is /v1/me/settings or /v1/users/NAME/settings.
export function transcriptPolicyForm(settingsPath, doc, onUpdate) {
  const current = doc.settings.transcripts;
  const draft = { ...current };
  const help = h("small", { class: "muted", text: MODE_HELP[draft.auto_transcribe] });
  const mode = segmented(MODES, draft.auto_transcribe, (v) => {
    draft.auto_transcribe = v;
    help.textContent = MODE_HELP[v];
  });
  const minutes = slider({
    label: "Longest video to transcribe automatically",
    value: Math.min(draft.auto_transcribe_max_minutes, 180),
    min: 5,
    max: 180,
    step: 5,
    format: (v) => v + " min",
    hint: "Longer videos wait until you ask for them.",
    onChange: (v) => (draft.auto_transcribe_max_minutes = v),
  });
  const msg = h("p", { class: "bad", text: "" });
  async function save() {
    msg.textContent = "";
    const changes = {};
    for (const k of Object.keys(draft)) if (draft[k] !== current[k]) changes[k] = draft[k];
    if (!Object.keys(changes).length) {
      toast("Nothing changed");
      return;
    }
    try {
      onUpdate(await api(settingsPath, { method: "PUT", body: { version: doc.version, settings: { transcripts: changes } } }));
      toast("Transcript policy saved");
    } catch (err) {
      msg.textContent = errorText(err);
    }
  }
  return card(
    "Automatic transcription",
    note("Videos without captions can be transcribed from their audio. The TV follows this policy once it reads settings from the server."),
    mode,
    help,
    minutes,
    msg,
    button("Save policy", save, { kind: "primary" }),
  );
}

function jobRow(job, reload) {
  const href = youtubeHref(job.video_id);
  const title = job.title || job.video_id;
  const ago = job.finished_at || job.created_at;
  return h(
    "div",
    { class: "job" },
    h(
      "div",
      { class: "row between nowrap" },
      href ? h("a", { class: "job-title", href, target: "_blank", rel: "noopener noreferrer", text: title }) : h("span", { class: "job-title", text: title }),
      pill(job.state, STATE_KIND[job.state] || ""),
    ),
    h("small", { class: "muted", text: job.kind + ", " + fmtAgo(ago) }),
    job.state === "processing" ? progressBar(job.progress) : null,
    job.retry_after_s ? h("small", { class: "muted", text: "Waiting for YouTube, about " + fmtDuration(job.retry_after_s) }) : null,
    job.error && job.state !== "cancelled" ? h("small", { class: "bad", text: job.error }) : null,
    job.state === "waiting" || job.state === "failed" || job.state === "cancelled"
      ? h(
          "div",
          { class: "row" },
          job.state === "waiting"
            ? button("Cancel", async () => {
                await api("/v1/jobs/" + job.id + "/cancel", { method: "POST" });
                toast("Cancelled");
                await reload();
              }, { kind: "sec" })
            : button("Retry", async () => {
                await api("/v1/jobs/" + job.id + "/retry", { method: "POST" });
                toast("Queued again");
                await reload();
              }, { kind: "sec" }),
        )
      : null,
  );
}

export async function render(view) {
  let doc = await api("/v1/me/settings");
  const host = h("div", { class: "stack" });
  const jobsHost = h("div", { class: "stack" });
  const ref = textInput("", { placeholder: "video id or YouTube link", maxlength: 500 });
  const msg = h("p", { class: "muted", text: "" });

  async function loadJobs() {
    const { jobs } = await api("/v1/jobs", { query: { limit: 30 } });
    mount(jobsHost, jobs.length ? jobs.map((j) => jobRow(j, loadJobs)) : empty("No jobs yet. Start one above."));
  }

  async function start(kind) {
    msg.className = "muted";
    msg.textContent = "";
    let id;
    try {
      id = (await api("/v1/videos/resolve", { method: "POST", body: { text: ref.value } })).video_id;
    } catch (err) {
      msg.className = "bad";
      msg.textContent = errorText(err);
      return;
    }
    try {
      if (kind === "transcript") {
        const r = await api("/v1/videos/" + id + "/transcribe", { method: "POST" });
        msg.className = "ok";
        msg.textContent = r.status === "ready" ? "This video already has a transcript." : "Queued. Estimated " + (r.estimate_s ? fmtDuration(r.estimate_s) : "a few minutes") + ".";
      } else {
        const r = await api("/v1/videos/" + id + "/captions", { method: "POST", body: { lang: "auto" } });
        msg.className = "ok";
        msg.textContent = "High-quality captions " + r.status + ".";
      }
      ref.value = "";
      await loadJobs();
    } catch (err) {
      msg.className = "bad";
      msg.textContent = errorText(err);
    }
  }

  function draw() {
    mount(
      host,
      h("h1", { class: "page-title", text: "Captions" }),
      transcriptPolicyForm("/v1/me/settings", doc, (next) => {
        doc = next;
        draw();
      }),
      card(
        "Transcribe a video",
        field("Video", ref, "Paste a link or an 11-character id."),
        h("div", { class: "row" }, button("Transcribe", () => start("transcript"), { kind: "primary" }), button("HQ captions", () => start("captions"), { kind: "sec" })),
        msg,
      ),
      card("Jobs", jobsHost),
    );
  }

  mount(view, host);
  draw();
  await loadJobs();
  return every(4000, () => loadJobs().catch(() => {}));
}
