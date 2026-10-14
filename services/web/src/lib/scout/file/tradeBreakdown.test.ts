import { describe, expect, it } from "vitest";
import type { RoundTrip } from "../types";
import { tradeBreakdown } from "./tradeBreakdown";

function trip(partial: Partial<RoundTrip> & { net_pnl_usd: number }): RoundTrip {
  return {
    coin: "BTC",
    side: "long",
    opened_ms: Date.UTC(2026, 9, 1, 0, 0),
    closed_ms: Date.UTC(2026, 9, 1, 1, 0),
    hold_h: 1,
    entry_px: 100,
    exit_px: 101,
    max_notional_usd: 1000,
    gross_pnl_usd: partial.net_pnl_usd,
    fee_usd: 0,
    funding_usd: 0,
    win: partial.net_pnl_usd > 0,
    liquidation: false,
    ...partial,
  };
}

describe("tradeBreakdown", () => {
  it("empty trips: zeros and nulls, never NaN or throwing", () => {
    const b = tradeBreakdown([], 10_000);
    expect(b).toEqual({
      longPnlUsd: 0,
      shortPnlUsd: 0,
      longTrips: 0,
      shortTrips: 0,
      largestWinUsd: null,
      largestLossUsd: null,
      avgTradeSizePctOfAccount: null,
      hourlyOpensUtc: new Array(24).fill(0),
      winRateByCoin: [],
    });
  });

  it("splits PnL and trip counts by side", () => {
    const trips = [
      trip({ coin: "BTC", side: "long", net_pnl_usd: 100 }),
      trip({ coin: "BTC", side: "long", net_pnl_usd: -30 }),
      trip({ coin: "ETH", side: "short", net_pnl_usd: 50 }),
    ];
    const b = tradeBreakdown(trips, 10_000);
    expect(b.longPnlUsd).toBe(70);
    expect(b.shortPnlUsd).toBe(50);
    expect(b.longTrips).toBe(2);
    expect(b.shortTrips).toBe(1);
  });

  it("largest win and loss are the single biggest magnitude in each direction, never mixed up", () => {
    const trips = [
      trip({ net_pnl_usd: 500 }),
      trip({ net_pnl_usd: -800 }),
      trip({ net_pnl_usd: 200 }),
      trip({ net_pnl_usd: -50 }),
    ];
    const b = tradeBreakdown(trips, 10_000);
    expect(b.largestWinUsd).toBe(500);
    expect(b.largestLossUsd).toBe(-800);
  });

  it("all-winning trips leave largestLossUsd null, not 0 or undefined", () => {
    const b = tradeBreakdown([trip({ net_pnl_usd: 10 }), trip({ net_pnl_usd: 20 })], 10_000);
    expect(b.largestLossUsd).toBeNull();
    expect(b.largestWinUsd).toBe(20);
  });

  it("avg trade size is the mean max_notional_usd as a percent of account value", () => {
    const trips = [trip({ net_pnl_usd: 1, max_notional_usd: 1000 }), trip({ net_pnl_usd: 1, max_notional_usd: 3000 })];
    const b = tradeBreakdown(trips, 10_000);   // mean 2000 / 10000 = 20%
    expect(b.avgTradeSizePctOfAccount).toBe(20);
  });

  it("avg trade size is null when the account has no value to divide by (never Infinity)", () => {
    const b = tradeBreakdown([trip({ net_pnl_usd: 1 })], 0);
    expect(b.avgTradeSizePctOfAccount).toBeNull();
  });

  it("buckets opens by UTC hour regardless of the runner's local timezone", () => {
    const trips = [
      trip({ net_pnl_usd: 1, opened_ms: Date.UTC(2026, 9, 1, 14, 30) }),
      trip({ net_pnl_usd: 1, opened_ms: Date.UTC(2026, 9, 2, 14, 45) }),
      trip({ net_pnl_usd: 1, opened_ms: Date.UTC(2026, 9, 3, 3, 0) }),
    ];
    const b = tradeBreakdown(trips, 10_000);
    expect(b.hourlyOpensUtc[14]).toBe(2);
    expect(b.hourlyOpensUtc[3]).toBe(1);
    expect(b.hourlyOpensUtc.reduce((a, c) => a + c, 0)).toBe(3);
  });

  it("win rate by coin: per-coin trip count and win rate, sorted by trip count desc", () => {
    const trips = [
      trip({ coin: "BTC", net_pnl_usd: 10 }),
      trip({ coin: "BTC", net_pnl_usd: -10 }),
      trip({ coin: "BTC", net_pnl_usd: 10 }),
      trip({ coin: "ETH", net_pnl_usd: -5 }),
    ];
    const b = tradeBreakdown(trips, 10_000);
    expect(b.winRateByCoin).toEqual([
      { coin: "BTC", trips: 3, winRatePct: pct(2, 3) },
      { coin: "ETH", trips: 1, winRatePct: 0 },
    ]);
  });

  it("a flip's two trips (opposite sides, same coin) both count toward the breakdown", () => {
    const flipClose = trip({ coin: "XPL", side: "long", net_pnl_usd: -100, opened_ms: 1, closed_ms: 2 });
    const flipOpen = trip({ coin: "XPL", side: "short", net_pnl_usd: 200, opened_ms: 2, closed_ms: 3 });
    const b = tradeBreakdown([flipClose, flipOpen], 10_000);
    expect(b.longTrips).toBe(1);
    expect(b.shortTrips).toBe(1);
    expect(b.winRateByCoin).toEqual([{ coin: "XPL", trips: 2, winRatePct: 50 }]);
  });
});

function pct(wins: number, trips: number): number {
  return (wins / trips) * 100;
}
