// Captures the phone screenshots of the web UI (390x844 at 2x) from a running demo server.
//
//   cd ai-backend && uv run python tests/webui_demo.py temp/webui-demo &
//   node docs/screenshots/webui/capture.cjs http://127.0.0.1:8791 docs/screenshots/webui
//
// Needs Playwright with a Chromium build (`require('playwright')`). Also fails when a page scrolls
// sideways at 360 px or logs a console error.
//
// Same orphan rule as scripts/webui_cuts_check.cjs: a killed node process cannot run its cleanup,
// and the headless Chromium it started would survive. So the whole run is budgeted below the
// shell timeout (BROWSER_BUDGET_MS, default 90 s), Playwright waits are capped at 10 s, the
// browser is closed in a finally, and SIGTERM/SIGINT close the browser before exiting.
const { chromium } = require("playwright");
const path = require("node:path");

const base = process.argv[2] || "http://127.0.0.1:8791";
const out = path.resolve(process.argv[3] || "docs/screenshots/webui");
const BUDGET_MS = Number(process.env.BROWSER_BUDGET_MS) || 90000;
const WAIT_MS = 10000;
const PAGES = ["home", "models", "prompts", "filters", "captions", "tvs", "settings", "settings/history", "updates", "account", "admin", "more"];
const problems = [];
let browser = null;
let reported = false;
let dying = false;

function fail(reason) {
  if (reason) problems.push(reason);
  if (reported) return;
  reported = true;
  console.error("PROBLEMS:\n" + problems.join("\n"));
  process.exitCode = 1;
}

// Stop without orphaning the browser: close it first, then exit (a hard stop 5 s later in case
// the close itself hangs). A second signal exits at once.
function closeAndExit(why) {
  fail(why);
  const hard = setTimeout(() => process.exit(process.exitCode || 1), 5000);
  hard.unref();
  if (!browser) process.exit(process.exitCode || 1);
  browser.close().catch(() => {}).then(() => process.exit(process.exitCode || 1));
}

const budget = setTimeout(
  () =>
    closeAndExit(
      "the capture exceeded its own " + BUDGET_MS + " ms budget; give the shell a longer timeout or raise BROWSER_BUDGET_MS",
    ),
  BUDGET_MS,
);

function onSignal(sig) {
  if (dying) process.exit(process.exitCode || 1);
  dying = true;
  closeAndExit(sig + " received; closing the browser before exiting");
}
process.on("SIGTERM", () => onSignal("SIGTERM"));
process.on("SIGINT", () => onSignal("SIGINT"));

async function scrollTo(page, locator) {
  await locator.evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 72));
  await page.waitForTimeout(150);
}

async function shot(page, name) {
  await page.waitForTimeout(250);
  await page.screenshot({ path: path.join(out, name + ".png") });
  console.log("wrote", name);
}

async function gate(page, state) {
  await page.evaluate((s) => fetch("/demo/gate/" + s, { method: "POST" }), state);
}

async function go(page, hash, settle = 700) {
  await page.evaluate((h) => {
    if (location.hash === h) window.dispatchEvent(new HashChangeEvent("hashchange"));
    else location.hash = h;
  }, "#/" + hash);
  await page.waitForTimeout(settle);
  await page.evaluate(() => window.scrollTo(0, 0));
}

