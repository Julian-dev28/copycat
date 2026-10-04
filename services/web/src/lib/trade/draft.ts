/**
 * Ticket draft (contract v7): Use global vs Custom for this wallet, the
 * per-field "inherit" resets, the request body, and which button to show.
 * Pure, unit-tested.
 *
 * Inheritable fields are null when they follow the Settings tab. A null is
 * never sent: an unset field in a custom WalletCopyRequest inherits server side.
 */
import { normAddr } from "@/lib/address";
import { clampLeverage, parseInvest } from "./form";
import type {
  ExposureMode, MarginMode, SettingsSource, SmallAccountMode, TradeOverride, TradeSettings, WalletCopyRequest, WalletPosition,
} from "./types";

export interface TicketDraft {
  source: SettingsSource;
  amountText: string;
  mode: ExposureMode;
  leverage: number;
  marginMode: MarginMode | null;
  maxWorseEntryPct: number | null;
  smallMode: SmallAccountMode | null;
  onlyNew: boolean | null;
}

export type InheritableField = "marginMode" | "maxWorseEntryPct" | "smallMode" | "onlyNew";

export interface ApiCaps {
  /** v7: settings_source, per-wallet leverage_mode and only_new_positions. */
  v7: boolean;
  /** v5: small_account_mode. */
  smallMode: boolean;
}

export function apiCaps(settings: TradeSettings | undefined): ApiCaps {
  return {
    v7: (settings?.contract_version ?? 0) >= 7,
    smallMode: Boolean(settings && "small_account_mode" in settings),
  };
}

/** Which terms a wallet copies with: the api says so (v7), else a stored allocation means custom. */
export function walletSource(wallet: Pick<WalletPosition, "settings_source" | "allocation_usd"> | null | undefined, o: TradeOverride | undefined, inBook: boolean): SettingsSource {
  if (wallet?.settings_source) return wallet.settings_source;
  if (wallet?.allocation_usd || o?.allocation_usd) return "custom";
  return inBook ? "global" : "custom";
}

const trimNum = (n: number) => String(Math.round(n * 100) / 100);

/** The saved terms of a wallet (or a fresh custom ticket when it isn't invested). */
export function initialDraft(settings: TradeSettings | undefined, address: string | null, wallet?: WalletPosition | null): TicketDraft {
  const a = address ? normAddr(address) : null;
  const o: TradeOverride | undefined = a ? settings?.leader_overrides[a] : undefined;
  const inBook = Boolean(a && settings?.leaders.includes(a));
  const alloc = wallet?.allocation_usd ?? o?.allocation_usd ?? null;
  return {
    source: walletSource(wallet, o, inBook),
    amountText: alloc && alloc > 0 ? trimNum(alloc) : "",
    mode: wallet?.exposure_mode ?? o?.exposure_mode ?? settings?.exposure_mode ?? "match",
    leverage: clampLeverage(wallet?.target_leverage ?? o?.target_leverage ?? settings?.target_leverage ?? 5),
    marginMode: o?.margin_mode ?? null,
    maxWorseEntryPct: o?.max_worse_entry_pct ?? null,
    smallMode: o?.small_account_mode ?? null,
    onlyNew: o?.only_new_positions ?? null,
  };
}

/** Clear one field so it follows the Settings tab again. */
export function inherit(d: TicketDraft, field: InheritableField): TicketDraft {
  return { ...d, [field]: null };
}

export interface Effective {
  marginMode: MarginMode;
  maxWorseEntryPct: number;
  smallMode: SmallAccountMode;
  onlyNew: boolean;
}

/** What actually applies: the draft's value, or the Settings tab's when inherited. */
export function effective(d: TicketDraft, s: TradeSettings | undefined): Effective {
  const custom = d.source === "custom";
  return {
    marginMode: (custom && d.marginMode) || s?.margin_mode || "isolated",
    maxWorseEntryPct: custom && d.maxWorseEntryPct !== null ? d.maxWorseEntryPct : s?.max_worse_entry_pct ?? 10,
    smallMode: (custom && d.smallMode) || s?.small_account_mode || "concentrate",
    onlyNew: custom && d.onlyNew !== null ? d.onlyNew : s?.only_new_positions ?? false,
  };
}

/**
 * The POST body. Global: just the source. Custom: the allocation terms plus
 * only the fields the user set. Pre-v7 apis get no v7 keys (extra="forbid").
 * Null when the draft can't be sent (custom without an amount, global on a pre-v7 api).
 */
export function buildCopyRequest(d: TicketDraft, caps: ApiCaps): WalletCopyRequest | null {
  if (d.source === "global") return caps.v7 ? { settings_source: "global" } : null;
  const amount = parseInvest(d.amountText);
  if (amount === null || amount <= 0) return null;
  const body: WalletCopyRequest = { allocation_usd: Math.round(amount * 100) / 100, exposure_mode: d.mode };
  if (caps.v7) body.settings_source = "custom";
  if (d.mode === "target") body.target_leverage = clampLeverage(d.leverage);
  // Follow their leverage: each copy opens at his leverage on that coin.
  else if (caps.v7) body.leverage_mode = "match";
  if (d.marginMode) body.margin_mode = d.marginMode;
  if (d.maxWorseEntryPct !== null) body.max_worse_entry_pct = d.maxWorseEntryPct;
  if (d.smallMode && caps.smallMode) body.small_account_mode = d.smallMode;
  if (d.onlyNew !== null && caps.v7) body.only_new_positions = d.onlyNew;
  return body;
}

export type TicketAction = "copy" | "update" | "unchanged";

function same(a: TicketDraft, b: TicketDraft): boolean {
  if (a.source !== b.source) return false;
  if (a.source === "global") return true;
  const amt = (d: TicketDraft) => parseInvest(d.amountText) ?? -1;
  return Math.abs(amt(a) - amt(b)) < 0.005 && a.mode === b.mode && (a.mode === "match" || a.leverage === b.leverage) &&
    a.marginMode === b.marginMode && a.maxWorseEntryPct === b.maxWorseEntryPct && a.smallMode === b.smallMode && a.onlyNew === b.onlyNew;
}

/** New wallet -> copy; invested and something changed -> update; else unchanged. */
export function ticketAction(d: TicketDraft, saved: TicketDraft | null, invested: boolean): TicketAction {
  if (!invested || !saved) return "copy";
  return same(d, saved) ? "unchanged" : "update";
}

/** Switching a running wallet between global and custom: Update asks for a confirm first. */
export function switchesSource(d: TicketDraft, saved: TicketDraft | null, invested: boolean): boolean {
  return invested && saved !== null && d.source !== saved.source;
}
