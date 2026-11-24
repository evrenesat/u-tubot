import assert from "node:assert/strict";
import { test } from "node:test";

import { variantManifest } from "../../build.mjs";

const FIREFOX = ["firefox-unlisted", "firefox-listed", "firefox-test"];
const RELEASE = ["firefox-unlisted", "firefox-listed", "chromium"];
const YOUTUBE = ["https://www.youtube.com/*", "https://m.youtube.com/*"];
const LOOPBACK = "127.0.0.1";

test("release variants name no loopback origin", () => {
  for (const variant of RELEASE) {
    const text = JSON.stringify(variantManifest(variant));
    assert.equal(text.includes(LOOPBACK), false, variant);
    assert.equal(variantManifest(variant).browser_specific_settings?.gecko?.id ?? null, variant.startsWith("firefox") ? "extension@utubot.dev" : null);
  }
});

test("Firefox variants are event pages with the permanent id and consent categories", () => {
  for (const variant of FIREFOX) {
    const manifest = variantManifest(variant);
    assert.deepEqual(manifest.background.scripts, ["background.js"], variant);
    assert.equal(manifest.background.service_worker, undefined, variant);
    assert.equal(manifest.browser_specific_settings.gecko.id, "extension@utubot.dev", variant);
    assert.equal(manifest.browser_specific_settings.gecko.strict_min_version, "140.0", variant);
    assert.deepEqual(manifest.browser_specific_settings.gecko.data_collection_permissions.required, [
      "browsingActivity",
      "websiteContent",
      "authenticationInfo",
    ]);
    assert.equal(manifest.browser_specific_settings.gecko_android.strict_min_version, "142.0", variant);
  }
});

test("the unlisted file updates from the extension-updates branch and the listed one does not", () => {
  const unlisted = variantManifest("firefox-unlisted");
  const listed = variantManifest("firefox-listed");
  assert.match(unlisted.browser_specific_settings.gecko.update_url, /extension-updates\/updates\.json$/);
  assert.equal(listed.browser_specific_settings.gecko.update_url, undefined);
});

test("the test variant moves YouTube to optional and takes the fixture origin", () => {
  const manifest = variantManifest("firefox-test");
  assert.deepEqual(manifest.host_permissions, ["http://127.0.0.1/*"]);
  assert.deepEqual(manifest.content_scripts[0].matches, ["http://127.0.0.1/*"]);
  for (const origin of YOUTUBE) {
    assert.equal(manifest.optional_host_permissions.includes(origin), true);
    assert.equal(manifest.host_permissions.includes(origin), false);
  }
});

test("the Chromium variant is a service worker without Firefox-only keys", () => {
  const manifest = variantManifest("chromium");
  assert.equal(manifest.background.service_worker, "background.js");
  assert.equal(manifest.background.scripts, undefined);
  assert.equal(manifest.browser_specific_settings, undefined);
  assert.equal(manifest.minimum_chrome_version, "121");
  assert.deepEqual(manifest.host_permissions, YOUTUBE);
});

test("the Chromium test variant requires the mock origins as host permissions", () => {
  const manifest = variantManifest("chromium-test");
  assert.deepEqual(manifest.host_permissions, ["http://127.0.0.1/*", "http://127.0.0.2/*", "http://127.0.0.3/*"]);
  assert.deepEqual(manifest.content_scripts[0].matches, ["http://127.0.0.1/*"]);
});