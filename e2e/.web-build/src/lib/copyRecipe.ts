/**
 * Pure helpers behind the /copy "recipe" card and the empty-account banner.
 * Display only: services/engine/sizing is the authority on real orders.
 *
 * Hyperliquid rejects orders under $10 notional. The contract keeps
 * HL_MIN_ORDER_USD = 10.5 for rounding room, so in fixed-margin mode each
 * copy needs margin M at leverage L with M x L >= $10.50.
 */
import type { Settings } from "./api/types";
import { HL_MIN_ORDER_USD } from "./api/types";
import { applyMinOrderRule, clamp, type MinOrderResult } from "./sizing";

/** Below this equity the account cannot fund even one minimum order with any margin buffer. */
export const MIN_ACCOUNT_EQUITY_USD = 11;

export type Heat = "calm" | "warm" | "hot" | "max";

export interface Vibe {
  label: string;
  heat: Heat;
}

/** Plain-words read of a leverage number. Boundaries are inclusive upper bounds. */
export function leverageVibe(leverage: number): Vibe {
  if (leverage <= 3) return { label: "comfy", heat: "calm" };
  if (leverage <= 10) return { label: "brisk", heat: "warm" };
  if (leverage <= 25) return { label: "spicy", heat: "hot" };
  return { label: "full send", heat: "max" };
}

/** Plain-words read of the max-worse-entry tolerance. */
export function worseEntryVibe(pct: number): Vibe {
  if (pct <= 1) return { label: "sniper", heat: "calm" };
  if (pct <= 5) return { label: "picky", heat: "warm" };
  if (pct <= 20) return { label: "relaxed", heat: "hot" };
  return { label: "anything goes", heat: "max" };
}

export function isAccountTooSmall(equityUsd: number | null | undefined): boolean {
  return equityUsd !== null && equityUsd !== undefined && Number.isFinite(equityUsd) && equityUsd < MIN_ACCOUNT_EQUITY_USD;
}

/**
 * The leverage a new copy opens at, as far as settings alone can tell.
 * "max" and "match" depend on the coin / the leader, so the cap is an upper
 * bound there, flagged with `upperBound`.
 */
export function settingsLeverage(s: Pick<Settings, "leverage_mode" | "leverage" | "max_position_leverage">): {
  leverage: number;
  upperBound: boolean;
} {
  const cap = clamp(s.max_position_leverage, 1, Number.MAX_SAFE_INTEGER);
  if (s.leverage_mode === "fixed") return { leverage: clamp(s.leverage, 1, cap), upperBound: false };
  return { leverage: cap, upperBound: true };
}

/** Smallest fixed margin that clears the minimum at leverage L. */
export function minMarginForLeverage(leverage: number): number {
  return HL_MIN_ORDER_USD / Math.max(1, leverage);
}

export interface CopyRecipe {
  sizingMode: Settings["sizing_mode"];
  leverage: number;
  leverageUpperBound: boolean;
  /** Per-copy notional before the min-order rule. Null for proportional (depends on the leader). */
  notionalUsd: number | null;
  /** Min-order outcome for notionalUsd. Null for proportional. */
  minOrder: MinOrderResult | null;
  /** Fixed margin needed at this leverage to clear $10.50. Null unless fixed_margin. */
  minMarginUsd: number | null;
}

export function copyRecipe(s: Settings): CopyRecipe {
  const { leverage, upperBound } = settingsLeverage(s);
  if (s.sizing_mode === "fixed_margin") {
    const notional = Math.max(0, s.fixed_margin_usd) * leverage;
    return {
      sizingMode: s.sizing_mode,
      leverage,
      leverageUpperBound: upperBound,
      notionalUsd: notional,
      minOrder: applyMinOrderRule(notional, s.min_order_bump),
      minMarginUsd: minMarginForLeverage(leverage),
    };
  }
  if (s.sizing_mode === "fixed_notional") {
    return {
      sizingMode: s.sizing_mode,
      leverage,
      leverageUpperBound: upperBound,
      notionalUsd: s.fixed_notional_usd,
      minOrder: applyMinOrderRule(s.fixed_notional_usd, s.min_order_bump),
      minMarginUsd: null,
    };
  }
  return {
    sizingMode: s.sizing_mode,
    leverage,
    leverageUpperBound: upperBound,
    notionalUsd: null,
    minOrder: null,
    minMarginUsd: null,
  };
}
