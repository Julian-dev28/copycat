/**
 * Copy Fit display logic. The number itself is computed server side in
 * services/discovery/discovery/copy_fit.py (spec section 3); this file only
 * explains it: the parts in a fixed order, what each contributed, and which
 * gate or cap moved the final value. Pure functions.
 *
 *   fit = 100 * sum(weight * part), then gates/caps in order:
 *   inactive -> 0, liquidated -> <= 20, too_few_trades -> <= 40, hft/vault -> <= 50
 */
import type { CopyFit } from "./types";

/** Display order: sim first (it is the dominant term), then the trader-quality terms. */
export const PART_ORDER = ["sim", "sharpe", "drawdown", "consistency", "sample", "win_rate", "capacity", "recency"] as const;

export const PART_META: Record<string, { label: string; hint: string }> = {
  sim: { label: "Your copy", hint: "Sim score at your settings and equity, ranked against the cohort" },
  sharpe: { label: "Sharpe", hint: "30d risk-adjusted return, ranked" },
  drawdown: { label: "Drawdown", hint: "Shallower 30d max drawdown ranks higher" },
  consistency: { label: "Green days", hint: "Share of profitable days in 30d, ranked" },
  sample: { label: "Sample size", hint: "Round trips in 30d; full marks at 50" },
  win_rate: { label: "Win rate", hint: "Share of winning round trips in 30d, ranked" },
  capacity: { label: "Copy capacity", hint: "Share of his opens the sim could execute at your size" },
  recency: { label: "Recency", hint: "Full marks if he traded in the last 24h, zero at 7 days" },
};

/** Caps in the order discovery applies them, with the ceiling each imposes. */
export const CAP_RULES: { flag: string; ceiling: number | null; text: string }[] = [
  { flag: "inactive", ceiling: 0, text: "Under $1,000 or no fill in 7 days: set to 0" },
  { flag: "liquidated", ceiling: 20, text: "A copy got liquidated in the sim: capped at 20" },
  { flag: "too_few_trades", ceiling: 40, text: "Fewer than 5 copies in the sim: capped at 40" },
  { flag: "hft", ceiling: 50, text: "Trades too fast for a 5s poll: capped at 50" },
  { flag: "vault", ceiling: 50, text: "A vault, PnL is pooled: capped at 50" },
  { flag: "fills_truncated", ceiling: null, text: "Only his latest 10,000 fills are visible, trade stats may undercount" },
];

export interface FitSegment {
  key: string;
  label: string;
  hint: string;
  /** 0..1, the part before weighting. */
  part: number;
  weight: number;
  /** Points this part adds to the blend: part * weight * 100. */
  points: number;
  /** Points available: weight * 100. Also the segment's width in the bar, in %. */
  max: number;
}

function clamp01(n: number): number {
  return Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : 0;
}

/** Segments in PART_ORDER, then any part the api added that we don't know yet, so nothing is hidden. */
export function fitSegments(fit: Pick<CopyFit, "parts" | "weights">): FitSegment[] {
  const keys: string[] = PART_ORDER.filter((k) => k in fit.weights || k in fit.parts);
  for (const k of Object.keys(fit.weights)) if (!keys.includes(k)) keys.push(k);
  return keys.map((key) => {
    const part = clamp01(fit.parts[key] ?? 0);
    const weight = Math.max(0, fit.weights[key] ?? 0);
    const meta = PART_META[key] ?? { label: key.replaceAll("_", " "), hint: "" };
    return { key, label: meta.label, hint: meta.hint, part, weight, points: part * weight * 100, max: weight * 100 };
  });
}

/** The pre-cap blend: sum of segment points. */
export function blendedFit(fit: Pick<CopyFit, "parts" | "weights">): number {
  return fitSegments(fit).reduce((a, s) => a + s.points, 0);
}

export interface CapLine {
  flag: string;
  text: string;
  /** True when this cap actually lowered the number (blend above the ceiling). */
  binding: boolean;
}

export function capLines(fit: CopyFit): CapLine[] {
  const blend = blendedFit(fit);
  const out: CapLine[] = [];
  for (const rule of CAP_RULES) {
    if (!fit.caps.some((c) => c.split(":")[0] === rule.flag)) continue;
    out.push({ flag: rule.flag, text: rule.text, binding: rule.ceiling !== null && blend > rule.ceiling + 1e-9 });
  }
  return out;
}

export type FitGrade = "strong" | "fair" | "weak" | "none";

export function fitGrade(value: number | null | undefined): FitGrade {
  if (value === null || value === undefined || !Number.isFinite(value)) return "none";
  if (value >= 70) return "strong";
  if (value >= 40) return "fair";
  return "weak";
}

/** The three parts that added the most points, for the card's one-line "why". */
export function topParts(fit: Pick<CopyFit, "parts" | "weights">, n = 3): FitSegment[] {
  return [...fitSegments(fit)].sort((a, b) => b.points - a.points || a.key.localeCompare(b.key)).slice(0, n);
}
