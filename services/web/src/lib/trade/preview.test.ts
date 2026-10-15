import { describe, expect, it } from "vitest";
import { concentrate, rawCopies, type TicketInput } from "./ticket";
import { estimateNote, localPreview } from "./preview";

const POS = [
  { coin: "BTC", side: "long" as const, notional_usd: 60_000, leverage: 10 },
  { coin: "ETH", side: "short" as const, notional_usd: 30_000, leverage: 5 },
  { coin: "kPEPE", side: "long" as const, notional_usd: 10_000, leverage: 3 },
];

const base: TicketInput = {
  allocationUsd: 50, mode: "target", targetLeverage: 10, marginMode: "isolated", smallMode: "skip",
  leaderEquityUsd: 50_000, positions: POS,
};

describe("rawCopies: their book in their proportions", () => {
  it("target: allocation x L spread by their gross notional", () => {
    // gross 100k; $50 x 10 = $500 -> 300 / 150 / 50
    expect(rawCopies(base)).toEqual([300, 150, 50]);
  });

  it("match: their notional / their equity x allocation (their own leverage)", () => {
    // he runs 2x on 50k equity: $50 carries $100
    expect(rawCopies({ ...base, mode: "match" })).toEqual([60, 30, 10]);
  });

  it("degenerate inputs size at 0, never NaN", () => {
    expect(rawCopies({ ...base, mode: "match", leaderEquityUsd: 0 })).toEqual([0, 0, 0]);
    expect(rawCopies({ ...base, positions: [] })).toEqual([]);
  });
});

describe("exposure, margin and the $10.50 minimum", () => {
  it("$50 at 10x: $500 exposure, $50 margin, all three clear the minimum", () => {
    const p = localPreview(base);
    expect(p.targetExposureUsd).toBe(500);
    expect(p.exposureUsd).toBeCloseTo(500);
    expect(p.marginUsd).toBeCloseTo(50);
    expect(p.copied).toBe(3);
    expect(p.copies.every((c) => c.leverage === 10)).toBe(true);
  });

  it("skip: a slice under $10.50 is flagged and dropped", () => {
    const p = localPreview({ ...base, allocationUsd: 10, targetLeverage: 5 }); // $50 -> 30 / 15 / 5
    expect(p.copies.map((c) => c.status)).toEqual(["copy", "copy", "skipped"]);
    expect(p.copies[2].reason).toMatch(/below \$10 min, skipped/);
    expect(p.copies[2].notionalUsd).toBe(0);
    expect(p.exposureUsd).toBeCloseTo(45);
  });

  it("$10.49 is under, $10.50 clears (boundary)", () => {
    const one = (n: number) => localPreview({ ...base, positions: [POS[0]], allocationUsd: n / 10 });
    expect(one(10.49).copies[0].status).toBe("skipped");
    expect(one(10.5).copies[0].status).toBe("copy");
  });

  it("concentrate: the skipped slice's dollars move to their bigger bets, total kept", () => {
    const p = localPreview({ ...base, allocationUsd: 10, targetLeverage: 5, smallMode: "concentrate" });
    expect(p.copies[2].status).toBe("skipped");
    expect(p.copies[0].notionalUsd).toBeCloseTo(33.33, 1); // 50 x 60/90
    expect(p.copies[1].notionalUsd).toBeCloseTo(16.67, 1);
    expect(p.exposureUsd).toBeCloseTo(50);
  });

  it("concentrate keeps dropping the smallest until everything left clears", () => {
    expect(concentrate([60, 30, 10], 20)).toEqual([20, 0, 0]);
    expect(concentrate([60, 30, 10], 5)).toEqual([0, 0, 0]);
  });

  it("bump: rounds a small slice up while margin fits the allocation x 1.02", () => {
    const p = localPreview({ ...base, allocationUsd: 10, targetLeverage: 5, smallMode: "bump" });
    // 30 + 15 at 5x = $9 margin, +10.5/5 = $2.10 -> $11.10 > $10.20 room: no room
    expect(p.copies[2].status).toBe("skipped");
    expect(p.copies[2].reason).toMatch(/no room/);
    const roomy = localPreview({ ...base, allocationUsd: 20, targetLeverage: 5, smallMode: "bump" }); // 60/30/10: $18 + $2.10 margin <= $20.40
    expect(roomy.copies[2].status).toBe("bumped");
    expect(roomy.copies[2].notionalUsd).toBe(10.5);
  });

  it("full book: the allocation where their smallest position clears the minimum", () => {
    const p = localPreview({ ...base, allocationUsd: 10, targetLeverage: 5 });
    expect(p.fullBookUsd).toBeCloseTo((10.5 * 100_000) / (10_000 * 5)); // $21
    expect(localPreview({ ...base, allocationUsd: p.fullBookUsd! }).copied).toBe(3);
  });
});

