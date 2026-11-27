import assert from "node:assert/strict";
import { test } from "node:test";

import { createClient, HttpError } from "../../src/background/client.js";

const BASE = "http://127.0.0.2:8790";
const TOKEN = "secret-token";
const VIDEO = "abcdefghijk";

function fake(body = {}, status = 200) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url: new URL(url), options });
    const payload = typeof body === "string" ? body : JSON.stringify(body);
    return {
      ok: status >= 200 && status < 300,
      status,
      text: async () => payload,
      arrayBuffer: async () => new TextEncoder().encode(payload),
    };
  };
  return { calls, fetchImpl };
}

async function one(run, body = {}) {
  const { calls, fetchImpl } = fake(body);
  const client = createClient(BASE, TOKEN, fetchImpl);
  await run(client);
  assert.equal(calls.length, 1);
  const call = calls[0];
  assert.equal(call.options.credentials, "omit");
  assert.equal(call.options.cache, "no-store");
  return call;
}

function bodyOf(call) {
  return call.options.body ? JSON.parse(call.options.body) : null;
}

function authOf(call) {
  return call.options.headers.Authorization ?? null;
}

test("every endpoint has its method, path and query", async () => {
  let call = await one((client) => client.health());
  assert.equal(call.options.method, "GET");
  assert.equal(call.url.pathname, "/v1/health");
  assert.equal(authOf(call), null);

  call = await one((client) => client.pair("123456", "Firefox (desktop)"));
  assert.equal(call.options.method, "POST");
  assert.equal(call.url.pathname, "/v1/pair");
  assert.deepEqual(bodyOf(call), { code: "123456", device: "Firefox (desktop)" });
  assert.equal(authOf(call), null);

  call = await one((client) => client.me(), {});
  assert.equal(call.url.pathname, "/v1/me");
  assert.equal(authOf(call), `Bearer ${TOKEN}`);

  call = await one((client) => client.assess([{ video_id: VIDEO, title: "Title", durationSec: 754 }], "home", 1200), { results: [] });
  assert.equal(call.options.method, "POST");
  assert.equal(call.url.pathname, "/v1/assess");
  assert.deepEqual(bodyOf(call).section, "home");
  assert.equal(bodyOf(call).wait_ms, 1200);
  assert.equal(bodyOf(call).videos[0].video_id, VIDEO);
  assert.equal(bodyOf(call).videos[0].duration_s, 754);
  assert.equal(bodyOf(call).videos[0].is_short, false);
  assert.equal(bodyOf(call).videos[0].is_live, false);
  assert.equal(authOf(call), `Bearer ${TOKEN}`);

  const meta = { title: "Title & more", channel: "A channel", durationSec: 754 };
  call = await one((client) => client.insight(VIDEO, meta, 20000));
  assert.equal(call.url.pathname, `/v1/videos/${VIDEO}/insight`);
  assert.equal(call.url.searchParams.get("wait_ms"), "20000");
  assert.equal(call.url.searchParams.get("title"), meta.title);
  assert.equal(call.url.searchParams.get("channel"), meta.channel);
  assert.equal(call.url.searchParams.get("duration_s"), "754");
  assert.equal(call.url.searchParams.has("is_live"), false);

  call = await one((client) => client.summary(VIDEO, "set/prompt", meta, 20000));
  assert.equal(call.url.pathname, `/v1/videos/${VIDEO}/summary`);
  assert.equal(call.url.searchParams.get("prompt"), "set/prompt");
  assert.equal(call.url.searchParams.get("wait_ms"), "20000");
  assert.equal(call.url.searchParams.get("title"), meta.title);

  call = await one((client) => client.transcribe(VIDEO, { title: "Title", channel: "C", durationSec: 600 }));
  assert.equal(call.options.method, "POST");
  assert.equal(call.url.pathname, `/v1/videos/${VIDEO}/transcribe`);
  assert.equal(call.url.searchParams.get("title"), "Title");
  assert.equal(call.url.searchParams.get("duration_s"), "600");
  assert.deepEqual(bodyOf(call), {});

  call = await one((client) => client.transcript(VIDEO));
  assert.equal(call.url.pathname, `/v1/videos/${VIDEO}/transcript`);
  assert.equal(authOf(call), `Bearer ${TOKEN}`);

  call = await one((client) => client.prompts());
  assert.equal(call.url.pathname, "/v1/prompts");
  assert.equal(authOf(call), `Bearer ${TOKEN}`);

  call = await one((client) => client.importPrompts("https://example.com/p.json"));
  assert.equal(call.options.method, "POST");
  assert.equal(call.url.pathname, "/v1/prompts/import");
  assert.deepEqual(bodyOf(call), { url: "https://example.com/p.json" });

  call = await one((client) => client.refreshPrompts());
  assert.equal(call.options.method, "POST");
  assert.equal(call.url.pathname, "/v1/prompts/refresh");
  assert.deepEqual(bodyOf(call), {});

  call = await one((client) => client.setDefaultPrompt("builtin/tldr"));
  assert.equal(call.options.method, "PUT");
  assert.equal(call.url.pathname, "/v1/prompts/default");
  assert.deepEqual(bodyOf(call), { key: "builtin/tldr" });

  call = await one((client) => client.captions(VIDEO));
  assert.equal(call.url.pathname, `/v1/videos/${VIDEO}/captions`);
  assert.equal(authOf(call), `Bearer ${TOKEN}`);

  call = await one((client) => client.prepareCaptions(VIDEO));
  assert.equal(call.options.method, "POST");
  assert.equal(call.url.pathname, `/v1/videos/${VIDEO}/captions`);
  assert.deepEqual(bodyOf(call), { lang: "auto", translate_to: null });

  call = await one((client) => client.captionFile(`/v1/videos/${VIDEO}/captions/en.vtt`), "WEBVTT");
  assert.equal(call.options.method, "GET");
  assert.equal(call.url.pathname, `/v1/videos/${VIDEO}/captions/en.vtt`);
  assert.equal(call.url.origin, "http://127.0.0.2:8790");
  assert.equal(authOf(call), `Bearer ${TOKEN}`);

  call = await one((client) => client.captionFile("https://other.example/x.vtt"), "WEBVTT");
  assert.equal(call.url.origin, "https://other.example");
  assert.equal(authOf(call), null);

  call = await one((client) => client.cuts(VIDEO), { configured: true, presets: [] });
  assert.equal(call.url.pathname, `/v1/videos/${VIDEO}/cuts`);
  assert.equal(authOf(call), `Bearer ${TOKEN}`);

  call = await one((client) => client.requestCut(VIDEO, "cut-demo", null, false, { title: "Title", channel: "C", durationSec: 240, isLive: true }), {});
  assert.equal(call.options.method, "POST");
  assert.equal(call.url.pathname, `/v1/videos/${VIDEO}/cuts`);
  assert.deepEqual(bodyOf(call), { preset: "cut-demo" });
  assert.equal(call.url.searchParams.get("title"), "Title");
  assert.equal(call.url.searchParams.get("duration_s"), "240");
  assert.equal(call.url.searchParams.get("is_live"), "true");

  call = await one((client) => client.cut("cut1", 10000));
  assert.equal(call.url.pathname, "/v1/cuts/cut1");
  assert.equal(call.url.searchParams.get("wait_ms"), "10000");
  assert.equal(authOf(call), `Bearer ${TOKEN}`);

  call = await one((client) => client.processed(50), { videos: [] });
  assert.equal(call.url.pathname, "/v1/processed");
  assert.equal(call.url.searchParams.get("limit"), "50");
  assert.equal(authOf(call), `Bearer ${TOKEN}`);
});

