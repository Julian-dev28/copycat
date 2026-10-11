/**
 * Daily PnL calendar: TraderProfile.daily_pnl (t = UTC midnight) laid out as
 * week columns x 7 weekday rows (Mon at the top), GitHub-style. Colour is
 * diverging: a level from -4 (worst loss) to +4 (best gain), 0 = flat, and
 * null = no data that day. Levels scale to the 90th percentile of |PnL| so
 * one outlier day can't wash every other cell to the palest step. Pure.
 */
import type { CurvePoint } from "./types";

const DAY = 86_400_000;

export interface CalendarCell {
  t_ms: number;
  value: number | null;
  level: number;
}

export interface CalendarGrid {
  /** weeks[col][row]: row 0 = Monday. Cells after `end` are omitted (shorter last column). */
  weeks: CalendarCell[][];
  /** Column index where a new month starts, with its short name. */
  months: { col: number; label: string }[];
  scale: number;
  total: number;
  green: number;
  red: number;
  best: CalendarCell | null;
  worst: CalendarCell | null;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function utcMidnight(t: number): number {
  return Math.floor(t / DAY) * DAY;
}

/** Monday = 0 ... Sunday = 6, in UTC. */
function weekdayMon0(t: number): number {
  return (new Date(t).getUTCDay() + 6) % 7;
}

export function levelFor(value: number, scale: number): number {
  if (value === 0 || scale <= 0) return 0;
  const step = Math.max(1, Math.ceil(Math.min(1, Math.abs(value) / scale) * 4));
  return value > 0 ? step : -step;
}

export function percentile(sortedAsc: number[], q: number): number {
  if (!sortedAsc.length) return 0;
  const idx = Math.min(sortedAsc.length - 1, Math.max(0, Math.ceil(q * sortedAsc.length) - 1));
  return sortedAsc[idx];
}

/** `days` cells ending on the UTC day of `endMs` (the latest data point by default). */
export function buildCalendar(daily: CurvePoint[], days = 182, endMs?: number): CalendarGrid {
  const byDay = new Map<number, number>();
  for (const p of daily) byDay.set(utcMidnight(p.t_ms), (byDay.get(utcMidnight(p.t_ms)) ?? 0) + p.value);
  const lastData = daily.length ? Math.max(...daily.map((p) => p.t_ms)) : Date.now();
  const end = utcMidnight(endMs ?? lastData);
  let start = end - (days - 1) * DAY;
  start -= weekdayMon0(start) * DAY; // back to a Monday so rows line up

  const values = [...byDay.entries()].filter(([t]) => t >= start && t <= end).map(([, v]) => Math.abs(v)).sort((a, b) => a - b);
  const scale = percentile(values.filter((v) => v > 0), 0.9);

  const weeks: CalendarCell[][] = [];
  const months: { col: number; label: string }[] = [];
  let total = 0;
  let green = 0;
  let red = 0;
  let best: CalendarCell | null = null;
  let worst: CalendarCell | null = null;
  let lastMonth = -1;
  for (let t = start; t <= end; t += DAY) {
    const col = Math.floor((t - start) / (7 * DAY));
    if (!weeks[col]) weeks[col] = [];
    const v = byDay.has(t) ? (byDay.get(t) as number) : null;
    const cell: CalendarCell = { t_ms: t, value: v, level: v === null ? 0 : levelFor(v, scale) };
    weeks[col].push(cell);
    const month = new Date(t).getUTCMonth();
    if (month !== lastMonth) {
      // label a month at the first column that starts inside it (skip a partial first week)
      if (weekdayMon0(t) === 0 || col === 0) {
        if (!months.length || months[months.length - 1].col !== col) months.push({ col, label: MONTHS[month] });
        lastMonth = month;
      }
    }
    if (v !== null) {
      total += v;
      if (v > 0) green++;
      if (v < 0) red++;
      if (!best || v > (best.value ?? -Infinity)) best = cell;
      if (!worst || v < (worst.value ?? Infinity)) worst = cell;
    }
  }
  return { weeks, months, scale, total, green, red, best, worst };
}
