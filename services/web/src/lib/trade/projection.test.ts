import { describe, expect, it } from "vitest";
import { curveStats, localProjection, normalizeProjection, projectionQueryString } from "./projection";

const idx = [100, 110, 99, 120].map((value, i) => ({ t_ms: i * 86_400_000, value }));
const base = { address: "0xa", index: idx, allocationUsd: 1_000, mode: "match" as const, hisLeverage: 2 };

describe("projection", () => {
  it("copy follows their returns on the allocation", () => {
    const p = localProjection({ ...base, direction: "copy" });
    expect(p.curve.map((c) => Math.round(c.value))).toEqual([1000, 1100, 990, 1200]);
    expect(p.return_pct).toBeCloseTo(20);
    expect(p.max_drawdown_pct).toBeCloseTo(10);
    expect(p.liquidations).toBe(0);
  });
  it("counter inverts every step (not a mirror of the total)", () => {
    const p = localProjection({ ...base, direction: "counter" });
    expect(p.curve[1].value).toBeCloseTo(900);
    expect(p.curve[2].value).toBeCloseTo(990);
    expect(p.curve[3].value).toBeCloseTo(990 * (1 - (120 / 99 - 1)));
    expect(p.trade_direction).toBe("counter");
    expect(p.return_pct).toBeLessThan(0);
  });
  it("set leverage scales their returns by L / their leverage; a wipe-out counts as a liquidation", () => {
    const p = localProjection({ ...base, direction: "counter", mode: "target", targetLeverage: 40, hisLeverage: 2 });
    expect(p.liquidations).toBe(1);
    expect(p.curve.at(-1)!.value).toBe(0);
  });
  it("202 / no curve -> building; 200 -> ready with stats filled when missing", () => {
    const q = { allocation_usd: 1_000, trade_direction: "copy" as const, exposure_mode: "match" as const };
    expect(normalizeProjection({ state: "queued" }, q, "0xa").kind).toBe("building");
    const r = normalizeProjection({ curve: [{ t_ms: 2, value: 1100 }, { t_ms: 1, value: 1000 }], allocation_usd: 1_000 }, q, "0xa");
    expect(r.kind).toBe("ready");
    if (r.kind === "ready") {
      expect(r.projection.curve[0].t_ms).toBe(1);
      expect(r.projection.return_pct).toBeCloseTo(10);
      expect(r.projection.trade_direction).toBe("copy");
    }
  });
  it("query string: leverage only for Set leverage", () => {
    expect(projectionQueryString({ allocation_usd: 1000, trade_direction: "counter", exposure_mode: "match", target_leverage: 5 })).toBe(
      "allocation_usd=1000&trade_direction=counter&exposure_mode=match",
    );
    expect(projectionQueryString({ allocation_usd: 50.555, trade_direction: "copy", exposure_mode: "target", target_leverage: 5 })).toContain("target_leverage=5");
  });
  it("curveStats handles empty", () => {
    expect(curveStats([], 1000)).toEqual({ returnPct: 0, maxDrawdownPct: 0 });
  });
});
