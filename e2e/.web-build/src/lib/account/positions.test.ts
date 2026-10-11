import { describe, expect, it } from "vitest";
import type { CopyPosition } from "@/lib/api/types";
import type { TraderPositionView } from "@/lib/scout/types";
import { isEngineAccount, mergeAccountPositions } from "./positions";

const L = "0x" + "a".repeat(40);
const own = (coin: string, notional: number): TraderPositionView => ({
  coin, side: "long", size: 1, notional_usd: notional, entry_px: 100, mark_px: 100, unrealized_pnl_usd: 0, roe_pct: 0,
  leverage: 5, is_cross: true, liquidation_px: null, liq_distance_pct: null, margin_usd: notional / 5, funding_since_open_usd: 0,
});
const copy: CopyPosition = {
  coin: "ETH", leader: L, side: "short", size: -0.005, entry_px: 2334, mark_px: 2330, notional_usd: 11.67, leverage: 15,
  is_cross: false, unrealized_pnl_usd: -0.02, liquidation_px: 2480, opened_ms: 1, sizing_mode: "allocation",
} as CopyPosition;

describe("mergeAccountPositions", () => {
  it("adds the engine's copy the account read missed (the audit's ETH short)", () => {
    const rows = mergeAccountPositions([], [copy], true);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ coin: "ETH", source: "copycat", leader: L, side: "short", leverage: 15 });
    expect(rows[0].margin_usd).toBeCloseTo(11.67 / 15);
    expect(rows[0].liq_distance_pct).toBeCloseTo((150 / 2330) * 100);
  });

  it("tags a coin the engine copies, keeps the rest manual, no duplicates", () => {
    const rows = mergeAccountPositions([own("BTC", 500), own("ETH", 12)], [copy], true);
    expect(rows.map((r) => [r.coin, r.source])).toEqual([["BTC", "manual"], ["ETH", "copycat"]]);
    expect(rows.find((r) => r.coin === "ETH")?.leader).toBe(L);
  });

  it("ignores copies when the engine trades another account", () => {
    expect(mergeAccountPositions([own("BTC", 1)], [copy], false).map((r) => r.source)).toEqual(["manual"]);
  });
});

describe("isEngineAccount", () => {
  it("matches the engine's address case-insensitively, or the active account in demo", () => {
    expect(isEngineAccount("0xABC", "0xabc", false, false)).toBe(true);
    expect(isEngineAccount("0xabc", null, false, true)).toBe(false);
    expect(isEngineAccount("0xabc", "0xdef", true, true)).toBe(true);
  });
});
