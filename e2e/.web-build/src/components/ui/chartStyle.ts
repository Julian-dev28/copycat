/**
 * Chart styling (DESIGN 5 Charts) for the hand-rolled SVG charts, so every
 * chart and sparkline draws the same way. Spread onto SVG elements:
 *   <path d={...} {...CHART.theirLine} />  <path d={...} {...CHART.yourLine} />
 * "Their" series is a thin --fg-soft line, "your copy" a thicker --accent
 * line: the comparison is about shape, not up/down. PnL areas fill --up
 * above zero and --down below at 14%. Grid is --faint, dashed 2/4.
 */
export const CHART = {
  theirLine: { fill: "none", stroke: "var(--fg-soft)", strokeOpacity: 0.8, strokeWidth: 1.25, strokeLinejoin: "round", strokeLinecap: "round", vectorEffect: "non-scaling-stroke" },
  yourLine: { fill: "none", stroke: "var(--accent)", strokeWidth: 1.75, strokeLinejoin: "round", strokeLinecap: "round", vectorEffect: "non-scaling-stroke" },
  line: { fill: "none", stroke: "var(--fg-soft)", strokeWidth: 1.5, strokeLinejoin: "round", strokeLinecap: "round", vectorEffect: "non-scaling-stroke" },
  areaUp: { fill: "var(--up)", opacity: 0.14 },
  areaDown: { fill: "var(--down)", opacity: 0.14 },
  grid: { stroke: "var(--faint)", strokeOpacity: 0.5, strokeWidth: 1, strokeDasharray: "2 4", vectorEffect: "non-scaling-stroke" },
  zero: { stroke: "var(--faint)", strokeOpacity: 0.5, strokeWidth: 1, strokeDasharray: "2 4", vectorEffect: "non-scaling-stroke" },
  crosshair: { stroke: "var(--border-strong)", strokeWidth: 1, vectorEffect: "non-scaling-stroke" },
  /** Axis tick text: num-sm muted. */
  axisText: { fill: "var(--muted)", fontSize: 11, fontFamily: "var(--font-mono)" },
} as const;

/** Area gradient stops: series color at 18% down to 0. */
export const AREA_STOPS = [
  { offset: "0%", stopOpacity: 0.18 },
  { offset: "100%", stopOpacity: 0 },
] as const;

/** Diverging 5-step ramp for the daily PnL calendar: down -> surface-3 -> up. Pair every cell with an aria-label. */
export const DIVERGING_RAMP = [
  "color-mix(in srgb, var(--down) 70%, var(--surface-3))",
  "color-mix(in srgb, var(--down) 35%, var(--surface-3))",
  "var(--surface-3)",
  "color-mix(in srgb, var(--up) 35%, var(--surface-3))",
  "color-mix(in srgb, var(--up) 70%, var(--surface-3))",
] as const;
