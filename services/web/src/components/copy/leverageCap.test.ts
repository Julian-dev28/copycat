import { describe, expect, it } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { Settings } from "@/lib/api/types";
import { fixedLeverageCap } from "./leverageCap";
import { EngineControlsPanel } from "./EngineControlsPanel";
import { CopyBehaviorPanel } from "./CopyBehaviorPanel";

// The operator's real shape: fixed 15x under a 15x cap, then the leverage slider is raised.
const base: Settings = {
  contract_version: 1,
  enabled: false,
  dry_run: true,
  leaders: [],
  sizing_mode: "fixed_margin",
  fixed_margin_usd: 5,
  fixed_notional_usd: 10.5,
  size_multiplier: 1,
  sleeve_frac: 1,
  leverage_mode: "fixed",
  leverage: 15,
  max_position_leverage: 15,
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

const noop = () => {};
const engine = (s: Settings) => renderToStaticMarkup(createElement(EngineControlsPanel, { settings: s, onPatch: noop }));
const behavior = (s: Settings) => renderToStaticMarkup(createElement(CopyBehaviorPanel, { settings: s, onPatch: noop }));

describe("fixedLeverageCap", () => {
  it("is the engine's min(leverage, max_position_leverage) in fixed mode", () => {
    expect(fixedLeverageCap({ ...base, leverage: 38 })).toEqual({ set: 38, effective: 15, capped: true });
    expect(fixedLeverageCap({ ...base, leverage: 15 })).toEqual({ set: 15, effective: 15, capped: false });
    expect(fixedLeverageCap({ ...base, leverage: 10, max_position_leverage: 40 })).toEqual({ set: 10, effective: 10, capped: false });
  });

  it("is null outside fixed mode (fixed leverage is unused there)", () => {
    expect(fixedLeverageCap({ ...base, leverage_mode: "max", leverage: 38 })).toBeNull();
    expect(fixedLeverageCap({ ...base, leverage_mode: "match", leverage: 38 })).toBeNull();
  });
});

describe("fixed leverage above max_position_leverage (the 'stuck leverage' report)", () => {
  it("Engine panel says the leverage is capped and shows liquidation at the effective 15x, not 38x", () => {
    const html = engine({ ...base, leverage: 38 });
    expect(html).toContain('data-testid="leverage-capped"');
    expect(html).toContain("Capped at 15x by Maximum position leverage");
    expect(html).toContain("15x isolated");
    expect(html).not.toContain("38x isolated");
  });

  it("Engine panel shows no cap note when leverage is within the cap", () => {
    const html = engine(base);
    expect(html).not.toContain('data-testid="leverage-capped"');
    expect(html).toContain("15x isolated");
  });

  it("Engine panel shows no cap note outside fixed mode", () => {
    expect(engine({ ...base, leverage_mode: "match", leverage: 38 })).not.toContain('data-testid="leverage-capped"');
  });

  it("Copy behavior panel flags a max position leverage below the fixed leverage", () => {
    expect(behavior({ ...base, leverage: 38 })).toContain('data-testid="max-leverage-caps-fixed"');
    expect(behavior(base)).not.toContain('data-testid="max-leverage-caps-fixed"');
  });
});
