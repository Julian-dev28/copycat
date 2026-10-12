/**
 * Scout (contract v3) wire types, mirrored by hand from contracts/models.py
 * (section "Scout (v3)") until services/api ships the scout routes and
 * `npm run gen:api` regenerates schema.gen.ts with them. When that lands,
 * swap each alias here for `Schemas["..."]` the way lib/api/types.ts does;
 * the rest of the app imports from this file only, so nothing else moves.
 *
 * Units follow the contract: USD, percent as percent (10.0 = 10%), epoch ms.
 */
import type { LeaderOverride, TraderScore as BaseTraderScore } from "@/lib/api/types";

export type PnlWindow = "1d" | "7d" | "30d" | "all";
export const PNL_WINDOWS: PnlWindow[] = ["1d", "7d", "30d", "all"];

export type TradingStyle = "algo" | "scalp" | "intraday" | "swing" | "position";
export const TRADING_STYLES: TradingStyle[] = ["algo", "scalp", "intraday", "swing", "position"];

export type SizeTier = "S" | "M" | "L" | "XL" | "XXL";
export type PnlTier = "losing" | "up" | "strong" | "elite";

export interface CurvePoint {
  t_ms: number;
  value: number;
}

export interface WindowPerf {
  window: PnlWindow;
  pnl_usd: number;
  roi_pct: number;
  volume_usd: number;
}

export interface RiskStats {
  window: PnlWindow;
  max_drawdown_pct?: number | null;
  sharpe?: number | null;
  sortino?: number | null;
  profitable_days_pct?: number | null;
  days: number;
}

export interface TradeStats {
  window: PnlWindow;
  trips: number;
  wins: number;
  long_trips: number;
  short_trips: number;
  win_rate_pct?: number | null;
  avg_hold_h?: number | null;
  median_hold_h?: number | null;
  opens_per_day: number;
}

export interface CoinStat {
  coin: string;
  volume_usd: number;
  pnl_usd: number;
  trips: number;
}

export interface CopyFit {
  value: number;
  parts: Record<string, number>;
  weights: Record<string, number>;
  caps: string[];
  cohort_size: number;
}

export type TraderScore = Omit<BaseTraderScore, "copy_fit" | "style"> & {
  copy_fit?: CopyFit | null;
  style?: TradingStyle | null;
};

export interface TraderRow {
  address: string;
  display_name?: string | null;
  account_value_usd: number;
  size_tier: SizeTier;
  pnl_tier: PnlTier;
  style?: TradingStyle | null;
  last_fill_ms?: number | null;
  perf: WindowPerf[];
  risk_30d: RiskStats;
  trades_30d: TradeStats;
  top_coins: CoinStat[];
  pnl_spark_30d: CurvePoint[];
  sim_spark_30d: CurvePoint[];
  score: TraderScore;
  in_book: boolean;
  flags: string[];
}

export interface TraderPage {
  as_of_ms: number;
  refresh_id: string;
  settings_hash: string;
  cohort_size: number;
  total: number;
  rows: TraderRow[];
  /** Spec 7.3: rows are from the previous settings while stage C reruns. */
  stale_settings?: boolean;
}

export interface TraderPositionView {
  coin: string;
  side: "long" | "short";
  size: number;
  notional_usd: number;
  entry_px: number;
  mark_px: number;
  unrealized_pnl_usd: number;
  roe_pct: number;
  leverage: number;
  is_cross: boolean;
  liquidation_px?: number | null;
  liq_distance_pct?: number | null;
  margin_usd: number;
  funding_since_open_usd: number;
}

export interface RoundTrip {
  coin: string;
  side: "long" | "short";
  opened_ms: number;
  closed_ms: number;
  hold_h: number;
  entry_px: number;
  exit_px: number;
  max_notional_usd: number;
  net_pnl_usd: number;
  win: boolean;
}

export interface AccountRisk {
  perps_usd: number;
  spot_usd: number;
  staked_usd: number;
  account_leverage: number;
  margin_usage_pct: number;
  nearest_liq_pct?: number | null;
  long_notional_usd: number;
  short_notional_usd: number;
  long_bias_pct?: number | null;
  unrealized_pnl_usd: number;
}

export interface LeaderFillView {
  time_ms: number;
  coin: string;
  side: "B" | "A";
  dir: string;
  px: number;
  sz: number;
  notional_usd: number;
  closed_pnl_usd: number;
  fee_usd: number;
}

