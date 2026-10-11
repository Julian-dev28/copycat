/**
 * Contract v8 TradeDirection on the ticket: copy mirrors his sides, counter
 * takes the opposite side of every position he opens (same sizes; his
 * reduces and closes are followed, inverted). Pure, unit-tested.
 */
import type { CurvePoint } from "@/lib/scout/types";
import type { PlannedCopy, TicketPreview } from "./ticket";
import type { TradeDirection } from "./types";

export const DIRECTION_META: Record<TradeDirection, { label: string; line: string }> = {
  copy: { label: "Copy", line: "Copy takes the same side as every position they open." },
  counter: { label: "Counter", line: "Counter takes the opposite side of every position they open." },
};

export type Side = "long" | "short";

export const flipSide = (s: Side): Side => (s === "long" ? "short" : "long");

/** The side our copy takes for his side. */
export function ourSide(his: Side, dir: TradeDirection): Side {
  return dir === "counter" ? flipSide(his) : his;
}

/**
 * Stamp our side on every planned copy. `side` stays HIS side (the contract's
 * WalletPreviewSlice is "one of his positions"); `ourSide` is what we open.
 * Sizes, leverage and margin are direction-blind, like the engine.
 */
export function applyDirection(p: TicketPreview, dir: TradeDirection): TicketPreview {
  const copies: PlannedCopy[] = p.copies.map((c) => ({ ...c, ourSide: ourSide(c.side, dir) }));
  return { ...p, copies, direction: dir };
}

/**
 * The equity index of trading against him: every step's return, negated,
 * compounded from the same start. Not 200 - index: a short loses more than a
 * long gains on the way up, and the series can hit zero (then it stays there).
 */
export function invertSeries(points: CurvePoint[]): CurvePoint[] {
  if (points.length === 0) return [];
  const sorted = [...points].sort((a, b) => a.t_ms - b.t_ms);
  const out: CurvePoint[] = [{ t_ms: sorted[0].t_ms, value: sorted[0].value }];
  for (let i = 1; i < sorted.length; i++) {
    const prev = sorted[i - 1].value;
    const last = out[i - 1].value;
    const r = prev > 0 ? sorted[i].value / prev - 1 : 0;
    out.push({ t_ms: sorted[i].t_ms, value: Math.max(0, last * (1 - r)) });
  }
  return out;
}

/** Effective direction: the ticket's choice, else the Settings default, else copy. */
export function effectiveDirection(draftDir: TradeDirection | null | undefined, settingsDir: TradeDirection | null | undefined): TradeDirection {
  return draftDir ?? settingsDir ?? "copy";
}
