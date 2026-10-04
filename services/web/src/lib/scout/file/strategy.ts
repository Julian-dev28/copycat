/**
 * Strategy tab data shaping. Pure.
 *
 * The fingerprint carries two marginal histograms (24 UTC hours, 7 weekdays
 * Monday first), not a joint 24x7 table. The heatmap cell is therefore the
 * expected trip count if hour and weekday were independent:
 *   cell[d][h] = weekday[d] * hour[h] / total
 * The UI says so, and the marginals are drawn on the edges as exact bars.
 */
import { formatHold } from "../labels";
import type { StrategyFingerprint, Thesis } from "../types";

export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export interface HeatGrid {
  /** cells[weekday][hour], expected trips. */
  cells: number[][];
  max: number;
  hours: number[];
  weekdays: number[];
  total: number;
  /** UTC hour with the most entries, or null when there are none. */
  peakHour: number | null;
  peakWeekday: number | null;
}

function fit(arr: number[] | undefined, n: number): number[] {
  return Array.from({ length: n }, (_, i) => {
    const v = arr?.[i] ?? 0;
    return Number.isFinite(v) && v > 0 ? v : 0;
  });
}

function argmax(a: number[]): number | null {
  let best = -1;
  let at: number | null = null;
  a.forEach((v, i) => {
    if (v > best && v > 0) {
      best = v;
      at = i;
    }
  });
  return at;
}

export function hourWeekdayGrid(fp: Pick<StrategyFingerprint, "hour_hist_utc" | "weekday_hist">): HeatGrid {
  const hours = fit(fp.hour_hist_utc, 24);
  const weekdays = fit(fp.weekday_hist, 7);
  const hTotal = hours.reduce((a, b) => a + b, 0);
  const dTotal = weekdays.reduce((a, b) => a + b, 0);
  const total = Math.max(hTotal, dTotal);
  const cells = weekdays.map((d) => hours.map((h) => (hTotal > 0 && dTotal > 0 ? (d / dTotal) * (h / hTotal) * total : 0)));
  const max = Math.max(0, ...cells.flat());
  return { cells, max, hours, weekdays, total, peakHour: argmax(hours), peakWeekday: argmax(weekdays) };
}

/** 0..1 intensity for a cell, 0 when the grid is empty. */
export function heatLevel(v: number, max: number): number {
  return max > 0 ? Math.min(1, Math.max(0, v / max)) : 0;
}

export interface KeyNumber {
  label: string;
  value: string;
  hint?: string;
}

const pct = (v: number | null | undefined, d = 0) => (v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v.toFixed(d)}%`);
const num = (v: number | null | undefined, d = 1, suffix = "") =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${Number(v.toFixed(d))}${suffix}`;
const usd = (v: number | null | undefined) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : `${v < 0 ? "-" : ""}$${Math.round(Math.abs(v)).toLocaleString("en-US")}`;

export function keyNumbers(fp: StrategyFingerprint): KeyNumber[] {
  return [
    { label: "Trips analyzed", value: String(fp.trips_analyzed), hint: `last ${fp.window_days} days` },
    { label: "Median hold", value: formatHold(fp.median_hold_h), hint: `p90 ${formatHold(fp.p90_hold_h)}` },
    { label: "Long share", value: pct(fp.long_pct) },
    { label: "Win rate", value: pct(fp.win_rate_pct) },
    { label: "Payoff ratio", value: num(fp.payoff_ratio, 2), hint: `avg win ${usd(fp.avg_win_usd)} / loss ${usd(fp.avg_loss_usd)}` },
    { label: "Trend-aligned", value: pct(fp.trend_aligned_pct), hint: "entries with the 24h move" },
    { label: "Breakout / pullback", value: `${pct(fp.breakout_pct)} / ${pct(fp.pullback_pct)}` },
    { label: "RSI at entry", value: `${num(fp.avg_rsi_long_entry, 0)} L / ${num(fp.avg_rsi_short_entry, 0)} S` },
    { label: "Scales in / out", value: `${pct(fp.scales_in_pct)} / ${pct(fp.scales_out_pct)}`, hint: `${num(fp.avg_adds_per_trip)} adds per trip` },
    { label: "Leverage", value: `${num(fp.avg_leverage, 1, "x")} avg`, hint: `max ${num(fp.max_leverage, 0, "x")}` },
    { label: "Loser hold vs winner", value: num(fp.loser_hold_vs_winner, 1, "x"), hint: "over 1x: sits in losers longer" },
    { label: "Worst trip", value: pct(fp.worst_trip_pct_of_equity, 1), hint: "of equity" },
    { label: "PnL from top coin", value: pct(fp.pnl_from_top_coin_pct) },
  ];
}

export const THESIS_SOURCE: Record<Thesis["source"], { label: string; tone: "neutral" | "accent" }> = {
  ta: { label: "TA, no AI", tone: "neutral" },
  claude_code: { label: "Claude Code", tone: "accent" },
};

/** "ta" first, then "claude_code"; newest per source. */
export function orderTheses(list: Thesis[]): Thesis[] {
  const latest = new Map<Thesis["source"], Thesis>();
  for (const t of list) {
    const cur = latest.get(t.source);
    if (!cur || t.created_ms > cur.created_ms) latest.set(t.source, t);
  }
  return (["ta", "claude_code"] as const).flatMap((s) => (latest.has(s) ? [latest.get(s) as Thesis] : []));
}

export function hasClaudeThesis(list: Thesis[]): boolean {
  return list.some((t) => t.source === "claude_code");
}

/** The command the hint card copies. */
export function thesisCommand(address: string): string {
  return `/copycat-thesis ${address.toLowerCase()}`;
}

export function contextChips(c: StrategyFingerprint["examples"][number]["context"]): string[] {
  const out: string[] = [];
  if (c.trend_aligned === true) out.push("with trend");
  if (c.trend_aligned === false) out.push("against trend");
  if (c.breakout) out.push("breakout");
  if (c.pullback) out.push("pullback");
  if (c.rsi_14 !== null && c.rsi_14 !== undefined) out.push(`RSI ${Math.round(c.rsi_14)}`);
  if (c.move_24h_pct !== null && c.move_24h_pct !== undefined) out.push(`24h ${c.move_24h_pct > 0 ? "+" : ""}${c.move_24h_pct.toFixed(1)}%`);
  out.push(`${String(c.hour_utc).padStart(2, "0")}:00 UTC`);
  return out;
}
