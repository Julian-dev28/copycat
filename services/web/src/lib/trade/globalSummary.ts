/**
 * "Use global": the Settings tab values that will apply to a wallet, as
 * plain label/value rows for the ticket's read-only summary. Pure, tested.
 */
import { formatUsd } from "@/lib/format";
import type { TradeSettings } from "./types";

export interface SummaryRow {
  label: string;
  value: string;
}

const SMALL: Record<string, string> = { concentrate: "Concentrate", bump: "Round up to $10", skip: "Skip" };

export function sizingText(s: TradeSettings): string {
  switch (s.sizing_mode) {
    case "fixed_margin":
      return `Fixed margin, ${formatUsd(s.fixed_margin_usd)} per copy`;
    case "fixed_notional":
      return `Fixed size, ${formatUsd(s.fixed_notional_usd)} per copy`;
    case "proportional":
      return `Proportional, ${s.size_multiplier}x their size on ${Math.round(s.sleeve_frac * 100)}% of equity`;
    case "allocation":
      return `${formatUsd(s.allocation_usd ?? 0)} per wallet`;
    default:
      return String(s.sizing_mode);
  }
}

export function leverageText(s: TradeSettings): string {
  const cap = s.max_position_leverage;
  if (s.sizing_mode === "allocation" && s.exposure_mode === "target") return `${s.target_leverage ?? 5}x on their positions (cap ${cap}x)`;
  if (s.leverage_mode === "match") return `Follow theirs, cap ${cap}x`;
  if (s.leverage_mode === "fixed") return `Fixed ${Math.min(s.leverage, cap)}x`;
  return `Each coin's max, cap ${cap}x`;
}

export function globalSummary(s: TradeSettings): SummaryRow[] {
  const rows: SummaryRow[] = [
    { label: "Sizing", value: sizingText(s) },
    { label: "Leverage", value: leverageText(s) },
    { label: "Margin", value: s.margin_mode === "cross" ? "Cross" : "Isolated" },
    { label: "Max worse entry", value: `${s.max_worse_entry_pct}%` },
  ];
  if (s.small_account_mode) rows.push({ label: "Under $10", value: SMALL[s.small_account_mode] ?? s.small_account_mode });
  rows.push({ label: "Only new positions", value: s.only_new_positions ? "On" : "Off" });
  if (s.trade_direction) rows.push({ label: "Direction", value: s.trade_direction === "counter" ? "Counter (opposite side)" : "Copy" });
  if (s.coin_allowlist?.length) rows.push({ label: "Only these coins", value: s.coin_allowlist.join(", ") });
  if (s.coin_blocklist?.length) rows.push({ label: "Never these coins", value: s.coin_blocklist.join(", ") });
  return rows;
}
