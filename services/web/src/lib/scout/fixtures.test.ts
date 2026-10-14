import { describe, expect, it } from "vitest";
import { applySimTerms, DEFAULT_SIM_TERMS, fixtureRows } from "./fixtures";
import type { ScoutSimTerms } from "./types";

const NOW = 1_700_000_000_000;

describe("applySimTerms (demo re-sim stand-in)", () => {
  it("is deterministic: same rows + same terms => byte-identical output", () => {
    const rows = fixtureRows(NOW);
    const a = applySimTerms(rows, DEFAULT_SIM_TERMS);
    const b = applySimTerms(rows, DEFAULT_SIM_TERMS);
    expect(a).toEqual(b);
  });

  it("different terms re-rank the board: the row order changes", () => {
    const rows = fixtureRows(NOW);
    const atDefault = applySimTerms(rows, DEFAULT_SIM_TERMS).map((r) => r.address);
    const atHigherLeverage: ScoutSimTerms = { ...DEFAULT_SIM_TERMS, leverage: 25, target_leverage: 25, allocation_usd: 500 };
    const atHigher = applySimTerms(rows, atHigherLeverage).map((r) => r.address);
    expect(atHigher).not.toEqual(atDefault);
  });

  it("every row keeps a valid Copy Fit (0..100) and the result stays sorted by it, descending", () => {
    const rows = fixtureRows(NOW);
    const out = applySimTerms(rows, { ...DEFAULT_SIM_TERMS, allocation_usd: 250, leverage: 10, target_leverage: 10 });
    for (const row of out) {
      const fit = row.score.copy_fit?.value;
      expect(fit).toBeGreaterThanOrEqual(0);
      expect(fit).toBeLessThanOrEqual(100);
    }
    const values = out.map((r) => r.score.copy_fit?.value ?? 0);
    for (let i = 1; i < values.length; i++) expect(values[i - 1]).toBeGreaterThanOrEqual(values[i]);
  });

  it("never renders the raw score (only recomputes sim fields and copy_fit)", () => {
    const rows = fixtureRows(NOW);
    const out = applySimTerms(rows, DEFAULT_SIM_TERMS);
    for (const row of out) {
      expect(typeof row.score.score).toBe("number"); // present (internal), unchanged by this function
    }
  });

  it("re-applies the same caps as the original fixture (liquidated/inactive/etc never silently lift)", () => {
    const rows = fixtureRows(NOW);
    const liquidatedBefore = rows.find((r) => r.flags.includes("liquidated"));
    expect(liquidatedBefore).toBeTruthy();
    const out = applySimTerms(rows, DEFAULT_SIM_TERMS);
    const liquidatedAfter = out.find((r) => r.address === liquidatedBefore!.address);
    expect(liquidatedAfter!.score.copy_fit!.value).toBeLessThanOrEqual(20);
    expect(liquidatedAfter!.score.copy_fit!.caps).toContain("liquidated");
  });
});
