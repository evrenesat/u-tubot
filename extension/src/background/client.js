/**
 * Blocking calls to the u-tubot backend over ai/CONTRACT.md. Every request carries `credentials: "omit"` and
 * `cache: "no-store"`; the bearer header is added only to a URL under the stored backend. Caption files are
 * fetched here and handed to the page as text.
 */
import { authorizationFor, isUnderBackend, stripTrailingSlash } from "./auth.js";
import { addLiveFlag, addMeta, videoToJson } from "../shared/meta.js";
import {
  parseAssess,
  parseCaptions,
  parseCutRequest,
  parseCuts,
  parseInsight,
  parseMe,
  parseProcessed,
  parsePromptSet,
  parsePrompts,
  parseSummary,
  parseTranscript,
} from "../shared/models.js";

const API_PREFIX = "/v1";
const MAX_ASSESS_VIDEOS = 50;
const MAX_CAPTION_BYTES = 4 * 1024 * 1024;
const DEFAULT_TIMEOUT_MS = 15000;
const LONG_POLL_SLACK_MS = 10000;
const IMPORT_TIMEOUT_MS = 30000;
const MAX_ERROR_CHARS = 120;
const LEDGER_PATH = "/ledger";
const REPORT_WINDOW_MS = 60000;
const MAX_REPORTS_PER_WINDOW = 10;

export class HttpError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "HttpError";
    this.code = code;
  }

  isUnauthorized() {
    return this.code === 401;
  }

  isPromptRejected() {
    return this.code === 400 || this.code === 404;
  }
}

function abbreviate(value) {
  return value.length > MAX_ERROR_CHARS ? value.slice(0, MAX_ERROR_CHARS) : value;
}

function backendUrl(baseUrl, path) {
  const base = stripTrailingSlash(baseUrl);

  if (!base) {
    throw new Error("Bad backend address");
  }

  let url;

  try {
    url = new URL(base + API_PREFIX + path);
  } catch {
    throw new Error(`Bad backend address: ${base}`);
  }

  return url;
}

/**
 * The failures worth telling the backend's error ledger about: one report per distinct operation and message per
 * window and a fixed number per window overall, so a dead backend never floods the ledger.
 */
export function createFailureThrottle(now = () => Date.now()) {
  let windowStart = -Infinity;
  let sent = 0;
  const seen = new Set();

  return (operation, message) => {
    const at = now();

    if (at - windowStart >= REPORT_WINDOW_MS) {
      windowStart = at;
      sent = 0;
      seen.clear();
    }

    const key = `${operation}|${message}`;

    if (seen.has(key) || sent >= MAX_REPORTS_PER_WINDOW) {
      return false;
    }

    seen.add(key);
    sent += 1;
    return true;
  };
}