test("every request carries credentials omit and cache no-store", async () => {
  const requests = [
    (client) => client.health(),
    (client) => client.pair("123456", "TV"),
    (client) => client.me(),
    (client) => client.summary(VIDEO, null, null, 1000),
    (client) => client.captions(VIDEO),
    (client) => client.captionFile("/v1/videos/abcdefghijk/captions/en.vtt"),
    (client) => client.cut("cut1", 0),
  ];
  for (const request of requests) {
    const call = await one(request);
    assert.equal(call.options.credentials, "omit");
    assert.equal(call.options.cache, "no-store");
  }
});

test("the bearer header is only on URLs under the backend", async () => {
  const call = await one((client) => client.captionFile("https://other.example/x.vtt"));
  assert.equal(authOf(call), null);
  assert.equal(createClient("https://u.example.com", TOKEN).authorizationFor("https://u.example.com.evil.net/x"), null);
});

test("an error status is an HttpError with the code", async () => {
  const { fetchImpl } = fake('{"error":"unauthorized"}', 401);
  const client = createClient(BASE, TOKEN, fetchImpl);
  await assert.rejects(() => client.me(), (error) => error instanceof HttpError && error.code === 401 && error.isUnauthorized());
});

test("too many videos in one assess call are refused before a request", async () => {
  const { calls, fetchImpl } = fake({ results: [] });
  const client = createClient(BASE, TOKEN, fetchImpl);
  await assert.rejects(() => client.assess(Array.from({ length: 51 }, (_, index) => ({ video_id: `${index}abcdefghij`.slice(0, 11) })), "home", 1200));
  assert.equal(calls.length, 0);
});

