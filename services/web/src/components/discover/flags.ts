import type { TraderScore } from "@/lib/api/types";
import { summarizeFlags, type FlagSummary } from "@/lib/scoreExplain";

/**
 * Flag badges for one Discover row. The "liquidated" count comes from
 * `sim_liquidations`, the same number the Liquidations column shows: the sim
 * writes a `liquidated` flag entry per event plus extras, so counting flag
 * entries disagreed with the column on every liquidated row (UX audit #7).
 * No liquidations: no badge, whatever the flags say.
 */
export function traderFlags(t: Pick<TraderScore, "flags" | "sim_liquidations">): FlagSummary[] {
  const rest = summarizeFlags(t.flags).filter((f) => f.key !== "liquidated");
  if (t.sim_liquidations <= 0) return rest;
  const meaning = summarizeFlags(["liquidated"])[0].meaning;
  return [{ key: "liquidated", count: t.sim_liquidations, meaning }, ...rest];
}
