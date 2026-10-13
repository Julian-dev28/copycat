import { describe, expect, it } from "vitest";
import { scrollProgressPct } from "./scrollProgress";

describe("scrollProgressPct", () => {
  it("is 0 at the top, 100 at the bottom, clamped in between", () => {
    expect(scrollProgressPct(0, 3000, 1000)).toBe(0);
    expect(scrollProgressPct(1000, 3000, 1000)).toBe(50);
    expect(scrollProgressPct(2000, 3000, 1000)).toBe(100);
    expect(scrollProgressPct(5000, 3000, 1000)).toBe(100);
    expect(scrollProgressPct(-10, 3000, 1000)).toBe(0);
  });
  it("is 0 when the page does not scroll", () => {
    expect(scrollProgressPct(0, 800, 1000)).toBe(0);
    expect(scrollProgressPct(0, 1000, 1000)).toBe(0);
    expect(scrollProgressPct(0, Number.NaN, 1000)).toBe(0);
  });
});
