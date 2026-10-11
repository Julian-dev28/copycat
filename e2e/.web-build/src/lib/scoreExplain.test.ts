import { describe, expect, it } from "vitest";
import type { TraderScore } from "./api/types";
import { explainScore, formatScore, isUnscored, recomputeScore, summarizeFlags } from "./scoreExplain";

function trader(over: Partial<TraderScore> = {}): TraderScore {
  return {
    address: "0x04a97ae7f350a22cd0cdb6b1875e8905b76495aa",
    account_value_usd: 100_000,
    pnl_30d_usd: 5_000,
    roi_30d_pct: 5,
    pnl_all_time_usd: 50_000,
    volume_30d_usd: 1_000_000,
    fills_30d: 200,
    opens_per_day: 3,
    coins: ["BTC"],
    sim_return_pct: 40,
    sim_max_drawdown_pct: -10,
    sim_liquidations: 0,
    sim_copies: 20,
    sim_skipped_min_order: 0,
    sim_fees_usd: 2,
    score: 4,
    flags: [],
    ...over,
  };
}

// Parity cases with services/discovery/tests/test_scoring.py semantics.
describe("recomputeScore mirrors scoring.py", () => {
  it("return / drawdown", () => {
    expect(recomputeScore(trader())).toBe(4);
  });

  it("drawdown floored at 5%", () => {
    expect(recomputeScore(trader({ sim_return_pct: 20, sim_max_drawdown_pct: -1 }))).toBe(4);
  });

  it("liquidation penalty is applied before the too-few-trades discount", () => {
    // (200/5 - 50) * 0.2 = -2
    expect(recomputeScore(trader({ sim_return_pct: 200, sim_max_drawdown_pct: -2, sim_liquidations: 1, sim_copies: 3 }))).toBeCloseTo(-2);
  });

  it("a liquidated star ranks below a steady leader", () => {
    const star = recomputeScore(trader({ sim_return_pct: 200, sim_max_drawdown_pct: -5, sim_liquidations: 1 }));
    const steady = recomputeScore(trader({ sim_return_pct: 10, sim_max_drawdown_pct: -5 }));
    expect(star).toBeLessThan(steady);
  });
});

describe("explainScore", () => {
  it("covers return, drawdown, liquidations and copies in plain words", () => {
    const text = explainScore(trader(), 1000).map((l) => l.text).join("\n");
    expect(text).toContain("+40.0%");
    expect(text).toContain("$1,000");
    expect(text).toContain("40.0 / 10.0 = 4.00");
    expect(text).toContain("No copy got liquidated.");
    expect(text).toContain("20 copies opened");
  });

  it("calls out the drawdown floor, liquidations and thin data as bad", () => {
    const lines = explainScore(trader({ sim_max_drawdown_pct: -2, sim_liquidations: 2, sim_copies: 1, sim_skipped_min_order: 3 }), 500);
    const text = lines.map((l) => l.text).join("\n");
    expect(text).toContain("treats anything under 5% as 5%");
    expect(text).toContain("2 copies got liquidated");
    expect(text).toContain("Only 1 copy opened");
    expect(text).toContain("3 trades were skipped");
    expect(lines.filter((l) => l.tone === "bad").length).toBe(2);
  });
});

describe("summarizeFlags", () => {
  it("collapses per-coin flags into one entry per kind with a count", () => {
    expect(summarizeFlags(["hft", "worse_entry:BTC", "worse_entry:ETH", "error:fills:Timeout"])).toEqual([
      { key: "hft", count: 1, meaning: "trades too fast to copy well" },
      { key: "worse_entry", count: 2, meaning: "entries skipped for slippage" },
      { key: "error", count: 1, meaning: "scoring error" },
    ]);
  });

  it("falls back to a readable label for unknown flags", () => {
    expect(summarizeFlags(["brand_new"])[0].meaning).toBe("brand new");
  });
});

describe("unscored sentinel (runner._flagged_score -> -1e9)", () => {
  const unscored = trader({ score: -1e9, sim_return_pct: 0, sim_max_drawdown_pct: 0, sim_copies: 0, fills_30d: 3, flags: ["too_few_trades"] });

  it("is detected and shown as n/a instead of -1000000000.00", () => {
    expect(isUnscored(unscored)).toBe(true);
    expect(formatScore(unscored)).toBe("n/a");
    expect(isUnscored(trader({ score: -60 }))).toBe(false);
    expect(formatScore(trader({ score: -60 }))).toBe("-60.00");
  });

  it("explains no-activity vs data error in one line", () => {
    expect(explainScore(unscored, 1000)).toEqual([
      expect.objectContaining({ tone: "bad", text: expect.stringContaining("opened nothing copyable") }),
    ]);
    const errored = explainScore({ ...unscored, flags: ["error:fills:Timeout"] }, 1000);
    expect(errored[0].text).toContain("data error");
  });
});
