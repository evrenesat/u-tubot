// Playwright check of the director's-cuts pages (the Cuts tab and the cut sheet) against the
// demo server. Self-contained: it clears the cut queue first, then walks the whole request life
// through the UI (paste a link, describe, build, ready parts list, a failing build, dismiss,
// queue order). Fails on console errors, page errors or sideways scrolling at 360 px.
//
//   cd ai-backend && uv run python tests/webui_demo.py temp/webui-demo &
//   NODE_PATH=<dir with playwright> node scripts/webui_cuts_check.cjs http://127.0.0.1:8791
//
// Needs Playwright with a Chromium build (same as docs/screenshots/webui/capture.cjs).
//
// The check never leans on the shell timeout to stop it: a killed node process cannot run its
// cleanup, and the headless Chromium it started would survive as an orphan (that filled p100's
// task limit on 2026-11-19). So the whole run is budgeted below the shell timeout
// (BROWSER_BUDGET_MS, default 90 s), every Playwright wait is capped at 10 s (the two build
// waits at 20 s), the browser is closed in a finally, and SIGTERM/SIGINT close the browser
// before exiting. Run the shell with a timeout above BROWSER_BUDGET_MS.
const { chromium } = require("playwright");

const base = process.argv[2] || "http://127.0.0.1:8791";
const BUDGET_MS = Number(process.env.BROWSER_BUDGET_MS) || 90000;
const WAIT_MS = 10000;
const BUILD_WAIT_MS = 20000;
// The demo's owner API token (tests/webui_demo.py prints it): the check drives the API with it,
// because the browser session's CSRF value is unreachable from the page context.
const DEMO_TOKEN = "utb_demo_owner";
// Video ids with a per-run nonce: a rerun after a killed run must not hit the demo's cached
// video metadata or the shared cut cache of that killed run (the cache key has the prompt in it,
// so the same prompt would jump straight to ready and skip the building stage). Five base36
// digits (every millisecond differs) plus a six-letter per-check prefix fill the eleven-character
// video id, so there are far more values than the ten a modulo-10 digit gave (EVR-514 note 1).
const NONCE = (Date.now() % (36 ** 5)).toString(36).padStart(5, "0");
const VID_BUILD = "cccccc" + NONCE;
const VID_FAIL = "dddddd" + NONCE;
const VID_WAIT = "eeeeee" + NONCE;
const VID_MIC_REDRAW = "ffffff" + NONCE;
const VID_MIC_BUILD = "gggggg" + NONCE;
const VID_MIC_LEAVE = "hhhhhh" + NONCE;
const VID_MIC_ACQUIRE = "iiiiii" + NONCE;
const VID_MIC_DOUBLE = "jjjjjj" + NONCE;
const VID_SHARE = "kkkkkk" + NONCE;
const VID_PRESET = "llllll" + NONCE;
const problems = [];
let checks = 0;
let browser = null;
let reported = false;
let dying = false;

