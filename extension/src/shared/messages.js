/**
 * Message names and the two sender sets of the plan's decision 6. There is no generic fetch message.
 */

export const YOUTUBE_ORIGINS = ["https://www.youtube.com/", "https://m.youtube.com/"];

export const PAGE_ONLY = new Set([
  "setup.fetch",
  "setup.apply",
  "pair",
  "backend.set",
  "token.set",
  "health",
  "me",
  "prompts.list",
  "prompts.import",
  "prompts.refresh",
  "prompts.default",
  "settings.read",
  "settings.write",
  "processed",
  "open.set",
  "diagnostics.read",
]);

export const CONTENT = new Set([
  "assess",
  "summary",
  "insight",
  "transcribe",
  "transcript",
  "prompts.list",
  "captions.status",
  "captions.prepare",
  "captions.file",
  "cuts.list",
  "cuts.request",
  "cuts.follow",
  "settings.read",
  "open.take",
  "diagnostics.report",
]);

export const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;

export function isPageSender(sender, extensionBase) {
  return Boolean(sender?.url?.startsWith(extensionBase));
}

export function isContentSender(sender, isTest) {
  if (!sender?.url) {
    return false;
  }

  if (YOUTUBE_ORIGINS.some((origin) => sender.url.startsWith(origin))) {
    return true;
  }

  if (!isTest) {
    return false;
  }

  try {
    return new URL(sender.url).hostname === "127.0.0.1";
  } catch {
    return false;
  }
}

export function checkMessage(message, sender, extensionBase, isTest) {
  if (!message || typeof message.type !== "string") {
    throw new Error("Bad message");
  }

  const page = isPageSender(sender, extensionBase);
  const content = isContentSender(sender, isTest);

  if (!page && !content) {
    throw new Error("This sender is not allowed");
  }

  if (!PAGE_ONLY.has(message.type) && !CONTENT.has(message.type)) {
    throw new Error("Unknown message");
  }

  if (PAGE_ONLY.has(message.type) && !CONTENT.has(message.type) && !page) {
    throw new Error("This message comes from an extension page only");
  }

  const payload = message.payload ?? {};

  if (payload.video_id !== undefined && !VIDEO_ID.test(payload.video_id)) {
    throw new Error("Bad video id");
  }

  return { page, payload };
}
