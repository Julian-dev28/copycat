import { describe, expect, it } from "vitest";
import { estimateLiquidationDistance, formatLiquidationHint } from "./liquidation";

describe("estimateLiquidationDistance", () => {
  it("cross margin returns null (account-wide, not a single-position number)", () => {
    expect(estimateLiquidationDistance(50, "cross")).toEqual({ adverseMovePct: null, isEstimate: true });
  });

  it("isolated at the reference max leverage: adverse move = 1/(2*maxLev)", () => {
    // 1/50 - 1/(2*50) = 0.02 - 0.01 = 0.01 -> 1%
    const { adverseMovePct } = estimateLiquidationDistance(50, "isolated", 50);
    expect(adverseMovePct).toBeCloseTo(1, 5);
  });

  it("isolated at half the reference max leverage gives more room before liquidation", () => {
    // 1/25 - 1/100 = 0.04 - 0.01 = 0.03 -> 3%
    const { adverseMovePct } = estimateLiquidationDistance(25, "isolated", 50);
    expect(adverseMovePct).toBeCloseTo(3, 5);
  });

  it("lower leverage always gives more room than higher leverage, same mode", () => {
    const low = estimateLiquidationDistance(5, "isolated", 50).adverseMovePct!;
    const high = estimateLiquidationDistance(40, "isolated", 50).adverseMovePct!;
    expect(low).toBeGreaterThan(high);
  });

  it("never returns a negative distance even above the reference leverage", () => {
    const { adverseMovePct } = estimateLiquidationDistance(10_000, "isolated", 50);
    expect(adverseMovePct).toBeGreaterThanOrEqual(0);
  });
});

describe("formatLiquidationHint", () => {
  it("matches the operator-facing phrasing for isolated margin", () => {
    expect(formatLiquidationHint(50, "isolated", 50)).toBe("50x isolated ~ 1.0% adverse move liquidates");
  });

  it("uses two decimals under 1% so small distances aren't rounded to 0.0%", () => {
    // 1/100 - 1/(2*100) = 0.01 - 0.005 = 0.005 -> 0.5%, needs 2 decimals to be legible.
    expect(formatLiquidationHint(100, "isolated", 100)).toBe("100x isolated ~ 0.50% adverse move liquidates");
  });

  it("describes cross margin without a specific percentage", () => {
    expect(formatLiquidationHint(50, "cross")).toBe("50x cross — liquidation depends on total account equity");
  });
});
