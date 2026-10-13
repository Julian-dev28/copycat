/**
 * Trade ticket preview math: "invest $A in this wallet" -> the copies the
 * engine would open against his CURRENT book. Pure and unit-tested.
 *
 * This is the optimistic placeholder: the authoritative preview is
 * POST /api/wallets/{a}/preview (the engine's own sizing), and the ticket
 * swaps to it when it lands. Same formulas as services/engine/engine/sizing.py:
 *
 *   target (Set leverage L):   copy_i = his_i / his_gross * A * L, at L
 *   match  (Follow leverage):  copy_i = his_i / his_equity * A, at ceil(his lev_i)
 *
 * then the small-account rule for slices under HL's $10.50 minimum:
 *   concentrate: drop the smallest slice and re-spread the same total over
 *                the rest, in his proportions, until every slice clears it
 *   bump:        round a slice up to $10.50 while total margin fits A * 1.02
 *   skip:        drop it
 * and the liquidity cap: one order <= max_order_volume_pct of the coin's 24h
 * volume, the rest fills over the next cycles.
 */
import { HL_MIN_ORDER_USD } from "@/lib/api/types";
import type { ExposureMode, MarginMode, SmallAccountMode } from "./types";

/** services/engine/engine/sizing.py ALLOCATION_SLACK: a wallet's margin may run 2% over A. */
export const ALLOCATION_SLACK = 1.02;
export const DEFAULT_MAX_ORDER_VOLUME_PCT = 0.5;

export interface LeaderPos {
  coin: string;
  side: "long" | "short";
  notional_usd: number;
  leverage: number;
  /** HL's max leverage for the coin (v12, audit S8); the engine never exceeds it. */
  max_leverage?: number | null;
}

export interface TicketInput {
  allocationUsd: number;
  mode: ExposureMode;
  targetLeverage: number;
  marginMode: MarginMode;
  smallMode: SmallAccountMode;
  leaderEquityUsd: number;
  positions: LeaderPos[];
  maxPositionLeverage?: number;
  /** Coin -> 24h volume USD, for the liquidity cap. Coins missing here are never capped. */
  volume24hUsd?: Record<string, number>;
  maxOrderVolumePct?: number;
  /** Our account equity, for the cross-margin liquidation estimate. */
  ourEquityUsd?: number | null;
  /** Exposure we already carry outside this wallet (cross shares one account). */
  otherExposureUsd?: number;
}

export type CopyStatus = "copy" | "bumped" | "skipped";

export interface PlannedCopy {
  coin: string;
  side: "long" | "short";
  hisNotionalUsd: number;
  hisLeverage: number;
  /** What the engine would send, 0 when skipped. */
  notionalUsd: number;
  leverage: number;
  marginUsd: number;
  status: CopyStatus;
  reason: string | null;
  /** Cycles to fill under the liquidity cap; 1 = one order. */
  cycles: number;
  /** v8: the side WE open (his side inverted for counter). `side` stays his. Unset = same as his. */
  ourSide?: "long" | "short";
  /** v8: skipped by your coin filters ("only these" / "never these"). */
  filtered?: boolean;
}

export type LiqEstimate =
  | { kind: "isolated"; pct: number; leverage: number }
  | { kind: "cross"; pct: number }
  | { kind: "unknown" };

export interface TicketPreview {
  copies: PlannedCopy[];
  copied: number;
  total: number;
  exposureUsd: number;
  marginUsd: number;
  /** A x L, or A x his account leverage. */
  targetExposureUsd: number;
  /** His gross notional / his equity (the "N.Nx now" in Follow mode). */
  hisLeverage: number | null;
  /** Smallest allocation that copies every current position without concentrating or skipping. */
  fullBookUsd: number | null;
  liq: LiqEstimate;
  liquidityCapped: boolean;
  maxCycles: number;
  /** Engine notes (api preview only), e.g. "his equity read is stale". */
  notes?: string[];
  source: "local" | "api";
  /** v8: the direction the sides were stamped with (applyDirection). */
  direction?: "copy" | "counter";
}

/** Raw (pre-minimum) notionals in his proportions. */
export function rawCopies(inp: TicketInput): number[] {
  const A = Math.max(0, inp.allocationUsd);
  const gross = inp.positions.reduce((a, p) => a + Math.abs(p.notional_usd), 0);
  return inp.positions.map((p) => {
    const n = Math.abs(p.notional_usd);
    if (inp.mode === "target") {
      // engine: n/gross x A x the coin's exchange leverage, which the coin max caps (S8)
      const coinMax = p.max_leverage && p.max_leverage > 0 ? p.max_leverage : Infinity;
      return gross > 0 ? (n / gross) * A * Math.max(1, Math.min(inp.targetLeverage, coinMax)) : 0;
    }
    return inp.leaderEquityUsd > 0 ? (n / inp.leaderEquityUsd) * A : 0;
  });
}

/** Concentrate: drop the smallest slice until the rest, re-spread over the same total, all clear the minimum. */
export function concentrate(his: number[], total: number, min = HL_MIN_ORDER_USD): number[] {
  const kept = his.map((n, i) => ({ n, i })).filter((x) => x.n > 0).sort((a, b) => b.n - a.n);
  while (kept.length) {
    const sum = kept.reduce((a, x) => a + x.n, 0);
    const smallest = kept[kept.length - 1];
    if ((smallest.n / sum) * total >= min) {
      const out = his.map(() => 0);
      for (const x of kept) out[x.i] = (x.n / sum) * total;
      return out;
    }
    kept.pop();
  }
  return his.map(() => 0);
}
