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
  return body;
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
