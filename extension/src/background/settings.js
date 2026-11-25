/**
 * The local switches and timing values, in the same defaults and keys as the TV's UtubotSettings. A setup's defaults
 * fill them when they are present; missing keys keep the current value.
 */

export const DEFAULT_WAIT_MS = 1200;
export const MAX_WAIT_MS = 3000;
export const NETWORK_SLACK_MS = 500;
export const DEFAULT_PANEL_DELAY_MS = 1800;
export const PANEL_DELAY_CHOICES_MS = [1000, 1800, 3000, 5000];

export const DEFAULT_SETTINGS = {
  assess: true,
  mark_only: false,
  answer_in_menu: true,
  summary_panel: false,
  auto_captions: true,
  auto_cuts: false,
  wait_ms: DEFAULT_WAIT_MS,
  panel_delay_ms: DEFAULT_PANEL_DELAY_MS,
};

export function readSettings(storage) {
  return storage.local.get(["utubot.settings"]).then((values) => ({ ...DEFAULT_SETTINGS, ...(values?.["utubot.settings"] ?? {}) }));
}

export async function writeSettings(storage, values) {
  const current = await readSettings(storage);
  const next = { ...current };

  for (const [key, value] of Object.entries(values ?? {})) {
    if (key === "panel_delay_ms") {
      if (PANEL_DELAY_CHOICES_MS.includes(Number(value))) {
        next[key] = Number(value);
      }
    } else if (typeof DEFAULT_SETTINGS[key] === "boolean") {
      if (typeof value === "boolean") {
        next[key] = value;
      }
    } else if (key === "wait_ms") {
      const wait = Number(value);
      if (Number.isFinite(wait)) {
        next[key] = Math.max(0, Math.min(MAX_WAIT_MS, wait));
      }
    }
  }

  await storage.local.set({ "utubot.settings": next });
  return next;
}

export async function applySetupDefaults(storage, defaults) {
  const stored = await storage.local.get(["utubot.settings"]);
  const current = { ...DEFAULT_SETTINGS, ...(stored?.["utubot.settings"] ?? {}) };

  for (const key of ["assess", "mark_only", "answer_in_menu", "summary_panel", "auto_captions"]) {
    if (typeof defaults?.[key] === "boolean") {
      current[key] = defaults[key];
    }
  }

  await storage.local.set({ "utubot.settings": current });
  return current;
}
