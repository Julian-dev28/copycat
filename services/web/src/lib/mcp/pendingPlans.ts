/**
 * Pending MCP plans (audit H2): Claude Code never sees a plan's confirm code,
 * so the human reads it here and types it back to Claude. Pure helpers for the
 * Portfolio panel; the component in components/mcp stays thin.
 */
import type { McpPendingPlan } from "@/lib/api/types";
import { formatLeverage, formatUsd, shortenAddress } from "@/lib/format";

/** Whole seconds until the plan expires, never negative. */
export function secondsLeft(plan: Pick<McpPendingPlan, "expires_ms">, nowMs: number): number {
  return Math.max(0, Math.floor((plan.expires_ms - nowMs) / 1000));
}

/** "4:05", "0:09". */
export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * Plans still usable at `nowMs`, newest first. The api already drops used and
 * expired plans; this also hides one that expired between two polls.
 */
export function livePlans(plans: readonly McpPendingPlan[] | undefined, nowMs: number): McpPendingPlan[] {
  return (plans ?? [])
    .filter((p) => p.expires_ms > nowMs)
    .slice()
    .sort((a, b) => b.created_ms - a.created_ms);
}

/** The code split for reading aloud: "ABC DEF". */
export function spacedCode(code: string): string {
  return code.length === 6 ? `${code.slice(0, 3)} ${code.slice(3)}` : code;
}

/** One line of terms, the same words the MCP shows Claude. */
export function planTerms(p: McpPendingPlan): string {
  const lev = p.leverage == null ? "trader's leverage" : formatLeverage(p.leverage);
  const dir = p.trade_direction === "counter" ? "countering their side" : "copying their side";
  const follow = p.follow ? "following new positions" : "one-shot";
  return `${formatUsd(p.amount_usd)} at ${lev}, ${dir}, entries within ${p.entry_deviation_pct}%, ${follow}`;
}

export function planTrader(p: McpPendingPlan): string {
  return shortenAddress(p.address);
}

/**
 * What happens if the human approves. Not executable: execute is refused.
 * Not live: settings save but no order goes out.
 */
export function planOutcome(p: McpPendingPlan): { tone: "accent" | "warn" | "danger"; text: string } {
  if (!p.executable) return { tone: "danger", text: "Not executable: copycat will refuse this plan" };
  if (!p.trading_live) return { tone: "warn", text: "Trading is off: approving saves settings, places no orders" };
  return { tone: "accent", text: "Live: approving places real orders" };
}
