/**
 * Copy Fit display logic. The number itself is computed server side in
 * services/discovery/discovery/copy_fit.py (spec section 3); this file only
 * explains it: the parts in a fixed order, what each contributed, and which
 * gate or cap moved the final value. Pure functions.
 *
 *   fit = 100 * sum(weight * part), then gates/caps in order:
 *   inactive -> 0, liquidated -> <= 20, too_few_trades -> <= 40, hft/vault -> <= 50
 */
import { formatPct, formatSignedPct } from "@/lib/format";
import type { CopyFit, TraderScore } from "./types";

/** Display order: sim first (it is the dominant term), then the trader-quality terms. */
export const PART_ORDER = ["sim", "sharpe", "drawdown", "consistency", "sample", "win_rate", "capacity", "recency"] as const;

export const PART_META: Record<string, { label: string; hint: string }> = {
  sim: { label: "Your copy", hint: "Sim score at your settings and the board's sim equity (see the page note), ranked against the cohort" },
  sharpe: { label: "Sharpe", hint: "30d risk-adjusted return, ranked" },
  drawdown: { label: "Drawdown", hint: "Shallower 30d max drawdown ranks higher" },
  consistency: { label: "Green days", hint: "Share of profitable days in 30d, ranked" },
  sample: { label: "Sample size", hint: "Round trips in 30d; full marks at 50" },
  win_rate: { label: "Win rate", hint: "Share of winning round trips in 30d, ranked" },
  capacity: { label: "Copy capacity", hint: "Share of their opens the sim could execute at the board's sim equity, not necessarily your own" },
  recency: { label: "Recency", hint: "Full marks if they traded in the last 24h, zero at 7 days" },
};

/** Caps in the order discovery applies them, with the ceiling each imposes. */
export const CAP_RULES: { flag: string; ceiling: number | null; text: string }[] = [
  { flag: "inactive", ceiling: 0, text: "Under $1,000 or no fill in 7 days: set to 0" },
  { flag: "liquidated", ceiling: 20, text: "A copy got liquidated in the sim: capped at 20" },
  { flag: "wallet_liquidated", ceiling: 50, text: "They were liquidated for real in the last 30d: capped at 50" },
  { flag: "too_few_trades", ceiling: 40, text: "Fewer than 5 copies in the sim: capped at 40" },
  { flag: "hft", ceiling: 50, text: "Trades too fast for a 5s poll: capped at 50" },
  { flag: "vault", ceiling: 50, text: "A vault, PnL is pooled: capped at 50" },
  { flag: "coattail", ceiling: 50, text: "Opens often land soon after another top wallet's: capped at 50" },
  { flag: "fills_truncated", ceiling: null, text: "Only their latest 10,000 fills are visible, trade stats may undercount" },
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

/**
 * Copy Fit bucket for the single-hue accent ramp (DESIGN 3.4): 90+, 70 to 89,
 * 50 to 69, below 50. A score is a ranking, not money, so it never uses
 * up/down colors. 3 = strongest; null = not scored.
 */
export type FitTier = 0 | 1 | 2 | 3;

export function fitTier(value: number | null | undefined): FitTier | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  if (value >= 90) return 3;
  if (value >= 70) return 2;
  if (value >= 50) return 1;
  return 0;
}

/**
 * The card's one-line "why", worded as score points so it can't be read as
 * a return (UX audit: "Your copy +37" looked like +37%):
 *   "Points: Your copy 37 · Sharpe 15 · Green days 10 (of 100)"
 */
export function fitPartsLine(fit: Pick<CopyFit, "parts" | "weights">, n = 3): string {
  const parts = topParts(fit, n).filter((p) => p.points >= 0.5);
  if (!parts.length) return "No part scored above zero";
  const words = parts.map((p) => `${p.label} ${Math.round(p.points)}`);
  return `Points: ${words.join(" · ")} (of 100)`;
}

/** Matches discovery/scout/simstage.py capacity_reason()'s stable "N% of skipped opens: <reason>" format (pinned by services/discovery/tests/test_scout_simstage.py), so the reason clause can be reused in a different sentence shape without the sim's wording itself becoming web code's business. */
const CAPACITY_NOTE_RE = /^\d+% of skipped opens: (.+)$/;

export interface IfCopiedText {
  /** "Your copy, 30d: -0.4%, worst dip 0.0%." or, with nothing simulated, why. */
  headline: string;
  /** "Only 4% of their opens fit your size; the rest were under the $10.50 minimum order at your size." null when there is nothing to explain (not simulated, or capacity high enough that the sim stays quiet about it). */
  capacity: string | null;
}

/**
 * "If you copied" as sentences a trader can read in one pass (UX audit:
 * "IF YOU COPIED 30D -0.4% · max dip 0.0% · capacity 4% · 100% of skipped
 * opens: under the $10.50 minimum order at your size" read like a raw stats
 * dump in both the good case, where it says nothing, and the starved case,
 * where the one fact that matters -- most of their opens never fit -- was
 * buried after two middle dots).
 */
export function ifCopiedText(s: Pick<TraderScore, "sim_copies" | "sim_return_pct" | "sim_max_drawdown_pct" | "sim_copy_capacity_pct" | "sim_capacity_note">): IfCopiedText {
  if (s.sim_copies === 0) return { headline: "No copy opened in the 30d sim", capacity: null };
  const headline = `Your copy, 30d: ${formatSignedPct(s.sim_return_pct)}, worst dip ${formatPct(Math.abs(s.sim_max_drawdown_pct))}.`;
  const cap = s.sim_copy_capacity_pct;
  if (cap === null || cap === undefined) return { headline, capacity: null };
  const capPct = formatPct(cap, 0);
  const reason = s.sim_capacity_note?.match(CAPACITY_NOTE_RE)?.[1] ?? null;
  const capacity = reason ? `Only ${capPct} of their opens fit your size; the rest were ${reason}.` : `${capPct} of their opens fit your size.`;
  return { headline, capacity };
}
