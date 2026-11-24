import assert from "node:assert/strict";
import { test } from "node:test";
import { Linter } from "eslint";

import config from "../../eslint.config.js";

const linter = new Linter();
const messages = (code, filename) => linter.verify(code, config, { filename });

test("eslint refuses browser and chrome outside api.js", () => {
  for (const code of ["browser.runtime.sendMessage({});", "chrome.runtime.sendMessage({});"]) {
    const found = messages(code, "src/content/probe.js");
    assert.equal(found.some((message) => message.message.includes("src/shared/api.js")), true, code);
  }
});

test("eslint allows the extension API in api.js", () => {
  assert.deepEqual(messages("globalThis.browser ?? globalThis.chrome;", "src/shared/api.js"), []);
});

test("eslint refuses window and document in the background", () => {
  for (const code of ["window.location.href;", "document.querySelector('video');"]) {
    const found = messages(code, "src/background/probe.js");
    assert.equal(found.length > 0, true, code);
    assert.equal(found.some((message) => message.message.includes("service worker") || message.message.includes("no window") || message.message.includes("no document")), true, code);
  }
});

test("eslint refuses HTML string insertion everywhere", () => {
  for (const snippet of ["node.innerHTML = '<b>x</b>';", "node.outerHTML;", "node.insertAdjacentHTML('beforeend', '<b>x</b>');"]) {
    const found = messages(snippet, "src/content/ui/probe.js");
    assert.equal(found.some((message) => message.message.includes("textContent")), true, snippet);
  }
});