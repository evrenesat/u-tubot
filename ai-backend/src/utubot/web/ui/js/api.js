// All data comes from authenticated JSON endpoints. The session lives in an HttpOnly cookie; the page
// only keeps the CSRF value the server derived for it, in memory.

export class ApiError extends Error {
  constructor(status, message, body) {
    super(message);
    this.status = status;
    this.body = body || {};
  }
}

export const session = { user: null, admin: false, csrf: null, via: null, hasPassword: false };

const SAFE = new Set(["GET", "HEAD"]);

export async function api(path, { method = "GET", body, query } = {}) {
  let url = path;
  if (query) {
    const qs = new URLSearchParams(query).toString();
    if (qs) url += (path.includes("?") ? "&" : "?") + qs;
  }
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (!SAFE.has(method) && session.csrf) headers["X-CSRF-Token"] = session.csrf;
  let res;
  try {
    res = await fetch(url, {
      method,
      headers,
      credentials: "same-origin",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "The server is not reachable");
  }
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (res.status === 401 && path !== "/v1/auth/login") {
    window.dispatchEvent(new CustomEvent("utubot:signed-out"));
  }
  if (!res.ok) {
    throw new ApiError(res.status, (data && data.error) || "HTTP " + res.status, data);
  }
  return data;
}

export async function loadSession() {
  try {
    const info = await api("/v1/auth/session");
    Object.assign(session, {
      user: info.user,
      admin: info.admin,
      csrf: info.csrf,
      via: info.via,
      hasPassword: info.has_password,
    });
    return true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return false;
    throw err;
  }
}

export function adoptLogin(info) {
  Object.assign(session, { user: info.user, admin: info.admin, csrf: info.csrf, via: "cookie" });
}

export function forgetSession() {
  Object.assign(session, { user: null, admin: false, csrf: null, via: null, hasPassword: false });
}
