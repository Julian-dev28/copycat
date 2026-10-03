/**
 * Liquidation distance hint shown next to the leverage slider on /copy
 * ("50x isolated ~ 1.5% adverse move liquidates"). This is a UI estimate
 * only — the real liquidation price for an open position comes straight
 * from Hyperliquid (contracts.venue.LeaderPosition / CopyPosition.liquidation_px)
 * and is shown as-is on /positions. This module never talks to the network.
 *
 * Isolated-margin derivation:
 *   initial margin fraction  = 1 / leverage                (what you post)
 *   maintenance margin frac  = 1 / (2 * referenceMaxLeverage)
 *     Hyperliquid fixes the maintenance margin at half the *asset's* max
 *     leverage initial-margin fraction, independent of the leverage you
 *     actually choose. We don't know each coin's real max leverage from
 *     settings alone, so this hint assumes `referenceMaxLeverage` (default:
 *     MAX_LEVERAGE_CAP, i.e. the highest HL tier) — call out explicitly
 *     that coins with a lower max leverage liquidate a bit sooner than
 *     this hint shows.
 *   adverse move to liquidation = initial margin frac - maintenance margin frac
 *                                = 1/leverage - 1/(2*referenceMaxLeverage)
 *
 * Cross margin draws on the whole account's equity, not one position, so
 * a single scalar number would be misleading; we return `null` for it
 * instead of a number that looks precise but isn't.
 */
import { MAX_LEVERAGE_CAP, type MarginMode } from "./api/types";
import { clamp } from "./sizing";

export interface LiquidationHint {
  /** Adverse move %, e.g. 1.5 for "1.5%". Null for cross margin (see module doc). */
  adverseMovePct: number | null;
  /** True if the reference max leverage assumption may be optimistic for this coin. */
  isEstimate: boolean;
}

export function estimateLiquidationDistance(
  leverage: number,
  marginMode: MarginMode,
  referenceMaxLeverage: number = MAX_LEVERAGE_CAP,
): LiquidationHint {
  if (marginMode === "cross") {
    return { adverseMovePct: null, isEstimate: true };
  }
  const lev = clamp(leverage, 1, referenceMaxLeverage);
  const initialMarginFrac = 1 / lev;
  const maintenanceMarginFrac = 1 / (2 * referenceMaxLeverage);
  const adverseFrac = Math.max(0, initialMarginFrac - maintenanceMarginFrac);
  return { adverseMovePct: adverseFrac * 100, isEstimate: true };
}

/** Formats the hint the way the /copy page shows it next to the leverage slider. */
export function formatLiquidationHint(
  leverage: number,
  marginMode: MarginMode,
  referenceMaxLeverage: number = MAX_LEVERAGE_CAP,
): string {
  const { adverseMovePct } = estimateLiquidationDistance(leverage, marginMode, referenceMaxLeverage);
  const modeLabel = marginMode === "isolated" ? "isolated" : "cross";
  if (adverseMovePct === null) {
    return `${leverage}x ${modeLabel}: liquidation depends on total account equity`;
  }
  const pct = adverseMovePct < 1 ? adverseMovePct.toFixed(2) : adverseMovePct.toFixed(1);
  return `${leverage}x ${modeLabel} ~ ${pct}% adverse move liquidates`;
}
