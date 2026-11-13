// Tiny DOM helpers. Every piece of text goes in through textContent or a text node, never as
// markup, so titles, prompt text and server messages cannot inject HTML or script.

const SVG_NS = "http://www.w3.org/2000/svg";

function append(parent, kids) {
  for (const kid of kids) {
    if (kid === null || kid === undefined || kid === false) continue;
    if (Array.isArray(kid)) append(parent, kid);
    else if (kid instanceof Node) parent.appendChild(kid);
    else parent.appendChild(document.createTextNode(String(kid)));
  }
}

export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "for") el.htmlFor = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (["value", "checked", "disabled", "type", "min", "max", "step", "selected", "readOnly"].includes(key)) {
      el[key] = value;
    } else el.setAttribute(key, value === true ? "" : String(value));
  }
  append(el, kids);
  return el;
}

const ICONS = {
  home: "M3 11l9-8 9 8v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z",
  models: "M8 6h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2zM9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3",
  prompts: "M4 5h16v11H9l-5 4zM8 9h8M8 12h5",
  filters: "M3 5h18l-7 8v6l-4-2v-4z",
  captions: "M3 6h18v12H3zM7 11h4M13 11h4M7 14h2M12 14h5",
  tv: "M4 6h16v11H4zM9 21h6M12 17v4",
  updates: "M12 3v12M7 11l5 5 5-5M4 20h16",
  admin: "M16 20v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M10 10a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM20 20v-2a4 4 0 0 0-3-3.9M16 3.1a3.5 3.5 0 0 1 0 6.8",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  account: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  close: "M6 6l12 12M18 6L6 18",
  refresh: "M20 11a8 8 0 0 0-14-4L4 9M4 4v5h5M4 13a8 8 0 0 0 14 4l2-2M20 20v-5h-5",
  check: "M5 12l5 5 9-10",
  external: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  warn: "M12 5l8 14H4zM12 10v4M12 17h.01",
  skip: "M7 12h10",
  run: "M12 4a8 8 0 1 0 8 8",
  info: "M12 11v5M12 8h.01",
  chevron: "M9 6l6 6-6 6",
  download: "M12 4v11M7 11l5 5 5-5M5 20h14",
  back: "M15 6l-6 6 6 6",
};

export function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", ICONS[name] || ICONS.more);
  svg.appendChild(path);
  return svg;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

export function mount(el, ...kids) {
  clear(el);
  append(el, kids);
  return el;
}

export function safeHref(url, hosts) {
  try {
    const u = new URL(url);
    if (u.protocol !== "https:") return null;
    if (hosts && !hosts.includes(u.hostname)) return null;
    return u.href;
  } catch {
    return null;
  }
}

export function youtubeHref(videoId) {
  return /^[A-Za-z0-9_-]{11}$/.test(videoId || "") ? "https://www.youtube.com/watch?v=" + videoId : null;
}
