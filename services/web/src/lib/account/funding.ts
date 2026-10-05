/**
 * Funding rules the Account page enforces before anything reaches a wallet or
 * the api. Pure. The api and vault re-check every one of these server-side;
 * these exist so the user sees the problem before signing, not after.
 *
 * Facts (bridge, USDC, 5 USDC minimum, $1 withdraw fee) come from
 * GET /api/accounts/{id}/funding-info, never from constants here.
 */
import { decodeFunctionResult, encodeFunctionData, erc20Abi, formatUnits, parseUnits } from "viem";
import { isValidAddress, normAddr } from "@/lib/address";
import { formatUsd, shortenAddress } from "@/lib/format";
import type { AccountBalances, FundingLimits, TradingAccount, UserActionKind } from "./types";

export const USDC_DECIMALS = 6;
const AMOUNT_RE = /^\d{1,12}(\.\d{1,6})?$/;

/** "12.5" -> 12.5. Null for anything that is not a plain decimal with at most 6 decimals. */
export function parseUsd(text: string): number | null {
  const t = text.trim();
  if (!AMOUNT_RE.test(t)) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

/** Floor to cents for a "Max" button, so rounding never asks for more than there is. */
export const floorCents = (n: number) => Math.max(0, Math.floor(n * 100 + 1e-9) / 100);

export function depositProblem(amountText: string, balanceUsd: number | null, minUsd: number): string | null {
  if (!amountText.trim()) return "Enter an amount.";
  const amt = parseUsd(amountText);
  if (amt === null) return "Enter a USDC amount (at most 6 decimals).";
  if (amt < minUsd) return `The minimum deposit is ${minUsd} USDC. Hyperliquid never credits a smaller deposit: it would be lost for good.`;
  if (balanceUsd !== null && amt > balanceUsd) return `Your wallet only holds ${formatUsd(balanceUsd)} of USDC on Arbitrum.`;
  return null;
}

/** The live maximum for one action, or null when the balances could not be read. */
export function actionCap(kind: UserActionKind, toPerp: boolean, limits: FundingLimits | null | undefined): number | null {
  if (!limits) return null;
  return kind === "usd_class_transfer" && toPerp ? limits.spot_usdc_free_usd : limits.perps_withdrawable_usd;
}

export interface ActionForm {
  amount: string;
  toPerp: boolean;
  destination: string;
  confirm: string;
  passphrase: string;
}

export const emptyForm = (toPerp = true): ActionForm => ({ amount: "", toPerp, destination: "", confirm: "", passphrase: "" });

export interface ActionContext {
  limits: FundingLimits | null | undefined;
  feeUsd: number;
  own: string;
  /** Addresses of the user's other vault accounts (usdSend may only go there). */
  others: string[];
  needsPassphrase: boolean;
}

/** Where a withdrawal goes: the account itself unless another address was typed. */
export function withdrawDestination(form: ActionForm, own: string): string {
  return form.destination.trim() ? normAddr(form.destination) : normAddr(own);
}

export function isOtherDestination(form: ActionForm, own: string): boolean {
  return withdrawDestination(form, own) !== normAddr(own);
}

export function actionProblem(kind: UserActionKind, form: ActionForm, ctx: ActionContext): string | null {
  if (kind === "usd_class_transfer" && ctx.limits?.unified) {
    return "This is a unified account: spot and perps share one USDC balance. There is nothing to move.";
  }
  if (kind === "usd_send") {
    if (!isValidAddress(form.destination)) return "Pick one of your accounts to send to.";
    if (normAddr(form.destination) === normAddr(ctx.own)) return "That is this account.";
    if (!ctx.others.map(normAddr).includes(normAddr(form.destination))) return "Sends can only go to another account in this copycat.";
  }
  if (kind === "withdraw" && form.destination.trim()) {
    if (!isValidAddress(form.destination)) return "The destination is not a 0x address.";
    if (isOtherDestination(form, ctx.own) && normAddr(form.confirm) !== normAddr(form.destination)) {
      return `Type ${shortenAddress(form.destination)} again in full to confirm it. Funds sent to a wrong address are gone.`;
    }
  }
  if (!form.amount.trim()) return "Enter an amount.";
  const amt = parseUsd(form.amount);
  if (amt === null || amt <= 0) return "Enter a USDC amount above 0 (at most 6 decimals).";
  const cap = actionCap(kind, form.toPerp, ctx.limits);
  if (cap === null) return "Balances could not be read from Hyperliquid. Retry in a moment.";
  if (amt > cap + 1e-9) return `At most ${formatUsd(cap)} is available for this.`;
  if (kind === "withdraw" && amt <= ctx.feeUsd) return `A withdrawal must be more than the ${formatUsd(ctx.feeUsd)} fee.`;
  if (ctx.needsPassphrase && !form.passphrase) return "Enter the passphrase.";
  return null;
}

/** Show "Move to perps" up front: perps is about empty while spot holds USDC (non-unified only). */
export function moveHint(balances: Pick<AccountBalances, "perps_usd">, limits: FundingLimits | null | undefined): boolean {
  if (!limits || limits.unified) return false;
  return balances.perps_usd < 1 && limits.spot_usdc_free_usd >= 0.01;
}

/** How this account's money actions get signed. */
export type SignerPath = "passphrase" | "browser" | "hl_app";

export function signerPath(account: Pick<TradingAccount, "kind" | "has_main_key">, hasWallet: boolean): SignerPath {
  if (account.kind === "created" && account.has_main_key) return "passphrase";
  return hasWallet ? "browser" : "hl_app";
}

/** Deposit credit check: the balance grew by (almost) the amount since the transfer was sent. */
export function isCredited(baselineUsd: number, nowUsd: number, amountUsd: number): boolean {
  return nowUsd - baselineUsd >= amountUsd * 0.99 - 0.01;
}

// ── ERC-20 (USDC on Arbitrum) ─────────────────────────────────────────────────

export const usdToUnits = (text: string): bigint => parseUnits(text.trim(), USDC_DECIMALS);
export const unitsToUsd = (units: bigint): number => Number(formatUnits(units, USDC_DECIMALS));

export function transferCalldata(to: string, units: bigint): `0x${string}` {
  return encodeFunctionData({ abi: erc20Abi, functionName: "transfer", args: [to as `0x${string}`, units] });
}

export function balanceOfCalldata(owner: string): `0x${string}` {
  return encodeFunctionData({ abi: erc20Abi, functionName: "balanceOf", args: [owner as `0x${string}`] });
}

export function decodeBalance(data: unknown): bigint {
  if (typeof data !== "string" || !data.startsWith("0x") || data === "0x") throw new Error("the wallet returned no balance");
  return decodeFunctionResult({ abi: erc20Abi, functionName: "balanceOf", data: data as `0x${string}` });
}
