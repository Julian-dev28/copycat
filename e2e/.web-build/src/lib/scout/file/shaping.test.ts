import { describe, expect, it } from "vitest";
import { buildCalendar } from "../calendar";
import { fixtureProfile } from "../fixtures";
import { linePath, linearScale } from "../spark";
import { chartData } from "../window";
import { buildWhatIfRequest, draftFromOverride, overrideSettingsPatch } from "../whatIf";
import { demoFileRow, fixtureFingerprint } from "./fixtures";
import { heatLevel, hourWeekdayGrid } from "./strategy";

const NOW = Date.UTC(2026, 9, 4, 12, 0);
const DAY = 86_400_000;
const ADDR = "0xe2823659be02e0f48a4660e4da008b5e1abfdf29";

describe("chart paths", () => {
  it("maps points to an M/L path inside the plot box", () => {
    const pts = [
      { t_ms: 0, value: 0 },
      { t_ms: 10, value: 10 },
      { t_ms: 20, value: 5 },
    ];
    const x = linearScale([0, 20], [0, 200]);
    const y = linearScale([0, 10], [100, 0]);
    const d = linePath(pts, x, y);
    expect(d.startsWith("M")).toBe(true);
    expect(d.match(/L/g)?.length).toBe(2);
    expect(d).toContain("100");
  });

  it("overlay turns his PnL and the sim into % series that start at 0", () => {
    const profile = fixtureProfile(demoFileRow(ADDR, NOW), NOW);
    const data = chartData(profile, "pnl", "30d", true);
    expect(data.unit).toBe("pct");
    const keys = data.series.map((s) => s.key);
    expect(keys).toContain("his");
    expect(keys).toContain("sim");
    for (const s of data.series) if (s.points.length) expect(Math.abs(s.points[0].value)).toBeLessThan(1e-9);
  });

  it("a what-if sim curve replaces the saved one in the overlay", () => {
    const profile = fixtureProfile(demoFileRow(ADDR, NOW), NOW);
    const curve = [
      { t_ms: NOW - 20 * DAY, value: 1000 },
      { t_ms: NOW, value: 1500 },
    ];
    const data = chartData({ ...profile, sim_curve: curve }, "pnl", "30d", true);
    const sim = data.series.find((s) => s.key === "sim");
    expect(sim?.points.at(-1)?.value).toBeCloseTo(50, 6);
  });
});

describe("calendar buckets", () => {
  it("sums same-day points, puts Monday on row 0 and counts green/red", () => {
    const mon = Date.UTC(2026, 8, 28); // a Monday
    const grid = buildCalendar(
      [
        { t_ms: mon + 3_600_000, value: 100 },
        { t_ms: mon + 7_200_000, value: 50 },
        { t_ms: mon + DAY, value: -80 },
      ],
      7,
      mon + 6 * DAY,
    );
    const first = grid.weeks.flat().find((c) => c.t_ms === mon);
    expect(first?.value).toBe(150);
    expect(grid.weeks[grid.weeks.length - 1][0].t_ms).toBe(mon);
    expect(grid.green).toBe(1);
    expect(grid.red).toBe(1);
    expect(grid.total).toBe(70);
    expect(grid.best?.value).toBe(150);
  });
});

describe("hour x weekday heatmap", () => {
  it("cells sum to the trip total and peak where both marginals peak", () => {
    const hours = Array(24).fill(0);
    hours[14] = 6;
    hours[2] = 2;
    const g = hourWeekdayGrid({ hour_hist_utc: hours, weekday_hist: [4, 4, 0, 0, 0, 0, 0] });
    const sum = g.cells.flat().reduce((a, b) => a + b, 0);
    expect(sum).toBeCloseTo(8, 9);
    expect(g.peakHour).toBe(14);
    expect(g.peakWeekday).toBe(0);
    expect(g.cells[0][14]).toBe(g.max);
    expect(heatLevel(g.max, g.max)).toBe(1);
  });

  it("tolerates short, empty or negative histograms", () => {
    const g = hourWeekdayGrid({ hour_hist_utc: [1, -3], weekday_hist: [] });
    expect(g.cells).toHaveLength(7);
    expect(g.cells[0]).toHaveLength(24);
    expect(g.max).toBe(0);
    expect(g.peakWeekday).toBeNull();
    expect(heatLevel(5, 0)).toBe(0);
  });

  it("the demo fingerprint fills a 7x24 grid", () => {
    const g = hourWeekdayGrid(fixtureFingerprint(ADDR, NOW));
    expect(g.total).toBeGreaterThan(0);
    expect(g.max).toBeGreaterThan(0);
  });
});

describe("what-if request", () => {
  it("builds the body for the chosen sizing mode only", () => {
    const d = { ...draftFromOverride(null, 2500), sizing_mode: "fixed_margin" as const, fixed_margin_usd: "50", size_multiplier: "3", leverage_mode: "fixed" as const, leverage: "5" };
    const r = buildWhatIfRequest(d);
    expect(r).toEqual({ ok: true, body: { sim_equity_usd: 2500, override: { sizing_mode: "fixed_margin", fixed_margin_usd: 50, leverage_mode: "fixed", leverage: 5 } } });
  });

  it("returns per-field errors instead of a body", () => {
    const r = buildWhatIfRequest({ ...draftFromOverride(null, 1000), equity: "0", leverage_mode: "fixed", leverage: "2.5" });
    expect(r.ok).toBe(false);
    if (!r.ok) expect(Object.keys(r.errors).sort()).toEqual(["equity", "leverage"]);
  });

  it("saving an empty override clears it", () => {
    expect(overrideSettingsPatch(ADDR.toUpperCase().replace("0X", "0x"), {})).toEqual({ leader_overrides: { [ADDR]: null } });
  });
});
