/**
 * Ticket amount helpers: the % chips, max, amount parsing for $10 to $10M.
 * Draft state and request bodies live in draft.ts. Pure, unit-tested.
 */
import { MAX_LEVERAGE_CAP } from "@/lib/api/types";
import { parseAmount } from "@/lib/scout/query";

export const MIN_INVEST_USD = 1;
export const MAX_INVEST_USD = 100_000_000;
export const CHIPS = [25, 50, 75, 100] as const;

export function clampLeverage(l: number): number {
  return Math.max(1, Math.min(MAX_LEVERAGE_CAP, Math.round(Number.isFinite(l) ? l : 1)));
}

/** "1,000" / "$2.5k" / "1.2m" -> dollars; null for blank or garbage. */
export function parseInvest(text: string): number | null {
  const v = parseAmount(text);
  return v === null || v === undefined || !Number.isFinite(v) || v < 0 ? null : v;
}

/** Dollars from a % chip of `maxUsd`, floored to cents (never over the max). */
export function chipAmount(maxUsd: number | null | undefined, pct: number): number | null {
  if (!maxUsd || maxUsd <= 0) return null;
  return Math.floor(maxUsd * (pct / 100) * 100) / 100;
}

/**
 * Max you can put in: free margin plus what this wallet already ties up
 * (re-sizing a wallet frees its own margin first). Null when unknown.
 */
export function maxInvest(availableMarginUsd: number | null | undefined, walletMarginUsd = 0): number | null {
  if (availableMarginUsd === null || availableMarginUsd === undefined || !Number.isFinite(availableMarginUsd)) return null;
  return Math.max(0, Math.floor((Math.max(0, availableMarginUsd) + Math.max(0, walletMarginUsd)) * 100) / 100);
}

export type AmountCheck = { ok: true; warn: string | null } | { ok: false; error: string };

export function checkAmount(amount: number | null, maxUsd: number | null): AmountCheck {
  if (amount === null) return { ok: false, error: "Enter an amount" };
  if (amount < MIN_INVEST_USD) return { ok: false, error: `At least $${MIN_INVEST_USD}` };
  if (amount > MAX_INVEST_USD) return { ok: false, error: "That is more than any account here" };
  if (maxUsd !== null && amount > maxUsd + 0.005) {
    return { ok: true, warn: "More than your free margin: copies open only as margin frees up." };
  }
  return { ok: true, warn: null };
}
