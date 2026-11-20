// Playwright check of the director's-cuts pages (the Cuts tab and the cut sheet) against the
// demo server. Self-contained: it clears the cut queue first, then walks the whole request life
// through the UI (paste a link, describe, build, ready parts list, a failing build, dismiss,
// queue order). Fails on console errors, page errors or sideways scrolling at 360 px.
//
//   cd ai-backend && uv run python tests/webui_demo.py temp/webui-demo &
//   NODE_PATH=<dir with playwright> node scripts/webui_cuts_check.cjs http://127.0.0.1:8791
//
// Needs Playwright with a Chromium build (same as docs/screenshots/webui/capture.cjs).
const { chromium } = require("playwright");

const base = process.argv[2] || "http://127.0.0.1:8791";
// The demo's owner API token (tests/webui_demo.py prints it): the check drives the API with it,
// because the browser session's CSRF value is unreachable from the page context.
const DEMO_TOKEN = "utb_demo_owner";
const problems = [];
let checks = 0;

function ok(condition, message) {
  checks += 1;
  if (!condition) problems.push("check failed: " + message);
}

async function go(page, hash, settle = 600) {
  await page.evaluate((h) => {
    if (location.hash === h) window.dispatchEvent(new HashChangeEvent("hashchange"));
    else location.hash = h;
  }, "#/" + hash);
  await page.waitForTimeout(settle);
}

async function api(ctx, path, options = {}) {
  const res = await ctx.request.fetch(base + path, {
    headers: { Authorization: "Bearer " + DEMO_TOKEN },
    ...options,
  });
  return { status: res.status(), body: await res.json().catch(() => null) };
}

