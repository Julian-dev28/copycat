import { describe, expect, it } from "vitest";
import { buildDualSparkline, buildSparkline, linearScale, linePath, niceTicks, timeExtent, valueExtent } from "./spark";

const pts = (vals: number[]) => vals.map((value, i) => ({ t_ms: i * 1000, value }));

describe("linearScale", () => {
  it("maps domain to range, zero-width domain to the middle", () => {
    const s = linearScale([0, 10], [0, 100]);
    expect(s(5)).toBe(50);
    expect(linearScale([3, 3], [0, 100])(3)).toBe(50);
  });
});

describe("linePath", () => {
  it("rounds to 2 decimals, never prints -0", () => {
    expect(linePath(pts([1, -0.0001]), (t) => t / 3000, (v) => v)).toBe("M0 1 L0.33 0");
    expect(linePath([], (t) => t, (v) => v)).toBe("");
  });
});

describe("extents", () => {
  it("value extent always includes zero", () => {
    expect(valueExtent([pts([5, 9])])).toEqual([0, 9]);
    expect(valueExtent([pts([-4, -1])])).toEqual([-4, 0]);
    expect(valueExtent([[]], false)).toEqual([0, 0]);
  });
  it("time extent over several series", () => {
    expect(timeExtent([pts([1, 2]), [{ t_ms: 9000, value: 0 }]])).toEqual([0, 9000]);
    expect(timeExtent([])).toEqual([0, 0]);
  });
});

describe("buildSparkline", () => {
  it("returns null under 2 points", () => {
    expect(buildSparkline(pts([5]), 100, 40)).toBeNull();
    expect(buildSparkline([], 100, 40)).toBeNull();
  });

  it("rebases to 0 at the window start and reports the net change", () => {
    const s = buildSparkline(pts([1000, 1500, 1200]), 100, 40)!;
    expect(s.change).toBe(200);
    expect(s.last.value).toBe(200);
    // first point sits on the zero line
    expect(s.path.startsWith(`M2 ${s.zeroY}`)).toBe(true);
  });

  it("sorts unsorted input by time", () => {
    const s = buildSparkline([{ t_ms: 2000, value: 3 }, { t_ms: 0, value: 1 }], 100, 40)!;
    expect(s.change).toBe(2);
  });

  it("an all-loss curve keeps zero at the top of the plot", () => {
    const s = buildSparkline(pts([0, -10, -20]), 100, 40, 2)!;
    expect(s.zeroY).toBe(2);
    expect(s.area.endsWith("Z")).toBe(true);
  });
});

describe("niceTicks", () => {
  it("uses 1/2/2.5/5 steps and includes 0", () => {
    expect(niceTicks(-50, 150, 4)).toEqual([-50, 0, 50, 100, 150]);
    expect(niceTicks(0, 1, 4)).toEqual([0, 0.25, 0.5, 0.75, 1]);
    expect(niceTicks(5, 5)).toEqual([5]);
    expect(niceTicks(Number.NaN, 1)).toEqual([]);
  });
});

describe("buildDualSparkline (his PnL + your sim, spec 4.1)", () => {
  it("needs 2 of his points; the sim is optional", () => {
    expect(buildDualSparkline(pts([1]), pts([1, 2]), 100, 40)).toBeNull();
    const s = buildDualSparkline(pts([0, 5]), pts([1000]), 100, 40)!;
    expect(s.sim).toBeNull();
  });

  it("scales each series to its own largest move so a $1k sim is not flattened by a $500k trader", () => {
    const s = buildDualSparkline(pts([0, 250_000, 500_000]), pts([1000, 1050, 1100]), 100, 40, 0)!;
    // both end at the top of the plot (each at +1 in its own units)
    expect(s.his.path.endsWith("L100 0")).toBe(true);
    expect(s.sim!.path.endsWith("L100 0")).toBe(true);
    // changes are reported in real dollars
    expect(s.his.change).toBe(500_000);
    expect(s.sim!.change).toBe(100);
  });

  it("shares one zero line, both series start on it", () => {
    const s = buildDualSparkline(pts([10, -40, 20]), pts([1000, 1100, 900]), 100, 40, 0)!;
    expect(s.zeroY).toBeGreaterThan(0);
    expect(s.zeroY).toBeLessThan(40);
    expect(s.his.path.startsWith(`M0 ${s.zeroY}`)).toBe(true);
    expect(s.sim!.path.startsWith(`M0 ${s.zeroY}`)).toBe(true);
  });

  it("a flat series stays on zero instead of dividing by zero", () => {
    const s = buildDualSparkline(pts([3, 3, 3]), pts([1000, 1000]), 100, 40, 0)!;
    expect(s.his.path).not.toContain("NaN");
    expect(s.sim!.path).not.toContain("NaN");
  });
});
