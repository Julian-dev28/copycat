/**
 * Slider geometry (DESIGN 5 Sliders): a value's position on the track as a
 * percent, clamped. Tick labels must sit at their real positions (the audit
 * found 1x/10x/25x/50x spaced evenly on a linear track). Pure, unit-tested.
 */
export function trackPct(value: number, min: number, max: number): number {
  if (!(max > min) || !Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100));
}

/** Ticks inside [min, max], each with its true position. */
export function ticksAt(ticks: number[], min: number, max: number): { value: number; pct: number }[] {
  return ticks.filter((t) => t >= min && t <= max).map((value) => ({ value, pct: trackPct(value, min, max) }));
}
