import { describe, expect, it } from "vitest";
import { normalizeSpark, periodText, shareCardData, shareFileName } from "./shareCard";
import type { WalletPosition } from "./types";

const A = "0x1234567890abcdef1234567890abcdef12345678";
const DAY = 86_400_000;
const NOW = Date.UTC(2026, 9, 11);
const w: WalletPosition = {
  address: A, read_ok: true, open_copies: 2, margin_used_usd: 100, exposure_usd: 500, unrealized_pnl_usd: 30, realized_pnl_usd: 25,
  fees_usd: 5, stopping: false, allocation_usd: 1_000, roe_pct: 5, invested_ms: NOW - 12 * DAY, trade_direction: "counter",
};

describe("PnL card data shaping", () => {
  it("only on-screen numbers: short address, direction, PnL $, % of exposure, ROE, period", () => {
    const d = shareCardData(w, { nowMs: NOW });
    expect(d.shortAddress).toBe("0x1234…5678");
    expect(d.title).toBe("0x1234…5678");
    expect(d.directionLabel).toBe("Countering");
    expect(d.pnlUsd).toBe(50);
    expect(d.pnlPct).toBeCloseTo(10);
    expect(d.roeText).toBe("+5.0%");
    expect(d.period).toBe("since Sep 29 · 12 days");
    const json = JSON.stringify(d);
    expect(json).not.toContain(A);
    expect(json).not.toContain("1,000");
  });
  it("uses pnl_usd when the api sends it; a name becomes the title", () => {
    const d = shareCardData({ ...w, pnl_usd: -7, trade_direction: "copy" }, { nowMs: NOW, name: "Kestrel" });
    expect(d.pnlText).toBe("-$7.00");
    expect(d.up).toBe(false);
    expect(d.title).toBe("Kestrel");
    expect(d.directionLabel).toBe("Copying");
  });
  it("sparkline: their index since the copy started, inverted for counter, in the unit box", () => {
    const index = [0, 1, 2, 3].map((i) => ({ t_ms: NOW - (20 - i * 5) * DAY, value: 100 + i * 10 }));
    const d = shareCardData(w, { nowMs: NOW, index });
    expect(d.spark.length).toBe(2); // only the points after invested_ms (12 days ago)
    expect(d.spark[0]).toEqual({ x: 0, y: 1 }); // counter of a rising index falls
    expect(d.spark.at(-1)!.y).toBe(0);
    expect(normalizeSpark([{ t_ms: 1, value: 1 }])).toEqual([]);
  });
  it("period and file name", () => {
    expect(periodText(null, NOW)).toBe("since you started");
    expect(periodText(NOW - 3_600_000, NOW)).toContain("today");
    expect(shareFileName({ shortAddress: "0x1234…5678", direction: "copy" })).toBe("copycat-0x1234-5678-copy-pnl.png");
  });
});
