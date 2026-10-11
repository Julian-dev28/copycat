import { describe, expect, it } from "vitest";
import { applySettingsPatch } from "./settings";
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
  leader_overrides: { "0xabc": { leverage: 10 } },
};

describe("applySettingsPatch", () => {
  it("merges top-level fields without touching unrelated ones", () => {
    const next = applySettingsPatch(base, { enabled: true });
    expect(next.enabled).toBe(true);
    expect(next.dry_run).toBe(true);
    expect(next.leaders).toBe(base.leaders);
  });

  it("replaces a leader's whole override", () => {
    const next = applySettingsPatch(base, {
      leader_overrides: { "0xabc": { leverage: 30, margin_mode: "cross" } },
    });
    expect(next.leader_overrides["0xabc"]).toEqual({ leverage: 30, margin_mode: "cross" });
  });

  it("a null override clears that leader's override entirely", () => {
    const next = applySettingsPatch(base, { leader_overrides: { "0xabc": null } });
    expect(next.leader_overrides).toEqual({});
  });

  it("leaves other leaders' overrides untouched", () => {
    const withTwo = applySettingsPatch(base, { leader_overrides: { "0xdef": { leverage: 5 } } });
    expect(withTwo.leader_overrides["0xabc"]).toEqual({ leverage: 10 });
    expect(withTwo.leader_overrides["0xdef"]).toEqual({ leverage: 5 });
  });

  it("does not mutate the input settings object", () => {
    const snapshot = JSON.parse(JSON.stringify(base));
    applySettingsPatch(base, { leader_overrides: { "0xabc": null }, enabled: true });
    expect(base).toEqual(snapshot);
  });
});
