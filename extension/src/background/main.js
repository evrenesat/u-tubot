/**
 * Loads the router with the real extension storage and API, and listens for the two message sets. On install the
 * options page opens, where the setup and the YouTube permission notice are the first things shown.
 */
import { api, extensionBaseUrl, onInstalled, onMessage, openOptionsPage } from "../shared/api.js";
import { createRouter } from "./router.js";

const storage = {
  local: {
    get: (keys) => api.storage.local.get(keys),
    set: (values) => api.storage.local.set(values),
  },
  session: {
    get: (keys) => api.storage.session.get(keys),
    set: (values) => api.storage.session.set(values),
    remove: (keys) => api.storage.session.remove(keys),
  },
};

const router = createRouter({
  storage,
  extensionBase: extensionBaseUrl(),
  isTest: __UTUBOT_TEST__,
});

onMessage((message, sender) => router.handleMessage(message, sender));

onInstalled((details) => {
  if (details.reason === "install") {
    openOptionsPage();
  }
});
