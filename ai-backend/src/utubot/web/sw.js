// u·tubot's service worker: what Android's Share button needs (the manifest's share_target),
// and nothing else. A shared YouTube link is kept here for the page that opens next; it never
// reaches the server as a POST.
const SHARE_CACHE = "utubot-share-v1";
const SHARE_KEY = "/__shared-item";
const SHARE_AT_KEY = "/__shared-at";
// Old shares are dropped by the page: it takes the item and deletes both keys.
const MAX_SHARE_AGE_MS = 10 * 60 * 1000;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname === "/shared" && event.request.method === "POST") {
    event.respondWith(handleShare(event.request));
  }
});

async function handleShare(request) {
  let value = "";
  try {
    const form = await request.formData();
    const url = (form.get("url") || "").toString().trim();
    const text = (form.get("text") || "").toString().trim();
    value = url || text;
  } catch {
    value = "";
  }
  if (value) {
    const cache = await caches.open(SHARE_CACHE);
    await cache.put(SHARE_KEY, new Response(value, { headers: { "Content-Type": "text/plain" } }));
    await cache.put(SHARE_AT_KEY, new Response(String(Date.now()), { headers: { "Content-Type": "text/plain" } }));
  }
  // The cut sheet opens; the page asks for the item with take-share.
  return Response.redirect("/#/cuts", 303);
}

self.addEventListener("message", (event) => {
  if (!event.data || event.data.type !== "take-share") return;
  const port = event.ports && event.ports[0];
  if (!port) return;
  event.waitUntil(takeShare().then((value) => port.postMessage({ value: value })));
});

async function takeShare() {
  const cache = await caches.open(SHARE_CACHE);
  const item = await cache.match(SHARE_KEY);
  if (!item) return null;
  const atText = await cache.match(SHARE_AT_KEY);
  const at = atText ? Number(await atText.text()) : 0;
  const value = await item.text();
  await cache.delete(SHARE_KEY);
  await cache.delete(SHARE_AT_KEY);
  if (!Number.isFinite(at) || Date.now() - at > MAX_SHARE_AGE_MS) return null;
  return value;
}
