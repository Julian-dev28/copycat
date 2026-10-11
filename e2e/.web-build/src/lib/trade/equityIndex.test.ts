import { describe, expect, it } from "vitest";
import { formatIndex, indexPrice, indexSeries, profileIndex, rowQuote, windowChangePct } from "./equityIndex";

const DAY = 86_400_000;

describe("index price: 100 thirty days ago", () => {
  it("+25% over 30d prices at 125", () => {
    expect(indexPrice(125_000, 25_000)).toBeCloseTo(125);
  });

  it("a losing month prices under 100", () => {
    expect(indexPrice(80_000, -20_000)).toBeCloseTo(80);
  });

  it("no positive base -> null, not a silly number", () => {
    expect(indexPrice(10_000, 10_000)).toBeNull();
    expect(indexPrice(0, 0)).toBeNull();
  });

  it("window change is PnL over equity at the window start", () => {
    expect(windowChangePct(110, 10)).toBeCloseTo(10);
    expect(windowChangePct(100, null)).toBeNull();
  });
});

describe("index series ignores deposits and withdrawals", () => {
  const pnl = [
    { t_ms: 0, value: 0 },
    { t_ms: DAY, value: 5_000 },
    { t_ms: 2 * DAY, value: 25_000 },
  ];

  it("starts at 100 and ends at the price", () => {
    const s = indexSeries(pnl, 125_000, 125);
    expect(s[0].value).toBeCloseTo(100);
    expect(s[2].value).toBeCloseTo(125);
    expect(s[1].value).toBeCloseTo(105);
  });

  it("every window lands on the same price now", () => {
    const row = { account_value_usd: 125_000, perf: [{ window: "30d" as const, pnl_usd: 25_000, roi_pct: 0, volume_usd: 0 }], pnl_spark_30d: pnl };
    const short = [{ t_ms: 0, value: 0 }, { t_ms: DAY, value: 2_000 }];
    const p = profileIndex({ row: row as never, pnl_curve: { "30d": pnl, "1d": short }, value_curve: {} }, "1d");
    expect(p.price).toBeCloseTo(125);
    expect(p.points.at(-1)!.value).toBeCloseTo(125);
    expect(p.changePct).toBeCloseTo((2_000 / 123_000) * 100);
  });

  it("falls back to account value when the ex-flows rebuild hits zero", () => {
    const row = { account_value_usd: 10_000, perf: [{ window: "30d" as const, pnl_usd: 1_000, roi_pct: 0, volume_usd: 0 }], pnl_spark_30d: [] };
    const all = [{ t_ms: 0, value: 0 }, { t_ms: DAY, value: 50_000 }];
    const values = [{ t_ms: 0, value: 5_000 }, { t_ms: DAY, value: 10_000 }];
    const p = profileIndex({ row: row as never, pnl_curve: { all }, value_curve: { all: values } }, "all");
    expect(p.points[0].value).toBeGreaterThan(0);
    expect(p.points[1].value).toBeCloseTo(p.price!);
  });

  it("rowQuote: price, 24h and 7d change from the board row", () => {
    const q = rowQuote({
      account_value_usd: 110_000,
      perf: [
        { window: "1d", pnl_usd: 1_000, roi_pct: 0, volume_usd: 0 },
        { window: "7d", pnl_usd: -2_000, roi_pct: 0, volume_usd: 0 },
        { window: "30d", pnl_usd: 10_000, roi_pct: 0, volume_usd: 0 },
      ],
      pnl_spark_30d: pnl,
    });
    expect(q.price).toBeCloseTo(110);
    expect(q.change24hPct).toBeCloseTo((1_000 / 109_000) * 100);
    expect(q.change7dPct).toBeLessThan(0);
    expect(q.spark).toHaveLength(3);
  });

  it("formats 2 decimals, compact when a wallet 100x'd", () => {
    expect(formatIndex(104.367)).toBe("104.37");
    expect(formatIndex(25_400)).toBe("25.4K");
    expect(formatIndex(null)).toBe("n/a");
  });
});
