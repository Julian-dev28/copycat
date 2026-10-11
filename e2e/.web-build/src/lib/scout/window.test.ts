import { describe, expect, it } from "vitest";
import { fixtureProfile, fixtureRows } from "./fixtures";
import { applyBoardQuery, DEFAULT_BOARD } from "./query";
import type { PnlWindow, TraderRow, WindowPerf } from "./types";
import { chartData, clipFrom, formatSignedUsdCompact, nearestIndex, pnlFigure, riskFor, toneOf, valueAt, windowPerf } from "./window";

const NOW = Date.UTC(2026, 9, 4, 12);

function perfRow(perf: Partial<Record<PnlWindow, [number, number]>>): Pick<TraderRow, "perf"> {
  return {
    perf: Object.entries(perf).map(([window, [pnl_usd, roi_pct]]) => ({ window, pnl_usd, roi_pct, volume_usd: 0 }) as unknown as WindowPerf),
  };
}

describe("window switching on the board", () => {
  const row = perfRow({ "1d": [-1200, -0.8], "30d": [2_500_000, 41.2], all: [0, 0] });

  it("each window picks its own PnL and ROI", () => {
    expect(pnlFigure(row, "1d", "usd")).toEqual({ text: "-$1,200", tone: "down" });
    expect(pnlFigure(row, "30d", "pct").tone).toBe("up");
    expect(pnlFigure(row, "30d", "pct").text).toContain("41.2");
    expect(pnlFigure(row, "30d", "usd").text).toBe("+$2.5M");
    expect(pnlFigure(row, "all", "usd").tone).toBe("flat");
  });

  it("a window the api did not send shows a dash, not zero", () => {
    expect(windowPerf(row, "7d")).toBeNull();
    expect(pnlFigure(row, "7d", "usd")).toEqual({ text: "—", tone: "flat" });
  });

  it("sorting by PnL follows the selected window", () => {
    const rows = fixtureRows(NOW);
    for (const w of ["1d", "7d", "30d", "all"] as PnlWindow[]) {
      const out = applyBoardQuery(rows, { ...DEFAULT_BOARD, window: w, sort: "pnl" }, NOW).rows;
      const vals = out.map((r) => windowPerf(r, w)?.pnl_usd ?? -Infinity);
      expect(vals).toEqual([...vals].sort((a, b) => b - a));
    }
  });

  it("the PnL filter applies to the selected window", () => {
    const rows = fixtureRows(NOW);
    const out = applyBoardQuery(rows, { ...DEFAULT_BOARD, window: "7d", minPnl: 0 }, NOW).rows;
    for (const r of out) expect(windowPerf(r, "7d")!.pnl_usd).toBeGreaterThanOrEqual(0);
  });
});

describe("number helpers", () => {
  it("toneOf", () => {
    expect([toneOf(1), toneOf(-1), toneOf(0), toneOf(null), toneOf(Number.NaN)]).toEqual(["up", "down", "flat", "flat", "flat"]);
  });
  it("compact signed USD", () => {
    expect(formatSignedUsdCompact(9_999.6)).toBe("+$10,000");
    expect(formatSignedUsdCompact(-3_400_000)).toBe("-$3.4M");
    expect(formatSignedUsdCompact(undefined)).toBe("—");
  });
});

describe("curve helpers", () => {
  const pts = [30, 10, 20].map((t) => ({ t_ms: t, value: t * 2 }));
  it("clipFrom sorts and clips", () => {
    expect(clipFrom(pts, 15).map((p) => p.t_ms)).toEqual([20, 30]);
    expect(clipFrom(pts, null).map((p) => p.t_ms)).toEqual([10, 20, 30]);
  });
  it("valueAt is a step lookup", () => {
    const s = clipFrom(pts, null);
    expect(valueAt(s, 25)).toBe(40);
    expect(valueAt(s, 5)).toBe(20);
    expect(valueAt([], 5)).toBeNull();
  });
  it("nearestIndex", () => {
    const s = clipFrom(pts, null);
    expect(nearestIndex(s, 26)).toBe(2);
    expect(nearestIndex(s, 14)).toBe(0);
    expect(nearestIndex([], 1)).toBe(-1);
  });
});

describe("trader file window fallbacks", () => {
  const profile = fixtureProfile(fixtureRows(NOW)[0], NOW);
  it("riskFor falls back to the nearest computed window", () => {
    const r = riskFor({ risk: profile.risk.filter((x) => x.window !== "1d") }, "1d");
    expect(r.exact).toBe(false);
  });
  it("chartData without overlay is USD rebased to 0; with overlay both lines are %", () => {
    const plain = chartData(profile, "pnl", "30d", false);
    expect(plain.unit).toBe("usd");
    expect(plain.series[0].points[0]?.value ?? 0).toBe(0);
    const over = chartData(profile, "pnl", "30d", true);
    expect(over.unit).toBe("pct");
    expect(over.series.map((s) => s.key)).toEqual(["his", "sim"]);
  });
});
