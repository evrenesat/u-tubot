import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { button, card, empty, errorText, field, note, pill, select, switchRow, textInput, toast } from "../components.js";

const TEMPLATE = {
  tubeai_prompt_set: 1,
  id: "my-prompts",
  name: "My prompts",
  version: "1",
  prompts: [
    {
      id: "tldr",
      label: "TL;DR",
      default: true,
      system: "You summarize YouTube videos for a TV viewer. Reply in {language}.",
      template: "Title: {title}\nChannel: {channel}\nDuration: {duration}\n\nTranscript:\n{transcript}\n\nGive a 5-bullet TL;DR.",
      max_tokens: 700,
      model: null,
    },
  ],
};
const ADHOC = "\u0000adhoc";
const POLL_ATTEMPTS = 8;
const POLL_WAIT_MS = 15000;

function allKeys(listing) {
  return listing.sets.flatMap((s) => s.prompts.map((p) => ({ value: p.key, label: p.label + "  (" + p.key + ")" })));
}

// "line 3 column 5" for a JSON.parse failure, so the message points somewhere.
function jsonProblem(text) {
  try {
    JSON.parse(text);
    return null;
  } catch (err) {
    const m = /position (\d+)/.exec(err.message || "");
    if (!m) return "Not valid JSON: " + err.message;
    const upto = text.slice(0, Number(m[1]));
    const line = upto.split("\n").length;
    const col = upto.length - upto.lastIndexOf("\n");
    return "Not valid JSON at line " + line + ", column " + col + ": " + err.message.replace(/ in JSON at position.*/, "");
  }
}