test("a backend call that needs a token is not sent without one", async () => {
  const { calls, fetchImpl } = fake({});
  const client = createClient(BASE, "", fetchImpl);
  for (const request of [
    (c) => c.me(),
    (c) => c.assess([{ video_id: VIDEO }], "home"),
    (c) => c.summary(VIDEO, null, null, 1000),
    (c) => c.captionFile("/v1/videos/abcdefghijk/captions/en.vtt"),
  ]) {
    await assert.rejects(() => request(client), /No token/);
  }
  assert.equal(calls.length, 0);

  const external = await one((c) => c.captionFile("https://other.example/x.vtt"), "WEBVTT");
  assert.equal(external.url.origin, "https://other.example");
  assert.equal(authOf(external), null);
});

test("a caption file over the size cap is refused", async () => {
  const big = "x".repeat(4 * 1024 * 1024 + 1);
  const { fetchImpl } = fake(big);
  await assert.rejects(() => createClient(BASE, TOKEN, fetchImpl).captionFile("/v1/videos/abcdefghijk/captions/en.vtt"));
});

test("a failed call is reported to the ledger once, a rejected one is not", async () => {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, method: init.method, body: init.body });
    if (url.endsWith("/v1/ledger")) {
      return new Response("{}", { status: 200 });
    }
    return new Response("boom", { status: 502 });
  };
  const client = createClient(BASE, TOKEN, fetchImpl, { reportFailures: true });
  await assert.rejects(() => client.me());
  await assert.rejects(() => client.me());
  await new Promise((resolve) => setTimeout(resolve, 10));
  const reports = calls.filter((c) => c.url.endsWith("/v1/ledger"));
  assert.equal(reports.length, 1);
  assert.equal(JSON.parse(reports[0].body).component, "client");

  const rejected = [];
  const reject = async (url) => {
    rejected.push(url);
    return new Response("no", { status: 401 });
  };
  await assert.rejects(() => createClient(BASE, TOKEN, reject, { reportFailures: true }).me());
  assert.equal(rejected.length, 1);
});

test("without the option nothing is reported", async () => {
  const urls = [];
  const fetchImpl = async (url) => {
    urls.push(url);
    return new Response("boom", { status: 502 });
  };
  await assert.rejects(() => createClient(BASE, TOKEN, fetchImpl).me());
  assert.equal(urls.length, 1);
});
