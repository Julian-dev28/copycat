import type { McpPendingPlan } from "@/lib/api/types";

/** A live, executable plan for tests. */
export function plan(over: Partial<McpPendingPlan> = {}): McpPendingPlan {
  return {
    plan_id: "plan_0123456789abcdef", confirm_code: "K7QX2M", created_ms: 1_000, expires_ms: 301_000,
    address: "0x77375a8c9d13bf79afb2a87f1b0ac1dfd5f5bf66", amount_usd: 50, leverage: 3,
    entry_deviation_pct: 2, trade_direction: "copy", follow: true, executable: true, trading_live: true,
    planned_notional_usd: 150, planned_margin_usd: 50, copied: 0, warnings: [], ...over,
  };
}
