import { ApiError, forgetSession, loadSession, session } from "./api.js";
import { h, icon, mount } from "./dom.js";
import { errorText, failure, loading } from "./components.js";
import * as account from "./pages/account.js";
import * as admin from "./pages/admin.js";
import * as devices from "./pages/devices.js";
import * as filtering from "./pages/filtering.js";
import * as home from "./pages/home.js";
import * as login from "./pages/login.js";
import * as models from "./pages/models.js";
import * as more from "./pages/more.js";
import * as prompts from "./pages/prompts.js";
import * as transcripts from "./pages/transcripts.js";
import * as updates from "./pages/updates.js";
import { applyTheme } from "./theme.js";

// path -> page. `primary` entries sit in the phone's bottom bar; the rest live under "More".
const ROUTES = [
  { path: "home", label: "Home", icon: "home", page: home, primary: true },
  { path: "models", label: "Models", icon: "models", page: models, primary: true },
  { path: "prompts", label: "Prompts", icon: "prompts", page: prompts, primary: true },
  { path: "filters", label: "Filters", icon: "filters", page: filtering, primary: true },
  { path: "captions", label: "Captions", icon: "captions", page: transcripts, primary: true },
  { path: "tvs", label: "TVs", icon: "tv", page: devices },
  { path: "updates", label: "Updates", icon: "updates", page: updates },
  { path: "account", label: "Account", icon: "account", page: account },
  { path: "admin", label: "Admin", icon: "admin", page: admin, adminOnly: true },
];

const view = document.getElementById("view");
const nav = document.getElementById("nav");
let cleanup = null;
let renderToken = 0;

function parseHash() {
  const raw = (location.hash || "#/home").replace(/^#\/?/, "");
  const [path, ...rest] = raw.split("/");
  return { path: path || "home", rest: rest.map(decodeURIComponent) };
}

function drawNav(current) {
  const items = ROUTES.filter((r) => !r.adminOnly || session.admin);
  const primary = items.filter((r) => r.primary);
  const links = primary.map((r) => navLink(r, current === r.path));
  links.push(
    h(
      "a",
      { href: "#/more", class: "nav-link more-link" + (!primary.some((r) => r.path === current) && current !== "" ? " on" : "") },
      icon("more"),
      h("span", { text: "More" }),
    ),
  );
  for (const r of items.filter((x) => !x.primary)) links.push(navLink(r, current === r.path, "wide-only"));
  mount(nav, links);
  nav.hidden = false;
}

function navLink(route, on, extra = "") {
  return h(
    "a",
    { href: "#/" + route.path, class: ["nav-link", on ? "on" : "", extra].join(" ").trim(), "aria-current": on ? "page" : null },
    icon(route.icon),
    h("span", { text: route.label }),
  );
}

async function renderRoute() {
  const token = ++renderToken;
  if (cleanup) {
    try {
      cleanup();
    } catch {
      /* page already gone */
    }
    cleanup = null;
  }
  if (!session.user) {
    nav.hidden = true;
    mount(view);
    cleanup = await login.render(view, { onSignedIn });
    return;
  }
  const { path, rest } = parseHash();
  if (path === "more") {
    drawNav("more");
    mount(view);
    cleanup = await more.render(view, { routes: ROUTES.filter((r) => !r.primary && (!r.adminOnly || session.admin)) });
    return;
  }
  const route = ROUTES.find((r) => r.path === path && (!r.adminOnly || session.admin));
  if (!route) {
    location.hash = "#/home";
    return;
  }
  drawNav(route.path);
  mount(view, loading());
  window.scrollTo(0, 0);
  try {
    const stop = await route.page.render(view, { rest, onSignedOut });
    if (token === renderToken) cleanup = stop || null;
    else if (stop) stop();
  } catch (err) {
    if (token !== renderToken) return;
    if (err instanceof ApiError && err.status === 401) return;
    mount(view, failure(err, renderRoute));
  }
}

async function onSignedIn() {
  location.hash = "#/home";
  await renderRoute();
  checkHealth();
}

function onSignedOut() {
  forgetSession();
  renderRoute();
}

async function checkHealth() {
  const el = document.getElementById("health");
  try {
    const res = await fetch("/v1/health", { cache: "no-store" });
    const body = await res.json();
    el.textContent = body.ok ? "online" : "down";
    el.className = "pill " + (body.ok ? "ok" : "bad");
  } catch {
    el.textContent = "offline";
    el.className = "pill bad";
  }
}

window.addEventListener("hashchange", renderRoute);
window.addEventListener("utubot:signed-out", () => {
  if (session.user) onSignedOut();
});

async function boot() {
  applyTheme();
  checkHealth();
  setInterval(checkHealth, 30000);
  try {
    await loadSession();
  } catch (err) {
    mount(view, h("p", { class: "bad pad", text: errorText(err) }));
    return;
  }
  await renderRoute();
}

boot();
