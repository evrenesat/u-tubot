/**
 * The message router of the plan's decision 6. The background is a stateless executor: every answer is made from
 * storage and the backend; no state lives in its memory. Page-only and content messages are two separate sets, and
 * only a page of this extension may call the page set. A failed call is one answer to one message.
 */
import { createClient, HttpError } from "./client.js";
import { clearSessionCaches, createCache, MAX_CAPTIONS, MAX_SUMMARIES, setOpenRequest, takeOpenRequest } from "./cache.js";
import { readSettings, writeSettings, applySetupDefaults, NETWORK_SLACK_MS, MAX_WAIT_MS } from "./settings.js";
import { SetupError, MAX_SETUP_BYTES, parseSetup, requireUrl, originOf } from "./setup.js";
import { checkMessage } from "../shared/messages.js";

const KEYS = {
  backend: "utubot.backend",
  token: "utubot.token",
  user: "utubot.user",
  pending: "utubot.pendingPromptSets",
  sessionPrompt: "utubot.sessionPrompt",
  diagnostics: "utubot.diagnostics",
};

const SUMMARY_WAIT_MS = 20000;
const CUT_WAIT_MS = 10000;

function connectionFrom(values) {
  return {
    backend: values?.[KEYS.backend] ?? "",
    token: values?.[KEYS.token] ?? "",
    user: values?.[KEYS.user] ?? "",
  };
}