export interface TraderProfile {
  row: TraderRow;
  account: AccountRisk;
  positions: TraderPositionView[];
  positions_as_of_ms: number;
  pnl_curve: Partial<Record<PnlWindow, CurvePoint[]>>;
  value_curve: Partial<Record<PnlWindow, CurvePoint[]>>;
  sim_curve: CurvePoint[];
  daily_pnl: CurvePoint[];
  risk: RiskStats[];
  trades: TradeStats[];
  longest_win_streak_days: number;
  coins: CoinStat[];
  recent_trips: RoundTrip[];
  recent_fills: LeaderFillView[];
}

/** GET .../orders row (contract v3.1 OpenOrderView). */
export interface OpenOrderWire {
  oid: number;
  coin: string;
  side: "B" | "A";
  order_type: string;
  limit_px: number;
  sz: number;
  orig_sz: number;
  notional_usd: number;
  reduce_only: boolean;
  is_trigger: boolean;
  trigger_px?: number | null;
  trigger_condition?: string | null;
  tif?: string | null;
  time_ms: number;
}

/**
 * HL's raw frontendOpenOrders row (strings for numbers). An api build that
 * predates v3.1 passed these through; lib/scout/labels.ts::normalizeOrders
 * reads both shapes.
 */
export interface RawOpenOrder {
  coin: string;
  side: "B" | "A";
  limitPx: string | number;
  sz: string | number;
  origSz?: string | number;
  oid: number;
  timestamp: number;
  orderType?: string;
  reduceOnly?: boolean;
  isTrigger?: boolean;
  triggerPx?: string | number;
  triggerCondition?: string;
  tif?: string | null;
}

export interface WhatIfRequest {
  sim_equity_usd: number;
  override: LeaderOverride;
}

export interface WhatIfResult {
  score: TraderScore;
  sim_curve: CurvePoint[];
}

export interface ScoutStatus {
  refresh_id: string | null;
  state: "idle" | "running" | "failed";
  stage?: "leaderboard" | "stats" | "sim" | null;
  done: number;
  total: number;
  eta_s?: number | null;
  last_ok_ms?: number | null;
  next_due_ms?: number | null;
  error?: string | null;
}

/** GET /api/scout/presets, contract v3.1 ScoutPresets (wire shape). */
export interface ScoutPresetsWire {
  refresh_id?: string | null;
  coins: string[];
  coin_counts: Record<string, number>;
  hip3_count: number;
  total: number;
}

/** What the preset row renders; lib/scout/query.ts::normalizePresets builds it from the wire shape. */
export interface ScoutPresets {
  coins: { coin: string; traders: number }[];
  hip3: number;
  total: number;
}

// ── Strategy (contract v3.1): fingerprint, evidence trades, theses ──────────

export interface EntryContext {
  trend_aligned?: boolean | null;
  breakout?: boolean | null;
  pullback?: boolean | null;
  rsi_14?: number | null;
  move_24h_pct?: number | null;
  hour_utc: number;
}

export interface TradeExample {
  coin: string;
  side: "long" | "short";
  opened_ms: number;
  closed_ms: number;
  hold_h: number;
  adds: number;
  max_leverage?: number | null;
  net_pnl_usd: number;
  return_pct: number;
  context: EntryContext;
  why_shown: string;
}

export interface StrategyFingerprint {
  address: string;
  as_of_ms: number;
  window_days: number;
  trips_analyzed: number;
  style?: TradingStyle | null;
  median_hold_h?: number | null;
  p90_hold_h?: number | null;
  long_pct?: number | null;
  trend_aligned_pct?: number | null;
  breakout_pct?: number | null;
  pullback_pct?: number | null;
  avg_rsi_long_entry?: number | null;
  avg_rsi_short_entry?: number | null;
  avg_adds_per_trip?: number | null;
  scales_in_pct?: number | null;
  scales_out_pct?: number | null;
  avg_leverage?: number | null;
  max_leverage?: number | null;
  win_rate_pct?: number | null;
  avg_win_usd?: number | null;
  avg_loss_usd?: number | null;
  payoff_ratio?: number | null;
  loser_hold_vs_winner?: number | null;
  worst_trip_pct_of_equity?: number | null;
  pnl_from_top_coin_pct?: number | null;
  hour_hist_utc: number[];
  weekday_hist: number[];
  /** 7 x 24 trip-entry counts, [weekday][hour], UTC, Monday first. Empty or missing on fingerprints cached before it existed. */
  entries_by_dow_hour?: number[][] | null;
  top_coins: CoinStat[];
  tags: string[];
  summary: string;
  examples: TradeExample[];
  caveats: string[];
}

export interface Thesis {
  address: string;
  source: "ta" | "claude_code";
  created_ms: number;
  title: string;
  markdown: string;
  fingerprint_as_of_ms?: number | null;
  author?: string | null;
}
