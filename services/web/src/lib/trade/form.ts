/**
 * The ticket form: draft state -> request body, which button to show, the
 * % chips, amount parsing for $10 to $10M. Pure, unit-tested.
 */
import { MAX_LEVERAGE_CAP } from "@/lib/api/types";
import { parseAmount } from "@/lib/scout/query";
import type { ExposureMode, MarginMode, SmallAccountMode, TradeOverride, TradeSettings, WalletCopyRequest, WalletPosition } from "./types";

export const MIN_INVEST_USD = 1;
export const MAX_INVEST_USD = 100_000_000;
export const CHIPS = [25, 50, 75, 100] as const;

export interface TicketDraft {
  amountText: string;
  mode: ExposureMode;
  leverage: number;
  marginMode: MarginMode;
  maxWorseEntryPct: number;
  smallMode: SmallAccountMode;
}

/** Fresh ticket for a wallet: its current allocation if invested, else the book-wide defaults. */
export function initialDraft(settings: TradeSettings | undefined, address: string | null, wallet?: WalletPosition | null): TicketDraft {
  const o: TradeOverride | undefined = address ? settings?.leader_overrides[address] : undefined;
  const alloc = wallet?.allocation_usd ?? o?.allocation_usd ?? null;
  return {
    amountText: alloc && alloc > 0 ? trimNum(alloc) : "",
    mode: wallet?.exposure_mode ?? o?.exposure_mode ?? settings?.exposure_mode ?? "match",
    leverage: clampLeverage(wallet?.target_leverage ?? o?.target_leverage ?? settings?.target_leverage ?? 5),
    marginMode: o?.margin_mode ?? settings?.margin_mode ?? "isolated",
    maxWorseEntryPct: o?.max_worse_entry_pct ?? settings?.max_worse_entry_pct ?? 10,
    smallMode: wallet?.small_account_mode ?? o?.small_account_mode ?? settings?.small_account_mode ?? "concentrate",
  };
}

export function clampLeverage(l: number): number {
  return Math.max(1, Math.min(MAX_LEVERAGE_CAP, Math.round(Number.isFinite(l) ? l : 1)));
}

/** "1,000" / "$2.5k" / "1.2m" -> dollars; null for blank or garbage. */
export function parseInvest(text: string): number | null {
  const v = parseAmount(text);
  return v === null || v === undefined || !Number.isFinite(v) || v < 0 ? null : v;
}

function trimNum(n: number): string {
  return String(Math.round(n * 100) / 100);
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

/** The POST body. Only sends keys the contract has; target_leverage only for target, small_account_mode only when the api knows it. */
export function buildCopyRequest(d: TicketDraft, amount: number, opts: { smallModeSupported: boolean }): WalletCopyRequest {
  const body: WalletCopyRequest = {
    allocation_usd: Math.round(amount * 100) / 100,
    exposure_mode: d.mode,
    margin_mode: d.marginMode,
    max_worse_entry_pct: d.maxWorseEntryPct,
  };
  if (d.mode === "target") body.target_leverage = clampLeverage(d.leverage);
  if (opts.smallModeSupported) body.small_account_mode = d.smallMode;
  return body;
}

export type TicketAction = "copy" | "update" | "unchanged";

/** New wallet -> copy; invested and something changed -> update; else unchanged. */
export function ticketAction(d: TicketDraft, amount: number | null, current: TicketDraft | null, invested: boolean): TicketAction {
  if (!invested || !current) return "copy";
  const same =
    amount !== null && Math.abs(amount - (parseInvest(current.amountText) ?? -1)) < 0.005 &&
    d.mode === current.mode && (d.mode === "match" || d.leverage === current.leverage) &&
    d.marginMode === current.marginMode && d.maxWorseEntryPct === current.maxWorseEntryPct && d.smallMode === current.smallMode;
  return same ? "unchanged" : "update";
}