function fail(reason) {
  if (reason) problems.push(reason);
  if (reported) return;
  reported = true;
  console.error("FAIL (" + checks + " checks)");
  for (const p of problems) console.error(" - " + p);
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
      "the check exceeded its own " + BUDGET_MS + " ms budget; give the shell a longer timeout or raise BROWSER_BUDGET_MS",
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
    // Owner rule: the check never contacts YouTube. Card thumbnails come from i.ytimg.com; the
    // browser must fail them locally instead of loading them (the demo has no network anyway).
    // Every origin but the demo host is aborted too, so nothing can sneak out while routes race.
    const blockYouTubeThumbs = async (ctx2) => {
      await ctx2.route("**://i.ytimg.com/**", (route) => route.abort());
      await ctx2.route((url) => !url.href.startsWith(base + "/"), (route) => route.abort());
    };
    await blockYouTubeThumbs(ctx);
    const page = await ctx.newPage();
    page.setDefaultTimeout(WAIT_MS);
    page.setDefaultNavigationTimeout(WAIT_MS);
    // The mic lifecycle checks assert that a canceled recording never reaches the route.
    let speechPosts = 0;
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().includes("/v1/speech")) speechPosts += 1;
    });
    page.on("console", (m) => {
      if (m.type() === "error" && !/Failed to load resource/.test(m.text())) problems.push("console: " + m.text());
    });
    page.on("pageerror", (e) => problems.push("pageerror: " + e.message));

    await page.addInitScript(() => {
      // A fake microphone for the voice check: getUserMedia and MediaRecorder produce a small
      // webm blob, so the sheet's Speak button exercises the real POST /v1/speech route.
      // __micDeferred holds the first acquisition open (a slow permission prompt): the check
      // then cancels or taps twice before calling __resolveMic().
      const makeStream = () => ({
        getTracks: () => [
          {
            stop() {
              window.__trackStops = (window.__trackStops || 0) + 1;
            },
          },
        ],
      });
      Object.defineProperty(navigator, "mediaDevices", {
        configurable: true,
        value: {
          getUserMedia: () => {
            window.__getumCalls = (window.__getumCalls || 0) + 1;
            window.__micStreams = window.__micStreams || [];
            const s = makeStream();
            window.__micStreams.push(s);
            if (!window.__micDeferred) return Promise.resolve(s);
            return new Promise((resolve) => {
              window.__resolveMic = () => {
                window.__resolveMic = null;
                resolve(s);
              };
            });
          },
        },
      });
      class FakeRecorder {
        constructor(_stream, options) {
          window.__recorders = (window.__recorders || 0) + 1;
          this.mimeType = (options && options.mimeType) || "audio/webm";
          this.state = "inactive";
          this.handlers = {};
        }
        static isTypeSupported() {
          return true;
        }
        addEventListener(name, handler) {
          this.handlers[name] = handler;
        }
        emit() {
          if (this.handlers.dataavailable) this.handlers.dataavailable({ data: new Blob(["fake-opus-bytes"], { type: this.mimeType }) });
        }
        start() {
          this.state = "recording";
          setTimeout(() => { if (this.state === "recording") this.emit(); }, 50);
        }
        stop() {
          this.state = "inactive";
          this.emit();
          setTimeout(() => { if (this.handlers.stop) this.handlers.stop(); }, 50);
        }
      }
      window.MediaRecorder = FakeRecorder;
    });
    await page.goto(base + "/");
    await page.locator("input[name=username]").fill("owner");
    await page.locator("input[name=password]").fill("demo-password-123");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await page.waitForSelector("#nav:not([hidden])");

    // A killed earlier run can leave the demo holding a build or forcing the bad model answer;
    // reset both so a rerun starts clean.
    await api(ctx, "/demo/cut/good", { method: "POST" });
    await api(ctx, "/demo/cut/release", { method: "POST" });

    // Clear the queue (the check creates its own states; the demo seed stays for manual poking).
    const { body } = await api(ctx, "/v1/cut-requests");
    for (const r of body.requests) await api(ctx, "/v1/cut-requests/" + r.id, { method: "DELETE" });

    // Empty queue.
    await go(page, "cuts", 900);
    ok(await page.getByRole("heading", { name: "Cuts", exact: true }).isVisible(), "Cuts heading");
    ok((await page.locator("#view").textContent()).includes("No cuts yet"), "empty queue message");

    // A new cut from a pasted link opens the waiting sheet with the preset chips.
    await page.getByPlaceholder("YouTube link or video id").fill("https://youtu.be/" + VID_BUILD + "?si=x");
    await page.getByRole("button", { name: "Describe this cut" }).click();
    await page.waitForTimeout(900);
    ok(/#\/cuts\/[a-z0-9]+/.test(await page.evaluate(() => location.hash)), "a new request opens its sheet");
    const box = page.locator("textarea");
    ok(await box.isVisible(), "the waiting sheet has a description box");
    const chips = await page.locator(".chip-btn").allTextContents();
    ok(chips.join("|").includes("No filler"), "preset chips are offered: " + chips.join("|"));
    const req = await currentRequest(page, ctx);
    ok(req && req.state === "waiting", "the request is waiting for the description");

    // Voice: Speak -> Stop sends the fake recording to POST /v1/speech; the text lands in the box
    // and stays editable, and nothing is sent automatically (the request stays waiting).
    // Hold the upload for a moment: the pause is the window where an owner might tap Speak again
    // (EVR-514 note 2), and the mic must stay disabled until the text arrives.
    await page.route("**/v1/speech", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1200));
      await route.continue();
    });
    await page.getByRole("button", { name: "Speak", exact: true }).click();
    await page.waitForTimeout(300);
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await page.waitForTimeout(250);
    const uploadButton = await page.evaluate(() => {
      const b = document.querySelector(".mic");
      return { text: b.textContent, disabled: b.disabled };
    });
    ok(uploadButton.disabled && uploadButton.text.includes("Uploading"), "the mic is disabled while the recording uploads");
    const acquisitionsBefore = await page.evaluate(() => window.__getumCalls || 0);
    await page.evaluate(() => document.querySelector(".mic").click());
    ok((await page.evaluate(() => window.__getumCalls || 0)) === acquisitionsBefore, "a tap while uploading starts no second acquisition");
    await page.waitForFunction(() => document.querySelector("textarea").value.includes("Hello there"), undefined, { timeout: WAIT_MS });
    await page.unroute("**/v1/speech");
    ok((await box.inputValue()).includes("Hello there. How are you doing today?"), "the spoken text lands in the box");
    ok((await page.evaluate(() => document.activeElement && document.activeElement.tagName)) === "TEXTAREA", "the box is focused after the speech");
    const stillWaiting = await currentRequest(page, ctx);
    ok(stillWaiting && stillWaiting.state === "waiting", "the spoken text was not sent automatically");
    ok((await page.locator("#view").textContent()).includes("Looking up the video"), "the title is not known yet and says so");

    // EVR-514 note 2: a Build that fails while the recording still uploads must keep the mic
    // disabled. The old resetButton cleared it, so a Speak tap there started a second stream and
    // the first upload's finally then wiped the live recorder (no Stop control). Here the PUT is
    // failed at the page level and the upload is held, so the window is deterministic.
    await page.route("**/v1/speech", async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1800));
      await route.continue();
    });
    await page.route("**/v1/cut-requests/**", (route) =>
      route.fulfill({ status: 500, contentType: "application/json", body: '{"error":"demo failure"}' }),
    );
    await page.getByRole("button", { name: "Speak", exact: true }).click();
    await page.waitForTimeout(250);
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await page.waitForTimeout(300);
    await page.getByRole("button", { name: "Build cut" }).click();
    await page.waitForTimeout(300);
    const beforeCalls = await page.evaluate(() => window.__getumCalls || 0);
    const beforeRecorders = await page.evaluate(() => window.__recorders || 0);
    await page.evaluate(() => document.querySelector(".mic").click());
    await page.waitForTimeout(1600);
    ok((await page.evaluate(() => window.__getumCalls || 0)) === beforeCalls, "a tap after a failed Build during the upload starts no second acquisition");
    ok((await page.evaluate(() => window.__recorders || 0)) === beforeRecorders, "no recorder is left live after the upload settles");
    await page.unroute("**/v1/speech");
    await page.unroute("**/v1/cut-requests/**");

    // Build: held model keeps it building with a stage line; releasing finishes it.
    await page.evaluate(() => fetch("/demo/cut/hold", { method: "POST" }));
    // Typing must survive the sheet's poll redraw (every 2.5 s): the box keeps its text.
    await box.fill("Keep ");
    await page.waitForTimeout(3200);
    ok((await box.inputValue()) === "Keep ", "typing survives the sheet redraw");
    ok((await page.evaluate(() => document.activeElement && document.activeElement.tagName)) === "TEXTAREA", "the box keeps focus across redraws");
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
      undefined,
      { timeout: BUILD_WAIT_MS },
    );
    doc = await currentRequest(page, ctx);
    ok(doc.state === "ready", "the cut is ready");
    ok(doc.cut.parts.length >= 2, "the parts list has parts");
    ok(doc.cut.skip_ranges_ms.length >= 3, "skip ranges cover the rest");
    ok((await page.locator("#view").textContent()).includes("The TV offers this cut"), "the sheet tells the owner where the cut plays");

    // A build whose model answer never validates: the repair round fails, the sheet shows a plain reason.
    await page.evaluate(() => fetch("/demo/cut/bad", { method: "POST" }));
    await go(page, "cuts", 700);
    await page.getByPlaceholder("YouTube link or video id").fill(VID_FAIL);
    await page.getByRole("button", { name: "Describe this cut" }).click();
    await page.waitForTimeout(900);
    await page.locator("textarea").fill("Only the part with the lock operation");
    await page.getByRole("button", { name: "Build cut" }).click();
    await page.waitForFunction(
      () => document.querySelector("#view .pill.bad") !== null,
      undefined,
      { timeout: BUILD_WAIT_MS },
    );
    doc = await currentRequest(page, ctx);
    ok(doc.state === "failed" && doc.error, "the failed sheet shows a plain reason: " + (doc.error || ""));
    ok(await page.getByRole("button", { name: "Try again" }).isVisible(), "failed sheet offers Retry");
    await page.evaluate(() => fetch("/demo/cut/good", { method: "POST" }));

    // Queue order per the plan: waiting, building, ready, failed. The ready card from the first
    // build must come before the failed one, and dismissing works from the card.
    await go(page, "cuts", 800);
    const states = await page.locator(".cut .pill").allTextContents();
    ok(states[0] === "ready" && states.includes("failed"), "ready before failed: " + states.join(", "));
    ok(
      states.indexOf("ready") < states.indexOf("failed"),
      "the queue order is waiting, building, ready, failed",
    );
    const bodyText = await page.locator("#view").textContent();
    ok(bodyText.includes("from the phone") || bodyText.includes("from Web UI"), "cards show their source");
    const failedCard = page.locator(".cut").filter({ has: page.locator(".pill.bad") }).first();
    await failedCard.getByRole("button", { name: "Dismiss" }).click();
    await page.waitForTimeout(900);
    ok(!(await page.locator("#view").textContent()).includes("failed"), "the dismissed card is gone");

    // A waiting card sits first in the queue.
    await page.getByPlaceholder("YouTube link or video id").fill(VID_WAIT);
    await page.getByRole("button", { name: "Describe this cut" }).click();
    await page.waitForTimeout(900);
    await go(page, "cuts", 800);
    const last = await page.locator(".cut .pill").allTextContents();
    ok(last[0] === "waiting for your description", "a waiting card comes first: " + last.join(", "));

    // ---- saved presets (checkpoint 4): the phone saves a description as its own chip --------
    await go(page, "cuts", 700);
    await page.getByPlaceholder("YouTube link or video id").fill(VID_PRESET);
    await page.getByRole("button", { name: "Describe this cut" }).click();
    await page.waitForTimeout(900);
    await page.locator("textarea").fill("Keep only the lock test and the result.");
    await page.getByPlaceholder("Preset name").fill("Lock test only");
    await page.getByRole("button", { name: "Save as preset" }).click();
    await page.waitForTimeout(1100);
    const savedChips = await page.locator(".chip-btn").allTextContents();
    ok(savedChips.join("|").includes("Lock test only"), "the saved preset becomes a chip: " + savedChips.join("|"));
    const savedReq = await currentRequest(page, ctx);
    ok(savedReq && savedReq.state === "waiting", "saving a preset does not start the build");
    const own = await api(ctx, "/v1/cut-presets");
    ok(own.body && own.body.presets.some((p) => p.label === "Lock test only"), "the preset is stored on the server");
    await go(page, "cuts", 900);
    ok((await page.locator("#view").textContent()).includes("Saved presets"), "the queue lists saved presets");
    ok((await page.locator("#view").textContent()).includes("Lock test only"), "the saved preset is listed");
    const presetCard = page.locator(".card").filter({ hasText: "Saved presets" });
    page.once("dialog", (dialog) => dialog.accept());
    await presetCard.getByRole("button", { name: "Delete" }).click();
    await page.waitForTimeout(1100);
    ok(!(await page.locator("#view").textContent()).includes("Lock test only"), "deleting the preset removes it from the list");
    ok((await api(ctx, "/v1/cut-presets")).body.presets.length === 0, "deleting the preset clears the server list");
    for (const r of (await api(ctx, "/v1/cut-requests")).body.requests.filter((x) => x.video_id === VID_PRESET)) {
      await api(ctx, "/v1/cut-requests/" + r.id, { method: "DELETE" });
    }

    // ---- the Android Share target (checkpoint 4): the service worker and its manifest -------
    const manifest = await api(ctx, "/manifest.webmanifest");
    ok(
      manifest.body && manifest.body.share_target && manifest.body.share_target.action === "/shared" &&
        manifest.body.share_target.method === "POST",
      "the manifest declares the Share target /shared (POST)",
    );
    const worker = await ctx.request.fetch(base + "/sw.js");
    ok(worker.status() === 200, "the service worker is served");
    ok(worker.headers()["service-worker-allowed"] === "/", "the worker may control the whole site");
    const controlling = await page.evaluate(async () => {
      const reg = await navigator.serviceWorker.ready;
      return Boolean(navigator.serviceWorker.controller || reg.active);
    });
    ok(controlling, "the service worker is registered and active");
    const sharedFetch = await page.evaluate(async (url) => {
      const form = new FormData();
      form.append("url", url);
      form.append("title", "A shared video");
      form.append("text", "");
      const res = await fetch("/shared", { method: "POST", body: form });
      return res.status;
    }, "https://youtu.be/" + VID_SHARE);
    ok(sharedFetch === 200, "a shared link POST is taken by the worker and redirected (status: " + sharedFetch + ")");
    await go(page, "cuts", 900);
    await page.waitForTimeout(1200);
    ok(/#\/cuts\/[a-z0-9]+/.test(await page.evaluate(() => location.hash)), "a shared link opens its cut sheet");
    const sharedReq = await currentRequest(page, ctx);
    ok(sharedReq && sharedReq.video_id === VID_SHARE && sharedReq.state === "waiting", "the shared link starts a waiting request");
    for (const r of (await api(ctx, "/v1/cut-requests")).body.requests.filter((x) => x.video_id === VID_SHARE)) {
      await api(ctx, "/v1/cut-requests/" + r.id, { method: "DELETE" });
    }

    // ---- the mic is tied to the sheet's lifecycle (EVR-510 blocking item) -------------------
    // A waiting request opened straight from its short URL, as the QR code does.
    async function openWaiting(id) {
      await api(ctx, "/v1/videos/" + id + "/cuts", {
        method: "POST",
        data: { await_prompt: true },
        headers: { Authorization: "Bearer " + DEMO_TOKEN, "Content-Type": "application/json" },
      });
      await go(page, "cuts/" + (await newestWaiting(ctx, id)), 700);
    }
    async function newestWaiting(ctx, videoId) {
      const { body } = await api(ctx, "/v1/cut-requests");
      const row = body.requests.find((r) => r.video_id === videoId && r.state === "waiting");
      return row ? row.id : "missing";
    }

    // 1. A redraw while recording keeps the same Speak/Stop control and one recorder; the old
    // code rebuilt the button, leaving the mic live with no Stop (it only ended at the timer).
    await openWaiting(VID_MIC_REDRAW);
    await page.evaluate(() => {
      window.__trackStops = 0;
      window.__recorders = 0;
    });
    speechPosts = 0;
    const rdraw = page.locator("textarea");
    await rdraw.fill("keep the demo");
    await page.getByRole("button", { name: "Speak", exact: true }).click();
    await page.waitForTimeout(300);
    ok(await page.getByRole("button", { name: "Stop", exact: true }).isVisible(), "recording shows its Stop control");
    // Force the visible signature (the title) to change, which redraws the waiting sheet mid-recording.
    await page.route("**/v1/cuts/**", async (route) => {
      const resp = await route.fetch();
      const json = await resp.json().catch(() => null);
      if (json && json.id) json.title = "The changed title";
      await route.fulfill({ status: resp.status(), contentType: "application/json", body: JSON.stringify(json || {}) });
    });
    await page.waitForTimeout(3600);
    ok(await page.getByRole("button", { name: "Stop", exact: true }).isVisible(), "a redraw keeps the live Stop control");
    const recorders = await page.evaluate(() => window.__recorders || 0);
    ok(recorders === 1, "the redraw does not start a second recorder (started: " + recorders + ")");
    ok((await page.locator("textarea").inputValue()) === "keep the demo", "the redraw keeps the text");
    await page.waitForTimeout(1900);
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await page.waitForFunction(() => document.querySelector("textarea").value.includes("Hello there"), undefined, { timeout: WAIT_MS });
    ok(speechPosts === 1, "the still-control mic uploads once after the redraw (POSTs: " + speechPosts + ")");
    await page.unroute("**/v1/cuts/**");
    const redrawDoc = await newestWaiting(ctx, VID_MIC_REDRAW);
    ok(redrawDoc !== "missing", "the spoken text did not send the request by itself");
    for (const r of (await api(ctx, "/v1/cut-requests")).body.requests.filter((x) => x.video_id === VID_MIC_REDRAW)) {
      await api(ctx, "/v1/cut-requests/" + r.id, { method: "DELETE" });
    }

    // 2. Tapping Build while recording stops the mic without uploading; the sheet leaves waiting.
    await openWaiting(VID_MIC_BUILD);
    await page.locator("textarea").fill("keep the lock demo");
    await page.evaluate(() => {
      window.__trackStops = 0;
    });
    speechPosts = 0;
    await page.getByRole("button", { name: "Speak", exact: true }).click();
    await page.waitForTimeout(300);
    await page.getByRole("button", { name: "Build cut" }).click();
    await page.waitForTimeout(1200);
    const buildStops = await page.evaluate(() => window.__trackStops || 0);
    ok(buildStops >= 1, "Build stops the recording and releases the microphone");
    ok(speechPosts === 0, "Build while recording never uploads the audio (POSTs: " + speechPosts + ")");
    const buildReq = await newestWaiting(ctx, VID_MIC_BUILD);
    for (const r of (await api(ctx, "/v1/cut-requests")).body.requests.filter((x) => x.video_id === VID_MIC_BUILD)) {
      await api(ctx, "/v1/cut-requests/" + r.id, { method: "DELETE" });
    }
    ok(buildReq === "missing", "the Build tap moved the request out of waiting");

    // 3. Leaving the sheet (Back / hash change) stops the mic without uploading.
    await openWaiting(VID_MIC_LEAVE);
    await page.evaluate(() => {
      window.__trackStops = 0;
    });
    speechPosts = 0;
    await page.getByRole("button", { name: "Speak", exact: true }).click();
    await page.waitForTimeout(300);
    await go(page, "cuts", 900);
    await page.waitForTimeout(1200);
    const leaveStops = await page.evaluate(() => window.__trackStops || 0);
    ok(leaveStops >= 1, "leaving the sheet stops the recording and releases the microphone");
    ok(speechPosts === 0, "leaving the sheet never uploads the audio (POSTs: " + speechPosts + ")");
    for (const r of (await api(ctx, "/v1/cut-requests")).body.requests.filter((x) => x.video_id === VID_MIC_LEAVE)) {
      await api(ctx, "/v1/cut-requests/" + r.id, { method: "DELETE" });
    }

    // ---- the acquisition window (EVR-512 blocking item) --------------------------------
    // 4. Build while getUserMedia is still pending: the late stream is released, not recorded.
    await openWaiting(VID_MIC_ACQUIRE);
    await page.locator("textarea").fill("keep the demo");
    await page.evaluate(() => {
      window.__micDeferred = true;
      window.__getumCalls = 0;
      window.__micStreams = [];
      window.__trackStops = 0;
      window.__recorders = 0;
    });
    speechPosts = 0;
    await page.getByRole("button", { name: "Speak", exact: true }).click();
    await page.waitForTimeout(200);
    ok(await page.locator(".mic").isDisabled(), "the mic is disabled while the permission prompt is open");
    await page.getByRole("button", { name: "Build cut" }).click();
    await page.waitForTimeout(700);
    ok((await page.evaluate(() => window.__getumCalls || 0)) === 1, "one acquisition is in flight");
    await page.evaluate(() => window.__resolveMic && window.__resolveMic());
    await page.waitForTimeout(900);
    ok((await page.evaluate(() => window.__recorders || 0)) === 0, "an acquisition cancelled by Build never starts a recorder");
    ok((await page.evaluate(() => window.__trackStops || 0)) >= 1, "the late stream from a cancelled acquisition is stopped");
    ok(speechPosts === 0, "an acquisition cancelled by Build never uploads (POSTs: " + speechPosts + ")");
    for (const r of (await api(ctx, "/v1/cut-requests")).body.requests.filter((x) => x.video_id === VID_MIC_ACQUIRE)) {
      await api(ctx, "/v1/cut-requests/" + r.id, { method: "DELETE" });
    }

    // 5. Double-tapping Speak while the prompt is open starts exactly one acquisition and one
    // recorder; a late second stream never appears. Leaving then stops it without uploading.
    await openWaiting(VID_MIC_DOUBLE);
    await page.evaluate(() => {
      window.__micDeferred = true;
      window.__getumCalls = 0;
      window.__micStreams = [];
      window.__trackStops = 0;
      window.__recorders = 0;
    });
    speechPosts = 0;
    await page.getByRole("button", { name: "Speak", exact: true }).click();
    await page.evaluate(() => {
      const b = document.querySelector(".mic");
      b.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await page.waitForTimeout(250);
    ok((await page.evaluate(() => window.__getumCalls || 0)) === 1, "a second tap does not start a second acquisition");
    ok((await page.evaluate(() => (window.__micStreams || []).length)) === 1, "a second tap acquires no second stream");
    await page.evaluate(() => window.__resolveMic && window.__resolveMic());
    await page.waitForTimeout(700);
    ok((await page.evaluate(() => window.__recorders || 0)) === 1, "the deferred acquisition starts one recorder");
    ok(await page.getByRole("button", { name: "Stop", exact: true }).isVisible(), "the deferred acquisition shows a live Stop control");
    await go(page, "cuts", 900);
    await page.waitForTimeout(1000);
    ok(speechPosts === 0, "leaving with the deferred mic never uploads (POSTs: " + speechPosts + ")");
    ok((await page.evaluate(() => window.__trackStops || 0)) >= 1, "leaving after the deferred acquisition stops its stream");
    await page.evaluate(() => {
      window.__micDeferred = false;
    });
    for (const r of (await api(ctx, "/v1/cut-requests")).body.requests.filter((x) => x.video_id === VID_MIC_DOUBLE)) {
      await api(ctx, "/v1/cut-requests/" + r.id, { method: "DELETE" });
    }

    // No sideways scrolling at 360 px.
    const narrow = await browser.newContext({ viewport: { width: 360, height: 740 } });
    await blockYouTubeThumbs(narrow);
    const npage = await narrow.newPage();
    npage.setDefaultTimeout(WAIT_MS);
    npage.setDefaultNavigationTimeout(WAIT_MS);
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

    if (problems.length) fail();
    else console.log("OK (" + checks + " checks)");
  } catch (e) {
    fail("script error: " + (e && e.message ? e.message : String(e)));
  } finally {
    clearTimeout(budget);
    if (browser) await browser.close().catch(() => {});
  }
})();