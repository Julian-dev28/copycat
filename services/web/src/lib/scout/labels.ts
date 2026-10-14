/** Plain-words labels and thresholds for Scout. Thresholds mirror spec section 2. Pure. */
import { formatAgo } from "@/lib/format";
import type { BadgeTone } from "@/components/ui/Badge";
import type { OpenOrderWire, PnlTier, RawOpenOrder, SizeTier, TraderScore, TradingStyle } from "./types";

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

/**
 * HL's own `cumFunding.sinceOpen` (TraderPositionView.funding_since_open_usd)
 * is reported positive = PAID by the trader (a cost) -- the opposite
 * convention from every other money figure here (positive = good). This
 * negates it for display so the sign and color both read the normal way:
 * positive/green when funding was a net benefit to the position, negative/red
 * when it cost the position money. Regression: the Positions tab used to
 * color a real $851 funding COST green (`>= 0` on the raw, unpaid-flipped
 * value), the exact opposite of what happened to the trader's money.
 */
export function netFundingSinceOpen(raw: number): number {
  return -raw;
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
  wallet_liquidated: "liquidated for real in the last 30d",
  too_few_trades: "too few trades to trust",
  hft: "trades too fast to copy",
  hft_not_simulated: "too fast to copy, not simulated",
  vault: "a vault, PnL is pooled",
  coattail: "opens often land soon after another top wallet's",
  fills_truncated: "only the latest 10k fills are visible",
  stale: "stats could not be refreshed last cycle",
  non_perp_ignored: "spot / HIP-3 holdings ignored by the sim",
  max_leverage_unknown: "max leverage unknown for a coin",
  candles_partial: "some price history missing",
  error: "the sim hit a data error",
};

/**
 * Badge tone per flag (UX audit: FileHeader rendered every flag as an
 * uppercase amber "warning" pill, so a plain scope disclaimer like
 * "spot / HIP-3 holdings ignored by the sim" read as an alarm). Only a flag
 * that bears on whether to trust or copy this trader is a warning; a note
 * about what the sim could or couldn't see is neutral. Unlisted flags
 * default to warning (new flags should get a loud color until someone
 * decides otherwise, not go silently neutral).
 */
export const FLAG_TONE: Record<string, BadgeTone> = {
  non_perp_ignored: "neutral",
  candles_partial: "neutral",
  stale: "neutral",
};

export function flagTone(flag: string): BadgeTone {
  return FLAG_TONE[flag.split(":")[0]] ?? "warning";
}

/**
 * Plain-language real-liquidation line for a board row (user_consensus P0
 * #3): "Liquidated 2x in 30d (last: 3d ago)". Distinct from the sim's own
 * "liquidated" flag (FLAG_TEXT.liquidated): this is the wallet's OWN real
 * HL liquidation history, not what would happen to a copy. null when it
 * never happened in the 30d window the stat covers.
 */
export function liquidationText(score: Pick<TraderScore, "liquidations_30d" | "last_liquidation_ms">, nowMs: number): string | null {
  if (!score.liquidations_30d) return null;
  const n = score.liquidations_30d;
  return `Liquidated ${n}x in 30d (last: ${formatAgo(score.last_liquidation_ms, nowMs)})`;
}

/** "Opens often land ~68% of the time soon after 0x1234...abcd's" (user_consensus P1 #6). */
export function coattailText(score: Pick<TraderScore, "coattail_leader" | "coattail_share_pct">): string | null {
  if (!score.coattail_leader) return null;
  const who = `${score.coattail_leader.slice(0, 6)}…${score.coattail_leader.slice(-4)}`;
  const share = score.coattail_share_pct !== null && score.coattail_share_pct !== undefined ? Math.round(score.coattail_share_pct) : null;
  return `Opens often land soon after ${who}'s${share !== null ? ` (${share}% of the time)` : ""}`;
}

/**
 * Plain words for any flag the api sends, including the prefixed ones
 * (`liquidated:BTC`, `max_leverage_unknown:ETH`, `error:sim:ValueError`).
 * Never returns a raw enum key: an unknown flag becomes words, not snake_case.
 */
export function flagText(flag: string): string {
  const [key, ...rest] = flag.split(":");
  const base = FLAG_TEXT[key] ?? key.replaceAll("_", " ").trim();
  const detail = key === "error" ? "" : rest.join(":");
  return detail ? `${base} (${detail})` : base;
}

/** Flags worth showing on a card or header: one entry per flag key, the 10k-fills note dropped. */
export function visibleFlags(flags: string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const f of flags) {
    const key = f.split(":")[0];
    if (key === "fills_truncated" || seen.has(key)) continue;
    seen.add(key);
    out.push(f);
  }
  return out;
}

/** Tooltip for a HIP-3 coin's dex chip (UX audit: unexplained "XYZ"). */
export function dexHint(dex: string): string {
  return `HIP-3 market (${dex} deployer)`;
}

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

/**
 * RefreshBadge progress: a real wallet count ("7/301"), not a bare percent
 * of a total the trader never sees (indexing tightening). Negative/missing
 * inputs (shouldn't happen, but ScoutStatus is server data) clamp to 0.
 */
export function refreshCountLabel(done: number, total: number): string {
  return `${Math.max(0, Math.trunc(done || 0))}/${Math.max(0, Math.trunc(total || 0))}`;
}

/**
 * "~12m left", rounded to the nearest minute and never "~0m left" (floors
 * at 1m while eta_s > 0). null/undefined/negative means no estimate yet --
 * ScoutStatus.eta_s is None server-side until the pass has enough signal
 * (refresh.eta_s's honesty gate: no estimate from 1-2 samples), and this
 * returns null the same way so the badge shows progress with no time.
 */
export function refreshEtaLabel(etaS: number | null | undefined): string | null {
  if (etaS === null || etaS === undefined || !Number.isFinite(etaS) || etaS < 0) return null;
  return `~${Math.max(1, Math.round(etaS / 60))}m left`;
}
