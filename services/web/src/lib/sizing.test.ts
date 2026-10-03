import { describe, expect, it } from "vitest";
import {
  applyMinOrderRule,
  clamp,
  dailyLossLimitToStored,
  previewNotionalUsd,
  resolveEffectiveLeverage,
  storedToDailyLossMagnitude,
} from "./sizing";

describe("resolveEffectiveLeverage", () => {
  it("max mode returns the leverage cap regardless of fixed leverage", () => {
    expect(resolveEffectiveLeverage({ leverageMode: "max", fixedLeverage: 3, maxLeverageCap: 50 })).toBe(50);
  });

  it("fixed mode returns the fixed leverage, clamped to the cap", () => {
    expect(resolveEffectiveLeverage({ leverageMode: "fixed", fixedLeverage: 20, maxLeverageCap: 50 })).toBe(20);
    expect(resolveEffectiveLeverage({ leverageMode: "fixed", fixedLeverage: 999, maxLeverageCap: 50 })).toBe(50);
    expect(resolveEffectiveLeverage({ leverageMode: "fixed", fixedLeverage: 0, maxLeverageCap: 50 })).toBe(1);
  });

  it("match mode mirrors the leader's leverage, rounded and clamped", () => {
    expect(
      resolveEffectiveLeverage({ leverageMode: "match", fixedLeverage: 1, maxLeverageCap: 50, leaderLeverage: 12.6 }),
    ).toBe(13);
  });

  it("match mode falls back to the cap when the leader's leverage is unknown", () => {
    expect(
      resolveEffectiveLeverage({ leverageMode: "match", fixedLeverage: 1, maxLeverageCap: 50, leaderLeverage: null }),
    ).toBe(50);
  });
});

describe("previewNotionalUsd", () => {
  const base = { fixedMarginUsd: 5, fixedNotionalUsd: 50, sizeMultiplier: 1, sleeveFrac: 1, minOrderBump: true };

  it("fixed_margin: notional = margin * leverage", () => {
    expect(previewNotionalUsd({ ...base, sizingMode: "fixed_margin" }, 20)).toBe(100);
  });

  it("fixed_notional: notional is flat, independent of leverage", () => {
    expect(previewNotionalUsd({ ...base, sizingMode: "fixed_notional" }, 50)).toBe(50);
    expect(previewNotionalUsd({ ...base, sizingMode: "fixed_notional" }, 1)).toBe(50);
  });

  it("proportional: his exposure / his equity * our allocation * size_multiplier", () => {
    // leader has $10k notional on $5k equity (2x exposure); we allocate our
    // whole $1k equity (sleeve_frac=1) at 1x size_multiplier.
    const result = previewNotionalUsd(
      { ...base, sizingMode: "proportional" },
      20,
      { leaderNotionalUsd: 10_000, leaderEquityUsd: 5_000, ourEquityUsd: 1_000 },
    );
    expect(result).toBe(2 * 1 * 1_000);
  });

  it("proportional: scales with sleeve_frac and size_multiplier", () => {
    const result = previewNotionalUsd(
      { ...base, sizingMode: "proportional", sleeveFrac: 0.5, sizeMultiplier: 2 },
      20,
      { leaderNotionalUsd: 10_000, leaderEquityUsd: 5_000, ourEquityUsd: 1_000 },
    );
    expect(result).toBe(2 * (0.5 * 1_000) * 2);
  });

  it("proportional: zero leader equity returns 0, not Infinity/NaN", () => {
    const result = previewNotionalUsd(
      { ...base, sizingMode: "proportional" },
      20,
      { leaderNotionalUsd: 10_000, leaderEquityUsd: 0, ourEquityUsd: 1_000 },
    );
    expect(result).toBe(0);
  });

  it("proportional: missing inputs return 0", () => {
    expect(previewNotionalUsd({ ...base, sizingMode: "proportional" }, 20)).toBe(0);
  });
});

describe("applyMinOrderRule", () => {
  it("passes through notionals at or above the HL minimum unchanged", () => {
    expect(applyMinOrderRule(20, true)).toEqual({ notionalUsd: 20, skipped: false, bumped: false });
  });

  it("bumps up to the minimum when >= 25% of it and bumping is enabled", () => {
    // 25% of 10.5 = 2.625
    expect(applyMinOrderRule(3, true)).toEqual({ notionalUsd: 10.5, skipped: false, bumped: true });
  });

  it("skips when below 25% of the minimum even with bumping enabled", () => {
    expect(applyMinOrderRule(1, true)).toEqual({ notionalUsd: 0, skipped: true, bumped: false });
  });

  it("skips anything below the minimum when bumping is disabled", () => {
    expect(applyMinOrderRule(9, false)).toEqual({ notionalUsd: 0, skipped: true, bumped: false });
  });
});

describe("daily loss limit sign conversion", () => {
  it("converts a positive magnitude to a non-positive stored value", () => {
    expect(dailyLossLimitToStored(500)).toBe(-500);
  });

  it("treats 0 or negative input as off (stored 0)", () => {
    expect(dailyLossLimitToStored(0)).toBe(0);
    expect(dailyLossLimitToStored(-10)).toBe(0);
  });

  it("round-trips through storedToDailyLossMagnitude", () => {
    expect(storedToDailyLossMagnitude(dailyLossLimitToStored(250))).toBe(250);
    expect(storedToDailyLossMagnitude(0)).toBe(0);
  });
});

describe("clamp", () => {
  it("clamps within range and treats NaN as the minimum", () => {
    expect(clamp(5, 1, 10)).toBe(5);
    expect(clamp(-5, 1, 10)).toBe(1);
    expect(clamp(50, 1, 10)).toBe(10);
    expect(clamp(NaN, 1, 10)).toBe(1);
  });
});
