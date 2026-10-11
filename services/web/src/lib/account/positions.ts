/**
 * Account > Positions (UX audit #4): the account's own positions (Scout file
 * read of the address) merged with the engine's copies (EngineStatus.positions),
 * so a copy is never missing from the tab. HL nets one position per coin per
 * account, so a coin the engine holds a copy of is tagged copycat with its
 * leader; a copy the account read does not show yet (stale read) is added from
 * the engine's own numbers.
 */
import type { CopyPosition } from "@/lib/api/types";
import type { TraderPositionView } from "@/lib/scout/types";

export type PositionSource = "manual" | "copycat";

export interface AccountPositionRow extends TraderPositionView {
  source: PositionSource;
  /** The copied trader, for copycat rows. */
  leader: string | null;
}

function fromCopy(c: CopyPosition): TraderPositionView {
  const margin = c.leverage > 0 ? Math.abs(c.notional_usd) / c.leverage : Math.abs(c.notional_usd);
  const liqDist = c.liquidation_px && c.mark_px ? (Math.abs(c.mark_px - c.liquidation_px) / c.mark_px) * 100 : null;
  return {
    coin: c.coin, side: c.side, size: c.size, notional_usd: Math.abs(c.notional_usd), entry_px: c.entry_px, mark_px: c.mark_px,
    unrealized_pnl_usd: c.unrealized_pnl_usd, roe_pct: margin > 0 ? (c.unrealized_pnl_usd / margin) * 100 : 0,
    leverage: c.leverage, is_cross: c.is_cross, liquidation_px: c.liquidation_px ?? null, liq_distance_pct: liqDist,
    margin_usd: margin, funding_since_open_usd: 0,
  };
}

/**
 * `copies` only count when the engine trades this account (`engineAccount`):
 * another account's copies are not here. Rows sort by notional, largest first.
 */
export function mergeAccountPositions(own: TraderPositionView[], copies: CopyPosition[], engineAccount: boolean): AccountPositionRow[] {
  const byCoin = new Map<string, CopyPosition>();
  if (engineAccount) for (const c of copies) if (!byCoin.has(c.coin)) byCoin.set(c.coin, c);
  const rows: AccountPositionRow[] = own.map((p) => {
    const c = byCoin.get(p.coin);
    return { ...p, source: c ? "copycat" : "manual", leader: c?.leader ?? null };
  });
  const seen = new Set(own.map((p) => p.coin));
  for (const [coin, c] of byCoin) {
    if (!seen.has(coin)) rows.push({ ...fromCopy(c), source: "copycat", leader: c.leader });
  }
  return rows.sort((a, b) => b.notional_usd - a.notional_usd || a.coin.localeCompare(b.coin));
}

/** Does the engine trade this account? In demo the active account stands in for it. */
export function isEngineAccount(accountAddress: string, ourAddress: string | null | undefined, demo: boolean, active: boolean): boolean {
  if (demo) return active;
  return Boolean(ourAddress) && ourAddress!.toLowerCase() === accountAddress.toLowerCase();
}
