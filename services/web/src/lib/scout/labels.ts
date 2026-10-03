/** Plain-words labels and thresholds for Scout. Thresholds mirror spec section 2. Pure. */
import type { OpenOrderWire, PnlTier, RawOpenOrder, SizeTier, TradingStyle } from "./types";

export const STYLE_META: Record<TradingStyle, { label: string; hint: string }> = {
  algo: { label: "Algo", hint: "Over 100 opens a day. Too fast to copy on a 5s poll." },
  scalp: { label: "Scalper", hint: "Median hold under 15 minutes." },
  intraday: { label: "Intraday", hint: "Median hold under 24 hours." },
  swing: { label: "Swing", hint: "Median hold 1 to 7 days." },
  position: { label: "Position", hint: "Median hold of a week or more." },
};

export const SIZE_TIER_HINT: Record<SizeTier, string> = {
  S: "Account under $10k",
  M: "Account $10k to $100k",
  L: "Account $100k to $1M",
  XL: "Account $1M to $10M",
  XXL: "Account $10M or more",
};

export const PNL_TIER_META: Record<PnlTier, { label: string; hint: string }> = {
  losing: { label: "Net losing", hint: "All-time PnL below zero" },
  up: { label: "Net up", hint: "All-time PnL $0 to $100k" },
  strong: { label: "Strong", hint: "All-time PnL $100k to $1M" },
  elite: { label: "Elite", hint: "All-time PnL $1M or more" },
};

/** Spec #27: long share of gross notional. */
export function biasLabel(longPct: number | null | undefined): string {
  if (longPct === null || longPct === undefined || !Number.isFinite(longPct)) return "No positions";
  if (longPct >= 80) return "Strongly long";
  if (longPct >= 60) return "Leaning long";
  if (longPct > 40) return "Balanced";
  if (longPct > 20) return "Leaning short";
  return "Strongly short";
}

export type RiskTone = "ok" | "warn" | "danger" | "none";

/** Distance to liquidation: under 10% is danger, under 25% a warning. */
export function liqTone(pct: number | null | undefined): RiskTone {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "none";
  if (pct < 10) return "danger";
  if (pct < 25) return "warn";
  return "ok";
}

/** 0.4h -> "24m", 5.5h -> "5.5h", 50h -> "2.1d". */
export function formatHold(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || !Number.isFinite(hours)) return "—";
  if (hours < 1) return `${Math.max(1, Math.round(hours * 60))}m`;
  if (hours < 48) return `${Number(hours.toFixed(1))}h`;
  return `${Number((hours / 24).toFixed(1))}d`;
}

/** Strip the HIP-3 dex prefix for display: "xyz:TSLA" -> "TSLA". */
export function coinLabel(coin: string): { name: string; dex: string | null } {
  const i = coin.indexOf(":");
  return i < 0 ? { name: coin, dex: null } : { name: coin.slice(i + 1), dex: coin.slice(0, i) };
}

export const FLAG_TEXT: Record<string, string> = {
  inactive: "inactive: tiny account or no fill in 7 days",
  liquidated: "a copy got liquidated in the sim",
  too_few_trades: "too few trades to trust",
  hft: "trades too fast to copy",
  vault: "a vault, PnL is pooled",
  fills_truncated: "only the latest 10k fills are visible",
  stale: "stats could not be refreshed last cycle",
};

export interface OpenOrderView {
  oid: number;
  coin: string;
  side: "buy" | "sell";
  type: string;
  px: number;
  size: number;
  origSize: number;
  notional: number;
  reduceOnly: boolean;
  trigger: string | null;
  time_ms: number;
}

function n(v: string | number | undefined): number {
  const x = typeof v === "number" ? v : Number(v);
  return Number.isFinite(x) ? x : 0;
}

function fromWire(r: OpenOrderWire): OpenOrderView {
  return {
    oid: n(r.oid), coin: r.coin, side: r.side === "B" ? "buy" : "sell", type: r.order_type || "Limit",
    px: n(r.limit_px), size: n(r.sz), origSize: n(r.orig_sz), notional: n(r.notional_usd), reduceOnly: Boolean(r.reduce_only),
    trigger: r.is_trigger ? `${r.trigger_condition ?? "trigger"} @ ${n(r.trigger_px ?? undefined)}` : null, time_ms: n(r.time_ms),
  };
}

function fromRaw(r: RawOpenOrder): OpenOrderView {
  const px = n(r.limitPx);
  const size = n(r.sz);
  return {
    oid: n(r.oid), coin: r.coin, side: r.side === "B" ? "buy" : "sell", type: r.orderType ?? "Limit", px, size,
    origSize: r.origSz === undefined ? size : n(r.origSz), notional: px * size, reduceOnly: Boolean(r.reduceOnly),
    trigger: r.isTrigger ? `${r.triggerCondition ?? "trigger"} @ ${n(r.triggerPx)}` : null, time_ms: n(r.timestamp),
  };
}

/**
 * GET .../orders -> display rows, newest first. Reads the v3.1 contract
 * shape (OpenOrderView, snake_case) and HL's raw frontendOpenOrders rows.
 * Rows without a coin or a B/A side are dropped, never rendered as NaN.
 */
export function normalizeOrders(raw: unknown): OpenOrderView[] {
  if (!Array.isArray(raw)) return [];
  const out: OpenOrderView[] = [];
  for (const r of raw as Record<string, unknown>[]) {
    if (!r || typeof r.coin !== "string" || (r.side !== "B" && r.side !== "A")) continue;
    out.push("limit_px" in r ? fromWire(r as unknown as OpenOrderWire) : fromRaw(r as unknown as RawOpenOrder));
  }
  return out.sort((a, b) => b.time_ms - a.time_ms);
}

/**
 * Spec 4.1: amber "stale" once the last good refresh is older than 3x the
 * schedule. The schedule is next_due - last_ok; unknown schedule = not stale.
 */
export function isStale(lastOkMs: number | null | undefined, nextDueMs: number | null | undefined, nowMs: number): boolean {
  if (!lastOkMs || !nextDueMs || nextDueMs <= lastOkMs) return false;
  return nowMs - lastOkMs > 3 * (nextDueMs - lastOkMs);
}
