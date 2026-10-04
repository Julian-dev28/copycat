/**
 * Trader-file demo fixtures (`?demo=1`): a row for ANY valid address (the
 * board fixtures only know their own random addresses), a strategy
 * fingerprint, and one thesis per source. Deterministic per address and
 * clock, no network.
 */
import { normAddr } from "@/lib/address";
import { fixtureRows, rng } from "../fixtures";
import type { StrategyFingerprint, Thesis, TradeExample, TraderRow } from "../types";

const HOUR = 3_600_000;

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

/** The board row with that address, or the top demo row re-addressed to it. */
export function demoFileRow(address: string, nowMs: number): TraderRow {
  const rows = fixtureRows(nowMs);
  const a = normAddr(address);
  const hit = rows.find((r) => r.address === a);
  if (hit) return hit;
  const base = rows[hash(a) % Math.min(6, rows.length)];
  return { ...base, address: a, display_name: null, in_book: false };
}

function example(r: () => number, nowMs: number, i: number, why: string, win: boolean): TradeExample {
  const coins = ["BTC", "ETH", "SOL", "HYPE", "xyz:TSLA"];
  const opened = nowMs - Math.floor((2 + i * 3.3 + r() * 2) * 24 * HOUR);
  const hold = why.startsWith("Longest") ? 46.5 : Math.round((2 + r() * 20) * 10) / 10;
  const ret = Math.round((win ? 1 + r() * 9 : -(0.5 + r() * 4)) * 100) / 100;
  return {
    coin: coins[i % coins.length],
    side: i % 3 === 2 ? "short" : "long",
    opened_ms: opened,
    closed_ms: opened + Math.round(hold * HOUR),
    hold_h: hold,
    adds: Math.floor(r() * 4),
    max_leverage: Math.round(3 + r() * 12),
    net_pnl_usd: Math.round(ret * 900 + (win ? 200 : -150)),
    return_pct: ret,
    context: {
      trend_aligned: r() > 0.3,
      breakout: /breakout|Largest win/.test(why),
      pullback: why.includes("pullback"),
      rsi_14: Math.round(35 + r() * 35),
      move_24h_pct: Math.round((r() * 10 - 3) * 10) / 10,
      hour_utc: (13 + i * 2) % 24,
    },
    why_shown: why,
  };
}

export function fixtureFingerprint(address: string, nowMs: number): StrategyFingerprint {
  const r = rng(hash(normAddr(address)));
  const hour = Array.from({ length: 24 }, (_, h) => Math.round((h >= 12 && h <= 20 ? 9 : 2) + r() * 5));
  const weekday = [14, 17, 15, 18, 13, 5, 4].map((v) => Math.round(v + r() * 3));
  const examples = [
    example(r, nowMs, 0, "Largest win in the window", true),
    example(r, nowMs, 1, "Typical pullback entry (median return)", true),
    example(r, nowMs, 2, "Largest loss in the window", false),
    example(r, nowMs, 3, "Typical breakout entry", true),
    example(r, nowMs, 4, "Longest hold", false),
  ];
  return {
    address: normAddr(address),
    as_of_ms: nowMs - 9 * 60_000,
    window_days: 30,
    trips_analyzed: hour.reduce((a, b) => a + b, 0),
    style: "intraday",
    median_hold_h: 7.5,
    p90_hold_h: 31,
    long_pct: 68,
    trend_aligned_pct: 71,
    breakout_pct: 44,
    pullback_pct: 38,
    avg_rsi_long_entry: 58.2,
    avg_rsi_short_entry: 61.4,
    avg_adds_per_trip: 1.6,
    scales_in_pct: 52,
    scales_out_pct: 34,
    avg_leverage: 6.8,
    max_leverage: 20,
    win_rate_pct: 57,
    avg_win_usd: 1840,
    avg_loss_usd: -1120,
    payoff_ratio: 1.64,
    loser_hold_vs_winner: 1.9,
    worst_trip_pct_of_equity: -4.2,
    pnl_from_top_coin_pct: 46,
    hour_hist_utc: hour,
    weekday_hist: weekday,
    top_coins: [
      { coin: "BTC", volume_usd: 8_400_000, pnl_usd: 41_200, trips: 61 },
      { coin: "ETH", volume_usd: 3_100_000, pnl_usd: 12_900, trips: 34 },
      { coin: "HYPE", volume_usd: 1_200_000, pnl_usd: -3_400, trips: 19 },
    ],
    tags: ["trend follower", "long bias", "scales in", "US session", "holds losers longer"],
    summary:
      "Intraday trend follower on majors. Mostly long, enters after a 24h move in the trend direction, adds to winners about half the time, and trades the US session. Losers are held about twice as long as winners.",
    examples,
    caveats: [
      "Entry context uses 1h candles; a fill inside a fast wick can read as a breakout.",
      "46% of PnL came from one coin, so the edge may not carry to others.",
    ],
  };
}

export function fixtureTheses(address: string, nowMs: number, withClaude = true): Thesis[] {
  const a = normAddr(address);
  const ta: Thesis = {
    address: a,
    source: "ta",
    created_ms: nowMs - 9 * 60_000,
    title: "Intraday trend follower on majors",
    markdown: [
      "## What the fills say",
      "",
      "- **71%** of entries go with the 24h trend; **44%** are breakouts.",
      "- Median hold **7.5h**, p90 **31h**.",
      "- Payoff ratio **1.64** at a **57%** win rate.",
      "",
      "> Losers are held about 1.9x as long as winners.",
    ].join("\n"),
    fingerprint_as_of_ms: nowMs - 9 * 60_000,
    author: null,
  };
  if (!withClaude) return [ta];
  const cc: Thesis = {
    address: a,
    source: "claude_code",
    created_ms: nowMs - 26 * HOUR,
    title: "Momentum on majors, with a slow stop",
    markdown: [
      "## Thesis",
      "",
      "He buys strength in BTC and ETH during the US session and lets winners run with adds.",
      "",
      "### Copy risks",
      "",
      "1. He sits in losers too long; a copy at higher leverage feels that first.",
      "2. Most PnL is BTC; if BTC chops, expect a flat month.",
      "",
      "| Check | Value |",
      "|---|---|",
      "| Trend-aligned entries | 71% |",
      "| Scales in | 52% |",
      "",
      "Inline code `size_multiplier = 0.5` and a [link](https://app.hyperliquid.xyz).",
    ].join("\n"),
    fingerprint_as_of_ms: nowMs - 27 * HOUR,
    author: "claude-opus-5-5 via copycat MCP",
  };
  return [ta, cc];
}
