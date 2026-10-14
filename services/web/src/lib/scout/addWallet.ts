/**
 * The Scout board's "Add wallet" box (contract v15, POST /api/scout/custom):
 * what the user typed or pasted -> one address, or the message to show
 * instead. Accepts a bare 0x address, one wrapped in spaces or quotes, or an
 * explorer link (lib/trade/pasteAddress.ts). Pure, tested.
 */
import { extractAddress } from "@/lib/trade/pasteAddress";

export type WalletInput = { address: string; error?: undefined } | { address?: undefined; error: string };

export const EMPTY_INPUT = "Paste a wallet address first.";
export const BAD_INPUT = "That is not a wallet address. Paste one 0x address with 40 hex characters, or an explorer link to it.";

export function parseWalletInput(text: string): WalletInput {
  if (!text.trim()) return { error: EMPTY_INPUT };
  const address = extractAddress(text);
  return address ? { address } : { error: BAD_INPUT };
}

/** 0x1234…abcd, for toasts and button labels. */
export function shortAddr(address: string): string {
  const a = address.toLowerCase();
  return a.length > 12 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a;
}

/** The toast after a successful add. `queued` = scout serve still has to build it. */
export function addedText(address: string, queued: boolean): string {
  return queued ? `Added ${shortAddr(address)} to Scout, building its file` : `${shortAddr(address)} is on the Scout board`;
}
