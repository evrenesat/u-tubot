/**
 * The setup file at /setup.json (ai/CONTRACT.md) and the rules that turn what the user types into the address to
 * fetch it from, ported from the TV's UtubotSetup. http is allowed for private addresses only.
 */

export const FORMAT_VERSION = 1;
export const SETUP_PATH = "/setup.json";
export const MAX_SETUP_BYTES = 64 * 1024;

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;
const LOCAL_SUFFIXES = [".local", ".lan", ".internal", ".home.arpa", ".ts.net"];

const PRIVATE_172_FIRST = 16;
const PRIVATE_172_LAST = 31;
const CGNAT_SECOND_FIRST = 64;
const CGNAT_SECOND_LAST = 127;

export class SetupError extends Error {
  constructor(message) {
    super(message);
    this.name = "SetupError";
  }
}

export function isPrivateHost(host) {
  if (!host) {
    return false;
  }

  const name = host.toLowerCase();

  if (name.includes(":")) {
    return name === "::1" || name.startsWith("fc") || name.startsWith("fd") || name.startsWith("fe80");
  }

  const ip = IPV4.exec(name);

  if (ip) {
    const a = Number(ip[1]);
    const b = Number(ip[2]);
    return a === 10 || a === 127 || (a === 169 && b === 254) || (a === 192 && b === 168)
      || (a === 172 && b >= PRIVATE_172_FIRST && b <= PRIVATE_172_LAST)
      || (a === 100 && b >= CGNAT_SECOND_FIRST && b <= CGNAT_SECOND_LAST);
  }

  if (!name.includes(".")) {
    return true;
  }

  return LOCAL_SUFFIXES.some((suffix) => name.endsWith(suffix));
}

function parseAddress(text) {
  try {
    return new URL(text);
  } catch {
    throw new SetupError(`Not a valid address: ${text}`);
  }
}

function requireAllowedScheme(url, host) {
  if (url.protocol === "https:") {
    return;
  }

  if (url.protocol === "http:" && isPrivateHost(host)) {
    return;
  }

  throw new SetupError(`http is allowed for private addresses only: ${url.href}`);
}

export function resolveUrl(input) {
  const typed = (input ?? "").trim();

  if (!typed) {
    throw new SetupError("Type the server address");
  }

  const full = typed.includes("://");
  const url = parseAddress(full ? typed : `https://${typed}`);

  if (full) {
    requireAllowedScheme(url, url.hostname);
    return typed;
  }

  const scheme = isPrivateHost(url.hostname) ? "http" : "https";
  const rawPath = url.pathname === "" || url.pathname === "/" ? SETUP_PATH : url.pathname;
  const port = url.port ? `:${url.port}` : "";
  const hostPart = url.hostname.includes(":") ? `[${url.hostname}]` : url.hostname;

  return `${scheme}://${hostPart}${port}${rawPath}${url.search}`;
}

export function originOf(address) {
  const url = parseAddress((address ?? "").trim());
  return `${url.protocol}//${url.hostname.toLowerCase()}${url.port ? `:${url.port}` : ""}`;
}

export function requireUrl(value, what) {
  const typed = (value ?? "").trim();

  if (!typed) {
    throw new SetupError(`The setup has no ${what}`);
  }

  const url = parseAddress(typed);
  requireAllowedScheme(url, url.hostname);
  return typed;
}

export function parseSetup(body) {
  let root;

  try {
    root = JSON.parse(body);
  } catch {
    throw new SetupError("Not a u·tubot setup file");
  }

  if (!root || Number(root.utubot_setup) !== FORMAT_VERSION) {
    throw new SetupError("Not a u·tubot setup file");
  }

  const defaults = {};
  for (const key of ["assess", "mark_only", "answer_in_menu", "summary_panel", "auto_captions"]) {
    if (typeof root.defaults?.[key] === "boolean") {
      defaults[key] = root.defaults[key];
    }
  }

  return {
    name: typeof root.name === "string" ? root.name : "",
    backendUrl: stripSetupUrl(requireUrl(root.backend_url, "backend_url")),
    updateUrl: typeof root.update_url === "string" && root.update_url.trim() ? requireUrl(root.update_url, "update_url") : "",
    pairing: typeof root.pairing === "boolean" ? root.pairing : true,
    defaults,
    promptSetUrls: (Array.isArray(root.prompt_set_urls) ? root.prompt_set_urls : [])
      .map((url) => (typeof url === "string" ? url.trim() : ""))
      .filter(Boolean),
  };
}

function stripSetupUrl(value) {
  return value.endsWith("/") ? value.slice(0, -1) : value;
}
