import { describe, expect, it } from "vitest";
import { applyDirection, effectiveDirection, invertSeries, ourSide } from "./direction";
import { localPreview } from "./preview";

const prev = localPreview({
  allocationUsd: 1_000, mode: "target", targetLeverage: 2, marginMode: "isolated", smallMode: "skip", leaderEquityUsd: 10_000,
  positions: [{ coin: "BTC", side: "long", notional_usd: 6_000, leverage: 5 }, { coin: "ETH", side: "short", notional_usd: 4_000, leverage: 5 }],
});

describe("counter preview inversion", () => {
  it("counter flips our side on every copy and keeps their side", () => {
    const p = applyDirection(prev, "counter");
    expect(p.copies.map((c) => [c.side, c.ourSide])).toEqual([["long", "short"], ["short", "long"]]);
    expect(p.direction).toBe("counter");
  });
  it("sizes, leverage and margin are direction-blind", () => {
    const c = applyDirection(prev, "counter");
    const k = applyDirection(prev, "copy");
    expect(c.copies.map((x) => x.notionalUsd)).toEqual(k.copies.map((x) => x.notionalUsd));
    expect(c.marginUsd).toBe(k.marginUsd);
    expect(k.copies.every((x) => x.ourSide === x.side)).toBe(true);
  });
  it("ourSide and the effective direction", () => {
    expect(ourSide("long", "counter")).toBe("short");
    expect(ourSide("short", "copy")).toBe("short");
    expect(effectiveDirection(null, "counter")).toBe("counter");
    expect(effectiveDirection("copy", "counter")).toBe("copy");
    expect(effectiveDirection(undefined, undefined)).toBe("copy");
  });
});

describe("chart overlay inversion", () => {
  it("negates each step's return, compounding from the same start", () => {
    const out = invertSeries([{ t_ms: 1, value: 100 }, { t_ms: 2, value: 110 }, { t_ms: 3, value: 99 }]);
    expect(out[0].value).toBe(100);
    expect(out[1].value).toBeCloseTo(90);
    expect(out[2].value).toBeCloseTo(99); // -10% for him -> +10% for us: 90 x 1.1
  });
  it("never goes below zero and stays there", () => {
    const out = invertSeries([{ t_ms: 1, value: 100 }, { t_ms: 2, value: 250 }, { t_ms: 3, value: 200 }]);
    expect(out[1].value).toBe(0);
    expect(out[2].value).toBe(0);
  });
  it("sorts by time and handles empty", () => {
    expect(invertSeries([])).toEqual([]);
    expect(invertSeries([{ t_ms: 2, value: 50 }, { t_ms: 1, value: 100 }]).map((p) => p.t_ms)).toEqual([1, 2]);
  });
});
