/**
 * The Scout ticker (components/scout/BoardTicker.tsx): the board's top rows
 * as one scrolling strip of "rank name  +12.3%". Pure.
 */
import type { PnlUnit } from "./query";
import type { PnlWindow, TraderRow } from "./types";
import { windowPerf } from "./window";

export interface TickerItem {
  address: string;
  /** Display name, else the shortened address. */
  name: string;
  /** The window's ROI % or PnL $ (per `unit`); null when the window has no data. */
  value: number | null;
  rank: number;
}

export const TICKER_MAX = 12;

export function tickerItems(rows: readonly TraderRow[], window: PnlWindow, unit: PnlUnit, max = TICKER_MAX): TickerItem[] {
  return rows.slice(0, max).map((r, i) => {
    const p = windowPerf(r, window);
    const v = p ? (unit === "pct" ? p.roi_pct : p.pnl_usd) : null;
    return {
      address: r.address,
      name: r.display_name?.trim() || `${r.address.slice(0, 6)}…${r.address.slice(-4)}`,
      value: v != null && Number.isFinite(v) ? v : null,
      rank: i + 1,
    };
  });
}

/** One loop takes about 6 s per item, never under 30 s, so it reads as a drift, not a flicker. */
export function tickerSpeedS(count: number): number {
  return Math.max(30, count * 6);
}
