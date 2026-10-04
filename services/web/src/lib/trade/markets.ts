/**
 * The Markets column and the "Your wallets" table as data. Pure, unit-tested.
 */
import { isValidAddress, normAddr } from "@/lib/address";
import { HIDE_FLAGS } from "@/lib/scout/query";
import type { TraderRow } from "@/lib/scout/types";
import { rowQuote, type MarketQuote } from "./equityIndex";
import type { TradeSettings, TradeStatus, WalletPosition } from "./types";

export type MarketTab = "mine" | "top" | "all";
export const TOP_N = 25;

export interface MarketItem {
  address: string;
  name: string | null;
  row: TraderRow | null;
  inBook: boolean;
  quote: MarketQuote | null;
}

function item(address: string, row: TraderRow | null, leaders: Set<string>): MarketItem {
  return {
    address,
    name: row?.display_name ?? null,
    row,
    inBook: leaders.has(address) || Boolean(row?.in_book),
    quote: row ? rowQuote(row) : null,
  };
}

export function buildMarkets(rows: TraderRow[], leaders: string[], tab: MarketTab, q: string): MarketItem[] {
  const book = new Set(leaders.map(normAddr));
  const byAddr = new Map(rows.map((r) => [normAddr(r.address), r]));
  let list: MarketItem[];
  if (tab === "mine") list = [...book].map((a) => item(a, byAddr.get(a) ?? null, book));
  else if (tab === "top") {
    list = rows
      .filter((r) => !r.flags.some((f) => HIDE_FLAGS.includes(f)) && !r.score.flags.some((f) => HIDE_FLAGS.includes(f)))
      .slice(0, TOP_N)
      .map((r) => item(normAddr(r.address), r, book));
  } else list = rows.map((r) => item(normAddr(r.address), r, book));

  const needle = q.trim().toLowerCase();
  if (!needle) return list;
  const hits = list.filter((m) => m.address.includes(needle) || (m.name ?? "").toLowerCase().includes(needle));
  if (isValidAddress(needle) && !hits.some((m) => m.address === normAddr(needle))) {
    const a = normAddr(needle);
    return [item(a, byAddr.get(a) ?? null, book), ...hits];
  }
  return hits;
}

export type WalletState = "active" | "dry_run" | "paused" | "stopping" | "no_read";

export const WALLET_STATE_LABEL: Record<WalletState, string> = {
  active: "active",
  dry_run: "dry run",
  paused: "paused",
  stopping: "stopping",
  no_read: "can't read",
};

export function walletState(w: Pick<WalletPosition, "stopping" | "read_ok">, s: Pick<TradeSettings, "enabled" | "dry_run"> | undefined): WalletState {
  if (w.stopping) return "stopping";
  if (s && !s.enabled) return "paused";
  if (!w.read_ok) return "no_read";
  if (s?.dry_run) return "dry_run";
  return "active";
}

export function roePct(w: Pick<WalletPosition, "roe_pct" | "allocation_usd" | "unrealized_pnl_usd" | "realized_pnl_usd" | "fees_usd">): number | null {
  if (w.roe_pct !== null && w.roe_pct !== undefined) return w.roe_pct;
  if (!w.allocation_usd) return null;
  return ((w.unrealized_pnl_usd + w.realized_pnl_usd - w.fees_usd) / w.allocation_usd) * 100;
}

/**
 * Fallback for an api without GET /api/wallets: the same rows from
 * /api/status leaders (v4 LeaderStatus fields) and the settings overrides.
 * Every book wallet counts: one with an allocation copies with custom terms,
 * one without follows the Settings tab (global).
 */
export function walletsFromStatus(status: TradeStatus | undefined, settings: TradeSettings | undefined): WalletPosition[] {
  if (!settings) return [];
  const byAddr = new Map((status?.leaders ?? []).map((l) => [normAddr(l.address), l]));
  return settings.leaders.flatMap((a) => {
    const o = settings.leader_overrides[a];
    const l = byAddr.get(a);
    return [{
      address: a,
      settings_source: o?.allocation_usd ? "custom" : "global",
      allocation_usd: o?.allocation_usd ?? settings.allocation_usd ?? null,
      exposure_mode: o?.exposure_mode ?? settings.exposure_mode ?? "match",
      target_leverage: o?.target_leverage ?? null,
      invested_ms: o?.invested_ms ?? null,
      open_copies: l?.open_copies ?? 0,
      margin_used_usd: l?.margin_used_usd ?? 0,
      exposure_usd: l?.exposure_usd ?? 0,
      unrealized_pnl_usd: l?.unrealized_pnl_usd ?? 0,
      realized_pnl_usd: l?.realized_pnl_usd ?? 0,
      fees_usd: l?.fees_usd ?? 0,
      roe_pct: null,
      stopping: l?.stopping ?? false,
      read_ok: l?.read_ok ?? true,
      equity_usd: l?.equity_usd ?? null,
      small_account_mode: o?.small_account_mode ?? null,
    } satisfies WalletPosition];
  });
}

/** "Global" / "Custom" badge for a Your wallets row. */
export function sourceBadge(w: Pick<WalletPosition, "settings_source" | "allocation_usd">): "Global" | "Custom" {
  const src = w.settings_source ?? (w.allocation_usd ? "custom" : "global");
  return src === "global" ? "Global" : "Custom";
}
