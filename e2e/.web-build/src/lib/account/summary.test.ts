import { describe, expect, it } from "vitest";
import { fixtureAccounts, fixtureSummary } from "./fixtures";
import {
  accountSeries, analysisStats, directionBias, equitySlices, HL_ACCOUNT_VALUE_DEF, HL_PNL_DEF,
  isEmptyAccount, longShare, overviewStats, performanceStats,
} from "./summary";
import type { AccountSummary } from "./types";

const NOW = 1_760_000_000_000;
const base = (): AccountSummary => fixtureSummary(fixtureAccounts(NOW)[1], NOW, false);

describe("equitySlices", () => {
  it("carves copytrade out of perps so the slices add up to total equity", () => {
    const s = equitySlices({ perps_usd: 1000, copytrade_usd: 300, spot_usd: 500, staked_usd: 500, total_usd: 2000, withdrawable_usd: 0 });
    expect(s.map((x) => [x.key, x.usd])).toEqual([["perps", 700], ["copytrade", 300], ["spot", 500], ["staked", 500]]);
    expect(s.reduce((a, x) => a + x.pct, 0)).toBeCloseTo(100);
    expect(s[0].pct).toBeCloseTo(35);
  });

  it("caps copytrade at perps and ignores negatives", () => {
    const s = equitySlices({ perps_usd: 100, copytrade_usd: 250, spot_usd: -5, staked_usd: 0, total_usd: 100, withdrawable_usd: 0 });
    expect(s.find((x) => x.key === "copytrade")?.usd).toBe(100);
    expect(s.find((x) => x.key === "perps")?.usd).toBe(0);
    expect(s.find((x) => x.key === "spot")?.usd).toBe(0);
  });

  it("is all zeros (not NaN) for an empty wallet", () => {
    const s = equitySlices(base().balances);
    expect(s.every((x) => x.pct === 0 && x.usd === 0)).toBe(true);
  });
});

describe("direction", () => {
  it("long share of gross notional", () => {
    expect(longShare({ long_notional_usd: 750, short_notional_usd: 250 })).toBe(75);
    expect(longShare({ long_notional_usd: 0, short_notional_usd: 0 })).toBeNull();
    expect(directionBias({ long_notional_usd: 900, short_notional_usd: 100 }).label).toBe("Strongly long");
    expect(directionBias({ long_notional_usd: 0, short_notional_usd: 0 }).label).toBe("No positions");
  });
});

describe("stat rows", () => {
  it("formats overview with tones and dashes for missing values", () => {
    const s = { ...base(), unrealized_pnl_usd: -42.5, account_leverage: 12, margin_usage_pct: 85 };
    const o = Object.fromEntries(overviewStats(s).map((x) => [x.label, x]));
    expect(o["Unrealized PnL"]).toMatchObject({ value: "-$42.50", tone: "down" });
    expect(o.Leverage.tone).toBe("warn");
    expect(o["Margin usage"].tone).toBe("warn");
    expect(o["All-time PnL"].value).toBe("—");
  });

  it("explains All-time PnL with Hyperliquid's own definition (research/user_consensus_2026-10.md)", () => {
    const o = Object.fromEntries(overviewStats(base()).map((x) => [x.label, x]));
    expect(o["All-time PnL"].hint).toBe(HL_PNL_DEF);
    expect(HL_PNL_DEF).toMatch(/account value \+ deposits/);
    expect(HL_ACCOUNT_VALUE_DEF).toMatch(/unrealized pnl from cross and isolated margin positions/);
  });

  it("says n/a, not 0 or a dash, while discovery has no metrics yet", async () => {
    const { metricsPending } = await import("./summary");
    const s = base();
    expect(metricsPending(s)).toBe(true);
    const all = [...analysisStats(s), ...performanceStats(s)];
    expect(all.every((x) => x.value === "n/a")).toBe(true);
    expect(performanceStats(s)[0].hint).toMatch(/discovery/);
    expect(metricsPending(fixtureSummary(fixtureAccounts(NOW)[0], NOW))).toBe(false);
  });

  it("analysis and performance read the scout labels", () => {
    const s: AccountSummary = {
      ...base(), style: "swing", pnl_tier: "strong", size_tier: "M", longest_win_streak_days: 9, avg_hold_h: 30, median_hold_h: 0.5,
      risk_30d: { window: "30d", max_drawdown_pct: 31.2, sharpe: 1.234, sortino: null, days: 30 },
      trades_30d: { window: "30d", trips: 20, wins: 13, long_trips: 12, short_trips: 8, win_rate_pct: 65, opens_per_day: 1 },
    };
    const a = Object.fromEntries(analysisStats(s).map((x) => [x.label, x.value]));
    expect(a).toMatchObject({ "Longest win streak": "9d", Style: "Swing", "Avg / median hold": "30h / 30m", "PnL cohort": "Strong", "Size cohort": "M" });
    const p = Object.fromEntries(performanceStats(s).map((x) => [x.label, x]));
    expect(p["Max drawdown"]).toMatchObject({ value: "31.2%", tone: "warn" });
    expect(p["Win rate"]).toMatchObject({ value: "65%", hint: "13 of 20 round trips" });
    expect(p.Sharpe.value).toBe("1.23");
    expect(p.Sortino.value).toBe("n/a");
  });
});

describe("accountSeries", () => {
  const s = { pnl_curve: { "7d": [{ t_ms: 2, value: 150 }, { t_ms: 1, value: 100 }, { t_ms: 3, value: 90 }] }, value_curve: { "7d": [{ t_ms: 1, value: 1000 }, { t_ms: 3, value: 1200 }] } };

  it("rebases PnL to the window start (sorted by time)", () => {
    const r = accountSeries(s, "pnl", "7d");
    expect(r.points.map((p) => p.value)).toEqual([0, 50, -10]);
    expect(r.change).toBe(-10);
  });

  it("leaves value as-is and reports the delta", () => {
    const r = accountSeries(s, "value", "7d");
    expect(r.points.map((p) => p.value)).toEqual([1000, 1200]);
    expect(r.change).toBe(200);
  });

  it("is empty for a missing window", () => {
    expect(accountSeries(s, "pnl", "1d")).toEqual({ points: [], change: null });
  });
});

describe("fixture summaries", () => {
  it("a funded demo account has balances that add up and every window", () => {
    const s = fixtureSummary(fixtureAccounts(NOW)[0], NOW);
    const b = s.balances;
    expect(b.total_usd).toBeCloseTo(b.perps_usd + b.spot_usd + b.staked_usd);
    expect(isEmptyAccount(s)).toBe(false);
    for (const w of ["1d", "7d", "30d", "all"] as const) expect(accountSeries(s, "value", w).points.length).toBeGreaterThan(1);
  });

  it("an unfunded one is empty", () => {
    expect(isEmptyAccount(base())).toBe(true);
  });
});
