/**
 * The share-PnL card: what goes on the PNG, shaped from a Your wallets row.
 * Only what the row already shows on screen: the short address (never the
 * full one), direction, PnL $, PnL % of exposure, ROE, the period, and a
 * sparkline of his index since you started (inverted for counter). No
 * allocation, equity, or our own address. Pure, unit-tested; the canvas
 * drawing lives in components/trade/ShareCardDialog.tsx.
 */
import { formatSignedPct, formatSignedUsd, shortenAddress } from "@/lib/format";
import type { CurvePoint } from "@/lib/scout/types";
import { invertSeries } from "./direction";
import { roePct } from "./markets";
import type { TradeDirection, WalletPosition } from "./types";

export interface ShareCardData {
  title: string;
  shortAddress: string;
  direction: TradeDirection;
  directionLabel: string;
  pnlUsd: number;
  pnlText: string;
  /** PnL over the exposure we carry (unleveraged move), null without exposure. */
  pnlPct: number | null;
  pnlPctText: string;
  roePct: number | null;
  roeText: string;
  period: string;
  /** 0..1 normalized points for the sparkline (x by time, y by value). */
  spark: { x: number; y: number }[];
  up: boolean;
}

const DAY = 86_400_000;

export function periodText(investedMs: number | null | undefined, endMs: number): string {
  if (!investedMs || investedMs > endMs) return "since you started";
  const days = Math.max(0, Math.floor((endMs - investedMs) / DAY));
  const since = new Date(investedMs).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  if (days < 1) return `since ${since} · today`;
  return `since ${since} · ${days} day${days === 1 ? "" : "s"}`;
}

/** Normalize a curve into the unit box, oldest first. Fewer than 2 points -> none. */
export function normalizeSpark(points: CurvePoint[]): { x: number; y: number }[] {
  const pts = [...points].filter((p) => Number.isFinite(p.value)).sort((a, b) => a.t_ms - b.t_ms);
  if (pts.length < 2) return [];
  const t0 = pts[0].t_ms;
  const t1 = pts[pts.length - 1].t_ms;
  const lo = Math.min(...pts.map((p) => p.value));
  const hi = Math.max(...pts.map((p) => p.value));
  return pts.map((p) => ({ x: t1 > t0 ? (p.t_ms - t0) / (t1 - t0) : 0, y: hi > lo ? (p.value - lo) / (hi - lo) : 0.5 }));
}

export function shareCardData(
  w: WalletPosition,
  opts: { name?: string | null; nowMs: number; index?: CurvePoint[] },
): ShareCardData {
  const direction: TradeDirection = w.trade_direction === "counter" ? "counter" : "copy";
  const pnl = w.pnl_usd ?? w.unrealized_pnl_usd + w.realized_pnl_usd - w.fees_usd;
  const roe = roePct(w);
  const pnlPct = w.exposure_usd > 0 ? (pnl / w.exposure_usd) * 100 : null;
  const end = w.archived_ms ?? opts.nowMs;
  const since = (opts.index ?? []).filter((p) => !w.invested_ms || p.t_ms >= w.invested_ms);
  const series = since.length >= 2 ? since : opts.index ?? [];
  const spark = normalizeSpark(direction === "counter" ? invertSeries(series) : series);
  const short = shortenAddress(w.address);
  return {
    title: opts.name?.trim() || short,
    shortAddress: short,
    direction,
    directionLabel: direction === "counter" ? "Countering" : "Copying",
    pnlUsd: pnl,
    pnlText: formatSignedUsd(pnl),
    pnlPct,
    pnlPctText: pnlPct === null ? "n/a" : formatSignedPct(pnlPct),
    roePct: roe,
    roeText: roe === null ? "n/a" : formatSignedPct(roe),
    period: periodText(w.invested_ms, end),
    spark,
    up: pnl >= 0,
  };
}

/** copycat-0xabcd…1234-copy-pnl.png, filesystem safe. */
export function shareFileName(d: Pick<ShareCardData, "shortAddress" | "direction">): string {
  return `copycat-${d.shortAddress.replace(/[^0-9a-zA-Z]+/g, "-")}-${d.direction}-pnl.png`.replace(/-+/g, "-");
}
