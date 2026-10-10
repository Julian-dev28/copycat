import { describe, expect, it } from "vitest";
import { leaderTerms } from "./leaderTerms";

const base = {
  sizing_mode: "allocation" as const, leverage_mode: "fixed" as const, leverage: 20, max_position_leverage: 15,
  fixed_margin_usd: 5, fixed_notional_usd: 10.5, size_multiplier: 1, sleeve_frac: 0.19,
  allocation_usd: 12.29, exposure_mode: "target" as const, target_leverage: 50,
};

describe("leaderTerms", () => {
  it("shows the wallet's own leverage and the cap that lowers it", () => {
    const t = leaderTerms(base);
    expect(t.leverage).toBe("50x → 15x cap");
    expect(t.capped).toBe(true);
    expect(t.sizing).toBe("Sized by Trade: $12.29 at your leverage");
  });

  it("target leverage under the cap is shown as is", () => {
    expect(leaderTerms({ ...base, target_leverage: 10 }).leverage).toBe("10x");
  });

  it("fixed leverage when not on target exposure", () => {
    expect(leaderTerms({ ...base, exposure_mode: "match" }).leverage).toBe("20x → 15x cap");
    expect(leaderTerms({ ...base, sizing_mode: "proportional" }).sizing).toBe("Sized by sleeve: 19% of equity");
  });

  it("match and max modes name the cap", () => {
    expect(leaderTerms({ ...base, exposure_mode: "match", leverage_mode: "match" }).leverage).toBe("their leverage, cap 15x");
    expect(leaderTerms({ ...base, exposure_mode: "match", leverage_mode: "max" }).leverage).toBe("coin max, cap 15x");
  });

  it("fixed sizing modes", () => {
    expect(leaderTerms({ ...base, sizing_mode: "fixed_margin" }).sizing).toBe("Fixed $5.00 margin per copy");
    expect(leaderTerms({ ...base, sizing_mode: "fixed_notional" }).sizing).toBe("Fixed $10.50 per copy");
  });
});
