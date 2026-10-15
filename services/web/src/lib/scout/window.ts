/**
 * Window switching for Scout. Every "which number / which curve for this
 * window" decision lives here so the board, the trader file and the tests
 * agree. Pure functions.
 */
import { formatSignedPct, formatUsd } from "@/lib/format";
import type { CurvePoint, PnlWindow, RiskStats, TradeStats, TraderProfile, TraderRow, WindowPerf } from "./types";

export const WINDOW_MS: Record<PnlWindow, number | null> = {
  "1d": 86_400_000,
  "7d": 7 * 86_400_000,
  "30d": 30 * 86_400_000,
  all: null,
};

/** Short enough for a four-way segmented control: "All time" rendered as "All ti…" (2026-10-16 sweep). */
export const WINDOW_LABEL: Record<PnlWindow, string> = { "1d": "24h", "7d": "7d", "30d": "30d", all: "All" };

export function windowPerf(row: Pick<TraderRow, "perf">, w: PnlWindow): WindowPerf | null {
  return row.perf.find((p) => p.window === w) ?? null;
}

export type Tone = "up" | "down" | "flat";

export function toneOf(v: number | null | undefined): Tone {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0) return "flat";
  return v > 0 ? "up" : "down";
}

/** The PnL figure on a card/row: $ or ROI % for the selected window. */
export function pnlFigure(row: Pick<TraderRow, "perf">, w: PnlWindow, unit: "usd" | "pct"): { text: string; tone: Tone } {
  const p = windowPerf(row, w);
  if (!p) return { text: "—", tone: "flat" };
  if (unit === "pct") return { text: formatSignedPct(p.roi_pct), tone: toneOf(p.roi_pct) };
  return { text: formatSignedUsdCompact(p.pnl_usd), tone: toneOf(p.pnl_usd) };
}

/** +$1.2M / -$3.4K: signed and compact, for dense cards. */
export function formatSignedUsdCompact(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (Math.abs(v) < 10_000) {
    const r = Math.round(v);
    return `${r > 0 ? "+" : r < 0 ? "-" : ""}$${Math.abs(r).toLocaleString("en-US")}`;
  }
  return `${v > 0 ? "+" : v < 0 ? "-" : ""}${formatUsd(Math.abs(v), true)}`;
}

/** Stats for a window, falling back to the nearest window the api computed (stats are 7d/30d/all in v1). */
export function riskFor(profile: Pick<TraderProfile, "risk">, w: PnlWindow): { stats: RiskStats | null; exact: boolean } {
  const exact = profile.risk.find((r) => r.window === w);
  if (exact) return { stats: exact, exact: true };
  const fallback = w === "1d" ? profile.risk.find((r) => r.window === "7d") : profile.risk.find((r) => r.window === "30d");
  return { stats: fallback ?? null, exact: false };
}

export function tradesFor(profile: Pick<TraderProfile, "trades">, w: PnlWindow): { stats: TradeStats | null; exact: boolean } {
  const exact = profile.trades.find((r) => r.window === w);
  if (exact) return { stats: exact, exact: true };
  const fallback = w === "1d" ? profile.trades.find((r) => r.window === "7d") : profile.trades.find((r) => r.window === "30d");
  return { stats: fallback ?? null, exact: false };
}

/** Points at or after `startMs`, sorted. */
export function clipFrom(points: CurvePoint[], startMs: number | null): CurvePoint[] {
  const sorted = [...points].sort((a, b) => a.t_ms - b.t_ms);
  return startMs === null ? sorted : sorted.filter((p) => p.t_ms >= startMs);
}

/** Value of the last point at or before t (step lookup); the first point if t is before the series. */
export function valueAt(points: CurvePoint[], t: number): number | null {
  if (!points.length) return null;
  let lo = 0;
  let hi = points.length - 1;
  if (t < points[0].t_ms) return points[0].value;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (points[mid].t_ms <= t) lo = mid;
    else hi = mid - 1;
  }
  return points[lo].value;
}

/** Index of the point whose t is closest to `t` (points sorted by t). -1 when empty. */
export function nearestIndex(points: CurvePoint[], t: number): number {
  if (!points.length) return -1;
  let lo = 0;
  let hi = points.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (points[mid].t_ms <= t) lo = mid;
    else hi = mid;
  }
  return Math.abs(points[lo].t_ms - t) <= Math.abs(points[hi].t_ms - t) ? lo : hi;
}

export type ChartMetric = "pnl" | "value";

/** The copy-sim series, everywhere it is drawn: a past replay at your settings, not a forecast. */
export const SIM_LABEL = "What you would have made";
export const WHATIF_SIM_LABEL = "What you would have made (this what-if)";

export interface ChartSeries {
  key: "his" | "sim";
  label: string;
  points: CurvePoint[];
}

export interface ChartData {
  unit: "usd" | "pct";
  series: ChartSeries[];
  /** Plain-words caveats shown under the chart. */
  notes: string[];
}

/**
 * What the trader-file chart draws for (metric, window, overlay).
 *
 * One y-axis only. His PnL is in his dollars (often $100k+), the sim is in
 * the copier's dollars ($1k), so overlaying them in USD would flatten the
 * sim to a line on zero. With the overlay on, both become % return indexed
 * to the window start:
 *   his PnL:   (pnl_t - pnl_0) / account_value_0 * 100
 *   his value: (value_t / value_0 - 1) * 100
 *   your sim:  (equity_t / equity_0 - 1) * 100
 */
export function chartData(
  profile: Pick<TraderProfile, "pnl_curve" | "value_curve" | "sim_curve" | "row">,
  metric: ChartMetric,
  w: PnlWindow,
  overlay: boolean,
): ChartData {
  const notes: string[] = [];
  const source = metric === "pnl" ? profile.pnl_curve[w] : profile.value_curve[w];
  const his = clipFrom(source ?? [], null);
  const hisLabel = metric === "pnl" ? "Their PnL" : "Their account value";
  if (metric === "value") notes.push("Account value includes deposits and withdrawals, so transfers show as steps.");

  if (!overlay) {
    const points = metric === "pnl" && his.length ? his.map((p) => ({ t_ms: p.t_ms, value: p.value - his[0].value })) : his;
    return { unit: "usd", series: [{ key: "his", label: hisLabel, points }], notes };
  }

  const start = his[0]?.t_ms ?? null;
  const hisPct: CurvePoint[] = [];
  if (his.length) {
    if (metric === "pnl") {
      const values = clipFrom(profile.value_curve[w] ?? [], null);
      const av0 = valueAt(values, his[0].t_ms) ?? profile.row.account_value_usd;
      if (av0 > 0) for (const p of his) hisPct.push({ t_ms: p.t_ms, value: ((p.value - his[0].value) / av0) * 100 });
    } else if (his[0].value > 0) {
      for (const p of his) hisPct.push({ t_ms: p.t_ms, value: (p.value / his[0].value - 1) * 100 });
    }
  }

  const sim = clipFrom(profile.sim_curve, w === "all" ? null : start);
  const simPct = sim.length && sim[0].value > 0 ? sim.map((p) => ({ t_ms: p.t_ms, value: (p.value / sim[0].value - 1) * 100 })) : [];
  if (w === "all" && simPct.length) notes.push("Your copy covers the last 30 days only: that is how far back the sim replays.");
  if (!simPct.length) notes.push("No sim curve for this trader yet.");

  return {
    unit: "pct",
    series: [
      { key: "his", label: metric === "pnl" ? "Their return" : "Their account value", points: hisPct },
      { key: "sim", label: SIM_LABEL, points: simPct },
    ],
    notes,
  };
}
