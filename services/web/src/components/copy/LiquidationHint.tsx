import { formatLiquidationHint } from "@/lib/liquidation";
import type { MarginMode } from "@/lib/api/types";

export function LiquidationHint({ leverage, marginMode }: { leverage: number; marginMode: MarginMode }) {
  return (
    <p className="font-num mt-1.5 text-xs text-muted">
      {formatLiquidationHint(leverage, marginMode)}
      <span className="ml-1 text-muted/70">(estimate, assumes {marginMode === "isolated" ? "the coin's real max leverage is close to the cap" : "isolated-style accounting"})</span>
    </p>
  );
}
