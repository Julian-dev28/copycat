import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  applyPnlMode,
  DEFAULT_PNL_MODE,
  PNL_BOOT_SCRIPT,
  PNL_GLYPH,
  PNL_MODE_STORAGE_KEY,
  PNL_MODES,
  pnlClass,
  pnlTone,
  readPnlMode,
  writePnlMode,
  type PnlMode,
} from "./pnlMode";
import { parseTokens, resolvePnl } from "./tokens";

const css = readFileSync(path.resolve(import.meta.dirname, "../../app/globals.css"), "utf8");
const tokens = parseTokens(css);

/** What each mode must resolve --up / --down to, per theme (DESIGN.md 3.3). */
const EXPECTED: Record<PnlMode, Record<"light" | "dark", { up: string; down: string }>> = {
  standard: { dark: { up: "#4fbf8f", down: "#ef5a68" }, light: { up: "#0b7347", down: "#c0263a" } },
  colorblind: { dark: { up: "#4cb0ff", down: "#ff9a2e" }, light: { up: "#0a6fc2", down: "#a84f00" } },
  "east-asia": { dark: { up: "#ef5a68", down: "#4fbf8f" }, light: { up: "#c0263a", down: "#0b7347" } },
};

afterEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.pnl;
});

describe("PnL color modes: CSS", () => {
  for (const mode of PNL_MODES) {
    for (const theme of ["light", "dark"] as const) {
      it(`${mode} / ${theme} maps --up and --down`, () => {
        expect(resolvePnl(tokens, theme, mode)).toEqual(EXPECTED[mode][theme]);
      });
    }
  }

  it("never remaps --danger: an error stays red in every mode", () => {
    for (const block of Object.values(tokens.modes)) expect(block.danger).toBeUndefined();
  });

  it("has a CSS block for every non-default mode", () => {
    expect(Object.keys(tokens.modes).sort()).toEqual(PNL_MODES.filter((m) => m !== DEFAULT_PNL_MODE).sort());
  });
});

describe("PnL color modes: classes", () => {
  it("gives the same mode-independent classes, so components cannot pick the wrong mode", () => {
    for (const mode of PNL_MODES) {
      applyPnlMode(mode);
      expect(pnlClass(12.5)).toBe("text-up");
      expect(pnlClass(-0.01)).toBe("text-down");
      expect(pnlClass(0)).toBe("text-muted");
    }
  });

  it("treats null, NaN and zero as flat", () => {
    expect(pnlTone(null)).toBe("flat");
    expect(pnlTone(undefined)).toBe("flat");
    expect(pnlTone(Number.NaN)).toBe("flat");
    expect(pnlTone(0)).toBe("flat");
  });

  it("always pairs color with a glyph for up and down", () => {
    expect(PNL_GLYPH.up).toBe("▲");
    expect(PNL_GLYPH.down).toBe("▼");
  });
});

describe("PnL color modes: storage", () => {
  it("defaults to standard", () => {
    expect(readPnlMode()).toBe("standard");
  });

  it("persists and applies a mode on <html>", () => {
    writePnlMode("colorblind");
    expect(localStorage.getItem(PNL_MODE_STORAGE_KEY)).toBe("colorblind");
    expect(document.documentElement.dataset.pnl).toBe("colorblind");
    expect(readPnlMode()).toBe("colorblind");
  });

  it("ignores garbage and a throwing storage", () => {
    localStorage.setItem(PNL_MODE_STORAGE_KEY, "rainbow");
    expect(readPnlMode()).toBe("standard");
    const throwing = { getItem: () => { throw new Error("blocked"); } };
    expect(readPnlMode(throwing)).toBe("standard");
  });

  it("boot script applies the stored mode before paint, and falls back on garbage", () => {
    localStorage.setItem(PNL_MODE_STORAGE_KEY, "east-asia");
    new Function(PNL_BOOT_SCRIPT)();
    expect(document.documentElement.dataset.pnl).toBe("east-asia");
    localStorage.setItem(PNL_MODE_STORAGE_KEY, "x");
    new Function(PNL_BOOT_SCRIPT)();
    expect(document.documentElement.dataset.pnl).toBe("standard");
  });
});
