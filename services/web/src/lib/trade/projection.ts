/**
 * "$1,000 copied over the last 30 days": a BACKTEST of his last 30 days
 * replayed onto an allocation, inverted for counter. The api computes it
 * (GET /api/wallets/{a}/projection, 202 while it builds); this file
 * normalizes that answer and holds the local estimate used by the demo and
 * by apis without the route. Pure, unit-tested.
 *
 * Local estimate, from his 30d equity index (deposits removed):
 *   r_t       = index_t / index_{t-1} - 1           his step return
 *   f         = 1 (follow his leverage) | L / his account leverage (set L)
 *   s         = +1 copy | -1 counter
 *   equity_t  = equity_{t-1} x (1 + s x f x r_t)    starting at the allocation
 * Equity at or under zero is a liquidation: the copy is wiped and stays flat.
 */
import type { CurvePoint } from "@/lib/scout/types";
import type { ExposureMode, ProjectionQuery, TradeDirection, WalletProjection } from "./types";

export const DEFAULT_PROJECTION_USD = 1_000;

export type ProjectionResult = { kind: "ready"; projection: WalletProjection } | { kind: "building"; note: string | null };

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** 200 with a WalletProjection -> ready; a 202 body (or anything without a curve) -> building. */
export function normalizeProjection(raw: unknown, q: ProjectionQuery, address: string): ProjectionResult {
  const o = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>;
  if (!Array.isArray(o.curve)) {
    const note = typeof o.note === "string" ? o.note : typeof o.detail === "string" ? o.detail : null;
    return { kind: "building", note };
  }
  const curve = (o.curve as unknown[])
    .map((p) => (p && typeof p === "object" ? { t_ms: num((p as CurvePoint).t_ms), value: num((p as CurvePoint).value) } : null))
    .filter((p): p is CurvePoint => p !== null && p.t_ms !== null && p.value !== null)
    .sort((a, b) => a.t_ms - b.t_ms);
  const stats = curveStats(curve, num(o.allocation_usd) ?? q.allocation_usd);
  return {
    kind: "ready",
    projection: {
      address: typeof o.address === "string" ? o.address : address,
      allocation_usd: num(o.allocation_usd) ?? q.allocation_usd,
      trade_direction: o.trade_direction === "counter" ? "counter" : o.trade_direction === "copy" ? "copy" : q.trade_direction,
      curve,
      return_pct: num(o.return_pct) ?? stats.returnPct,
      max_drawdown_pct: num(o.max_drawdown_pct) ?? stats.maxDrawdownPct,
      liquidations: num(o.liquidations) ?? 0,
      copies: num(o.copies) ?? 0,
      skipped: num(o.skipped) ?? 0,
      note: typeof o.note === "string" ? o.note : null,
    },
  };
}

/** Return vs the start and the worst peak-to-trough drop, both in % (drawdown as a positive number). */
export function curveStats(curve: CurvePoint[], start: number): { returnPct: number; maxDrawdownPct: number } {
  if (!curve.length || start <= 0) return { returnPct: 0, maxDrawdownPct: 0 };
  let peak = start;
  let dd = 0;
  for (const p of curve) {
    peak = Math.max(peak, p.value);
    if (peak > 0) dd = Math.max(dd, (peak - p.value) / peak);
  }
  return { returnPct: (curve[curve.length - 1].value / start - 1) * 100, maxDrawdownPct: dd * 100 };
}

export interface LocalProjectionInput {
  address: string;
  /** His equity index over the last 30 days (lib/trade/equityIndex profileIndex(...).points). */
  index: CurvePoint[];
  allocationUsd: number;
  direction: TradeDirection;
  mode: ExposureMode;
  targetLeverage?: number;
  /** His gross notional / equity now (Set leverage scales by L over this). */
  hisLeverage: number | null;
}

export function localProjection(inp: LocalProjectionInput): WalletProjection {
  const A = Math.max(0, inp.allocationUsd);
  const pts = [...inp.index].sort((a, b) => a.t_ms - b.t_ms);
  const f = inp.mode === "target" && inp.hisLeverage && inp.hisLeverage > 0 ? Math.max(1, inp.targetLeverage ?? 1) / inp.hisLeverage : 1;
  const s = inp.direction === "counter" ? -1 : 1;
  const curve: CurvePoint[] = [];
  let eq = A;
  let liquidations = 0;
  pts.forEach((p, i) => {
    if (i > 0 && eq > 0) {
      const prev = pts[i - 1].value;
      const r = prev > 0 ? p.value / prev - 1 : 0;
      eq = eq * (1 + s * f * r);
      if (eq <= 0) {
        eq = 0;
        liquidations += 1;
      }
    }
    curve.push({ t_ms: p.t_ms, value: eq });
  });
  const st = curveStats(curve, A);
  return {
    address: inp.address,
    allocation_usd: A,
    trade_direction: inp.direction,
    curve,
    return_pct: st.returnPct,
    max_drawdown_pct: st.maxDrawdownPct,
    liquidations,
    copies: 0,
    skipped: 0,
    note: "Estimate from their equity index: no fills, fees or slippage.",
  };
}

/** The query string for the route. Leverage only for Set leverage. */
export function projectionQueryString(q: ProjectionQuery): string {
  const p = new URLSearchParams({
    allocation_usd: String(Math.round(q.allocation_usd * 100) / 100),
    trade_direction: q.trade_direction,
    exposure_mode: q.exposure_mode,
  });
  if (q.exposure_mode === "target" && q.target_leverage) p.set("target_leverage", String(q.target_leverage));
  return p.toString();
}
