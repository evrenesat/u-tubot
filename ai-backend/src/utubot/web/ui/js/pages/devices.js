import { api, session } from "../api.js";
import { h, mount } from "../dom.js";
import { bigCode, button, card, empty, every, errorText, fmtAgo, fmtDuration, note, numberInput, field, segmented, switchRow, toast } from "../components.js";

// Settings the TV will read from the server in a later release.
export function tvSettingsForm(settingsPath, doc, onUpdate) {
  const current = doc.settings.tv;
  const draft = { ...current };
  const delay = numberInput(current.summary_delay_ms, { min: 0, max: 10000, step: 100 });
  delay.addEventListener("input", () => (draft.summary_delay_ms = Math.max(0, Math.round(Number(delay.value) || 0))));
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
      onUpdate(await api(settingsPath, { method: "PUT", body: { version: doc.version, settings: { tv: changes } } }));
      toast("TV settings saved");
    } catch (err) {
      msg.textContent = errorText(err);
    }
  }
  return card(
    "TV settings",
    note("Kept on the server and applied to your TVs once they read settings from it (a later app release)."),
    switchRow("Summary panel on by default", "Show the side panel while browsing.", current.summary_panel, (v) => (draft.summary_panel = v)),
    field("Wait before summarizing (ms)", delay, "How long a card must stay focused first."),
    switchRow("Prepare captions automatically", "Offer u·tubot captions when they exist.", current.auto_captions, (v) => (draft.auto_captions = v)),
    switchRow("Check for app updates", "The TV asks this server for a newer app.", current.update_checks, (v) => (draft.update_checks = v)),
    msg,
    button("Save TV settings", save, { kind: "primary" }),
  );
}

// Your default cut mode, per user; a pick in the TV picker or the cut sheet can still choose the other mode.
export function cutModeForm(settingsPath, doc, onUpdate) {
  const current = doc.settings.cuts || {};
  const value = current.cut_mode || "quick";
  let draft = value;
  const msg = h("p", { class: "bad", text: "" });
  const control = segmented(
    [
      ["quick", "Quick"],
      ["watched", "Watched"],
    ],
    value,
    (v) => (draft = v),
  );
  async function save() {
    msg.textContent = "";
    if (draft === value) {
      toast("Nothing changed");
      return;
    }
    try {
      onUpdate(await api(settingsPath, { method: "PUT", body: { version: doc.version, settings: { cuts: { cut_mode: draft } } } }));
      toast("Cut mode saved");
    } catch (err) {
      msg.textContent = errorText(err);
    }
  }
  return card(
    "Cut mode",
    note("Quick reads the transcript only; Watched also looks at the picture and takes longer. The TV offers Quick when a watched cut fails."),
    control,
    msg,
    button("Save cut mode", save, { kind: "primary" }),
  );
}

const RETENTION_CHOICES = [
  [0, "Keep nothing"],
  [7, "7 days"],
  [30, "30 days"],
  [90, "90 days"],
];

// Voice control: one switch per linked device (off until the user has read what it means), the
// all-off switch and how long the command history is kept. The server serves the consent text.
export function voiceForm(onChange) {
  const host = h("div", {});
  let consentFor = null;

  async function load() {
    draw(await api("/v1/me/voice"));
  }

  async function put(path, body) {
    try {
      draw(await api(path, { method: "PUT", body }));
    } catch (err) {
      toast(errorText(err), "bad");
      await load();
    }
  }

  function consentPanel(overview, dev) {
    return h(
      "div",
      { class: "placeholder" },
      h("strong", { text: "Voice on " + dev.device }),
      h("ul", { class: "consent" }, overview.consent.text.map((line) => h("li", { text: line }))),
      h(
        "div",
        { class: "row" },
        button(
          "Allow voice",
          async () => {
            consentFor = null;
            await put("/v1/me/devices/" + encodeURIComponent(dev.id) + "/voice", { enabled: true, consent_version: overview.consent.version });
          },
          { kind: "primary" },
        ),
        button("Cancel", async () => {
          consentFor = null;
          await load();
        }),
      ),
    );
  }

  function deviceRow(overview, dev) {
    const path = "/v1/me/devices/" + encodeURIComponent(dev.id) + "/voice";
    const toggle = switchRow(dev.device, dev.enabled ? "Voice is on" : consentFor === dev.id ? "Read what it means, then allow or cancel" : "Voice is off", dev.enabled || consentFor === dev.id, async (on) => {
      if (on) {
        consentFor = dev.id;
        draw(overview);
        return;
      }
      consentFor = null;
      await put(path, { enabled: false });
    });
    const extra = [];
    if (dev.enabled) {
      extra.push(
        switchRow("Spoken replies", "The device may read its answers aloud.", dev.speak, (v) => put(path, { speak: v })),
        switchRow("Hands-free", "Listen for the wake word instead of waiting for Talk (robot mode only).", dev.listen_mode === "wake", (v) =>
          put(path, { listen_mode: v ? "wake" : "push" }),
        ),
      );
    }
    return h("div", { class: "job" }, toggle, extra, consentFor === dev.id && !dev.enabled ? consentPanel(overview, dev) : null);
  }

  function draw(overview) {
    const keep = h("select", {});
    for (const [days, label] of RETENTION_CHOICES) {
      const opt = h("option", { value: String(days), text: label });
      if (days === overview.retention_days) opt.selected = true;
      keep.appendChild(opt);
    }
    if (!RETENTION_CHOICES.some(([d]) => d === overview.retention_days)) {
      const opt = h("option", { value: String(overview.retention_days), text: overview.retention_days + " days" });
      opt.selected = true;
      keep.appendChild(opt);
    }
    keep.addEventListener("change", () => put("/v1/me/voice", { retention_days: Number(keep.value) }).then(() => toast("Retention saved")));
    mount(
      host,
      card(
        "Voice control",
        note("Off for every device until you switch it on. No audio is stored; only the text of what you said and what it did is kept."),
        overview.devices.length ? overview.devices.map((d) => deviceRow(overview, d)) : empty("Link a device first."),
        field("Keep the history for", keep, "Older entries are deleted. See Voice for the list."),
        overview.devices.some((d) => d.enabled)
          ? button("Switch voice off on every device", async () => {
              await put("/v1/me/voice", { all_off: true });
              toast("Voice is off everywhere");
              if (onChange) onChange();
            }, { kind: "danger", full: true })
          : null,
      ),
    );
  }

  load().catch((err) => mount(host, note(errorText(err), "bad")));
  return host;
}

