/**
 * Pure view logic for the Trade ticket and the trader's positions table
 * (UX_AUDIT.md Top 10 #3, #5, #8, #10; user_consensus_2026-10-14.md P0 #4).
 * Components stay thin: they render what these functions decide.
 */
import { formatUsd } from "@/lib/format";
import { estimateLiquidationDistance } from "@/lib/liquidation";
import type { LiqEstimate, TicketPreview } from "./ticket";
import type { ExposureMode } from "./types";

function money(n: number): string {
  return formatUsd(n, Math.abs(n) >= 100_000);
}

function pctText(pct: number): string {
  return `${pct.toFixed(pct < 1 ? 2 : 1)}%`;
}

/* ---------- #10: where the allocation goes ---------- */

export interface AllocationBreakdown {
  /** Margin the copies open right now would lock. */
  marginNowUsd: number;
  /** Notional those copies carry. */
  exposureUsd: number;
  /** The rest of the allocation: margin for their next trades. */
  reservedUsd: number;
}

/** "Margin used now · Exposure · Reserved for their next trades". Null until there is an amount and a preview. */
export function allocationBreakdown(amount: number | null, preview: Pick<TicketPreview, "marginUsd" | "exposureUsd"> | null): AllocationBreakdown | null {
  if (amount === null || !(amount > 0) || !preview) return null;
  const margin = Math.max(0, preview.marginUsd);
  return { marginNowUsd: margin, exposureUsd: Math.max(0, preview.exposureUsd), reservedUsd: Math.max(0, amount - margin) };
}

/**
 * When copying every current position needs more than the account holds:
 * "needs $48; you have $20". Null when it fits or either number is unknown.
 */
export function fullBookShortfall(fullBookUsd: number | null | undefined, equityUsd: number | null | undefined): { needUsd: number; haveUsd: number; text: string } | null {
  if (fullBookUsd == null || equityUsd == null || !Number.isFinite(fullBookUsd) || !Number.isFinite(equityUsd)) return null;
  const need = Math.ceil(fullBookUsd);
  if (need <= equityUsd) return null;
  return { needUsd: need, haveUsd: equityUsd, text: `Copying all their positions needs ${money(need)}; you have ${money(equityUsd)}.` };
}

/* ---------- #3: effective leverage ---------- */

/** "25x" or "25x → 15x cap" when Settings' Maximum position leverage lowers it. */
export function effectiveLeverageText(set: number | null | undefined, cap: number | null | undefined): string {
  if (set == null || !Number.isFinite(set)) return "n/a";
  const s = Math.round(set);
  if (cap != null && Number.isFinite(cap) && cap > 0 && s > cap) return `${s}x → ${Math.round(cap)}x cap`;
  return `${s}x`;
}

/* ---------- #5: held vs next trade vs would copy ---------- */

export type CopyRowState = "held" | "next" | "would";

/**
 * One row of the trader's positions, from your side:
 * - held:  you hold a copy of it now (real money)
 * - next:  you copy this trader but hold no copy of it (only-new, skipped, filtered,
 *          or not opened yet): the size applies to their next trade
 * - would: you do not copy this trader; the size is what a copy would open
 */
export function copyRowState(invested: boolean, heldCoins: ReadonlySet<string>, coin: string): CopyRowState {
  if (!invested) return "would";
  return heldCoins.has(coin) ? "held" : "next";
}

export const COPY_ROW_LABEL: Record<CopyRowState, string> = { held: "held", next: "next trade", would: "would copy" };

/** Column header: money you hold is "Your copy"; money you don't is "Would copy". */
export function copyColumnTitle(invested: boolean): "Your copy" | "Would copy" {
  return invested ? "Your copy" : "Would copy";
}

/* ---------- #8: the pinned action bar ---------- */

export type LiqTone = "danger" | "warn" | "muted";

