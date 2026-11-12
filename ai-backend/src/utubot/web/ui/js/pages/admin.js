import { api, session } from "../api.js";
import { h, mount } from "../dom.js";
import { bigCode, button, card, empty, errorText, field, fmtAgo, note, pill, switchRow, textInput, toast } from "../components.js";
import { filteringForm } from "./filtering.js";
import { modelsForm } from "./models.js";
import { transcriptPolicyForm } from "./transcripts.js";
import { tvSettingsForm } from "./devices.js";

function userRow(user, reload) {
  const panel = h("div", {});
  const flags = [
    user.admin ? pill("admin", "ok") : null,
    pill(user.has_password ? "password" : "no password", user.has_password ? "" : "warn"),
    pill(user.has_token ? "token" : "no token"),
    pill(user.devices + (user.devices === 1 ? " TV" : " TVs")),
  ];

  function passwordForm() {
    const pw = textInput("", { type: "password", autocomplete: "new-password", maxlength: 512 });
    const msg = h("p", { class: "bad", text: "" });
    mount(
      panel,
      h(
        "form",
        { class: "stack inset", onsubmit: (e) => e.preventDefault() },
        field("New password for " + user.name, pw, "At least 10 characters. Their other sessions are signed out."),
        msg,
        h("div", { class: "row" }, button("Set password", async () => {
          try {
            const r = await api("/v1/users/" + encodeURIComponent(user.name) + "/password", { method: "PUT", body: { password: pw.value } });
            if (r.csrf) session.csrf = r.csrf;
            toast("Password set for " + user.name);
            await reload();
          } catch (err) {
            msg.textContent = errorText(err);
          }
        }, { kind: "primary", type: "submit" }), button("Cancel", () => mount(panel), { kind: "sec" })),
      ),
    );
    pw.focus();
  }

  async function pairing() {
    const r = await api("/v1/admin/pair", { method: "POST", body: { user: user.name } });
    mount(panel, h("div", { class: "inset" }, bigCode(r.code), h("small", { class: "muted", text: "One-time code for " + user.name + ", valid " + Math.round(r.expires_in_s / 60) + " minutes." })));
  }

  async function toggleAdmin() {
    await api("/v1/users/" + encodeURIComponent(user.name), { method: "PUT", body: { admin: !user.admin } });
    toast(user.name + (user.admin ? " is no longer an admin" : " is now an admin"));
    await reload();
  }

  return h(
    "div",
    { class: "job" },
    h("strong", { text: user.name }),
    h("div", { class: "row" }, flags),
    h(
      "div",
      { class: "row" },
      h("a", { class: "btn sec", href: "#/admin/user/" + encodeURIComponent(user.name), text: "Settings" }),
      button("Password", passwordForm, { kind: "sec" }),
      button("Pairing code", pairing, { kind: "sec" }),
      user.admin_editable && user.name !== session.user ? button(user.admin ? "Remove admin" : "Make admin", toggleAdmin, { kind: "sec" }) : null,
    ),
    panel,
  );
}

function newUserCard(reload) {
  const name = textInput("", { placeholder: "name", maxlength: 32, autocomplete: "off" });
  const pw = textInput("", { type: "password", autocomplete: "new-password", maxlength: 512 });
  const adminSwitch = switchRow("Admin", "Can manage users and see every user's settings.", false);
  const msg = h("p", { class: "bad", text: "" });
  return card(
    "Add a user",
    h(
      "form",
      { class: "stack", onsubmit: (e) => e.preventDefault() },
      field("Name", name, "Letters, digits, dot, dash and underscore."),
      field("Password (optional)", pw, "Without one the user can only sign in with a token or from a TV."),
      adminSwitch,
      msg,
      button("Create user", async () => {
        msg.textContent = "";
        try {
          await api("/v1/users", { method: "POST", body: { name: name.value.trim(), password: pw.value || null, admin: adminSwitch.input.checked } });
          toast("User created");
          name.value = "";
          pw.value = "";
          await reload();
        } catch (err) {
          msg.textContent = errorText(err);
        }
      }, { kind: "primary", type: "submit" }),
    ),
  );
}

async function usersPage(view) {
  const host = h("div", { class: "stack" });
  async function load() {
    const { users } = await api("/v1/users");
    mount(
      host,
      h("h1", { class: "page-title", text: "Admin" }),
      card("Users", users.length ? users.map((u) => userRow(u, load)) : empty("No users.")),
      newUserCard(load),
      note("Users declared in config.toml keep their admin flag there. Tokens are created with `utubot user add`."),
    );
  }
  mount(view, host);
  await load();
}

async function userSettingsPage(view, name) {
  const path = "/v1/users/" + encodeURIComponent(name) + "/settings";
  let doc = await api(path);
  let catalog = await api("/v1/models");
  let target = (await api("/v1/admin/users")).users.find((u) => u.name === name);
  const host = h("div", { class: "stack" });

  async function draw() {
    const models = await modelsForm(path, doc, catalog, (next) => {
      doc = next;
      draw();
    });
    const update = (next) => {
      doc = next;
      draw();
    };
    mount(
      host,
      h("a", { class: "back", href: "#/admin", text: "Back to users" }),
      h("h1", { class: "page-title", text: "Settings of " + name }),
      note("Version " + doc.version + ". Prompt defaults: panel " + doc.settings.prompts.panel_default + ", long " + doc.settings.prompts.default + " (the user changes these themselves)."),
      card("Models", models),
      filteringForm(path, doc, update),
      transcriptPolicyForm(path, doc, update),
      tvSettingsForm(path, doc, update),
      card(
        "Linked TVs",
        target && target.devices.length
          ? target.devices.map((d) =>
              h(
                "div",
                { class: "job" },
                h("div", { class: "row between nowrap" }, h("strong", { class: "job-title", text: d.device }), button("Revoke", async () => {
                  if (!window.confirm("Revoke " + d.device + "?")) return;
                  await api("/v1/admin/devices/" + encodeURIComponent(d.id), { method: "DELETE" });
                  toast("Revoked");
                  target = (await api("/v1/admin/users")).users.find((u) => u.name === name);
                  await draw();
                }, { kind: "danger" })),
                h("small", { class: "muted", text: "Linked " + fmtAgo(d.created_at) + ", last used " + fmtAgo(d.last_used) }),
              ),
            )
          : empty("No TV is linked."),
      ),
    );
  }
  mount(view, host);
  await draw();
}

export async function render(view, { rest }) {
  if (rest[0] === "user" && rest[1]) return userSettingsPage(view, rest[1]);
  return usersPage(view);
}
