/**
 * The storage.session caches of the plan's decision 7: verdicts (2000), ready summaries (100) and captions answers
 * (30). Nothing lives in the background's memory. A backend or token change clears these caches; the IndexedDB
 * caption store is never cleared by it.
 */

export const MAX_VERDICTS = 2000;
export const MAX_SUMMARIES = 100;
export const MAX_CAPTIONS = 30;

const PREFIX = "utubot.cache.";

export function createCache(storage, name, max) {
  const key = PREFIX + name;

  async function readEntries() {
    const values = await storage.session.get([key]);
    return Array.isArray(values?.[key]) ? values[key] : [];
  }

  return {
    async get(itemKey) {
      const entries = await readEntries();
      return entries.find((entry) => entry.key === itemKey)?.value ?? null;
    },

    async set(itemKey, value) {
      const entries = (await readEntries()).filter((entry) => entry.key !== itemKey);

      if (entries.length >= max) {
        entries.sort((a, b) => a.at - b.at);
        while (entries.length >= max) {
          entries.shift();
        }
      }

      entries.push({ key: itemKey, value, at: Date.now() });
      await storage.session.set({ [key]: entries });
    },

    async delete(itemKey) {
      const entries = (await readEntries()).filter((entry) => entry.key !== itemKey);
      await storage.session.set({ [key]: entries });
    },

    async clear() {
      await storage.session.remove([key]);
    },
  };
}

export async function clearSessionCaches(storage) {
  const all = await storage.session.get(null);
  const keys = Object.keys(all ?? {}).filter((key) => key.startsWith(PREFIX) || key === "utubot.openRequests");

  if (keys.length > 0) {
    await storage.session.remove(keys);
  }
}

export async function setOpenRequest(storage, videoId, request) {
  const stored = await storage.session.get(["utubot.openRequests"]);
  const requests = { ...(stored?.["utubot.openRequests"] ?? {}), [videoId]: request };
  await storage.session.set({ "utubot.openRequests": requests });
}

export async function takeOpenRequest(storage, videoId) {
  const stored = await storage.session.get(["utubot.openRequests"]);
  const requests = { ...(stored?.["utubot.openRequests"] ?? {}) };
  const request = requests[videoId] ?? null;

  if (request) {
    delete requests[videoId];
    await storage.session.set({ "utubot.openRequests": requests });
  }

  return request;
}
