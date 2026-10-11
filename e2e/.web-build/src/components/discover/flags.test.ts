import { describe, expect, it } from "vitest";
import { traderFlags } from "./flags";

describe("traderFlags", () => {
  it("counts liquidations from sim_liquidations, not flag entries", () => {
    const f = traderFlags({ flags: ["liquidated", "liquidated:BTC", "liquidated:ETH", "hft"], sim_liquidations: 2 });
    expect(f.find((x) => x.key === "liquidated")?.count).toBe(2);
    expect(f.find((x) => x.key === "hft")?.count).toBe(1);
  });

  it("drops the badge when the column says zero", () => {
    expect(traderFlags({ flags: ["liquidated:BTC"], sim_liquidations: 0 }).some((x) => x.key === "liquidated")).toBe(false);
  });

  it("adds the badge when the sim liquidated but no flag says so", () => {
    expect(traderFlags({ flags: [], sim_liquidations: 3 })).toEqual([
      { key: "liquidated", count: 3, meaning: "a copy got liquidated" },
    ]);
  });

  it("badge and column agree for every count", () => {
    for (let n = 0; n < 6; n++) {
      const flags = Array.from({ length: n + 1 }, (_, i) => `liquidated:C${i}`);
      const badge = traderFlags({ flags, sim_liquidations: n }).find((x) => x.key === "liquidated");
      expect(badge?.count ?? 0).toBe(n);
    }
  });
});