export function createRouter({ storage, fetchImpl = globalThis.fetch, extensionBase, isTest = false }) {
  async function connection() {
    return connectionFrom(await storage.local.get([KEYS.backend, KEYS.token, KEYS.user]));
  }

  async function clientFor(connectionValues) {
    return createClient(connectionValues.backend, connectionValues.token, fetchImpl, { reportFailures: true });
  }

  async function setConnection(backend, token, user) {
    const previous = await connection();
    const changed = previous.backend !== backend || previous.token !== (token ?? "");

    await storage.local.set({
      [KEYS.backend]: backend,
      [KEYS.token]: token ?? "",
      [KEYS.user]: user ?? "",
    });

    if (changed) {
      await clearSessionCaches(storage);
    }
  }

  async function fetchSetup(url) {
    let address;

    try {
      address = new URL(url);
    } catch {
      throw new SetupError(`Not a valid address: ${url}`);
    }

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);

    try {
      const response = await fetchImpl(address.href, {
        method: "GET",
        credentials: "omit",
        cache: "no-store",
        redirect: "follow",
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new HttpError(response.status, `HTTP ${response.status}`);
      }

      const bytes = await response.arrayBuffer();
      if (bytes.byteLength > MAX_SETUP_BYTES) {
        throw new SetupError("The setup file is too large");
      }

      return parseSetup(new TextDecoder().decode(bytes));
    } catch (error) {
      if (error?.name === "AbortError") {
        throw new Error("Timeout");
      }

      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  async function dispatchPage(type, payload) {
    switch (type) {
      case "setup.fetch":
        return fetchSetup(payload.url);

      case "setup.apply": {
        const setup = payload.setup ?? {};
        const backend = requireUrl(setup.backendUrl, "backend_url");
        await setConnection(backend, "", "");
        await applySetupDefaults(storage, setup.defaults ?? {});
        await storage.local.set({ [KEYS.pending]: setup.promptSetUrls ?? [] });
        return { applied: true, backendUrl: backend };
      }

      case "pair": {
        const current = await connection();
        const result = await (await clientFor(current)).pair(payload.code, payload.device);
        await setConnection(current.backend, result.token, result.user);
        return result;
      }

      case "backend.set": {
        const url = requireUrl(payload.url, "backend address");
        const previous = await connection();
        const dropToken = previous.backend && originOf(previous.backend) !== originOf(url);
        await setConnection(url, dropToken ? "" : previous.token, dropToken ? "" : previous.user);
        return { backendUrl: url };
      }

      case "token.set": {
        const current = await connection();
        await setConnection(current.backend, payload.token ?? "", "");
        return { token: Boolean(payload.token) };
      }

      case "health":
        return { ok: await (await clientFor(await connection())).health() };

      case "me":
        return (await clientFor(await connection())).me();

      case "prompts.list":
        return (await clientFor(await connection())).prompts();

      case "prompts.import":
        return (await clientFor(await connection())).importPrompts(payload.url);

      case "prompts.refresh":
        return (await clientFor(await connection())).refreshPrompts();

      case "prompts.default":
        return (await clientFor(await connection())).setDefaultPrompt(payload.key);

      case "settings.read":
        return readSettings(storage);

      case "settings.write":
        return writeSettings(storage, payload.settings ?? payload);

      case "processed":
        return (await clientFor(await connection())).processed(payload.limit ?? 50);

      case "open.set":
        await setOpenRequest(storage, payload.video_id, payload.request ?? { kind: "captions" });
        return { ok: true };

      case "diagnostics.read": {
        const stored = await storage.session.get([KEYS.diagnostics]);
        return stored?.[KEYS.diagnostics] ?? null;
      }

      default:
        throw new Error(`Unknown page message: ${type}`);
    }
  }

  async function dispatchContent(type, payload) {
    switch (type) {
      case "assess": {
        const settings = await readSettings(storage);
        const wanted = Math.min(MAX_WAIT_MS, payload.wait_ms ?? settings.wait_ms ?? 1200);
        return (await clientFor(await connection())).assess(payload.videos ?? [], payload.section ?? "other", wanted, wanted + NETWORK_SLACK_MS);
      }

      case "summary": {
        const client = await clientFor(await connection());
        const cache = createCache(storage, "summaries", MAX_SUMMARIES);
        const key = `${payload.video_id}|${payload.prompt ?? ""}`;
        const cached = await cache.get(key);

        if (cached?.status === "ready") {
          return cached;
        }

        const answer = await client.summary(payload.video_id, payload.prompt, payload.meta, payload.wait_ms ?? SUMMARY_WAIT_MS);

        if (answer.status === "ready") {
          await cache.set(key, answer);
        }

        return answer;
      }

      case "insight":
        return (await clientFor(await connection())).insight(payload.video_id, payload.meta, payload.wait_ms ?? SUMMARY_WAIT_MS);

      case "transcribe":
        return (await clientFor(await connection())).transcribe(payload.video_id, payload.meta);

      case "transcript":
        return (await clientFor(await connection())).transcript(payload.video_id);

      case "prompts.list":
        return (await clientFor(await connection())).prompts();

      case "captions.status": {
        const client = await clientFor(await connection());
        const cache = createCache(storage, "captions", MAX_CAPTIONS);
        const cached = await cache.get(payload.video_id);

        if (cached?.status === "ready") {
          return cached;
        }

        const answer = await client.captions(payload.video_id);

        if (answer.status === "ready") {
          await cache.set(payload.video_id, answer);
        }

        return answer;
      }

      case "captions.prepare":
        return { status: await (await clientFor(await connection())).prepareCaptions(payload.video_id) };

      case "captions.file":
        return { text: await (await clientFor(await connection())).captionFile(payload.track_url) };

      case "cuts.list":
        return (await clientFor(await connection())).cuts(payload.video_id);

      case "cuts.request":
        return (await clientFor(await connection())).requestCut(
          payload.video_id,
          payload.preset ?? null,
          payload.prompt ?? null,
          Boolean(payload.await_prompt),
          payload.meta ?? null,
        );

      case "cuts.follow":
        return (await clientFor(await connection())).cut(payload.request_id, payload.wait_ms ?? CUT_WAIT_MS);

      case "settings.read":
        return readSettings(storage);

      case "open.take":
        return takeOpenRequest(storage, payload.video_id);

      case "diagnostics.report":
        await storage.session.set({ [KEYS.diagnostics]: payload.report ?? payload });
        return { ok: true };

      default:
        throw new Error(`Unknown content message: ${type}`);
    }
  }

  return {
    async handleMessage(message, sender) {
      const { payload } = checkMessage(message, sender, extensionBase, isTest);
      const type = message.type;

      if (["setup.fetch", "setup.apply", "pair", "backend.set", "token.set", "health", "me", "prompts.import", "prompts.refresh",
        "prompts.default", "settings.write", "processed", "open.set", "diagnostics.read"].includes(type)) {
        return dispatchPage(type, payload);
      }

      if (type === "settings.read") {
        return readSettings(storage);
      }

      return dispatchContent(type, payload);
    },
  };
}
