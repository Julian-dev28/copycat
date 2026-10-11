import { describe, expect, it } from "vitest";
import { effectiveSettingsForLeader } from "./forLeader";
import type { Settings } from "./api/types";

const base: Settings = {
  contract_version: 1,
  enabled: false,
  dry_run: true,
  leaders: ["0xabc"],
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

describe("effectiveSettingsForLeader", () => {
  it("returns the book-wide settings unchanged when there's no override", () => {
    expect(effectiveSettingsForLeader(base, "0xabc")).toEqual(base);
  });

  it("applies only the override's explicitly-set fields", () => {
    const withOverride: Settings = {
      ...base,
      leader_overrides: { "0xabc": { leverage: 5, margin_mode: "cross" } },
    };
    const effective = effectiveSettingsForLeader(withOverride, "0xabc");
    expect(effective.leverage).toBe(5);
    expect(effective.margin_mode).toBe("cross");
    expect(effective.leverage_mode).toBe("max"); // untouched, inherits book-wide
  });

  it("normalizes the address before lookup (case-insensitive)", () => {
    const withOverride: Settings = { ...base, leader_overrides: { "0xabc": { leverage: 7 } } };
    expect(effectiveSettingsForLeader(withOverride, "0xABC").leverage).toBe(7);
  });

  it("explicit null fields inside an override are treated as inherit", () => {
    const withOverride: Settings = {
      ...base,
      leader_overrides: { "0xabc": { leverage: null, margin_mode: "cross" } },
    };
    const effective = effectiveSettingsForLeader(withOverride, "0xabc");
    expect(effective.leverage).toBe(base.leverage);
    expect(effective.margin_mode).toBe("cross");
  });
});