/** Liquidation distance under 10% is danger, under 25% warn (UX audit, Trade demo). */
export function liqTone(liq: LiqEstimate): LiqTone {
  if (liq.kind === "unknown") return "muted";
  if (liq.pct < 10) return "danger";
  if (liq.pct < 25) return "warn";
  return "muted";
}

export function liqText(liq: LiqEstimate): string {
  if (liq.kind === "unknown") return "n/a";
  return `~${liq.pct.toFixed(liq.pct < 1 ? 2 : 1)}%`;
}

export interface SummaryPart {
  label: string;
  value: string;
  tone?: LiqTone;
}

/** "Exposure $217.96 · Margin $13.94 · Liq ~1.5%": the action bar's one line. */
export function actionSummary(preview: Pick<TicketPreview, "exposureUsd" | "marginUsd" | "liq"> | null): SummaryPart[] {
  if (!preview) return [];
  return [
    { label: "Exposure", value: money(preview.exposureUsd) },
    { label: "Margin", value: money(preview.marginUsd) },
    { label: "Liq", value: liqText(preview.liq), tone: liqTone(preview.liq) },
  ];
}

/** Why the primary button is disabled, for its tooltip (DESIGN 5 Buttons). Null when enabled. */
export function disabledReason(o: { hasBody: boolean; action: "copy" | "update" | "unchanged"; pending: boolean; custom: boolean; amountText: string; error: string | null }): string | null {
  if (o.pending) return "Sending…";
  if (o.action === "unchanged") return "Nothing changed yet";
  if (o.hasBody) return null;
  if (o.custom && !o.amountText.trim()) return "Enter an amount";
  return o.error ?? "Not ready yet";
}

/* ---------- P0 (user_consensus_2026-10-14.md #4): your leverage vs their effective leverage ---------- */

export interface LeverageMismatch {
  /** Your liquidation distance at your chosen (capped) leverage, isolated. */
  yourPct: number;
  /** Their own estimated liquidation distance, from their effective (gross notional / their equity) leverage, isolated. */
  theirPct: number;
  /** Their effective leverage: gross notional / their equity (TicketPreview.hisLeverage). */
  theirLeverage: number;
  /** Your cushion is at most half of theirs: confirm before the copy opens (the most common documented way a copier is liquidated on a move the leader survives). */
  severe: boolean;
}

/**
 * Only meaningful in "Set leverage" (target) mode: a chosen number,
 * independent of the leader's own. In "Follow their leverage" (match) mode
 * each copy already opens at the leader's own per-coin leverage by
 * construction, so comparing it against his blended portfolio ratio
 * (gross notional / equity, across coins this ticket may not even copy)
 * would flag the safest, most faithful mode as if it were the risky one.
 *
 * Null when there is nothing comparable to warn about: match mode, cross
 * margin (no single isolated number), their leverage unknown, or your
 * cushion is already as wide as theirs or wider. The leader's own margin
 * mode is unknown from a position read alone, so "their effective
 * leverage" is always treated as isolated here; that is an approximation,
 * stated in the warning text, not a silent exact number.
 */
export function leverageMismatch(liq: LiqEstimate, theirLeverage: number | null | undefined, mode: ExposureMode): LeverageMismatch | null {
  if (mode !== "target" || liq.kind !== "isolated" || theirLeverage == null || !Number.isFinite(theirLeverage) || theirLeverage <= 0) return null;
  const theirPct = estimateLiquidationDistance(theirLeverage, "isolated").adverseMovePct;
  if (theirPct == null || liq.pct >= theirPct) return null;
  return { yourPct: liq.pct, theirPct, theirLeverage, severe: liq.pct <= theirPct / 2 };
}

/** "You liquidate on a ~9.0% move; they run an effective 3.0x (~32.3% cushion)." */
export function leverageMismatchText(m: LeverageMismatch): string {
  return `You liquidate on a ~${pctText(m.yourPct)} move; they run an effective ${m.theirLeverage.toFixed(1)}x (~${pctText(m.theirPct)} cushion). A move they'd survive could wipe your copy.`;
}
