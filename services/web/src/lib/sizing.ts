/**
 * Pure sizing math for the /copy settings page. These are UI preview
 * helpers only — the engine (services/engine/sizing) is the authoritative
 * implementation that actually places orders. Nothing here calls the
 * network; every function is deterministic (same input -> same output),
 * which is why it lives in deterministic space with its own unit tests
 * instead of being eyeballed in a component.
 *
 * Mirrors the semantics documented on contracts.models.Settings:
 *   fixed_margin:   new copy posts `fixed_margin_usd` margin at the
 *                   resolved leverage -> notional = margin * leverage.
 *   fixed_notional: new copy is a flat notional, independent of leverage.
 *   proportional:   his exposure / his equity * our allocation * size_multiplier,
 *                   where our allocation = sleeve_frac * our_equity.
 */
import type { LeverageMode, MarginMode, SizingMode } from "./api/types";
import { HL_MIN_ORDER_USD } from "./api/types";

export interface SizingInputs {
  sizingMode: SizingMode;
  fixedMarginUsd: number;
  fixedNotionalUsd: number;
  sizeMultiplier: number;
  sleeveFrac: number;
  minOrderBump: boolean;
}

export interface LeverageInputs {
  leverageMode: LeverageMode;
  fixedLeverage: number;
  maxLeverageCap: number;
  /** The leader's leverage on the coin being copied, if known (for "match" mode previews). */
  leaderLeverage?: number | null;
}

/** Resolves the leverage a copy would open at, for display only. */
export function resolveEffectiveLeverage(inputs: LeverageInputs): number {
  const { leverageMode, fixedLeverage, maxLeverageCap, leaderLeverage } = inputs;
  switch (leverageMode) {
    case "max":
      return maxLeverageCap;
    case "fixed":
      return clamp(fixedLeverage, 1, maxLeverageCap);
    case "match":
      return leaderLeverage && leaderLeverage > 0
        ? clamp(Math.round(leaderLeverage), 1, maxLeverageCap)
        : maxLeverageCap; // unknown leader leverage: preview falls back to max, same as "no data yet"
  }
}

export interface ProportionalInputs {
  leaderNotionalUsd: number;
  leaderEquityUsd: number;
  ourEquityUsd: number;
}

/**
 * Preview notional for one hypothetical copy, in USD, before the
 * HL_MIN_ORDER_USD bump/skip rule is applied. Returns 0 for degenerate
 * inputs (e.g. leader equity <= 0) rather than NaN/Infinity.
 */
export function previewNotionalUsd(sizing: SizingInputs, leverage: number, proportional?: ProportionalInputs): number {
  switch (sizing.sizingMode) {
    case "fixed_margin":
      return Math.max(0, sizing.fixedMarginUsd) * Math.max(1, leverage);
    case "fixed_notional":
      return Math.max(0, sizing.fixedNotionalUsd);
    case "proportional": {
      if (!proportional) return 0;
      const { leaderNotionalUsd, leaderEquityUsd, ourEquityUsd } = proportional;
      if (leaderEquityUsd <= 0) return 0;
      const exposureRatio = leaderNotionalUsd / leaderEquityUsd;
      const allocationUsd = clamp(sizing.sleeveFrac, 0, 1) * Math.max(0, ourEquityUsd);
      return Math.max(0, exposureRatio * allocationUsd * sizing.sizeMultiplier);
    }
  }
}

export interface MinOrderResult {
  /** The notional the engine would actually send, after the min-order rule. */
  notionalUsd: number;
  /** True if this copy would be skipped entirely (below minimum, bump disabled or too far below to bump). */
  skipped: boolean;
  /** True if the raw notional was bumped up to HL_MIN_ORDER_USD. */
  bumped: boolean;
}

/**
 * Applies the same min-order rule described by Settings.min_order_bump:
 * "bump to HL_MIN_ORDER_USD when >= 25% of it". Below 25% of the minimum,
 * bumping would multiply the intended size by >4x, so it's skipped instead.
 */
export function applyMinOrderRule(rawNotionalUsd: number, minOrderBump: boolean): MinOrderResult {
  if (rawNotionalUsd >= HL_MIN_ORDER_USD) {
    return { notionalUsd: rawNotionalUsd, skipped: false, bumped: false };
  }
  if (minOrderBump && rawNotionalUsd >= HL_MIN_ORDER_USD * 0.25) {
    return { notionalUsd: HL_MIN_ORDER_USD, skipped: false, bumped: true };
  }
  return { notionalUsd: 0, skipped: true, bumped: false };
}

/**
 * The daily loss limit is stored as a non-positive number
 * (Settings.daily_loss_limit_usd, 0 = off). The UI shows the operator a
 * plain positive "lose at most $X/day" magnitude; these two functions are
 * the only place that sign flip happens, so it can't drift between forms.
 */
export function dailyLossLimitToStored(magnitudeUsd: number): number {
  if (!Number.isFinite(magnitudeUsd) || magnitudeUsd <= 0) return 0;
  return -Math.abs(magnitudeUsd);
}

export function storedToDailyLossMagnitude(storedUsd: number): number {
  if (!Number.isFinite(storedUsd)) return 0;
  return Math.abs(Math.min(0, storedUsd));
}

export function marginModeLabel(mode: MarginMode): string {
  return mode === "isolated" ? "Isolated" : "Cross";
}

export function clamp(value: number, min: number, max: number): number {
  if (Number.isNaN(value)) return min;
  return Math.min(max, Math.max(min, value));
}
