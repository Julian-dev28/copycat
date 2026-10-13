/**
 * AccountSummary -> what the Account page shows. Every number the page
 * renders is picked and formatted here so the tests pin it. Pure.
 */
import { formatLeverage, formatPct, formatSignedUsd, formatUsd } from "@/lib/format";
import { biasLabel, formatHold, PNL_TIER_META, SIZE_TIER_HINT, STYLE_META } from "@/lib/scout/labels";
import type { CurvePoint, PnlWindow } from "@/lib/scout/types";
import { clipFrom } from "@/lib/scout/window";
import type { AccountBalances, AccountSummary } from "./types";

export type Tone = "up" | "down" | "flat" | "warn";

/**
 * Hyperliquid's own definitions, quoted verbatim (docs/research/user_consensus_2026-10.md,
 * sourced from hyperliquid.gitbook.io/hyperliquid-docs/trading/portfolio-graphs). Keep this
 * wording: it is what HL's own app says, so a user sees the same words in both places.
 */
export const HL_ACCOUNT_VALUE_DEF =
  "Hyperliquid's definition: “Account value includes unrealized pnl from cross and isolated margin positions, as well as vault balances.”";
export const HL_PNL_DEF =
  "Hyperliquid's definition: “Pnl is defined as account value plus net deposits, i.e. account value + deposits − withdrawals.” Deposits are not trading profit.";

export interface Stat {
  label: string;
  value: string;
  tone?: Tone;
  hint?: string;
}

export interface EquitySlice {
  key: "perps" | "copytrade" | "spot" | "staked";
  label: string;
  usd: number;
  /** Share of total equity, 0..100. */
  pct: number;
}

const tone = (v: number | null | undefined): Tone => (v === null || v === undefined || v === 0 || Number.isNaN(v) ? "flat" : v > 0 ? "up" : "down");
const pos = (v: number) => (Number.isFinite(v) && v > 0 ? v : 0);

/**
 * Bar slices that add up to total equity. Copytrade margin sits inside the
 * perps balance, so it is carved out of perps instead of added on top
 * (adding it would double count and push the bar past 100%).
 */
export function equitySlices(b: AccountBalances): EquitySlice[] {
  const perps = pos(b.perps_usd);
  const copy = Math.min(pos(b.copytrade_usd), perps);
  const parts: Omit<EquitySlice, "pct">[] = [
    { key: "perps", label: "Perps", usd: perps - copy },
    { key: "copytrade", label: "Copytrade", usd: copy },
    { key: "spot", label: "Spot", usd: pos(b.spot_usd) },
    { key: "staked", label: "Staked", usd: pos(b.staked_usd) },
  ];
  const sum = parts.reduce((a, p) => a + p.usd, 0);
  return parts.map((p) => ({ ...p, pct: sum > 0 ? (p.usd / sum) * 100 : 0 }));
}

/** Long share of gross notional, or null with no positions. */
export function longShare(s: Pick<AccountSummary, "long_notional_usd" | "short_notional_usd">): number | null {
  const gross = pos(s.long_notional_usd) + pos(s.short_notional_usd);
  return gross > 0 ? (pos(s.long_notional_usd) / gross) * 100 : null;
}

export function directionBias(s: Pick<AccountSummary, "long_notional_usd" | "short_notional_usd">): { longPct: number | null; label: string } {
  const longPct = longShare(s);
  return { longPct, label: biasLabel(longPct) };
}

export function overviewStats(s: AccountSummary): Stat[] {
  return [
    { label: "Unrealized PnL", value: formatSignedUsd(s.unrealized_pnl_usd), tone: tone(s.unrealized_pnl_usd) },
    { label: "Leverage", value: formatLeverage(s.account_leverage), tone: s.account_leverage >= 10 ? "warn" : undefined, hint: "Open notional over account value" },
    { label: "Margin usage", value: formatPct(s.margin_usage_pct, 0), tone: s.margin_usage_pct >= 80 ? "warn" : undefined },
    { label: "All-time PnL", value: formatSignedUsd(s.all_time_pnl_usd), tone: tone(s.all_time_pnl_usd), hint: HL_PNL_DEF },
    { label: "Volume", value: formatUsd(s.volume_usd, true), hint: "All-time traded notional" },
    { label: "Withdrawable", value: formatUsd(s.balances.withdrawable_usd) },
  ];
}

