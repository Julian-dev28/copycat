import { describe, expect, it } from "vitest";
import type { Settings } from "./api/types";
import {
  copyRecipe, isAccountTooSmall, leverageVibe, minMarginForLeverage, settingsLeverage, worseEntryVibe,
} from "./copyRecipe";

const base: Settings = {
  contract_version: 1,
  enabled: false,
  dry_run: true,
  leaders: [],
  sizing_mode: "fixed_margin",
  fixed_margin_usd: 1,
  fixed_notional_usd: 10.5,
  size_multiplier: 1,
  sleeve_frac: 1,
  leverage_mode: "max",
  leverage: 20,
  max_position_leverage: 50,
  margin_mode: "isolated",
  include_spot_staked: false,
  only_new_positions: false,
  max_worse_entry_pct: 10,
  min_order_bump: true,
  daily_loss_limit_usd: 0,
  max_open_copies: 10,
  poll_interval_s: 5,
  leader_overrides: {},
};

describe("leverageVibe / worseEntryVibe boundaries", () => {
  it.each([
    [1, "comfy"], [3, "comfy"], [4, "brisk"], [10, "brisk"], [11, "spicy"], [25, "spicy"], [26, "full send"], [50, "full send"],
  ])("%ix is %s", (lev, label) => {
    expect(leverageVibe(lev).label).toBe(label);
  });

  it.each([
    [0, "sniper"], [1, "sniper"], [2, "picky"], [5, "picky"], [6, "relaxed"], [20, "relaxed"], [21, "anything goes"],
  ])("%i%% is %s", (pct, label) => {
    expect(worseEntryVibe(pct).label).toBe(label);
  });
});

describe("isAccountTooSmall", () => {
  it("is true only for a known equity under $11", () => {
    expect(isAccountTooSmall(0)).toBe(true);
    expect(isAccountTooSmall(10.99)).toBe(true);
    expect(isAccountTooSmall(11)).toBe(false);
    expect(isAccountTooSmall(null)).toBe(false);
    expect(isAccountTooSmall(undefined)).toBe(false);
    expect(isAccountTooSmall(Number.NaN)).toBe(false);
  });
});

describe("settingsLeverage", () => {
  it("fixed mode uses the fixed leverage, clamped to the position cap", () => {
    expect(settingsLeverage({ ...base, leverage_mode: "fixed", leverage: 20, max_position_leverage: 10 })).toEqual({
      leverage: 10, upperBound: false,
    });
  });

  it("max and match modes report the cap as an upper bound", () => {
    expect(settingsLeverage({ ...base, leverage_mode: "max" })).toEqual({ leverage: 50, upperBound: true });
    expect(settingsLeverage({ ...base, leverage_mode: "match", max_position_leverage: 5 })).toEqual({
      leverage: 5, upperBound: true,
    });
  });
});

describe("copyRecipe min-order math (M x L >= $10.50)", () => {
  it("$1 at 50x = $50 notional, clears the minimum", () => {
    const r = copyRecipe(base);
    expect(r.notionalUsd).toBe(50);
    expect(r.minOrder).toEqual({ notionalUsd: 50, skipped: false, bumped: false });
    expect(r.minMarginUsd).toBeCloseTo(0.21, 2);
  });

  it("$1 at 5x = $5: bumped to $10.50 when bump is on (>= 25% of min)", () => {
    const r = copyRecipe({ ...base, leverage_mode: "fixed", leverage: 5 });
    expect(r.notionalUsd).toBe(5);
    expect(r.minOrder).toEqual({ notionalUsd: 10.5, skipped: false, bumped: true });
    expect(r.minMarginUsd).toBe(2.1);
  });

  it("$1 at 2x = $2: skipped (< 25% of min)", () => {
    const r = copyRecipe({ ...base, leverage_mode: "fixed", leverage: 2 });
    expect(r.minOrder?.skipped).toBe(true);
  });

  it("fixed notional ignores leverage; proportional has no static notional", () => {
    expect(copyRecipe({ ...base, sizing_mode: "fixed_notional", fixed_notional_usd: 25 }).notionalUsd).toBe(25);
    const p = copyRecipe({ ...base, sizing_mode: "proportional" });
    expect(p.notionalUsd).toBeNull();
    expect(p.minOrder).toBeNull();
  });

  it("minMarginForLeverage never divides by < 1", () => {
    expect(minMarginForLeverage(0)).toBe(10.5);
    expect(minMarginForLeverage(10)).toBeCloseTo(1.05);
  });
});