export async function render(view) {
  let doc = await api("/v1/me/settings");
  const host = h("div", { class: "stack" });
  const codeHost = h("div", {});
  const devicesHost = h("div", {});
  let stopCountdown = null;

  async function loadDevices() {
    const { devices } = await api("/v1/me/devices");
    mount(
      devicesHost,
      devices.length
        ? devices.map((d) =>
            h(
              "div",
              { class: "job" },
              h("div", { class: "row between nowrap" }, h("strong", { class: "job-title", text: d.device }), button("Revoke", async () => {
                if (!window.confirm("Revoke " + d.device + "? It will have to be linked again.")) return;
                await api("/v1/me/devices/" + encodeURIComponent(d.id), { method: "DELETE" });
                toast("Revoked");
                await loadDevices();
              }, { kind: "danger" })),
              h("small", { class: "muted", text: "Linked " + fmtAgo(d.created_at) + ", last used " + fmtAgo(d.last_used) }),
              session.settingsSync ? h("a", { href: "#/settings/tv/" + encodeURIComponent(d.id), text: "Settings of this TV" }) : null,
            ),
          )
        : empty("No TV is linked yet."),
    );
  }

  async function makeCode() {
    const r = await api("/v1/me/pair", { method: "POST" });
    const expires = Date.now() + r.expires_in_s * 1000;
    const left = h("small", { class: "muted", text: "" });
    const tick = () => {
      const s = Math.max(0, Math.round((expires - Date.now()) / 1000));
      left.textContent = s ? "Valid for " + fmtDuration(s) + ", single use." : "Expired. Make a new code.";
    };
    tick();
    if (stopCountdown) stopCountdown();
    stopCountdown = every(1000, tick);
    mount(
      codeHost,
      bigCode(r.code),
      left,
      h(
        "ol",
        { class: "steps" },
        h("li", { text: "Install u·tubot on the TV (see Updates for the download)." }),
        h("li", { text: "Open Settings, u·tubot, Import setup, and type this server's address: " + location.host + "." }),
        h("li", { text: "When the TV asks for the pairing code, enter the digits above." }),
      ),
    );
  }

  function draw() {
    mount(
      host,
      h("h1", { class: "page-title", text: "TV devices" }),
      card(
        "Link a TV",
        note("Make a one-time code and type it on the TV. Each TV gets its own access that you can revoke here."),
        button("Make a code", makeCode, { kind: "primary", full: true }),
        codeHost,
        h("div", { class: "placeholder" }, h("strong", { text: "Scan to link" }), h("small", { class: "muted", text: "A QR code and a one-step enrollment link are planned for a later release." })),
      ),
      card("Linked TVs", devicesHost),
      session.voice ? voiceForm() : null,
      session.settingsSync
        ? card("TV settings", note("Every TV setting is on the Settings page, with a tab for each TV."), h("a", { class: "btn sec", href: "#/settings", text: "Open Settings" }))
        : tvSettingsForm("/v1/me/settings", doc, (next) => {
            doc = next;
            draw();
          }),
      cutModeForm("/v1/me/settings", doc, (next) => {
        doc = next;
        draw();
      }),
    );
  }

  mount(view, host);
  draw();
  await loadDevices();
  return () => stopCountdown && stopCountdown();
}
