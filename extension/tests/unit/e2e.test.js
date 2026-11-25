import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const E2E = new URL("../../tests/e2e/", import.meta.url);

function read(name) {
  return readFileSync(new URL(name, E2E), "utf8");
}

test("the committed profile names every service group and its preference", () => {
  const text = read("user.js");
  const groups = [...text.matchAll(/^\/\/ group: (.+)$/gm)];
  assert.ok(groups.length >= 18, `only ${groups.length} groups`);

  for (const [index, group] of groups.entries()) {
    const start = group.index;
    const end = groups[index + 1]?.index ?? text.length;
    const body = text.slice(start, end);
    assert.match(body, /user_pref\("/, group[1]);
  }

  for (const name of ["updates", "add-on metadata", "blocklist", "remote settings", "telemetry and health report",
    "Normandy and experiments", "safe browsing lists", "captive-portal and connectivity checks", "DNS over HTTPS",
    "DNS and link prefetch", "speculative connections", "push service", "new-tab content and sponsored tiles",
    "search suggestions and search-engine updates", "location services", "default browser and first-run pages"]) {
    assert.match(text, new RegExp(`^// group: ${name}$`, "m"), name);
  }

  const pref = (key) => {
    const match = text.match(new RegExp(`user_pref\\("${key.replaceAll(".", "\\.")}", (.*)\\);`));
    assert.ok(match, key);
    return match[1];
  };

  assert.equal(pref("network.proxy.type"), "1");
  assert.equal(pref("network.proxy.no_proxies_on"), '"127.0.0.1,127.0.0.2,127.0.0.3"');
  assert.equal(pref("network.proxy.allow_hijacking_localhost"), "false");
  assert.equal(pref("extensions.blocklist.enabled"), "false");
  assert.equal(pref("services.settings.server"), '"data:,#remote-settings-dummy/v1"');
  assert.equal(pref("network.trr.mode"), "5");
  assert.equal(pref("extensions.webextOptionalPermissionPrompts"), "false");
});

test("the tool lock pins the ESR Firefox and geckodriver with hashes", () => {
  const lock = JSON.parse(read("tools.lock"));
  assert.deepEqual(Object.keys(lock).sort(), ["firefox", "geckodriver"]);

  assert.equal(lock.firefox.version, "140.4.0esr");
  assert.match(lock.firefox.url, /^https:\/\/ftp\.mozilla\.org\/pub\/firefox\/releases\/140\.4\.0esr\//);
  assert.equal(lock.geckodriver.version, "0.36.0");
  assert.match(lock.geckodriver.url, /^https:\/\/github\.com\/mozilla\/geckodriver\/releases\/download\/v0\.36\.0\//);

  for (const tool of Object.values(lock)) {
    assert.match(tool.sha256, /^[0-9a-f]{64}$/);
  }
});