function currentRequest(page, ctx) {
  return page.evaluate(() => location.hash).then(async (hash) => {
    const m = hash.match(/#\/cuts\/([a-z0-9]+)/);
    if (!m) return null;
    return (await api(ctx, "/v1/cuts/" + m[1])).body;
  });
}

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 2,
    colorScheme: "dark",
    locale: "en-US",
    timezoneId: "UTC",
    reducedMotion: "reduce",
    hasTouch: true,
    isMobile: true,
  });
  const page = await ctx.newPage();
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource/.test(m.text())) problems.push("console: " + m.text());
  });
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));

  await page.goto(base + "/");
  await page.locator("input[name=username]").fill("owner");
  await page.locator("input[name=password]").fill("demo-password-123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForSelector("#nav:not([hidden])");

  // Clear the queue (the check creates its own states; the demo seed stays for manual poking).
  const { body } = await api(ctx, "/v1/cut-requests");
  for (const r of body.requests) await api(ctx, "/v1/cut-requests/" + r.id, { method: "DELETE" });

  // Empty queue.
  await go(page, "cuts", 900);
  ok(await page.getByRole("heading", { name: "Cuts", exact: true }).isVisible(), "Cuts heading");
  ok((await page.locator("#view").textContent()).includes("No cuts yet"), "empty queue message");

  // A new cut from a pasted link opens the waiting sheet with the preset chips.
  await page.getByPlaceholder("YouTube link or video id").fill("https://youtu.be/ccccccccccc1?si=x");
  await page.getByRole("button", { name: "Describe this cut" }).click();
  await page.waitForTimeout(900);
  ok(/#\/cuts\/[a-z0-9]+/.test(await page.evaluate(() => location.hash)), "a new request opens its sheet");
  const box = page.locator("textarea");
  ok(await box.isVisible(), "the waiting sheet has a description box");
  const chips = await page.locator(".chip-btn").allTextContents();
  ok(chips.join("|").includes("No filler"), "preset chips are offered: " + chips.join("|"));
  const req = await currentRequest(page, ctx);
  ok(req && req.state === "waiting", "the request is waiting for the description");
  ok((await page.locator("#view").textContent()).includes("Looking up the video"), "the title is not known yet and says so");

  // Build: held model keeps it building with a stage line; releasing finishes it.
  await page.evaluate(() => fetch("/demo/cut/hold", { method: "POST" }));
  await box.fill("Skip the intro and the gear list; keep the actual test.");
  await page.getByRole("button", { name: "Build cut" }).click();
  await page.waitForTimeout(1500);
  let doc = await currentRequest(page, ctx);
  ok(doc.state === "building" || doc.state === "needs_transcript", "the request is building (state: " + doc.state + ")");
  const buildingText = await page.locator("#view").textContent();
  ok(/building|model|transcript/i.test(buildingText), "the sheet shows the build stage");
  await page.evaluate(() => fetch("/demo/cut/release", { method: "POST" }));
  await page.waitForFunction(
    () => document.querySelector("#view").textContent.includes("kept of"),
    { timeout: 30000 },
  );
  doc = await currentRequest(page, ctx);
  ok(doc.state === "ready", "the cut is ready");
  ok(doc.cut.parts.length >= 2, "the parts list has parts");
  ok(doc.cut.skip_ranges_ms.length >= 3, "skip ranges cover the rest");
  ok((await page.locator("#view").textContent()).includes("The TV offers this cut"), "the sheet tells the owner where the cut plays");

  // A build whose model answer never validates: the repair round fails, the sheet shows a plain reason.
  await page.evaluate(() => fetch("/demo/cut/bad", { method: "POST" }));
  await go(page, "cuts", 700);
  await page.getByPlaceholder("YouTube link or video id").fill("dddddddddd1");
  await page.getByRole("button", { name: "Describe this cut" }).click();
  await page.waitForTimeout(900);
  await page.locator("textarea").fill("Only the part with the lock operation");
  await page.getByRole("button", { name: "Build cut" }).click();
  await page.waitForFunction(
    () => document.querySelector("#view .pill.bad") !== null,
    { timeout: 30000 },
  );
  doc = await currentRequest(page, ctx);
  ok(doc.state === "failed" && doc.error, "the failed sheet shows a plain reason: " + (doc.error || ""));
  ok(await page.getByRole("button", { name: "Try again" }).isVisible(), "failed sheet offers Retry");
  await page.evaluate(() => fetch("/demo/cut/good", { method: "POST" }));

  // Queue order: failed, ready; dismiss works from the sheet and the card.
  await go(page, "cuts", 800);
  const states = await page.locator(".cut .pill").allTextContents();
  ok(states[0] === "failed" && states.includes("ready"), "queue order failed-first: " + states.join(", "));
  const bodyText = await page.locator("#view").textContent();
  ok(bodyText.includes("from the phone") || bodyText.includes("from Web UI"), "cards show their source");
  await page.locator(".cut").first().getByRole("button", { name: "Dismiss" }).click();
  await page.waitForTimeout(900);
  ok(!(await page.locator("#view").textContent()).includes("failed"), "the dismissed card is gone");

  // A waiting card sits first in the queue.
  await page.getByPlaceholder("YouTube link or video id").fill("eeeeeeeee22");
  await page.getByRole("button", { name: "Describe this cut" }).click();
  await page.waitForTimeout(900);
  await go(page, "cuts", 800);
  const last = await page.locator(".cut .pill").allTextContents();
  ok(last[0] === "waiting for your description", "a waiting card comes first: " + last.join(", "));

  // No sideways scrolling at 360 px.
  const narrow = await browser.newContext({ viewport: { width: 360, height: 740 } });
  const npage = await narrow.newPage();
  npage.on("pageerror", (e) => problems.push("pageerror(narrow): " + e.message));
  await npage.goto(base + "/");
  await npage.locator("input[name=username]").fill("owner");
  await npage.locator("input[name=password]").fill("demo-password-123");
  await npage.getByRole("button", { name: "Sign in", exact: true }).click();
  await npage.waitForSelector("#nav:not([hidden])");
  for (const hash of ["cuts", "cuts/" + (doc ? doc.id : "democut0010")]) {
    await go(npage, hash, 700);
    const extra = await npage.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (extra > 0) problems.push(`${hash}: ${extra}px of horizontal scroll at 360px`);
    checks += 1;
  }
  await narrow.close();

  await browser.close();
  if (problems.length) {
    console.error("FAIL (" + checks + " checks)");
    for (const p of problems) console.error(" - " + p);
    process.exit(1);
  }
  console.log("OK (" + checks + " checks)");
})();