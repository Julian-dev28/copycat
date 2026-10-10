import type { Settings } from "@/lib/api/types";
import { formatUsd } from "@/lib/format";

export interface LeaderTerms {
  /** How this wallet is sized, in its own terms ("Sized by Trade: $12.29"). */
  sizing: string;
  /** Leverage new copies open at after the max_position_leverage cap ("50x → 15x cap"). */
  leverage: string;
  /** True when the cap lowers what the wallet's own terms ask for. */
  capped: boolean;
}

type Terms = Pick<Settings, "sizing_mode" | "leverage_mode" | "leverage" | "max_position_leverage" | "fixed_margin_usd"
  | "fixed_notional_usd" | "size_multiplier" | "sleeve_frac" | "allocation_usd" | "exposure_mode" | "target_leverage">;

/**
 * One wallet's effective terms (Settings.for_leader: book-wide + its override),
 * worded like the engine applies them (engine/sizing.py exchange_leverage):
 * every leverage is capped by max_position_leverage (and the coin's own max,
 * which varies per coin and is left out here).
 * - allocation + exposure target: target_leverage, whatever leverage_mode says.
 * - fixed: leverage. match: their leverage per coin. max: the coin's max.
 */
export function leaderTerms(s: Terms): LeaderTerms {
  const cap = Math.max(1, s.max_position_leverage);
  let sizing: string;
  switch (s.sizing_mode) {
    case "allocation":
      sizing = `Sized by Trade: ${formatUsd(s.allocation_usd ?? null)}${s.exposure_mode === "target" ? " at your leverage" : " at their leverage"}`;
      break;
    case "proportional":
      sizing = `Sized by sleeve: ${Math.round(s.sleeve_frac * 100)}% of equity${s.size_multiplier !== 1 ? ` x${s.size_multiplier}` : ""}`;
      break;
    case "fixed_notional":
      sizing = `Fixed ${formatUsd(s.fixed_notional_usd)} per copy`;
      break;
    default:
      sizing = `Fixed ${formatUsd(s.fixed_margin_usd)} margin per copy`;
  }

  const asked =
    s.sizing_mode === "allocation" && s.exposure_mode === "target" ? s.target_leverage ?? null
      : s.leverage_mode === "fixed" ? s.leverage
        : null;
  if (asked !== null) {
    const capped = asked > cap;
    return { sizing, leverage: capped ? `${asked}x → ${cap}x cap` : `${asked}x`, capped };
  }
  if (s.leverage_mode === "match") return { sizing, leverage: `their leverage, cap ${cap}x`, capped: false };
  return { sizing, leverage: `coin max, cap ${cap}x`, capped: false };
}
