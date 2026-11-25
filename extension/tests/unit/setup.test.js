import assert from "node:assert/strict";
import { test } from "node:test";

import { isPrivateHost, originOf, parseSetup, requireUrl, resolveUrl, SetupError } from "../../src/background/setup.js";

const rejects = (fn) => assert.throws(fn, SetupError);

test("a bare host gets https and the setup path", () => {
  assert.equal(resolveUrl("utubot.example.com"), "https://utubot.example.com/setup.json");
  assert.equal(resolveUrl("  utubot.example.com/ "), "https://utubot.example.com/setup.json");
  assert.equal(resolveUrl("utubot.example.com:8443"), "https://utubot.example.com:8443/setup.json");
});

test("a bare private address gets http", () => {
  assert.equal(resolveUrl("10.0.0.10:8790"), "http://10.0.0.10:8790/setup.json");
  assert.equal(resolveUrl("nas:8790"), "http://nas:8790/setup.json");
  assert.equal(resolveUrl("100.64.0.7:8790"), "http://100.64.0.7:8790/setup.json");
});

test("a full URL is used as typed", () => {
  assert.equal(resolveUrl("https://example.com/me/setup.json"), "https://example.com/me/setup.json");
  assert.equal(resolveUrl("http://10.0.0.10:8790/setup.json"), "http://10.0.0.10:8790/setup.json");
});

test("http is only for private addresses", () => {
  rejects(() => resolveUrl("http://example.com/setup.json"));
  rejects(() => resolveUrl("http://8.8.8.8/setup.json"));
  rejects(() => resolveUrl("ftp://example.com/setup.json"));
  rejects(() => resolveUrl(""));
  rejects(() => resolveUrl("   "));
  rejects(() => resolveUrl(null));
});

test("private hosts", () => {
  for (const host of ["10.0.0.1", "172.16.5.5", "172.31.255.1", "192.168.0.9", "127.0.0.1", "169.254.1.1", "::1", "fd00::1", "localhost", "nas.local", "[::1]", "[fd00::1]", "[FE80::1]"]) {
    assert.equal(isPrivateHost(host), true, host);
  }
  for (const host of ["172.32.0.1", "100.128.0.1", "8.8.8.8", "example.com", "", "[2001:db8::1]"]) {
    assert.equal(isPrivateHost(host), false, host);
  }
});

test("bracketed IPv6 addresses work like the TV's", () => {
  assert.equal(resolveUrl("http://[::1]:8790/setup.json"), "http://[::1]:8790/setup.json");
  assert.equal(resolveUrl("http://[fd00::1]:8790/setup.json"), "http://[fd00::1]:8790/setup.json");
  assert.equal(resolveUrl("[::1]:8790"), "http://[::1]:8790/setup.json");
  assert.equal(resolveUrl("[fd00::1]"), "http://[fd00::1]/setup.json");
  assert.equal(resolveUrl("[2001:db8::1]:8443"), "https://[2001:db8::1]:8443/setup.json");
  assert.equal(resolveUrl("https://[2001:db8::1]:8443"), "https://[2001:db8::1]:8443");
  rejects(() => resolveUrl("http://[2001:db8::1]/setup.json"));
  const setup = parseSetup('{"utubot_setup":1,"backend_url":"http://[fd00::1]:8790"}');
  assert.equal(setup.backendUrl, "http://[fd00::1]:8790");
  rejects(() => parseSetup('{"utubot_setup":1,"backend_url":"http://[2001:db8::1]"}'));
  assert.equal(originOf("http://[::1]:8790/setup.json"), "http://[::1]:8790");
  assert.equal(originOf("https://[2001:DB8::1]/setup.json"), "https://[2001:db8::1]");
  assert.equal(requireUrl("http://[::1]:8790/setup.json", "what"), "http://[::1]:8790/setup.json");
});

test("parses the setup file", () => {
  const setup = parseSetup('{"utubot_setup":1,"name":"Home","backend_url":"https://utubot.example.com/","update_url":"https://utubot.example.com/app/update.json","pairing":true,"defaults":{"assess":true,"mark_only":true,"summary_panel":false,"auto_captions":true},"prompt_set_urls":["https://example.com/p.json",""]}');
  assert.equal(setup.name, "Home");
  assert.equal(setup.backendUrl, "https://utubot.example.com");
  assert.equal(setup.updateUrl, "https://utubot.example.com/app/update.json");
  assert.equal(setup.pairing, true);
  assert.equal(setup.defaults.mark_only, true);
  assert.equal(setup.defaults.summary_panel, false);
  assert.equal(setup.defaults.answer_in_menu, undefined);
  assert.deepEqual(setup.promptSetUrls, ["https://example.com/p.json"]);
});

test("a minimal setup keeps the defaults unset", () => {
  const setup = parseSetup('{"utubot_setup":1,"backend_url":"http://10.0.0.10:8790"}');
  assert.equal(setup.updateUrl, "");
  assert.equal(setup.pairing, true);
  assert.equal(setup.defaults.assess, undefined);
  assert.deepEqual(setup.promptSetUrls, []);
});

test("bad setup files are rejected", () => {
  for (const body of [
    "not json",
    '{"backend_url":"https://utubot.example.com"}',
    '{"utubot_setup":2,"backend_url":"https://utubot.example.com"}',
    '{"utubot_setup":1}',
    '{"utubot_setup":1,"backend_url":"http://example.com"}',
    '{"utubot_setup":1,"backend_url":"https://utubot.example.com","update_url":"http://example.com/u.json"}',
  ]) {
    rejects(() => parseSetup(body));
  }
});

test("requireUrl follows the same scheme rule", () => {
  assert.equal(requireUrl("https://example.com/x", "what"), "https://example.com/x");
  assert.equal(requireUrl("http://10.0.0.5:8790/x", "what"), "http://10.0.0.5:8790/x");
  rejects(() => requireUrl("http://example.com/x", "what"));
  rejects(() => requireUrl("", "what"));
});