async function checkOverflow(browser) {
  const ctx = await browser.newContext({ viewport: { width: 360, height: 740 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.setDefaultTimeout(WAIT_MS);
  page.setDefaultNavigationTimeout(WAIT_MS);
  page.on("pageerror", (e) => problems.push("pageerror: " + e.message));
  await page.goto(base + "/");
  await page.locator("input[name=username]").fill("owner");
  await page.locator("input[name=password]").fill("demo-password-123");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForSelector("#nav:not([hidden])");
  for (const name of [...PAGES, "admin/user/partner", "jobs/demojob0005", "jobs/demojob0006", "jobs/demojob0002", "jobs/demojob0000"]) {
    await go(page, name, 600);
    const extra = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (extra > 0) problems.push(`${name}: ${extra}px of horizontal scroll at 360px`);
  }
  await ctx.close();
}

(async () => {
  try {
    browser = await chromium.launch();
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
    page.setDefaultTimeout(WAIT_MS);
    page.setDefaultNavigationTimeout(WAIT_MS);
    page.on("console", (m) => {
      if (m.type() === "error" && !/Failed to load resource/.test(m.text())) problems.push("console: " + m.text());
    });
    page.on("pageerror", (e) => problems.push("pageerror: " + e.message));

    await page.goto(base + "/");
    await page.waitForSelector("input[name=username]");
    await shot(page, "01-sign-in");
    await page.locator("input[name=username]").fill("owner");
    await page.locator("input[name=password]").fill("demo-password-123");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.waitForSelector("#nav:not([hidden])");

    await gate(page, "open");
    await go(page, "home");
    await shot(page, "02-home");
    await scrollTo(page, page.getByRole("heading", { name: "Today (UTC)" }));
    await shot(page, "03-home-usage");

    await go(page, "models");
    await shot(page, "04-models");
    await scrollTo(page, page.getByRole("heading", { name: "Model list" }));
    await shot(page, "05-models-list");

    await go(page, "prompts");
    await shot(page, "06-prompts");
    await page.getByRole("button", { name: "Edit JSON" }).first().click();
    await page.getByRole("button", { name: "Validate" }).click();
    await page.waitForTimeout(500);
    await scrollTo(page, page.getByRole("heading", { name: "Edit a prompt set" }));
    await shot(page, "07-prompts-editor");
    await page.locator("textarea.code").first().fill('{"tubeai_prompt_set": 1, "id": "broken id", "name": "X", "prompts": [{"id": "a", "label": "A", "template": ""}]}');
    await page.getByRole("button", { name: "Validate" }).click();
    await page.waitForTimeout(500);
    await shot(page, "08-prompts-validation-error");
    await gate(page, "close");
    await scrollTo(page, page.getByRole("heading", { name: "Try a prompt" }));
    await page.getByPlaceholder("video id or YouTube link").fill("https://youtu.be/dQw4w9WgXcQ?si=share");
    await page.getByRole("button", { name: "Run" }).click();
    await page.waitForSelector("pre.result", { timeout: 20000 });
    await scrollTo(page, page.getByRole("heading", { name: "Try a prompt" }));
    await shot(page, "09-prompts-try");

    await go(page, "filters");
    await shot(page, "10-filters");
    await scrollTo(page, page.getByRole("heading", { name: "Thresholds" }));
    await shot(page, "11-filters-thresholds");

    await gate(page, "open");
    await go(page, "captions");
    await shot(page, "12-captions");
    await scrollTo(page, page.getByRole("heading", { name: "Jobs" }));
    await shot(page, "13-captions-jobs");

    await go(page, "captions");
    await page.getByRole("link", { name: "Türkiye'de enflasyon neden düşmüyor?" }).click();
    await page.waitForSelector(".timeline");
    await shot(page, "22-job-detail");
    await scrollTo(page, page.getByRole("heading", { name: "What happened" }));
    await shot(page, "23-job-timeline");
    await go(page, "captions");
    await page.getByRole("link", { name: "Slow TV: eight hours of canal boats" }).click();
    await page.waitForSelector(".timeline");
    await shot(page, "24-job-failed");

    await go(page, "tvs");
    await page.getByRole("button", { name: "Make a code" }).click();
    await page.waitForSelector(".bigcode");
    await shot(page, "14-tv-link");
    await scrollTo(page, page.getByRole("heading", { name: "Linked TVs" }));
    await shot(page, "15-tv-devices");

    await go(page, "settings");
    await shot(page, "25-settings");
    const accounts = page.getByText("Accounts and services", { exact: true });
    if (await accounts.count()) {
      await scrollTo(page, accounts);
      await shot(page, "29-settings-accounts");
    }
    await go(page, "settings/history");
    await shot(page, "26-settings-history");
    // a TV on a current app (its own update interval and cut keys, copy from another TV) and one on an old app
    const tvs = await page.evaluate(async () => (await (await fetch("/v1/me/settings/status")).json()).devices.map((d) => [d.device, d.id]));
    for (const [device, name] of [["Living room TV", "27-settings-tv"], ["Bedroom Fire Stick", "28-settings-tv-old-app"]]) {
      const found = tvs.find(([n]) => n === device);
      if (!found) continue;
      await go(page, "settings/tv/" + encodeURIComponent(found[1]));
      const own = page.getByText("This TV only", { exact: true });
      if (await own.count()) await scrollTo(page, own);
      await shot(page, name);
    }

    await go(page, "updates");
    await shot(page, "16-updates");

    await go(page, "admin");
    await shot(page, "17-admin");
    await go(page, "admin/user/partner", 900);
    await shot(page, "18-admin-user-settings");

    await go(page, "more");
    await shot(page, "19-more");

    await page.emulateMedia({ colorScheme: "light" });
    await go(page, "home");
    await shot(page, "20-home-light");
    await go(page, "filters");
    await shot(page, "21-filters-light");

    await gate(page, "close");
    await ctx.close();
    await checkOverflow(browser);

    if (problems.length) fail();
    else console.log("ok: no console errors, no sideways scroll at 360px");
  } catch (e) {
    fail("script error: " + (e && e.message ? e.message : String(e)));
  } finally {
    clearTimeout(budget);
    if (browser) await browser.close().catch(() => {});
  }
})();