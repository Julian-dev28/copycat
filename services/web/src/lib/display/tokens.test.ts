import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { contrast, mix } from "./contrast";
import { PNL_MODES } from "./pnlMode";
import { parseTokens, resolve, type Theme } from "./tokens";

const css = readFileSync(path.resolve(import.meta.dirname, "../../app/globals.css"), "utf8");
const t = parseTokens(css);
const THEMES: Theme[] = ["light", "dark"];
const AA = 4.5;

/** Text tokens x the backgrounds they sit on (DESIGN.md 3.1 / 3.2). */
const TEXT = ["fg", "fg-soft", "muted", "accent", "warn", "danger", "ok"];
const BGS = ["bg", "surface", "surface-2"];

describe("contrast math", () => {
  it("matches known WCAG values", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 5);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
    expect(mix("#ffffff", 50, "#000000")).toBe("#808080");
  });
});

describe("palette is exactly DESIGN.md", () => {
  it.each([
    ["dark", "bg", "#08080a"], ["dark", "surface", "#101012"], ["dark", "surface-2", "#17171a"], ["dark", "surface-3", "#1e1e22"],
    ["dark", "fg", "#ececee"], ["dark", "muted", "#96969f"], ["dark", "accent", "#7aa2ff"], ["dark", "brand", "#ff7a1a"],
    ["dark", "warn", "#f2b544"], ["light", "bg", "#f7f7f8"], ["light", "accent", "#2d5bd8"], ["light", "warn", "#8f5a00"],
    ["light", "muted", "#5d5d66"], ["light", "brand", "#b04a08"],
  ] as const)("%s --%s = %s", (theme, name, hex) => {
    expect(resolve(t, theme, name)).toBe(hex);
  });

  it("dark soft PnL tints match the documented hexes within rounding", () => {
    expect(resolve(t, "dark", "up-soft")).toBe("#192924");
    expect(resolve(t, "dark", "down-soft")).toBe("#2f1a1e");
  });
});

describe("WCAG AA (4.5:1) for every text token", () => {
  for (const theme of THEMES) {
    for (const fg of TEXT) {
      for (const bg of BGS) {
        it(`${theme}: --${fg} on --${bg}`, () => {
          expect(contrast(resolve(t, theme, fg), resolve(t, theme, bg))).toBeGreaterThanOrEqual(AA);
        });
      }
    }
    it(`${theme}: accent-fg on accent (primary button)`, () => {
      expect(contrast(resolve(t, theme, "accent-fg"), resolve(t, theme, "accent"))).toBeGreaterThanOrEqual(AA);
    });
    it(`${theme}: accent on accent-soft (selected pill)`, () => {
      expect(contrast(resolve(t, theme, "accent"), resolve(t, theme, "accent-soft"))).toBeGreaterThanOrEqual(AA);
    });
    it(`${theme}: warn on warn-soft (demo strip, banners)`, () => {
      expect(contrast(resolve(t, theme, "warn"), resolve(t, theme, "warn-soft"))).toBeGreaterThanOrEqual(AA);
    });
    it(`${theme}: muted on surface-3 (hover row)`, () => {
      expect(contrast(resolve(t, theme, "muted"), resolve(t, theme, "surface-3"))).toBeGreaterThanOrEqual(AA);
    });
    // Notice bodies, the demo and stale-build strips and the ticket's leverage
    // alert set --muted text on a tinted well. Dark --muted was #8d8d96, 4.46:1
    // on --warn-soft, so the Scout axe gate had to exclude color-contrast.
    for (const bg of ["warn-soft", "danger-soft", "accent-soft", "up-soft", "down-soft"]) {
      it(`${theme}: muted on --${bg} (Notice body, strips, badge wells)`, () => {
        expect(contrast(resolve(t, theme, "muted"), resolve(t, theme, bg))).toBeGreaterThanOrEqual(AA);
      });
    }
    for (const mode of PNL_MODES) {
      it(`${theme} / ${mode}: up and down on every surface and on their soft tint`, () => {
        for (const k of ["up", "down"]) {
          const c = resolve(t, theme, k, mode);
          for (const bg of [...BGS, `${k}-soft`]) expect(contrast(c, resolve(t, theme, bg, mode)), `${k} on ${bg}`).toBeGreaterThanOrEqual(AA);
        }
      });
    }
  }

  it("--faint is decorative: below AA by design, so it must never be used as text", () => {
    expect(contrast(resolve(t, "dark", "faint"), resolve(t, "dark", "bg"))).toBeLessThan(AA);
  });
});
