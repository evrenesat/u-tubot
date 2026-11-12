import { ApiError, api, forgetSession, session } from "../api.js";
import { h, mount } from "../dom.js";
import { button, card, errorText, field, segmented, statRow, textInput, toast } from "../components.js";
import { getTheme, setTheme } from "../theme.js";

export async function render(view, { onSignedOut }) {
  const info = await api("/v1/auth/session");
  const current = textInput("", { type: "password", autocomplete: "current-password", maxlength: 512 });
  const next = textInput("", { type: "password", autocomplete: "new-password", maxlength: 512 });
  const msg = h("p", { class: "bad", text: "" });

  async function changePassword() {
    msg.textContent = "";
    try {
      const body = { new_password: next.value };
      if (info.has_password) body.current_password = current.value;
      const r = await api("/v1/me/password", { method: "PUT", body });
      if (r.csrf) session.csrf = r.csrf;
      current.value = "";
      next.value = "";
      toast("Password changed. Other sessions were signed out.");
    } catch (err) {
      msg.textContent = errorText(err);
    }
  }

  async function signOut() {
    try {
      await api("/v1/auth/logout", { method: "POST" });
    } catch (err) {
      if (!(err instanceof ApiError)) throw err;
    }
    forgetSession();
    onSignedOut();
  }

  const form = h(
    "form",
    { class: "stack", autocomplete: "on" },
    info.has_password ? field("Current password", current) : h("p", { class: "muted", text: "This account has no password yet. Set one to sign in with a username." }),
    field("New password", next, "At least 10 characters."),
    msg,
    button("Change password", changePassword, { kind: "primary", type: "submit" }),
  );
  form.addEventListener("submit", (e) => e.preventDefault());

  mount(
    view,
    h("h1", { class: "page-title", text: "Account" }),
    card("Signed in", statRow("User", info.user), statRow("Role", info.admin ? "admin" : "user"), statRow("Session", info.via === "cookie" ? "browser session" : "token")),
    card("Password", form),
    card(
      "Theme",
      segmented(
        [
          ["auto", "Auto"],
          ["light", "Light"],
          ["dark", "Dark"],
        ],
        getTheme(),
        setTheme,
      ),
    ),
    card("Session", button("Sign out", signOut, { kind: "danger", full: true })),
  );
}
