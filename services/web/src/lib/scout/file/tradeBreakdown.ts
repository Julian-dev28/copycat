/**
 * Copy-decision stats a serious copier expects (Hyperdash / HL's own trade
 * history show these; copycat's StatTiles didn't): long vs short PnL split,
 * largest win/loss, average trade size relative to the leader's own
 * account, and UTC hour-of-day activity. Pure: derived entirely from
 * `recent_trips` (already fetched for the Trips tab) and the leader's
 * account value, no new api call, no contract change.
 *
 * `recent_trips` is capped at RECENT_MAX (100) trips server side, newest
 * first: for a wallet with 100 or fewer 30d round trips this is the whole
 * window; for a busier one it's the most recent slice, same caveat the
 * Trips tab itself already carries.
 */
import type { RoundTrip } from "../types";

export interface CoinWinRate {
  coin: string;
  trips: number;
  winRatePct: number | null;
}

export interface TradeBreakdown {
  longPnlUsd: number;
  shortPnlUsd: number;
  longTrips: number;
  shortTrips: number;
  largestWinUsd: number | null;
  largestLossUsd: number | null;
  /** mean(max_notional_usd) / accountValueUsd * 100, null when there's no account value to divide by. */
  avgTradeSizePctOfAccount: number | null;
  /** Count of trips opened in each UTC hour (index 0 = 00:00 UTC), length 24. */
  hourlyOpensUtc: number[];
  /** Sorted by trip count desc, then coin name. */
  winRateByCoin: CoinWinRate[];
}

export function tradeBreakdown(trips: RoundTrip[], accountValueUsd: number): TradeBreakdown {
  const hourlyOpensUtc = new Array(24).fill(0) as number[];
  let longPnlUsd = 0;
  let shortPnlUsd = 0;
  let longTrips = 0;
  let shortTrips = 0;
  let largestWinUsd: number | null = null;
  let largestLossUsd: number | null = null;
  let sizeSum = 0;
  const byCoin = new Map<string, { trips: number; wins: number }>();

  for (const t of trips) {
    if (t.side === "long") {
      longPnlUsd += t.net_pnl_usd;
      longTrips += 1;
    } else {
      shortPnlUsd += t.net_pnl_usd;
      shortTrips += 1;
    }
    if (t.net_pnl_usd > 0) largestWinUsd = largestWinUsd === null ? t.net_pnl_usd : Math.max(largestWinUsd, t.net_pnl_usd);
    if (t.net_pnl_usd < 0) largestLossUsd = largestLossUsd === null ? t.net_pnl_usd : Math.min(largestLossUsd, t.net_pnl_usd);
    sizeSum += t.max_notional_usd;
    const hour = new Date(t.opened_ms).getUTCHours();
    hourlyOpensUtc[hour] += 1;
    const c = byCoin.get(t.coin) ?? { trips: 0, wins: 0 };
    c.trips += 1;
    if (t.win) c.wins += 1;
    byCoin.set(t.coin, c);
  }

  const winRateByCoin: CoinWinRate[] = [...byCoin.entries()]
    .map(([coin, c]) => ({ coin, trips: c.trips, winRatePct: c.trips > 0 ? (c.wins / c.trips) * 100 : null }))
    .sort((a, b) => b.trips - a.trips || a.coin.localeCompare(b.coin));

  return {
    longPnlUsd,
    shortPnlUsd,
    longTrips,
    shortTrips,
    largestWinUsd,
    largestLossUsd,
    avgTradeSizePctOfAccount: trips.length && accountValueUsd > 0 ? (sizeSum / trips.length / accountValueUsd) * 100 : null,
    hourlyOpensUtc,
    winRateByCoin,
  };
}
