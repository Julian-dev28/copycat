"use client";

import { Loader2 } from "lucide-react";
import { formatUsd } from "@/lib/format";
import { linePath, linearScale, timeExtent, valueExtent } from "@/lib/scout/spark";
import type { TraderProfile } from "@/lib/scout/types";
import { apiProblem, problemText } from "@/lib/trade/apiState";
import { profileIndex } from "@/lib/trade/equityIndex";
import { DEFAULT_PROJECTION_USD, localProjection } from "@/lib/trade/projection";
import type { ExposureMode, ProjectionQuery, TradeDirection, WalletProjection } from "@/lib/trade/types";
import { ChangeText } from "./bits";
import { useWalletProjection } from "./hooks";

const W = 300;
const H = 90;

/** "$1,000 copied over the last 30 days": a backtest, labelled as one. Amount follows the ticket. */
export function ProjectionPanel({
  address,
  amount,
  direction,
  mode,
  leverage,
  profile,
}: {
  address: string;
  amount: number | null;
  direction: TradeDirection;
  mode: ExposureMode;
  leverage: number;
  profile: TraderProfile | undefined;
}) {
  const allocation = amount && amount > 0 ? amount : DEFAULT_PROJECTION_USD;
  const q: ProjectionQuery = { allocation_usd: allocation, trade_direction: direction, exposure_mode: mode, ...(mode === "target" ? { target_leverage: leverage } : {}) };
  const res = useWalletProjection(address, q);
  const tooOld = apiProblem(res.error) === "too_old";
  let proj: WalletProjection | null = res.data?.kind === "ready" ? res.data.projection : null;
  let estimate = false;
  if (!proj && tooOld && profile) {
    // Pre-v8 api: the same replay from his equity index, in the browser.
    const gross = profile.positions.reduce((a, p) => a + Math.abs(p.notional_usd), 0);
    const av = profile.row.account_value_usd;
    proj = localProjection({
      address, index: profileIndex(profile, "30d").points, allocationUsd: allocation, direction, mode, targetLeverage: leverage,
      hisLeverage: av > 0 ? gross / av : null,
    });
    estimate = true;
  }
  const building = res.data?.kind === "building";

  return (
    <section aria-label="30-day backtest" className="flex flex-col gap-2 rounded-lg border border-border p-3 text-xs">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-medium text-foreground">
          {formatUsd(allocation)} {direction === "counter" ? "countered" : "copied"} over the last 30 days
        </span>
        {res.isFetching ? <Loader2 size={11} className="animate-spin text-muted" aria-hidden="true" /> : null}
      </div>
      {proj && proj.curve.length >= 2 ? (
        <>
          <Spark curve={proj.curve} start={proj.allocation_usd} />
          <div className="font-num grid grid-cols-3 gap-2">
            <Stat label="Return"><ChangeText pct={proj.return_pct} digits={1} /></Stat>
            <Stat label="Max DD"><span className="text-danger">-{proj.max_drawdown_pct.toFixed(1)}%</span></Stat>
            <Stat label="Liquidations"><span className={proj.liquidations ? "text-danger" : "text-foreground"}>{proj.liquidations}</span></Stat>
          </div>
        </>
      ) : building ? (
        <p className="flex items-center gap-1.5 py-4 text-muted">
          <Loader2 size={12} className="animate-spin" aria-hidden="true" /> Building: reading his last 30 days{res.data?.kind === "building" && res.data.note ? ` (${res.data.note})` : ""}.
        </p>
      ) : res.error && !tooOld ? (
        <p className="text-muted">{problemText(res.error, "projection")}</p>
      ) : proj ? (
        <p className="text-muted">Not enough history for a 30-day replay.</p>
      ) : (
        <div className="h-[90px] animate-pulse rounded bg-surface-2" />
      )}
      <p className="text-[11px] text-muted">
        Backtest of his past trades{direction === "counter" ? ", inverted" : ""}, not a promise. Real copies enter later and pay fees, slippage and funding over the time a position stays open.
        {estimate ? " Estimate from his equity index: your api has no projection route yet." : proj?.note ? ` ${proj.note}` : ""}
      </p>
    </section>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wide text-muted">{label}</span>
      <span>{children}</span>
    </div>
  );
}

function Spark({ curve, start }: { curve: { t_ms: number; value: number }[]; start: number }) {
  const [t0, t1] = timeExtent([curve]);
  const [lo, hi] = valueExtent([curve], false);
  const yLo = Math.min(lo, start);
  const yHi = Math.max(hi, start);
  const pad = (yHi - yLo || 1) * 0.08;
  const x = linearScale([t0, t1], [0, W]);
  const y = linearScale([yLo - pad, yHi + pad], [H - 2, 2]);
  const up = curve[curve.length - 1].value >= start;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" role="img" aria-label={`Backtest equity from ${formatUsd(start)} to ${formatUsd(curve[curve.length - 1].value)}`}>
      <line x1={0} x2={W} y1={y(start)} y2={y(start)} stroke="var(--border)" strokeDasharray="3 3" />
      <path d={linePath(curve, x, y)} fill="none" stroke={up ? "var(--success)" : "var(--danger)"} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
