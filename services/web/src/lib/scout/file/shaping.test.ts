import { describe, expect, it } from "vitest";
import { buildCalendar, rampIndex } from "../calendar";
import { fixtureProfile, fixtureRows } from "../fixtures";
import { linePath, linearScale } from "../spark";
import { chartData } from "../window";
import { buildWhatIfRequest, changedFields, draftFromOverride, draftStale, overrideSettingsPatch } from "../whatIf";
import { demoFileRow, fixtureFingerprint } from "./fixtures";
import { realGrid } from "../../../components/scout/file/StrategyHeatmapGrid";
import { heatLevel, keyNumbers } from "./strategy";

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

describe("strategy fingerprint (demo)", () => {
  it("carries a real 7x24 matrix whose sums are the two histograms", () => {
    const fp = fixtureFingerprint(ADDR, NOW);
    const g = realGrid(fp.entries_by_dow_hour);
    expect(g).not.toBeNull();
    expect(g?.weekdays).toEqual(fp.weekday_hist);
    expect(g?.hours).toEqual(fp.hour_hist_utc);
    expect(g?.total).toBe(fp.trips_analyzed);
  });

  it("heatLevel is 0..1 and 0 on an empty grid", () => {
    expect(heatLevel(5, 10)).toBe(0.5);
    expect(heatLevel(20, 10)).toBe(1);
    expect(heatLevel(5, 0)).toBe(0);
  });

  it("names trade leverage so it can't be confused with account leverage", () => {
    const labels = keyNumbers(fixtureFingerprint(ADDR, NOW)).map((k) => k.label);
    expect(labels).toContain("Avg trade leverage");
    expect(labels).not.toContain("Leverage");
  });
});

describe("demo recent_trips cover the Trade history checklist shapes", () => {
  it("every wallet with enough trips shows a real flip: same coin, opposite sides, touching instant", () => {
    const rows = fixtureRows(NOW);
    const row = rows.find((r) => r.trades_30d.trips >= 7 && !r.flags.includes("too_few_trades"));
    expect(row).toBeTruthy();
    const profile = fixtureProfile(row!, NOW);
    const trips = profile.recent_trips;
    const flipIdx = trips.findIndex((t, i) => i > 0 && t.coin === trips[i - 1].coin && t.side !== trips[i - 1].side && t.closed_ms === trips[i - 1].opened_ms);
    expect(flipIdx).toBeGreaterThan(-1);
  });

  it("the wallet_liquidated board row carries that liquidation onto a real round trip, not just the score", () => {
    const rows = fixtureRows(NOW);
    const row = rows.find((r) => r.flags.includes("wallet_liquidated"));
    expect(row).toBeTruthy();
    const profile = fixtureProfile(row!, NOW);
    expect(profile.recent_trips.some((t) => t.liquidation)).toBe(true);
  });

  it("fixtureProfile is deterministic: same row and clock, byte-identical recent_trips", () => {
    const row = fixtureRows(NOW)[0];
    const a = fixtureProfile(row, NOW).recent_trips;
    const b = fixtureProfile(row, NOW).recent_trips;
    expect(a).toEqual(b);
  });
});

describe("calendar ramp", () => {
  it("maps -4..4 onto the 5-step diverging ramp with flat in the middle", () => {
    expect([-4, -3, -2, -1, 0, 1, 2, 3, 4].map(rampIndex)).toEqual([0, 0, 1, 1, 2, 3, 3, 4, 4]);
    expect(rampIndex(Number.NaN)).toBe(2);
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

describe("what-if changed fields", () => {
  const saved = draftFromOverride({ leverage_mode: "fixed", leverage: 10 }, 1000);

  it("nothing changed right after seeding", () => {
    expect(changedFields(saved, saved)).toEqual([]);
  });

  it("lists changed inputs in form order and treats 10 and 10.0 as equal", () => {
    const d = { ...saved, leverage: "10.0", equity: "5000", margin_mode: "isolated" as const };
    expect(changedFields(d, saved)).toEqual(["equity", "margin_mode"]);
  });

  it("clearing a saved value back to inherit counts as a change", () => {
    expect(changedFields({ ...saved, leverage: "" }, saved)).toEqual(["leverage"]);
  });

  it("a result goes stale once the form moves away from what ran", () => {
    expect(draftStale(saved, null)).toBe(false);
    expect(draftStale(saved, saved)).toBe(false);
    expect(draftStale({ ...saved, equity: "2000" }, saved)).toBe(true);
  });
});
