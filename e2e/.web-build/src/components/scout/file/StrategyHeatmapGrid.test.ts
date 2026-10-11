import { describe, expect, it } from "vitest";
import { axisBars, realGrid } from "./StrategyHeatmapGrid";

const empty = () => Array.from({ length: 7 }, () => Array<number>(24).fill(0));

describe("realGrid", () => {
  it("keeps every cell as sent: no cell is invented from the axis totals", () => {
    const m = empty();
    m[0][9] = 3; // Mon 09:00
    m[4][21] = 1; // Fri 21:00
    const g = realGrid(m)!;
    expect(g.cells[0][9]).toBe(3);
    expect(g.cells[4][21]).toBe(1);
    expect(g.cells[0][21]).toBe(0); // the product model would put ~0.75 here
    expect(g.cells[4][9]).toBe(0);
    expect(g.weekdays[0]).toBe(3);
    expect(g.hours[21]).toBe(1);
    expect(g.total).toBe(4);
    expect(g.max).toBe(3);
    expect(g.peakHour).toBe(9);
    expect(g.peakWeekday).toBe(0);
  });

  it("is null for an old cached fingerprint (missing or wrong shape)", () => {
    expect(realGrid(undefined)).toBeNull();
    expect(realGrid([])).toBeNull();
    expect(realGrid([[1, 2, 3]])).toBeNull();
  });

  it("an all-zero matrix has no peak", () => {
    const g = realGrid(empty())!;
    expect(g.total).toBe(0);
    expect(g.peakHour).toBeNull();
  });
});

describe("axisBars", () => {
  it("pads short histograms and drops junk", () => {
    const b = axisBars([1, 2], [5, Number.NaN, -1]);
    expect(b.hours).toHaveLength(24);
    expect(b.weekdays).toEqual([5, 0, 0, 0, 0, 0, 0]);
    expect(b.total).toBe(5);
  });
});
