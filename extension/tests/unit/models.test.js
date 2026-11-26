import assert from "node:assert/strict";
import { test } from "node:test";

import {
  parseAssess,
  parseCaptions,
  parseCutRequest,
  parseCuts,
  parseProcessed,
  parsePrompts,
  parseSummary,
  parseTranscript,
  revive,
  UNKNOWN,
} from "../../src/shared/models.js";

function json(value) {
  return JSON.parse(JSON.stringify(value));
}

function assertPlain(value) {
  assert.deepEqual(structuredClone(value), value);
  assert.deepEqual(json(value), value);
}

test("every parser returns plain data that survives a message or storage boundary", () => {
  assertPlain(parseSummary({ status: "ready", text: "T" }));
  assertPlain(parseAssess({ results: [{ status: "ready" }] }).map((verdict) => verdict));
  assertPlain(parseTranscript({ status: "transcribing", progress: 0.5 }));
  assertPlain(parsePrompts({ default: "a/b", sets: [{ id: "a", prompts: [{ id: "b" }] }] }));
  assertPlain(parseCaptions({ status: "ready", tracks: [{ url: "https://example.test/c.vtt" }] }));
  assertPlain(parseCuts({ configured: true, presets: [{ id: "p", state: "ready", cut: { video_id: "v" } }] }));
  assertPlain(parseCutRequest({ request_id: "r", state: "building" }));
  assertPlain(parseProcessed({
    videos: [{
      video_id: "v",
      captions: [{ job_id: "c", state: "ready" }],
      cuts: [{ request_id: "r", state: "ready" }],
    }],
  }));
});

test("a processed item carries its duration in seconds, or UNKNOWN when unknown", () => {
  const processed = parseProcessed({
    videos: [
      { video_id: "v", duration_s: 633.0, captions: [], cuts: [] },
      { video_id: "w", captions: [], cuts: [] },
    ],
  });
  assert.equal(processed.videos[0].durationSec, 633);
  assert.equal(processed.videos[1].durationSec, UNKNOWN);
});

test("revive re-attaches the helpers on the receiving side", () => {
  const summary = revive("summary", parseSummary({ status: "ready" }));
  assert.equal(summary.isReady(), true);
  assert.equal(summary.isTransient(), false);

  const verdict = revive("assess", parseAssess({ results: [{ status: "ready" }] }))[0];
  assert.equal(verdict.isReady(), true);

  const transcript = revive("transcript", parseTranscript({ status: "transcribing" }));
  assert.equal(transcript.isTranscribing(), true);
  assert.equal(transcript.isDone(), false);

  const prompts = revive("prompts.list", parsePrompts({
    default: "a/b",
    sets: [{ id: "a", prompts: [{ id: "b" }] }],
  }));
  assert.equal(prompts.allPrompts().length, 1);
  assert.equal(prompts.first().key, "a/b");
  assert.equal(prompts.find("a/b").label, "b");

  const captions = revive("captions.status", parseCaptions({ status: "ready", tracks: [{ url: "u" }] }));
  assert.equal(captions.isReady(), true);

  const cuts = revive("cuts.list", parseCuts({ presets: [{ id: "p", state: "ready", cut: { video_id: "v" } }] }));
  assert.equal(cuts.presets[0].isReady(), true);

  const waiting = revive("cuts.request", parseCutRequest({ request_id: "r", state: "waiting" }));
  assert.equal(waiting.isWaiting(), true);
  assert.equal(waiting.isBuilding(), false);

  const processed = revive("processed", parseProcessed({
    videos: [{
      video_id: "v",
      captions: [{ job_id: "c", state: "ready" }],
      cuts: [{ request_id: "r", state: "ready" }],
    }],
  }));
  assert.equal(processed.videos[0].captions[0].isReady(), true);
  assert.equal(processed.videos[0].cuts[0].isReady(), true);
});

test("revived helpers stay out of the serialized form", () => {
  const parsed = parseSummary({ status: "ready", text: "T" });
  const revived = revive("summary", parsed);
  assert.deepEqual(json(revived), parsed);
  assert.equal(Object.keys(revived).includes("isReady"), false);
  assert.deepEqual(structuredClone(revived), parsed);
});

test("an unknown type is left untouched", () => {
  const value = { status: "ready" };
  assert.equal(revive("no.such", value), value);
});
