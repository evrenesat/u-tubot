/**
 * The only module that touches the extension API (`browser` on Firefox, `chrome` on Chromium).
 * Promise style everywhere; message handlers answer through `sendResponse` and return `true`.
 */

export const api = globalThis.browser ?? globalThis.chrome;

export function extensionBaseUrl() {
  return api.runtime.getURL("");
}

export function extensionUrl(path = "") {
  return api.runtime.getURL(path);
}

export function sendMessage(message) {
  return new Promise((resolve, reject) => {
    api.runtime.sendMessage(message, (answer) => {
      const error = api.runtime.lastError;

      if (error) {
        reject(new Error(error.message ?? String(error)));
      } else if (answer && answer.error) {
        reject(new Error(answer.error));
      } else {
        resolve(answer);
      }
    });
  });
}

/**
 * One long-lived listener. `handler(message, sender)` returns a value or a promise; the router
 * wraps it in the callback style both browsers accept.
 */
export function onMessage(handler) {
  api.runtime.onMessage.addListener((message, sender, sendResponse) => {
    Promise.resolve()
      .then(() => handler(message, sender))
      .then(
        (answer) => sendResponse(answer ?? null),
        (error) => sendResponse({ error: error?.message ?? String(error) }),
      );

    return true;
  });
}

export function storageLocalGet(keys) {
  return api.storage.local.get(keys);
}

export function storageLocalSet(values) {
  return api.storage.local.set(values);
}

export function storageLocalRemove(keys) {
  return api.storage.local.remove(keys);
}

export function storageLocalClear() {
  return api.storage.local.clear();
}

export function storageSessionGet(keys) {
  return api.storage.session.get(keys);
}

export function storageSessionSet(values) {
  return api.storage.session.set(values);
}

export function storageSessionRemove(keys) {
  return api.storage.session.remove(keys);
}

export function storageSessionClear() {
  return api.storage.session.clear();
}

export function storageLocalOnChange(listener) {
  api.storage.onChanged.addListener((changes, area) => {
    if (area === "local") {
      listener(changes);
    }
  });
}

export function openOptionsPage() {
  return api.runtime.openOptionsPage();
}

export function onInstalled(listener) {
  api.runtime.onInstalled.addListener(listener);
}

export function setBadgeText(text) {
  return api.action.setBadgeText({ text });
}

export function setBadgeBackgroundColor(color) {
  return api.action.setBadgeBackgroundColor({ color });
}

export function permissionsContains(origins) {
  return api.permissions.contains({ origins });
}

export function permissionsRequest(origins) {
  return api.permissions.request({ origins });
}

export function permissionsRemove(origins) {
  return api.permissions.remove({ origins });
}