export async function render(view) {
  let listing = await api("/v1/prompts");
  let doc = await api("/v1/me/settings");
  let cancelled = false;
  const host = h("div", { class: "stack" });
  const editor = h("textarea", { class: "code", rows: 14, spellcheck: "false", autocapitalize: "off", placeholder: "prompt set JSON" });
  const editorMsg = h("div", { class: "msgs" });

  function showMessages(kind, lines) {
    mount(editorMsg, lines.map((line) => h("p", { class: kind, text: line })));
  }

  async function reload() {
    [listing, doc] = await Promise.all([api("/v1/prompts"), api("/v1/me/settings")]);
    draw();
  }

  // ---- defaults ----------------------------------------------------------------------------
  function defaultsCard() {
    const keys = allKeys(listing);
    const draft = { panel: listing.panel_default, long: listing.default, language: doc.settings.summaries.language, auto_long: doc.settings.summaries.auto_long };
    const panel = select(keys, draft.panel, (v) => (draft.panel = v));
    const long = select(keys, draft.long, (v) => (draft.long = v));
    const lang = textInput(draft.language, { maxlength: 40, placeholder: "en" });
    lang.addEventListener("input", () => (draft.language = lang.value.trim()));
    const auto = switchRow("Also build the long summary", "After a panel summary, the long one is prepared in the background.", draft.auto_long, (v) => (draft.auto_long = v));
    const msg = h("p", { class: "bad", text: "" });
    async function save() {
      msg.textContent = "";
      const settings = {
        prompts: { default: draft.long, panel_default: draft.panel },
        summaries: { language: draft.language || null, auto_long: draft.auto_long },
      };
      try {
        doc = await api("/v1/me/settings", { method: "PUT", body: { version: doc.version, settings } });
        toast("Defaults saved");
        await reload();
      } catch (err) {
        msg.textContent = errorText(err);
      }
    }
    return card(
      "Defaults",
      field("Side panel prompt", panel, "Short card shown while you browse."),
      field("Long summary prompt", long, "What the Summary view shows."),
      field("Summary language", lang, "Used for {language} in prompts."),
      auto,
      msg,
      button("Save defaults", save, { kind: "primary" }),
    );
  }

  // ---- sets --------------------------------------------------------------------------------
  function setCard(set) {
    const builtin = set.id === "builtin";
    return h(
      "div",
      { class: "set" },
      h("div", { class: "row between" }, h("strong", { text: set.name }), pill(builtin ? "built in" : "v" + (set.version || "?"))),
      h("small", { class: "muted", text: set.id + (set.source_url ? "  from " + set.source_url : "") }),
      h(
        "ul",
        { class: "plain prompts" },
        set.prompts.map((p) =>
          h(
            "li",
            {},
            h("span", { text: p.label }),
            p.default ? pill("long", "ok") : null,
            p.panel_default ? pill("panel", "ok") : null,
          ),
        ),
      ),
      h(
        "div",
        { class: "row" },
        button(builtin ? "View JSON" : "Edit JSON", async () => {
          editor.value = JSON.stringify(await api("/v1/prompts/sets/" + encodeURIComponent(set.id)), null, 2);
          showMessages("ok", [(builtin ? "Built-in sets cannot be changed; copy it under another id to edit." : "Loaded " + set.id)]);
          editor.scrollIntoView({ behavior: "smooth", block: "center" });
        }, { kind: "sec" }),
        builtin
          ? null
          : button("Delete", async () => {
              if (!window.confirm("Delete the set " + set.name + "?")) return;
              await api("/v1/prompts/sets/" + encodeURIComponent(set.id), { method: "DELETE" });
              toast("Deleted");
              await reload();
            }, { kind: "danger" }),
      ),
    );
  }

  function importCard() {
    const url = textInput("", { placeholder: "https://... prompt set URL", type: "url", maxlength: 500 });
    return card(
      "Import",
      field("Prompt set URL", url, "Short links are followed. Sets from a URL can be refreshed later."),
      h(
        "div",
        { class: "row" },
        button("Import", async () => {
          if (!url.value.trim()) return;
          const set = await api("/v1/prompts/import", { method: "POST", body: { url: url.value.trim() } });
          toast("Imported " + set.id);
          url.value = "";
          await reload();
        }, { kind: "primary" }),
        button("Refresh all", async () => {
          const r = await api("/v1/prompts/refresh", { method: "POST" });
          const lines = Object.entries(r.refreshed).map(([id, state]) => id + ": " + state);
          toast(lines.length ? lines.join("; ") : "Nothing to refresh (no set was imported from a URL)");
          await reload();
        }, { kind: "sec" }),
      ),
    );
  }

  function editorCard() {
    async function validate(announce = true) {
      const syntax = jsonProblem(editor.value);
      if (syntax) {
        showMessages("bad", [syntax]);
        return null;
      }
      try {
        const r = await api("/v1/prompts/validate", { method: "POST", body: JSON.parse(editor.value) });
        if (announce) showMessages("ok", ["Valid: set " + r.id + " with " + r.prompts + (r.prompts === 1 ? " prompt" : " prompts")]);
        return JSON.parse(editor.value);
      } catch (err) {
        showMessages("bad", errorText(err).split("; "));
        return null;
      }
    }
    return card(
      "Edit a prompt set",
      note("A set is JSON with an id, a name and prompts. Variables: {title} {channel} {duration} {description} {transcript} {language} {question}."),
      editor,
      editorMsg,
      h(
        "div",
        { class: "row" },
        button("New from template", () => {
          editor.value = JSON.stringify(TEMPLATE, null, 2);
          showMessages("muted", ["Template loaded. Change the id and save."]);
        }, { kind: "sec" }),
        button("Validate", () => validate(true), { kind: "sec" }),
        button("Save set", async () => {
          const data = await validate(false);
          if (!data) return;
          await api("/v1/prompts/sets/" + encodeURIComponent(data.id), { method: "PUT", body: data });
          showMessages("ok", ["Saved " + data.id]);
          toast("Saved " + data.id);
          await reload();
        }, { kind: "primary" }),
      ),
    );
  }

  // ---- try ---------------------------------------------------------------------------------
  function tryCard() {
    const keys = [...allKeys(listing), { value: ADHOC, label: "Ad-hoc text (below)" }];
    const ref = textInput("", { placeholder: "video id or YouTube link", maxlength: 500 });
    const pick = select(keys, listing.default);
    const adhoc = h("textarea", { class: "code", rows: 5, placeholder: "Ad-hoc prompt, e.g. List the tools mentioned in {transcript}", hidden: true });
    pick.addEventListener("change", () => (adhoc.hidden = pick.value !== ADHOC));
    const status = h("p", { class: "muted", text: "" });
    const out = h("div", {});

    async function run() {
      mount(out);
      status.className = "muted";
      status.textContent = "Resolving the video...";
      let videoId;
      try {
        videoId = (await api("/v1/videos/resolve", { method: "POST", body: { text: ref.value } })).video_id;
      } catch (err) {
        status.className = "bad";
        status.textContent = errorText(err);
        return;
      }
      const useAdhoc = pick.value === ADHOC;
      if (useAdhoc && !adhoc.value.trim()) {
        status.className = "bad";
        status.textContent = "Type the ad-hoc prompt first.";
        return;
      }
      for (let attempt = 1; attempt <= POLL_ATTEMPTS && !cancelled; attempt++) {
        status.className = "muted";
        status.textContent = attempt === 1 ? "Working..." : "Still working (" + attempt + ")...";
        const r = useAdhoc
          ? await api("/v1/videos/" + videoId + "/summary", { method: "POST", body: { prompt_text: adhoc.value, wait_ms: POLL_WAIT_MS } })
          : await api("/v1/videos/" + videoId + "/summary", { query: { prompt: pick.value, wait_ms: POLL_WAIT_MS } });
        if (r.status === "pending" && r.transcript_status !== "delayed") {
          if (r.transcript_status === "transcribing") status.textContent = "Transcribing the audio " + Math.round((r.progress || 0) * 100) + "%...";
          continue;
        }
        showResult(r, videoId);
        return;
      }
      status.textContent = "Still pending. Try again in a moment.";
    }

    function showResult(r, videoId) {
      status.className = r.status === "ready" ? "ok" : r.status === "failed" ? "bad" : "muted";
      status.textContent = r.status + (r.source ? " (transcript from " + r.source + ")" : "");
      if (r.status === "ready") {
        mount(out, h("pre", { class: "result", text: r.text }), h("small", { class: "muted", text: "Prompt: " + r.prompt }));
      } else if (r.status === "needs_transcript") {
        mount(
          out,
          h("p", { text: r.message }),
          r.can_transcribe
            ? button("Transcribe in background", async () => {
                await api("/v1/videos/" + videoId + "/transcribe", { method: "POST" });
                toast("Transcription queued; see Captions");
              }, { kind: "primary" })
            : null,
        );
      } else {
        mount(out, h("p", { class: r.status === "failed" ? "bad" : "muted", text: r.error || "No result yet." }));
      }
    }

    return card("Try a prompt", field("Video", ref), field("Prompt", pick), adhoc, h("div", { class: "row" }, button("Run", run, { kind: "primary" })), status, out);
  }

  function draw() {
    mount(
      host,
      h("h1", { class: "page-title", text: "Prompts" }),
      defaultsCard(),
      card("Prompt sets", listing.sets.length ? listing.sets.map(setCard) : empty("No sets.")),
      importCard(),
      editorCard(),
      tryCard(),
    );
  }

  mount(view, host);
  draw();
  return () => {
    cancelled = true;
  };
}
