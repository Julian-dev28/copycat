import type { TradeStats } from "./types";

/** Long vs short share of a trader's round trips, for the card's stat strip. null when there were none. */
export function longShortSplit(t: Pick<TradeStats, "long_trips" | "short_trips"> | null | undefined): { long: number; short: number; longPct: number } | null {
  const long = Math.max(0, t?.long_trips ?? 0);
  const short = Math.max(0, t?.short_trips ?? 0);
  const total = long + short;
  if (total <= 0) return null;
  return { long, short, longPct: Math.round((long / total) * 100) };
}
