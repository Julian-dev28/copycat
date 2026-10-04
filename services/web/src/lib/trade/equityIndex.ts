/**
 * The "price" of a wallet on the Trade page: an equity index, 100 at the
 * start of the last 30 days. Pure functions, unit-tested.
 *
 * Raw account value is a bad price: a deposit or withdrawal moves it without
 * any trading. So the index follows equity EX FLOWS, rebuilt from PnL:
 *
 *   equity_ex_flows(t) = V_now - (pnl_now - pnl_t)
 *   index(t)           = P * equity_ex_flows(t) / V_now
 *   P (price now)      = 100 * V_now / (V_now - pnl_30d)
 *
 * so index = 100 exactly 30 days ago and every window (1d, 7d, 30d, all)
 * lands on the same price now, like one market seen over different ranges.
 * When V_now - pnl_30d <= 0 (account funded mostly by recent gains, or bad
 * data) there is no sane base and the price is null.
 */
import type { CurvePoint, PnlWindow, TraderProfile, TraderRow } from "@/lib/scout/types";

/** Price now, or null when the 30d base is not positive. */
export function indexPrice(accountValueUsd: number, pnl30dUsd: number): number | null {
  const base = accountValueUsd - pnl30dUsd;
  if (!Number.isFinite(base) || base <= 0 || !Number.isFinite(accountValueUsd) || accountValueUsd <= 0) return null;
  return (100 * accountValueUsd) / base;
}

/** % change of equity ex flows over a window whose PnL was `pnlUsd`. Null without a positive base. */
export function windowChangePct(accountValueUsd: number, pnlUsd: number | null | undefined): number | null {
  if (pnlUsd === null || pnlUsd === undefined || !Number.isFinite(pnlUsd)) return null;
  const base = accountValueUsd - pnlUsd;
  if (!Number.isFinite(base) || base <= 0) return null;
  return (pnlUsd / base) * 100;
}

/** The index over one PnL curve, anchored so its last point equals `price`. Never below 0. */
export function indexSeries(pnl: CurvePoint[], accountValueUsd: number, price: number): CurvePoint[] {
  if (pnl.length === 0 || accountValueUsd <= 0) return [];
  const sorted = [...pnl].sort((a, b) => a.t_ms - b.t_ms);
  const last = sorted[sorted.length - 1].value;
  return sorted.map((p) => ({
    t_ms: p.t_ms,
    value: Math.max(0, (price * (accountValueUsd - (last - p.value))) / accountValueUsd),
  }));
}

export interface MarketQuote {
  price: number | null;
  change24hPct: number | null;
  change7dPct: number | null;
  change30dPct: number | null;
  /** 30d index curve for the row sparkline (from pnl_spark_30d). */
  spark: CurvePoint[];
}

function perfPnl(row: Pick<TraderRow, "perf">, w: PnlWindow): number | null {
  return row.perf.find((p) => p.window === w)?.pnl_usd ?? null;
}

/** A board row as a market ticker. */
export function rowQuote(row: Pick<TraderRow, "account_value_usd" | "perf" | "pnl_spark_30d">): MarketQuote {
  const av = row.account_value_usd;
  const pnl30 = perfPnl(row, "30d");
  const price = pnl30 === null ? null : indexPrice(av, pnl30);
  return {
    price,
    change24hPct: windowChangePct(av, perfPnl(row, "1d")),
    change7dPct: windowChangePct(av, perfPnl(row, "7d")),
    change30dPct: windowChangePct(av, pnl30),
    spark: price === null ? [] : indexSeries(row.pnl_spark_30d, av, price),
  };
}

export interface IndexChartData {
  points: CurvePoint[];
  /** Change from the window's first point to its last, %. */
  changePct: number | null;
  price: number | null;
}

/**
 * The chart series for one window of a trader file. Over long windows the
 * ex-flows rebuild can hit zero (he made more than today's balance, so the
 * account was mostly funded later): then fall back to account value scaled
 * to the same price, which at least keeps the shape honest.
 */
export function profileIndex(profile: Pick<TraderProfile, "row" | "pnl_curve" | "value_curve">, w: PnlWindow): IndexChartData {
  const av = profile.row.account_value_usd;
  const pnl30 = perfPnl(profile.row, "30d") ?? lastValueChange(profile.pnl_curve["30d"]);
  const price = pnl30 === null ? null : indexPrice(av, pnl30);
  const curve = profile.pnl_curve[w] ?? [];
  if (price === null || curve.length < 2) return { points: [], changePct: null, price };
  let points = indexSeries(curve, av, price);
  const values = profile.value_curve[w] ?? [];
  if (points.some((p) => p.value <= price * 0.01) && values.length >= 2) {
    const sorted = [...values].sort((a, b) => a.t_ms - b.t_ms);
    const now = sorted[sorted.length - 1].value;
    if (now > 0) points = sorted.map((p) => ({ t_ms: p.t_ms, value: (price * Math.max(0, p.value)) / now }));
  }
  const first = points[0].value;
  const last = points[points.length - 1].value;
  return { points, price, changePct: first > 0 ? (last / first - 1) * 100 : null };
}

function lastValueChange(pts: CurvePoint[] | undefined): number | null {
  if (!pts || pts.length < 2) return null;
  const s = [...pts].sort((a, b) => a.t_ms - b.t_ms);
  return s[s.length - 1].value - s[0].value;
}

/** "104.37" style: 2 decimals under 10k, compact above (a wallet that 50x'd). */
export function formatIndex(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "n/a";
  if (v >= 10_000) return v.toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });
  return v.toFixed(2);
}