describe("follow their leverage", () => {
  it("opens each copy at ceil(their leverage) and reports their account leverage", () => {
    const p = localPreview({ ...base, mode: "match", positions: [{ ...POS[0], leverage: 2.4 }, POS[1]] });
    expect(p.copies.map((c) => c.leverage)).toEqual([3, 5]);
    expect(p.hisLeverage).toBeCloseTo(1.8); // 90k / 50k
    expect(p.targetExposureUsd).toBeCloseTo(90);
  });

  it("caps leverage at max_position_leverage", () => {
    const p = localPreview({ ...base, targetLeverage: 40, maxPositionLeverage: 20 });
    expect(p.copies[0].leverage).toBe(20);
  });
});

describe("liquidation distance", () => {
  it("isolated at your leverage: 1/L - 1/(2 x 50)", () => {
    const p = localPreview(base);
    expect(p.liq).toMatchObject({ kind: "isolated", leverage: 10 });
    expect(p.liq.kind === "isolated" && p.liq.pct).toBeCloseTo(9);
  });

  it("follow mode uses the highest leverage you'd run", () => {
    const p = localPreview({ ...base, mode: "match", allocationUsd: 1000 });
    expect(p.liq.kind === "isolated" && p.liq.leverage).toBe(10);
  });

  it("cross: equity over total exposure, including other wallets", () => {
    const p = localPreview({ ...base, marginMode: "cross", ourEquityUsd: 1000, otherExposureUsd: 500 });
    expect(p.liq.kind).toBe("cross");
    expect(p.liq.kind === "cross" && p.liq.pct).toBeCloseTo(99); // 1000/1000 - 1%
  });

  it("cross without known equity is unknown, not a fake number", () => {
    expect(localPreview({ ...base, marginMode: "cross" }).liq.kind).toBe("unknown");
  });
});

describe("liquidity cap", () => {
  it("a copy over 0.5% of 24h volume fills over several cycles", () => {
    const p = localPreview({ ...base, allocationUsd: 100_000, volume24hUsd: { BTC: 1e8, ETH: 1e9 } });
    // BTC copy 600k vs 500k per order -> 2 cycles; ETH 300k vs 5M -> 1
    expect(p.copies[0].cycles).toBe(2);
    expect(p.copies[1].cycles).toBe(1);
    expect(p.liquidityCapped).toBe(true);
    expect(p.maxCycles).toBe(2);
  });

  it("no volume data: never capped", () => {
    expect(localPreview({ ...base, allocationUsd: 1e7 }).liquidityCapped).toBe(false);
  });
});

describe("audit S8: coin max and the estimate label", () => {
  it("target sizing and leverage are capped by the coin's max, like the engine", () => {
    const pos = [{ ...POS[0], max_leverage: 5 }, POS[1], POS[2]];
    // BTC: 0.6 x $50 x min(10, 5) = $150, the rest at 10x
    expect(rawCopies({ ...base, positions: pos })).toEqual([150, 150, 50]);
    expect(localPreview({ ...base, positions: pos }).copies[0].leverage).toBe(5);
  });

  it("labels the local estimate whenever it is shown, with the data's age", () => {
    const now = 10 * 3_600_000;
    expect(estimateNote(null, true, now - 3 * 3_600_000, now)).toBe(
      "Estimate from cached data (their positions as of 3 h ago); the engine preview replaces it in a moment.");
    expect(estimateNote("too_old", true, now - 5 * 60_000, now)).toMatch(/^Local estimate \(their positions as of 5 min ago\): your api/);
    expect(estimateNote(null, false, now, now)).toBeNull();
  });
});
