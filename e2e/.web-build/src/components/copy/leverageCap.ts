import type { Settings } from "@/lib/api/types";

export interface LeverageCap {
  /** The fixed leverage the operator set. */
  set: number;
  /** What new copies actually open at: min(set, max_position_leverage), like engine/sizing.py. */
  effective: number;
  /** True when max_position_leverage silently overrides the fixed leverage. */
  capped: boolean;
}

/**
 * Fixed-mode leverage after the max_position_leverage cap. The engine applies
 * min(leverage, max_position_leverage) in every mode, so a fixed leverage above
 * the cap is a no-op. Returns null outside fixed mode (nothing to explain).
 */
export function fixedLeverageCap(
  s: Pick<Settings, "leverage_mode" | "leverage" | "max_position_leverage">,
): LeverageCap | null {
  if (s.leverage_mode !== "fixed") return null;
  const cap = Math.max(1, s.max_position_leverage);
  const effective = Math.max(1, Math.min(s.leverage, cap));
  return { set: s.leverage, effective, capped: s.leverage > cap };
}
