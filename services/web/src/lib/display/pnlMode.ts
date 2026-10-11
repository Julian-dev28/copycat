/**
 * PnL color mode (DESIGN.md 3.3): a per-browser display setting.
 *
 * The mode lives in localStorage and is applied as `data-pnl` on <html>.
 * globals.css remaps --up / --down per mode, so components never branch on
 * the mode: they use `text-up` / `text-down` (or <Pnl>, which also adds a
 * sign and an arrow so color is never the only signal).
 */

export const PNL_MODES = ["standard", "colorblind", "east-asia"] as const;
export type PnlMode = (typeof PNL_MODES)[number];
export const DEFAULT_PNL_MODE: PnlMode = "standard";
export const PNL_MODE_STORAGE_KEY = "copycat.pnlMode";
/** Fired on window after a change in this tab (the storage event covers other tabs). */
export const PNL_MODE_EVENT = "copycat:pnl-mode";

export const PNL_MODE_LABELS: Record<PnlMode, { label: string; hint: string }> = {
  standard: { label: "Green up, red down", hint: "Western convention" },
  colorblind: { label: "Blue up, orange down", hint: "Easier with red-green color blindness" },
  "east-asia": { label: "Red up, green down", hint: "China, Taiwan, Japan convention" },
};

export function isPnlMode(v: unknown): v is PnlMode {
  return typeof v === "string" && (PNL_MODES as readonly string[]).includes(v);
}

export function parsePnlMode(v: unknown): PnlMode {
  return isPnlMode(v) ? v : DEFAULT_PNL_MODE;
}

/** Storage can be missing or throw (private mode, blocked site data): fall back to the default. */
export function readPnlMode(storage: Pick<Storage, "getItem"> | null | undefined = safeStorage()): PnlMode {
  try {
    return parsePnlMode(storage?.getItem(PNL_MODE_STORAGE_KEY));
  } catch {
    return DEFAULT_PNL_MODE;
  }
}

export function applyPnlMode(mode: PnlMode, root: HTMLElement | null = typeof document === "undefined" ? null : document.documentElement): void {
  if (root) root.dataset.pnl = mode;
}

export function writePnlMode(mode: PnlMode, storage: Pick<Storage, "setItem"> | null | undefined = safeStorage()): void {
  try {
    storage?.setItem(PNL_MODE_STORAGE_KEY, mode);
  } catch {
    // storage blocked: the mode still applies for this page view
  }
  applyPnlMode(mode);
  if (typeof window !== "undefined") window.dispatchEvent(new Event(PNL_MODE_EVENT));
}

function safeStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

/**
 * Inline script for <head>: sets data-pnl before first paint so a colorblind
 * user never sees a flash of green/red. Kept tiny and dependency-free.
 */
export const PNL_BOOT_SCRIPT = `try{var m=localStorage.getItem(${JSON.stringify(PNL_MODE_STORAGE_KEY)});document.documentElement.dataset.pnl=${JSON.stringify(PNL_MODES)}.indexOf(m)>-1?m:${JSON.stringify(DEFAULT_PNL_MODE)}}catch(e){document.documentElement.dataset.pnl=${JSON.stringify(DEFAULT_PNL_MODE)}}`;

export type PnlTone = "up" | "down" | "flat";

/** Sign of a money change. null/NaN/0 are flat (no color). */
export function pnlTone(value: number | null | undefined): PnlTone {
  if (value == null || !Number.isFinite(value) || value === 0) return "flat";
  return value > 0 ? "up" : "down";
}

/**
 * The text class for a money change. Identical in every mode on purpose:
 * the mode is applied by CSS variables, so a component can never pick the
 * wrong color for the user's mode.
 */
export const PNL_TEXT_CLASS: Record<PnlTone, string> = { up: "text-up", down: "text-down", flat: "text-muted" };
export const PNL_BG_CLASS: Record<PnlTone, string> = { up: "bg-up-soft", down: "bg-down-soft", flat: "bg-surface-2" };
/** Non-color signal that always travels with the color (DESIGN 3.3). */
export const PNL_GLYPH: Record<PnlTone, string> = { up: "▲", down: "▼", flat: "" };

export function pnlClass(value: number | null | undefined): string {
  return PNL_TEXT_CLASS[pnlTone(value)];
}
