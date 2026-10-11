import { describe, expect, it } from "vitest";
import { ticksAt, trackPct } from "./slider";

describe("slider geometry", () => {
  it("places values linearly and clamps", () => {
    expect(trackPct(1, 1, 50)).toBe(0);
    expect(trackPct(50, 1, 50)).toBe(100);
    expect(trackPct(99, 1, 50)).toBe(100);
    expect(trackPct(5, 5, 5)).toBe(0);
    expect(trackPct(Number.NaN, 0, 10)).toBe(0);
  });

  it("puts 10x at ~18% of a 1-50x track, not at a third (UX audit)", () => {
    const t = ticksAt([1, 10, 25, 50], 1, 50);
    expect(t.map((x) => Math.round(x.pct))).toEqual([0, 18, 49, 100]);
  });

  it("drops ticks outside the range", () => {
    expect(ticksAt([1, 10, 25, 50], 1, 20).map((x) => x.value)).toEqual([1, 10]);
  });
});
