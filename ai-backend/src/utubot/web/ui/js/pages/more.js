import { h, icon, mount } from "../dom.js";

const DESCRIPTIONS = {
  tvs: "Link a TV, revoke devices, TV settings",
  updates: "App version on this server and on GitHub",
  account: "Password, theme, sign out",
  admin: "Users, settings and the media archive",
};

export async function render(view, { routes }) {
  mount(
    view,
    h("h1", { class: "page-title", text: "More" }),
    h(
      "div",
      { class: "menu" },
      routes.map((r) =>
        h(
          "a",
          { href: "#/" + r.path, class: "menu-item" },
          icon(r.icon),
          h("span", { class: "menu-text" }, h("strong", { text: r.label }), h("small", { class: "muted", text: DESCRIPTIONS[r.path] || "" })),
        ),
      ),
    ),
  );
}