export const NA = "n/a";
const PENDING = "Computed by discovery; shows after its next pass";
const orNa = <T,>(v: T | null | undefined, f: (x: T) => string) => (v === null || v === undefined ? NA : f(v));

/** True while discovery has not produced this account's metrics yet (every derived stat is null). */
export function metricsPending(s: AccountSummary): boolean {
  return !s.risk_30d && !s.trades_30d && !s.style && s.longest_win_streak_days == null && !s.daily_pnl.length;
}

export function analysisStats(s: AccountSummary): Stat[] {
  return [
    { label: "Longest win streak", value: orNa(s.longest_win_streak_days, (d) => `${d}d`), hint: s.longest_win_streak_days == null ? PENDING : "Consecutive green days" },
    { label: "Style", value: s.style ? STYLE_META[s.style].label : NA, hint: s.style ? STYLE_META[s.style].hint : PENDING },
    { label: "Avg / median hold", value: s.avg_hold_h == null && s.median_hold_h == null ? NA : `${formatHold(s.avg_hold_h)} / ${formatHold(s.median_hold_h)}` },
    { label: "PnL cohort", value: s.pnl_tier ? PNL_TIER_META[s.pnl_tier].label : NA, hint: s.pnl_tier ? PNL_TIER_META[s.pnl_tier].hint : undefined },
    { label: "Size cohort", value: s.size_tier ?? NA, hint: s.size_tier ? SIZE_TIER_HINT[s.size_tier] : undefined },
  ];
}

const n2 = (v: number | null | undefined) => orNa(v, (x) => (Number.isFinite(x) ? x.toFixed(2) : NA));

export function performanceStats(s: AccountSummary): Stat[] {
  const r = s.risk_30d;
  const t = s.trades_30d;
  return [
    { label: "Max drawdown", value: orNa(r?.max_drawdown_pct, (v) => formatPct(v)), tone: (r?.max_drawdown_pct ?? 0) >= 25 ? "warn" : undefined, hint: r ? undefined : PENDING },
    { label: "Win rate", value: orNa(t?.win_rate_pct, (v) => formatPct(v, 0)), hint: t ? `${t.wins} of ${t.trips} round trips` : PENDING },
    { label: "Sharpe", value: n2(r?.sharpe) },
    { label: "Sortino", value: n2(r?.sortino) },
  ];
}

export type AccountMetric = "pnl" | "value";

export interface AccountSeries {
  points: CurvePoint[];
  /** Change over the window: PnL earned, or value delta. */
  change: number | null;
}

/** PnL is rebased to 0 at the window start so the line reads "earned in this window". */
export function accountSeries(s: Pick<AccountSummary, "pnl_curve" | "value_curve">, metric: AccountMetric, w: PnlWindow): AccountSeries {
  const raw = clipFrom((metric === "pnl" ? s.pnl_curve[w] : s.value_curve[w]) ?? [], null);
  if (!raw.length) return { points: [], change: null };
  const base = raw[0].value;
  const points = metric === "pnl" ? raw.map((p) => ({ t_ms: p.t_ms, value: p.value - base })) : raw;
  return { points, change: raw[raw.length - 1].value - base };
}

/** "Empty" = brand new wallet with nothing in it: the page shows the fund panel instead of zeros. */
export function isEmptyAccount(s: Pick<AccountSummary, "balances" | "volume_usd">): boolean {
  return s.balances.total_usd <= 0 && !s.volume_usd;
}
