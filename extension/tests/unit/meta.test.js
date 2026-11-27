import assert from "node:assert/strict";
import { test } from "node:test";

import { videoToJson } from "../../src/shared/meta.js";

const VIDEO = "abcdefghijk";

test("the optional assess context is omitted when the meta has none of it", () => {
  const body = videoToJson({ videoId: VIDEO, title: "Title", durationSec: 754, isShort: false, isLive: false }, VIDEO);
  assert.equal(body.video_id, VIDEO);
  assert.equal(body.is_short, false);
  assert.equal(body.is_live, false);
  for (const key of ["is_subscribed", "upload_date", "likes", "dislikes", "subscriber_count", "channel_description", "channel_titles"]) {
    assert.equal(body.hasOwnProperty(key), false, key);
  }
});

test("is_subscribed is sent only when true, never as false", () => {
  assert.deepEqual(videoToJson({ videoId: VIDEO, isSubscribed: true }, VIDEO).is_subscribed, true);
  assert.equal(videoToJson({ videoId: VIDEO, isSubscribed: false }, VIDEO).hasOwnProperty("is_subscribed"), false);
  assert.equal(videoToJson({ videoId: VIDEO }, VIDEO).hasOwnProperty("is_subscribed"), false);
  // The snake_case form the contract uses rides through too.
  assert.deepEqual(videoToJson({ videoId: VIDEO, is_subscribed: true }, VIDEO).is_subscribed, true);
});

test("the text context rides through when found and is dropped when empty", () => {
  const body = videoToJson(
    { videoId: VIDEO, uploadDate: "2026-11-20", channelDescription: "A channel", channelTitles: ["A show", "A vlog"] },
    VIDEO,
  );
  assert.equal(body.upload_date, "2026-11-20");
  assert.equal(body.channel_description, "A channel");
  assert.deepEqual(body.channel_titles, ["A show", "A vlog"]);

  const empty = videoToJson({ videoId: VIDEO, uploadDate: "", channelDescription: "", channelTitles: [] }, VIDEO);
  assert.equal(empty.hasOwnProperty("upload_date"), false);
  assert.equal(empty.hasOwnProperty("channel_description"), false);
  assert.equal(empty.hasOwnProperty("channel_titles"), false);

  // Non-string titles are dropped, the rest kept.
  assert.deepEqual(videoToJson({ videoId: VIDEO, channelTitles: ["Keep", 3, null, "Also"] }, VIDEO).channel_titles, ["Keep", "Also"]);
});

test("the numeric context is sent as a number and skipped when not a finite count", () => {
  const body = videoToJson(
    { videoId: VIDEO, likes: 12000, dislikes: 300, subscriberCount: 6200000 },
    VIDEO,
  );
  assert.equal(body.likes, 12000);
  assert.equal(body.dislikes, 300);
  assert.equal(body.subscriber_count, 6200000);

  // A human "1.2M" the reader has not parsed is not a count, so it is omitted rather than sent as 0.
  const unparsed = videoToJson({ videoId: VIDEO, likes: "1.2M", dislikes: "", subscriberCount: null }, VIDEO);
  assert.equal(unparsed.hasOwnProperty("likes"), false);
  assert.equal(unparsed.hasOwnProperty("dislikes"), false);
  assert.equal(unparsed.hasOwnProperty("subscriber_count"), false);

  // A real zero count is a found value and is sent.
  assert.deepEqual(videoToJson({ videoId: VIDEO, likes: 0 }, VIDEO).likes, 0);
  assert.deepEqual(videoToJson({ videoId: VIDEO, likes: "8" }, VIDEO).likes, 8);
});
