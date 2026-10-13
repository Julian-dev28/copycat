import { describe, expect, it } from "vitest";
import { tickerItems, tickerSpeedS } from "./ticker";
import type { TraderRow } from "./types";

const row = (over: Partial<TraderRow>): TraderRow =>
  ({
    address: "0x" + "ab".repeat(20),
    display_name: null,
    perf: [{ window: "30d", pnl_usd: 1234, roi_pct: 12.5, volume_usd: 1 }],
    ...over,
  }) as TraderRow;

describe("tickerItems", () => {
  it("takes the top rows in order, named by display name else short address", () => {
    const items = tickerItems([row({ display_name: "whale" }), row({ address: "0x" + "12".repeat(20) })], "30d", "pct");
    expect(items.map((i) => [i.rank, i.name, i.value])).toEqual([[1, "whale", 12.5], [2, "0x1212…1212", 12.5]]);
  });
  it("uses $ PnL in usd mode and null when the window is missing", () => {
    expect(tickerItems([row({})], "30d", "usd")[0].value).toBe(1234);
    expect(tickerItems([row({ perf: [] })], "30d", "pct")[0].value).toBeNull();
  });
  it("caps the strip", () => {
    expect(tickerItems(Array.from({ length: 40 }, () => row({})), "30d", "pct")).toHaveLength(12);
  });
  it("drifts slowly", () => {
    expect(tickerSpeedS(3)).toBe(30);
    expect(tickerSpeedS(12)).toBe(72);
  });
});
