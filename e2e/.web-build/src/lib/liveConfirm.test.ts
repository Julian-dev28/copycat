import { describe, expect, it } from "vitest";
import type { Settings } from "./api/types";
import { isLiveTrading, patchGoesLive } from "./settings";
import { compactOverride, hasActiveOverride, isOverrideSet } from "./forLeader";

const base = {
  contract_version: 1, enabled: false, dry_run: true, leaders: [], sizing_mode: "fixed_margin", fixed_margin_usd: 1,
  fixed_notional_usd: 10.5, size_multiplier: 1, sleeve_frac: 1, leverage_mode: "max", leverage: 20,
  max_position_leverage: 50, margin_mode: "isolated", include_spot_staked: false, only_new_positions: false,
  max_worse_entry_pct: 10, min_order_bump: true, daily_loss_limit_usd: 0, max_open_copies: 10, poll_interval_s: 5,
  leader_overrides: {},
} satisfies Settings;

describe("patchGoesLive: the real-money confirm fires from either switch", () => {
  it("enable while dry run is off -> confirm", () => {
    expect(patchGoesLive({ ...base, dry_run: false }, { enabled: true })).toBe(true);
  });

  it("enable while dry run is on -> no confirm (still paper)", () => {
    expect(patchGoesLive(base, { enabled: true })).toBe(false);
  });

  it("regression: dry run off while already enabled -> confirm", () => {
    expect(patchGoesLive({ ...base, enabled: true, dry_run: true }, { dry_run: false })).toBe(true);
  });

  it("dry run off while disabled -> no confirm (nothing trades)", () => {
    expect(patchGoesLive(base, { dry_run: false })).toBe(false);
  });

  it("both at once -> confirm", () => {
    expect(patchGoesLive(base, { enabled: true, dry_run: false })).toBe(true);
  });

  it("already live -> no repeat confirm; going safer never confirms", () => {
    const live = { ...base, enabled: true, dry_run: false };
    expect(isLiveTrading(live)).toBe(true);
    expect(patchGoesLive(live, { max_worse_entry_pct: 5 })).toBe(false);
    expect(patchGoesLive(live, { dry_run: true })).toBe(false);
    expect(patchGoesLive(live, { enabled: false })).toBe(false);
  });
});

describe("override null handling (api sends unset fields as null)", () => {
  it("null and undefined both mean inherit", () => {
    expect(isOverrideSet(null)).toBe(false);
    expect(isOverrideSet(undefined)).toBe(false);
    expect(isOverrideSet(0)).toBe(true);
    expect(isOverrideSet("max")).toBe(true);
  });

  it("regression: an all-null override from the server is not an active override", () => {
    const fromServer = {
      sizing_mode: null, size_multiplier: null, fixed_margin_usd: null, fixed_notional_usd: null,
      leverage_mode: null, leverage: null, margin_mode: null, max_worse_entry_pct: null,
    };
    expect(hasActiveOverride(fromServer)).toBe(false);
    expect(hasActiveOverride({ ...fromServer, leverage: 5 })).toBe(true);
    expect(hasActiveOverride(undefined)).toBe(false);
  });

  it("compactOverride keeps only real fields (including falsy zero)", () => {
    expect(compactOverride({ leverage: null, max_worse_entry_pct: 0, margin_mode: "cross" })).toEqual({
      max_worse_entry_pct: 0, margin_mode: "cross",
    });
  });
});