export function createClient(baseUrl, token, fetchImpl = globalThis.fetch, { reportFailures = false } = {}) {
  const base = stripTrailingSlash(baseUrl);
  const bearer = (token ?? "").trim();
  const shouldReport = createFailureThrottle();

  /** Fire and forget: the ledger is best effort and the report call is never itself reported. */
  function reportFailure(url, method, error) {
    const clientSide = !(error instanceof HttpError) || error.code >= 500;
    const path = url.pathname.replace(API_PREFIX, "");

    if (!reportFailures || !bearer || !clientSide || path === LEDGER_PATH) {
      return;
    }

    const operation = `${method} ${path.replace(/[0-9A-Za-z_-]{11}/g, "{id}")}`;
    const message = abbreviate(String(error?.message ?? error?.name ?? "error"));

    if (!shouldReport(operation, message)) {
      return;
    }

    json(backendUrl(base, LEDGER_PATH), {
      method: "POST",
      body: { component: "client", operation, message, detail: String(error?.name ?? "") },
    }).catch(() => {});
  }

  async function send(url, options = {}) {
    const headers = {};
    const authorization = options.auth === false ? null : authorizationFor(base, bearer, url.href);

    if (options.auth !== false && isUnderBackend(base, url.href) && !authorization) {
      throw new Error("No token");
    }

    if (authorization) {
      headers.Authorization = authorization;
    }

    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json; charset=utf-8";
    }

    const controller = new AbortController();
    const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetchImpl(url.href, {
        method: options.method ?? "GET",
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        credentials: "omit",
        cache: "no-store",
        redirect: "follow",
        signal: controller.signal,
      });

      if (!response.ok) {
        const body = await response.text();
        let detail = body;

        try {
          detail = JSON.parse(body).error ?? body;
        } catch {
          // keep the plain body
        }

        throw new HttpError(response.status, `HTTP ${response.status}: ${abbreviate(String(detail))}`);
      }

      return response;
    } catch (error) {
      const failure = error?.name === "AbortError" ? new Error("Timeout") : error;
      reportFailure(url, options.method ?? "GET", failure);
      throw failure;
    } finally {
      clearTimeout(timer);
    }
  }

  async function json(url, options) {
    const response = await send(url, options);
    const body = await response.text();

    if (!body) {
      return {};
    }

    try {
      return JSON.parse(body);
    } catch {
      throw new Error("Bad answer");
    }
  }

  function withQuery(url, fields) {
    for (const [key, value] of Object.entries(fields)) {
      if (value !== null && value !== undefined && value !== "") {
        url.searchParams.set(key, String(value));
      }
    }

    return url;
  }

  return {
    baseUrl: base,

    async health() {
      const answer = await json(backendUrl(base, "/health"), { auth: false });
      return Boolean(answer.ok);
    },

    async pair(code, device) {
      const answer = await json(backendUrl(base, "/pair"), {
        method: "POST",
        auth: false,
        body: { code: String(code ?? ""), device: String(device ?? "") },
      });
      return { token: answer.token ?? "", user: answer.user ?? "" };
    },

    async me() {
      return parseMe(await json(backendUrl(base, "/me")));
    },

    async assess(videos, section, waitMs = 1200, hardTimeoutMs = waitMs + 500) {
      if (videos.length > MAX_ASSESS_VIDEOS) {
        throw new Error(`Too many videos in one assess call: ${videos.length}`);
      }

      const body = { videos: videos.map((video) => videoToJson(video, video.video_id ?? video.videoId)), section, wait_ms: waitMs };
      const answer = await json(backendUrl(base, "/assess"), { method: "POST", body, timeoutMs: hardTimeoutMs || DEFAULT_TIMEOUT_MS });
      return parseAssess(answer);
    },

    async insight(videoId, meta, waitMs = 20000) {
      const url = withQuery(backendUrl(base, `/videos/${videoId}/insight`), { wait_ms: waitMs });
      addMeta(url.searchParams, meta);
      return parseInsight(await json(url, { timeoutMs: waitMs + LONG_POLL_SLACK_MS }));
    },

    async summary(videoId, promptKey, meta, waitMs = 20000) {
      const url = withQuery(backendUrl(base, `/videos/${videoId}/summary`), { wait_ms: waitMs, prompt: promptKey });
      addMeta(url.searchParams, meta);
      return parseSummary(await json(url, { timeoutMs: waitMs + LONG_POLL_SLACK_MS }));
    },

    async transcribe(videoId, meta) {
      const url = backendUrl(base, `/videos/${videoId}/transcribe`);
      addMeta(url.searchParams, meta);
      return parseTranscript(await json(url, { method: "POST", body: {} }));
    },

    async transcript(videoId) {
      return parseTranscript(await json(backendUrl(base, `/videos/${videoId}/transcript`)));
    },

    async prompts() {
      return parsePrompts(await json(backendUrl(base, "/prompts")));
    },

    async importPrompts(sourceUrl) {
      const answer = await json(backendUrl(base, "/prompts/import"), {
        method: "POST",
        body: { url: sourceUrl },
        timeoutMs: IMPORT_TIMEOUT_MS,
      });
      return parsePromptSet(answer);
    },

    async refreshPrompts() {
      return json(backendUrl(base, "/prompts/refresh"), { method: "POST", body: {}, timeoutMs: IMPORT_TIMEOUT_MS });
    },

    async setDefaultPrompt(key) {
      return json(backendUrl(base, "/prompts/default"), { method: "PUT", body: { key } });
    },

    async captions(videoId) {
      return parseCaptions(await json(backendUrl(base, `/videos/${videoId}/captions`)));
    },

    async prepareCaptions(videoId) {
      const answer = await json(backendUrl(base, `/videos/${videoId}/captions`), {
        method: "POST",
        body: { lang: "auto", translate_to: null },
      });
      return answer.status ?? "queued";
    },

    async captionFile(trackUrl) {
      const absolute = trackUrl.startsWith("http") ? trackUrl : base + trackUrl;
      let url;

      try {
        url = new URL(absolute);
      } catch {
        throw new Error(`Bad caption address: ${absolute}`);
      }

      const response = await send(url, { timeoutMs: DEFAULT_TIMEOUT_MS });
      const bytes = await response.arrayBuffer();

      if (bytes.byteLength > MAX_CAPTION_BYTES) {
        throw new Error("The caption file is too large");
      }

      return new TextDecoder().decode(bytes);
    },

    async cuts(videoId) {
      return parseCuts(await json(backendUrl(base, `/videos/${videoId}/cuts`)));
    },

    async requestCut(videoId, presetId, prompt, awaitPrompt, meta) {
      const url = backendUrl(base, `/videos/${videoId}/cuts`);
      addMeta(url.searchParams, meta);
      addLiveFlag(url.searchParams, meta);
      const body = {};

      if (awaitPrompt) {
        body.await_prompt = true;
      } else if (presetId) {
        body.preset = presetId;
      } else if (prompt) {
        body.prompt = prompt;
      } else {
        throw new Error("A cut needs a preset, a prompt or a waiting request");
      }

      return parseCutRequest(await json(url, { method: "POST", body }));
    },

    async cut(requestId, waitMs = 0) {
      const url = withQuery(backendUrl(base, `/cuts/${requestId}`), { wait_ms: waitMs > 0 ? waitMs : null });
      return parseCutRequest(await json(url, { timeoutMs: waitMs + LONG_POLL_SLACK_MS }));
    },

    async processed(limit = 0) {
      const url = withQuery(backendUrl(base, "/processed"), { limit: limit > 0 ? limit : null });
      return parseProcessed(await json(url));
    },

    cutRequestUrl(requestId) {
      return base + `/cuts/${requestId}`;
    },

    captionUrl(trackUrl) {
      return trackUrl.startsWith("http") ? trackUrl : base + trackUrl;
    },

    authorizationFor(absoluteUrl) {
      return authorizationFor(base, bearer, absoluteUrl);
    },
  };
}
