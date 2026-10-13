import { describe, expect, it } from "vitest";
import { liqDistancePct, marginUsd, roePct } from "./view";

describe("marginUsd", () => {
  it("is |notional| / leverage", () => {
    expect(marginUsd({ notional_usd: 200, leverage: 10 })).toBe(20);
    expect(marginUsd({ notional_usd: -200, leverage: 10 })).toBe(20);
  });
  it("falls back to |notional| when leverage is not positive (never divides by zero)", () => {
    expect(marginUsd({ notional_usd: 200, leverage: 0 })).toBe(200);
  });
});

describe("roePct", () => {
  it("is uPnL over margin, not over notional (HL's own convention)", () => {
    // $200 notional at 10x = $20 margin; +$5 uPnL = +25% ROE, not +2.5%.
    expect(roePct({ notional_usd: 200, leverage: 10, unrealized_pnl_usd: 5 })).toBe(25);
  });
  it("is null when margin is 0", () => {
    expect(roePct({ notional_usd: 0, leverage: 10, unrealized_pnl_usd: 5 })).toBeNull();
  });
});

describe("liqDistancePct", () => {
  it("is the adverse move to liquidation as a % of mark", () => {
    expect(liqDistancePct({ liquidation_px: 90, mark_px: 100 })).toBe(10);
    expect(liqDistancePct({ liquidation_px: 110, mark_px: 100 })).toBe(10);
  });
  it("is null without a mark or a liquidation price", () => {
    expect(liqDistancePct({ liquidation_px: null, mark_px: 100 })).toBeNull();
    expect(liqDistancePct({ liquidation_px: 90, mark_px: 0 })).toBeNull();
  });
});
