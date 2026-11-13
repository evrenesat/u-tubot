// Captures the phone screenshots of the web UI (390x844 at 2x) from a running demo server.
//
//   cd ai-backend && uv run python tests/webui_demo.py temp/webui-demo &
//   node docs/screenshots/webui/capture.cjs http://127.0.0.1:8791 docs/screenshots/webui
//
// Needs Playwright with a Chromium build (`require('playwright')`). Also fails when a page scrolls
// sideways at 360 px or logs a console error.
const { chromium } = require("playwright");
const path = require("node:path");

const base = process.argv[2] || "http://127.0.0.1:8791";
const out = path.resolve(process.argv[3] || "docs/screenshots/webui");
const PAGES = ["home", "models", "prompts", "filters", "captions", "tvs", "updates", "account", "admin", "more"];
const problems = [];

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
  await page.waitForSelector("pre.result", { timeout: 30000 });
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
  await browser.close();
  if (problems.length) {
    console.error("PROBLEMS:\n" + problems.join("\n"));
    process.exit(1);
  }
  console.log("ok: no console errors, no sideways scroll at 360px");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
