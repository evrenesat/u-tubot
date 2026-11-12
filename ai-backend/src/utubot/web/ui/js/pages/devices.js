import { api } from "../api.js";
import { h, mount } from "../dom.js";
import { bigCode, button, card, empty, every, errorText, fmtAgo, fmtDuration, note, numberInput, field, switchRow, toast } from "../components.js";

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
      tvSettingsForm("/v1/me/settings", doc, (next) => {
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
