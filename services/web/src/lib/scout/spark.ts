/**
 * SVG geometry for Scout's sparklines and line chart. Pure: points in, path
 * strings and scales out, so the shapes are unit-tested and the components
 * only render. No chart library: two polylines and a zero line don't need one.
 */
import type { CurvePoint } from "./types";

export interface Scale {
  (v: number): number;
  domain: [number, number];
  range: [number, number];
}

/** Linear scale. A zero-width domain maps everything to the middle of the range. */
export function linearScale(domain: [number, number], range: [number, number]): Scale {
  const [d0, d1] = domain;
  const [r0, r1] = range;
  const span = d1 - d0;
  const f = ((v: number) => (span === 0 ? (r0 + r1) / 2 : r0 + ((v - d0) / span) * (r1 - r0))) as Scale;
  f.domain = domain;
  f.range = range;
  return f;
}

function r2(n: number): string {
  // 2 decimals, and no "-0"
  const s = (Math.round(n * 100) / 100).toFixed(2).replace(/\.?0+$/, "");
  return s === "-0" ? "0" : s;
}

/** "M x y L x y ..." through every point. Empty string for no points. */
export function linePath(points: CurvePoint[], x: (t: number) => number, y: (v: number) => number): string {
  return points.map((p, i) => `${i ? "L" : "M"}${r2(x(p.t_ms))} ${r2(y(p.value))}`).join(" ");
}

/** [min, max] of values across series, always including 0 so the zero line is on the plot. */
export function valueExtent(series: CurvePoint[][], includeZero = true): [number, number] {
  let lo = includeZero ? 0 : Infinity;
  let hi = includeZero ? 0 : -Infinity;
  for (const s of series) for (const p of s) {
    if (p.value < lo) lo = p.value;
    if (p.value > hi) hi = p.value;
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 0];
  return [lo, hi];
}

export function timeExtent(series: CurvePoint[][]): [number, number] {
  let lo = Infinity;
  let hi = -Infinity;
  for (const s of series) for (const p of s) {
    if (p.t_ms < lo) lo = p.t_ms;
    if (p.t_ms > hi) hi = p.t_ms;
  }
  return Number.isFinite(lo) ? [lo, hi] : [0, 0];
}

export interface Sparkline {
  width: number;
  height: number;
  /** Line through every point. */
  path: string;
  /** Closed area between the line and the zero line, for the soft fill. */
  area: string;
  /** y of value 0 in px; the line is green above it, red below (two clip rects). */
  zeroY: number;
  last: CurvePoint;
  /** Net change over the series: last - first. */
  change: number;
}

/**
 * A PnL sparkline rebased so the first point is 0 (the window start), with
 * the zero line inside the plot. Returns null with fewer than 2 points:
 * one point is not a trend, and the card shows "no curve yet" instead.
 */
export function buildSparkline(points: CurvePoint[], width: number, height: number, pad = 2): Sparkline | null {
  if (points.length < 2) return null;
  const sorted = [...points].sort((a, b) => a.t_ms - b.t_ms);
  const base = sorted[0].value;
  const rebased = sorted.map((p) => ({ t_ms: p.t_ms, value: p.value - base }));
  const x = linearScale(timeExtent([rebased]), [pad, width - pad]);
  const [lo, hi] = valueExtent([rebased]);
  const y = linearScale([lo, hi], [height - pad, pad]);
  const zeroY = y(0);
  const path = linePath(rebased, x, y);
  const first = rebased[0];
  const last = rebased[rebased.length - 1];
  const area = `${path} L${r2(x(last.t_ms))} ${r2(zeroY)} L${r2(x(first.t_ms))} ${r2(zeroY)} Z`;
  return { width, height, path, area, zeroY, last, change: last.value - first.value };
}

/**
 * "Nice" axis ticks: steps of 1, 2, 2.5 or 5 x 10^k covering [lo, hi],
 * about `count` of them. Always includes 0 when the range crosses it.
 */
export function niceTicks(lo: number, hi: number, count = 4): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [];
  if (lo === hi) return [lo];
  const raw = (hi - lo) / Math.max(1, count);
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) {
    out.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toPrecision(12)));
  }
  return out;
}
