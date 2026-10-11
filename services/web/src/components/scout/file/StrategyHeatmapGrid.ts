/**
 * The "When they enter" chart data (UX audit #9). A real cell grid only when the
 * api sent `entries_by_dow_hour` (7 x 24 entry counts, UTC, Monday first);
 * otherwise (fingerprints cached before the field) null, and the chart draws
 * the two exact histograms instead of cells invented from their product.
 */
export interface RealGrid {
  /** cells[weekday][hour], real entry counts. */
  cells: number[][];
  max: number;
  hours: number[];
  weekdays: number[];
  total: number;
  peakHour: number | null;
  peakWeekday: number | null;
}

const argmax = (xs: number[]): number | null => {
  let best: number | null = null;
  xs.forEach((v, i) => {
    if (v > 0 && (best === null || v > xs[best])) best = i;
  });
  return best;
};

const count = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) && v > 0 ? v : 0);

/** The real matrix, or null when it is missing or not 7 x 24. */
export function realGrid(m: number[][] | null | undefined): RealGrid | null {
  if (!Array.isArray(m) || m.length !== 7 || !m.every((r) => Array.isArray(r) && r.length === 24)) return null;
  const cells = m.map((r) => r.map(count));
  const weekdays = cells.map((r) => r.reduce((a, b) => a + b, 0));
  const hours = Array.from({ length: 24 }, (_, h) => cells.reduce((a, r) => a + r[h], 0));
  const total = weekdays.reduce((a, b) => a + b, 0);
  return { cells, max: Math.max(0, ...cells.flat()), hours, weekdays, total, peakHour: argmax(hours), peakWeekday: argmax(weekdays) };
}

/** Exact per-axis bars for the fallback: 24 hours and 7 weekdays, padded or cut to length. */
export function axisBars(hourHist: number[] | null | undefined, weekdayHist: number[] | null | undefined): { hours: number[]; weekdays: number[]; total: number } {
  const fit = (xs: number[] | null | undefined, n: number) => Array.from({ length: n }, (_, i) => count(xs?.[i]));
  const hours = fit(hourHist, 24);
  const weekdays = fit(weekdayHist, 7);
  return { hours, weekdays, total: Math.max(hours.reduce((a, b) => a + b, 0), weekdays.reduce((a, b) => a + b, 0)) };
}
