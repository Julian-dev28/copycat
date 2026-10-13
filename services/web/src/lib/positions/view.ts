/**
 * Pure view math for the Portfolio positions table (components/positions/
 * PositionsTable.tsx): ROE and liquidation distance, so the table reads like
 * Hyperliquid's own positions table (entry, mark, liq, uPnL (ROE), leverage,
 * margin type, opened), not just the raw contract fields.
 *
 * Same formulas as lib/account/positions.ts `fromCopy` (Account's merged
 * positions tab): margin = |notional| / leverage, ROE = uPnL / margin x 100.
 * Kept here, independently, so this file's tests pin the Portfolio table's
 * own contract without reaching into another page's module.
 */
import type { CopyPosition } from "@/lib/api/types";

export function marginUsd(p: Pick<CopyPosition, "notional_usd" | "leverage">): number {
  return p.leverage > 0 ? Math.abs(p.notional_usd) / p.leverage : Math.abs(p.notional_usd);
}

/** Return on the margin actually at risk, not on notional (HL's own convention). Null when margin is 0 (can't divide). */
export function roePct(p: Pick<CopyPosition, "notional_usd" | "leverage" | "unrealized_pnl_usd">): number | null {
  const margin = marginUsd(p);
  return margin > 0 ? (p.unrealized_pnl_usd / margin) * 100 : null;
}

/** Adverse move still available before liquidation, as a % of mark. Null without a mark or a liquidation price (cross margin with no single liq price). */
export function liqDistancePct(p: Pick<CopyPosition, "liquidation_px" | "mark_px">): number | null {
  if (!p.liquidation_px || !p.mark_px || p.mark_px <= 0) return null;
  return (Math.abs(p.mark_px - p.liquidation_px) / p.mark_px) * 100;
}
