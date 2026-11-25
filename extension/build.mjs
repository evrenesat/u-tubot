/**
 * build.mjs: builds one manifest variant of the extension into `dist/<variant>/`.
 *
 *   node build.mjs --variant firefox-unlisted
 *
 * Variants (decision 25 of ai/BROWSER_EXTENSION_PLAN.md): firefox-unlisted, firefox-listed,
 * firefox-test, chromium, chromium-test. The manifest is `manifest.base.json` merged with the
 * variant's keys; the test variant replaces the two YouTube origins with the fixture page's
 * loopback origin and turns the fixture-site override on. esbuild bundles the background and the
 * content script unminified; page sources, styles, locales and icons are copied.
 */
import { build } from "esbuild";
import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const variants = ["firefox-unlisted", "firefox-listed", "firefox-test", "chromium", "chromium-test"];

const YOUTUBE_MATCHES = ["https://www.youtube.com/*", "https://m.youtube.com/*"];
const FIXTURE_MATCHES = ["http://127.0.0.1/*"];
const MOCK_ORIGINS = ["http://127.0.0.1/*", "http://127.0.0.2/*", "http://127.0.0.3/*"];
const UPDATE_URL = "https://raw.githubusercontent.com/evrenesat/u-tubot/extension-updates/updates.json";

export function parseVariant(argv) {
  const flag = argv.indexOf("--variant");
  const value = flag >= 0 ? argv[flag + 1] : null;

  if (!value || !variants.includes(value)) {
    throw new Error(`usage: node build.mjs --variant <${variants.join("|")}>`);
  }

  return value;
}

function readJson(path) {
  return JSON.parse(readFileSync(join(root, path), "utf8"));
}

function deepMerge(base, extra) {
  const merged = { ...base };

  for (const [key, value] of Object.entries(extra)) {
    if (Array.isArray(value) && Array.isArray(merged[key])) {
      merged[key] = value;
    } else if (value && typeof value === "object" && !Array.isArray(value) && merged[key] && typeof merged[key] === "object") {
      merged[key] = deepMerge(merged[key], value);
    } else {
      merged[key] = value;
    }
  }

  return merged;
}

function applyTestSettings(manifest, variant) {
  const optional = new Set([...(manifest.optional_host_permissions ?? []), ...YOUTUBE_MATCHES]);
  const required = variant === "chromium-test" ? [...MOCK_ORIGINS] : [...FIXTURE_MATCHES];

  return {
    ...manifest,
    host_permissions: [...required],
    optional_host_permissions: [...optional],
    content_scripts: (manifest.content_scripts ?? []).map((script) => ({ ...script, matches: [...FIXTURE_MATCHES] })),
  };
}

export function variantManifest(variant) {
  const base = readJson("manifest.base.json");
  const perBrowser = readJson(variant.startsWith("firefox") ? "manifest.firefox.json" : "manifest.chromium.json");
  let manifest = deepMerge(base, perBrowser);

  manifest.version = readFileSync(join(root, "version"), "utf8").trim();

  if (variant === "firefox-unlisted") {
    manifest.browser_specific_settings.gecko.update_url = UPDATE_URL;
  }

  if (variant === "firefox-listed") {
    delete manifest.browser_specific_settings.gecko.update_url;
  }

  if (variant.endsWith("-test")) {
    manifest = applyTestSettings(manifest, variant);
  }

  return manifest;
}

async function bundle(variant, outDir) {
  const isFirefox = variant.startsWith("firefox");
  const isTest = variant.endsWith("-test");
  const entries = {
    background: join(root, "src/background/main.js"),
    content: join(root, "src/content/main.js"),
  };
  const pageEntries = {};

  for (const entry of ["options.js", "popup.js", "processed.js"]) {
    if (existsSync(join(root, "src/pages", entry))) {
      pageEntries[`pages/${entry.replace(/\.js$/, "")}`] = join(root, "src/pages", entry);
    }
  }

  const common = {
    outdir: outDir,
    bundle: true,
    target: isFirefox ? "firefox140" : "chrome121",
    minify: false,
    sourcemap: false,
    legalComments: "none",
    logLevel: "warning",
    define: { __UTUBOT_TEST__: isTest ? "true" : "false" },
  };

  await build({ ...common, entryPoints: entries, format: "iife" });

  if (Object.keys(pageEntries).length > 0) {
    await build({ ...common, entryPoints: pageEntries, format: "esm" });
  }
}

function copyStatic(outDir) {
  for (const [sourceFolder, targetFolder] of [
    ["assets", "assets"],
    ["_locales", "_locales"],
    ["src/pages", "pages"],
    ["src/content/ui", "content/ui"],
  ]) {
    const source = join(root, sourceFolder);

    if (existsSync(source)) {
      mkdirSync(join(outDir, targetFolder), { recursive: true });
      cpSync(source, join(outDir, targetFolder), { recursive: true, filter: (path) => !path.endsWith(".js") });
    }
  }
}

export async function buildVariant(variant) {
  const outDir = join(root, "dist", variant);

  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });

  writeFileSync(join(outDir, "manifest.json"), JSON.stringify(variantManifest(variant), null, 2) + "\n");
  await bundle(variant, outDir);
  copyStatic(outDir);
  console.log(`built ${variant} -> ${outDir}`);
  return outDir;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await buildVariant(parseVariant(process.argv.slice(2)));
}