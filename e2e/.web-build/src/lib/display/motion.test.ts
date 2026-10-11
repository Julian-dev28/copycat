import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { DURATION, exitDuration, FLASH_THROTTLE_MS, motionDuration, nextFlash, prefersReducedMotion, REDUCED_MOTION_QUERY } from "./motion";

const css = readFileSync(path.resolve(import.meta.dirname, "../../app/globals.css"), "utf8");
const reducedBlock = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));

describe("reduced motion", () => {
  it("reads the OS query", () => {
    const mm = (q: string) => ({ matches: q === REDUCED_MOTION_QUERY });
    expect(prefersReducedMotion(mm)).toBe(true);
    expect(prefersReducedMotion(() => ({ matches: false }))).toBe(false);
    expect(prefersReducedMotion(undefined)).toBe(false);
    expect(prefersReducedMotion(() => { throw new Error("no matchMedia"); })).toBe(false);
  });

  it("drops movement to 0 and keeps short opacity fades", () => {
    expect(motionDuration(DURATION.slow, true)).toBe(0);
    expect(motionDuration(DURATION.slow, true, "fade")).toBe(80);
    expect(motionDuration(DURATION.slow, false)).toBe(320);
  });

  it("globals.css keeps the 0.01ms floor and turns off translate, flash fade and view transitions", () => {
    expect(reducedBlock).toContain("transition-duration: 0.01ms !important");
    expect(reducedBlock).toContain("animation-duration: 0.01ms !important");
    expect(reducedBlock).toMatch(/\[data-enter\]\s*\{\s*transform: none !important/);
    expect(reducedBlock).toMatch(/\.animate-flash-up\s*\{\s*animation: none !important;\s*box-shadow: inset 2px 0 0 var\(--up\)/);
    expect(reducedBlock).toContain("::view-transition-new(*)");
    expect(reducedBlock).toContain("scroll-behavior: auto !important");
  });

  it("CSS motion tokens match the JS durations", () => {
    for (const [k, ms] of Object.entries(DURATION)) expect(css).toContain(`--dur-${k}: ${ms}ms`);
    expect(css).toContain("--ease-out: cubic-bezier(0.16, 1, 0.3, 1)");
  });

  it("exits run at 0.75x", () => {
    expect(exitDuration(320)).toBe(240);
  });
});

describe("value-change flash", () => {
  it("flashes in the direction of the change", () => {
    expect(nextFlash(1, 2, null, 0)).toBe("up");
    expect(nextFlash(2, 1, null, 0)).toBe("down");
  });

  it("does not flash on first value, no change, or non-finite", () => {
    expect(nextFlash(undefined, 2, null, 0)).toBeNull();
    expect(nextFlash(2, 2, null, 0)).toBeNull();
    expect(nextFlash(2, Number.NaN, null, 0)).toBeNull();
  });

  it("throttles to one flash per cell per 2s", () => {
    expect(nextFlash(1, 2, 1000, 1000 + FLASH_THROTTLE_MS - 1)).toBeNull();
    expect(nextFlash(1, 2, 1000, 1000 + FLASH_THROTTLE_MS)).toBe("up");
  });
});
