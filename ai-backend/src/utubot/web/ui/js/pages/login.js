import { ApiError, adoptLogin, api } from "../api.js";
import { h, mount } from "../dom.js";
import { button, card, field, segmented, textInput } from "../components.js";

const ABI_NOTES = {
  "arm64-v8a": "most current TVs and boxes",
  "armeabi-v7a": "older and 32-bit TVs",
  x86: "x86 devices and emulators",
  x86_64: "x86-64 devices",
  universal: "works everywhere, larger",
};

export async function render(view, { onSignedIn }) {
  let mode = "password";
  const message = h("p", { class: "bad", role: "alert", text: "" });
  const body = h("div", {});

  async function submit(payload) {
    message.textContent = "";
    try {
      adoptLogin(await api("/v1/auth/login", { method: "POST", body: payload }));
      await onSignedIn();
    } catch (err) {
      message.textContent = err instanceof ApiError ? err.message : "Could not sign in";
    }
  }

  function draw() {
    const form = h("form", { class: "stack", autocomplete: "on" });
    if (mode === "password") {
      const user = textInput("", { autocomplete: "username", maxlength: 64 });
      user.name = "username";
      const pass = textInput("", { type: "password", autocomplete: "current-password", maxlength: 512 });
      pass.name = "password";
      form.append(field("Username", user), field("Password", pass));
      form.append(button("Sign in", () => submit({ username: user.value.trim(), password: pass.value }), { kind: "primary", full: true, type: "submit" }));
    } else {
      const token = textInput("", { type: "password", autocomplete: "off", maxlength: 512 });
      token.name = "token";
      form.append(field("User token", token, "The token printed by `utubot user add`. It is exchanged for a session; this page does not keep it."));
      form.append(button("Sign in with token", () => submit({ token: token.value.trim() }), { kind: "primary", full: true, type: "submit" }));
    }
    form.addEventListener("submit", (e) => e.preventDefault());
    mount(body, form, message);
  }

  draw();
  const modeSwitch = segmented(
    [
      ["password", "Password"],
      ["token", "Token"],
    ],
    mode,
    (value) => {
      mode = value;
      draw();
    },
  );
  const downloads = h("div", {});
  mount(view, h("div", { class: "login" }, card("Sign in", modeSwitch, body), downloads));
  loadDownloads(downloads);
}

async function loadDownloads(host) {
  try {
    const res = await fetch("/app/info.json");
    if (!res.ok) return;
    const info = await res.json();
    const abis = Object.keys(info.files || {});
    if (!abis.length) return;
    const codes = info.downloader_codes || {};
    mount(
      host,
      card(
        "Get the TV app",
        h("p", {}, "Latest version ", h("strong", { text: info.version_name || "" })),
        h(
          "ul",
          { class: "plain" },
          abis.map((abi) =>
            h(
              "li",
              {},
              h("a", { href: info.files[abi].path, text: abi }),
              " ",
              h("span", { class: "muted", text: ABI_NOTES[abi] || "" }),
              codes[abi] ? h("span", { class: "pill", text: "Downloader " + codes[abi] }) : null,
            ),
          ),
        ),
        h("p", { class: "muted", text: "On the TV: Settings, u·tubot, Import setup, then type this server's address." }),
      ),
    );
  } catch {
    /* the public download section is optional */
  }
}
