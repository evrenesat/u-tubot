/**
 * The video facts the client knows, as the contract's VideoMeta body and query fields. Every field but video_id
 * is optional; no value is added when it is empty or false, except is_short and is_live in the body (the TV sends
 * them always).
 */

export function videoToJson(meta, videoId) {
  const body = { video_id: videoId };

  for (const key of ["title", "channel", "channel_id", "published", "views", "description"]) {
    if (meta?.[key]) {
      body[key] = String(meta[key]);
    }
  }

  if (Number(meta?.durationSec) > 0) {
    body.duration_s = Number(meta.durationSec);
  }

  body.is_short = Boolean(meta?.isShort ?? meta?.is_short);
  body.is_live = Boolean(meta?.isLive ?? meta?.is_live);

  // Optional assess context (ai/CONTRACT.md VideoMeta): each is added only where the page or the
  // signed-in user's subscription list exposes it, so an unknown signal never reads as a negative
  // (the TV sends is_subscribed only when true for the same reason).
  if (meta?.isSubscribed ?? meta?.is_subscribed) {
    body.is_subscribed = true;
  }
  putText(body, "upload_date", meta?.uploadDate ?? meta?.upload_date);
  putInt(body, "likes", meta?.likes);
  putInt(body, "dislikes", meta?.dislikes);
  putInt(body, "subscriber_count", meta?.subscriberCount ?? meta?.subscriber_count);
  putText(body, "channel_description", meta?.channelDescription ?? meta?.channel_description);
  putTitles(body, "channel_titles", meta?.channelTitles ?? meta?.channel_titles);

  return body;
}

function putText(body, key, value) {
  if (value) {
    body[key] = String(value);
  }
}

function putInt(body, key, value) {
  if (value == null || value === "") {
    return;
  }
  const number = Number(value);
  if (Number.isFinite(number)) {
    body[key] = number;
  }
}

function putTitles(body, key, values) {
  if (!Array.isArray(values)) {
    return;
  }
  const titles = values.filter((value) => typeof value === "string" && value);
  if (titles.length) {
    body[key] = titles;
  }
}

export function addMeta(query, meta) {
  if (!meta) {
    return query;
  }

  if (meta.title) {
    query.set("title", meta.title);
  }

  if (meta.channel) {
    query.set("channel", meta.channel);
  }

  if (Number(meta.durationSec) > 0) {
    query.set("duration_s", String(meta.durationSec));
  }

  return query;
}

export function addLiveFlag(query, meta) {
  if (meta?.isLive || meta?.is_live) {
    query.set("is_live", "true");
  }

  return query;
}
