import { api } from "../api.js";
import { h, mount, safeHref } from "../dom.js";
import { button, card, fmtAgo, fmtTime, note, pill, statRow, toast } from "../components.js";

function parseIso(text) {
  const ms = Date.parse(text || "");
  return Number.isNaN(ms) ? 0 : ms / 1000;
}

export async function render(view) {
  let info = await api("/v1/updates");
  const host = h("div", { class: "stack" });

  async function check() {
    info = await api("/v1/updates/refresh", { method: "POST" });
    toast("Checked GitHub");
    draw();
  }

  function draw() {
    const ch = info.channel;
    const gh = info.github;
    const sync = info.last_sync;
    const latest = gh.latest;
    const url = latest ? safeHref(latest.url, ["github.com"]) : null;
    mount(
      host,
      h("h1", { class: "page-title", text: "App updates" }),
      card(
        "On this server",
        ch.published
          ? [
              statRow("Version", ch.version_name + " (" + ch.version_code + ")"),
              statRow("Published", fmtAgo(ch.published_at)),
              statRow("Builds", Object.keys(ch.files).join(", ")),
              ch.changelog && ch.changelog.length ? h("ul", { class: "plain" }, ch.changelog.slice(0, 6).map((l) => h("li", { text: l }))) : null,
            ]
          : note("No app is published on this server yet."),
      ),
      card(
        "Latest GitHub release",
        !gh.configured
          ? note("No repository is configured. Set [app] github_repo to follow releases.")
          : gh.error
            ? h("p", { class: "bad", text: gh.error })
            : latest
              ? [
                  h("div", { class: "row between" }, h("strong", { text: latest.version }), info.behind === true ? pill("newer than this server", "warn") : info.behind === false ? pill("server is current", "ok") : null),
                  statRow("Released", latest.published_at ? fmtAgo(parseIso(latest.published_at)) : "unknown"),
                  url ? h("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: "Release notes on GitHub" }) : null,
                ]
              : note("No release found."),
        gh.configured ? h("div", { class: "row" }, button("Check now", check, { kind: "sec" })) : null,
      ),
      card(
        "Last sync",
        sync
          ? [
              statRow("Time", fmtTime(sync.checked_at)),
              statRow("Result", sync.status, sync.status === "error" || sync.status === "unreachable" ? "bad" : ""),
              sync.error ? h("p", { class: "bad", text: sync.error }) : null,
            ]
          : note("No sync has run. Schedule `utubot app sync-github` to follow GitHub releases automatically."),
      ),
      card("TV update address", h("p", { class: "mono", text: info.update_url }), note("TVs poll this address for new versions.")),
    );
  }

  mount(view, host);
  draw();
}
