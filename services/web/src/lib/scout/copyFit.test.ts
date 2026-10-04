import { describe, expect, it } from "vitest";
import { blendedFit, capLines, fitGrade, fitSegments, PART_ORDER, topParts } from "./copyFit";
import { FIT_WEIGHTS } from "./fixtures";
import type { CopyFit } from "./types";

function fit(parts: Record<string, number>, caps: string[] = [], value?: number): CopyFit {
  const f = { value: 0, parts, weights: FIT_WEIGHTS, caps, cohort_size: 280 } as unknown as CopyFit;
  f.value = value ?? blendedFit(f);
  return f;
}

const allHalf = Object.fromEntries(Object.keys(FIT_WEIGHTS).map((k) => [k, 0.5]));

describe("fitSegments", () => {
  it("weights sum to 1, so the bar widths sum to 100%", () => {
    const segs = fitSegments(fit(allHalf));
    expect(segs.reduce((a, s) => a + s.max, 0)).toBeCloseTo(100, 6);
  });

  it("orders known parts by PART_ORDER, sim first", () => {
    const keys = fitSegments(fit(allHalf)).map((s) => s.key);
    expect(keys[0]).toBe("sim");
    expect(keys).toEqual(PART_ORDER.filter((k) => k in FIT_WEIGHTS));
  });

  it("clamps parts to 0..1 and treats NaN/missing as 0", () => {
    const segs = fitSegments(fit({ sim: 1.7, sharpe: Number.NaN, drawdown: -0.2 }));
    const by = Object.fromEntries(segs.map((s) => [s.key, s.part]));
    expect(by.sim).toBe(1);
    expect(by.sharpe).toBe(0);
    expect(by.drawdown).toBe(0);
    expect(by.recency).toBe(0);
  });

  it("keeps parts the api adds that the ui does not know yet", () => {
    const f = { value: 10, parts: { sim: 1, novel_thing: 1 }, weights: { sim: 0.5, novel_thing: 0.5 }, caps: [], cohort_size: 1 } as unknown as CopyFit;
    const segs = fitSegments(f);
    expect(segs.map((s) => s.key)).toEqual(["sim", "novel_thing"]);
    expect(segs[1].label).toBe("novel thing");
  });
});

describe("blendedFit", () => {
  it("is 100 * sum(weight * part)", () => {
    expect(blendedFit(fit(allHalf))).toBeCloseTo(50, 6);
    expect(blendedFit(fit({}))).toBe(0);
  });
});

describe("capLines", () => {
  it("marks a cap binding only when the blend is above its ceiling", () => {
    const high = fit(Object.fromEntries(Object.keys(FIT_WEIGHTS).map((k) => [k, 0.9])), ["liquidated"], 20);
    expect(capLines(high)).toEqual([expect.objectContaining({ flag: "liquidated", binding: true })]);
    const low = fit(Object.fromEntries(Object.keys(FIT_WEIGHTS).map((k) => [k, 0.1])), ["hft"]);
    expect(capLines(low)[0].binding).toBe(false);
  });

  it("matches flags with a detail suffix and keeps discovery's cap order", () => {
    const f = fit(allHalf, ["hft", "too_few_trades:3", "unknown"]);
    expect(capLines(f).map((c) => c.flag)).toEqual(["too_few_trades", "hft"]);
  });

  it("fills_truncated is informational, never binding", () => {
    expect(capLines(fit(allHalf, ["fills_truncated"]))[0].binding).toBe(false);
  });
});

describe("fitGrade / topParts", () => {
  it("grades at 40 and 70", () => {
    expect(fitGrade(70)).toBe("strong");
    expect(fitGrade(69.9)).toBe("fair");
    expect(fitGrade(40)).toBe("fair");
    expect(fitGrade(39)).toBe("weak");
    expect(fitGrade(null)).toBe("none");
    expect(fitGrade(Number.NaN)).toBe("none");
  });

  it("topParts returns the 3 biggest contributors", () => {
    const top = topParts(fit({ ...allHalf, sim: 1 }));
    expect(top).toHaveLength(3);
    expect(top[0].key).toBe("sim");
    for (let i = 1; i < top.length; i++) expect(top[i - 1].points).toBeGreaterThanOrEqual(top[i].points);
  });
});
