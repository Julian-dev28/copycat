"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { clsx } from "clsx";
import { PnlCalendar } from "@/components/scout/file/PnlCalendar";
import { Panel } from "@/components/ui/Panel";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { formatUsd } from "@/lib/format";
import { accountSeries, type AccountMetric } from "@/lib/account/summary";
import type { AccountSummary } from "@/lib/account/types";
import { linePath, linearScale, niceTicks, timeExtent, valueExtent } from "@/lib/scout/spark";
import { PNL_WINDOWS, type PnlWindow } from "@/lib/scout/types";
import { formatSignedUsdCompact, nearestIndex, WINDOW_LABEL } from "@/lib/scout/window";

const H = 240;
const PAD = { top: 12, right: 12, bottom: 24, left: 56 };
type View = AccountMetric | "calendar";

function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(0); // 0 until measured: a guessed width would overflow phones for a frame
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((e) => {
      const next = Math.round(e[0].contentRect.width);
      if (next > 0) setW(next);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

const fmtT = (t: number, w: PnlWindow) =>
  new Date(t).toLocaleString("en-US", w === "1d" ? { hour: "2-digit", minute: "2-digit", hour12: false } : { month: "short", day: "numeric", ...(w === "all" ? { year: "2-digit" } : {}) });

export function AccountChart({ summary }: { summary: AccountSummary }) {
  const [view, setView] = useState<View>("pnl");
  const [win, setWin] = useState<PnlWindow>("30d");
  const [hover, setHover] = useState<number | null>(null);
  const [ref, width] = useWidth();
  const metric: AccountMetric = view === "value" ? "value" : "pnl";
  const { points, change } = accountSeries(summary, metric, win);
  const signed = metric === "pnl";
  const fmt = (v: number) => (signed ? formatSignedUsdCompact(v) : formatUsd(v, true));

  const [t0, t1] = timeExtent([points]);
  const [lo, hi] = valueExtent([points], signed);
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.08;
  const ticks = niceTicks(lo - pad, hi + pad, 4);
  const x = linearScale([t0, t1], [PAD.left, width - PAD.right]);
  const y = linearScale([Math.min(lo - pad, ticks[0] ?? lo), Math.max(hi + pad, ticks.at(-1) ?? hi)], [H - PAD.bottom, PAD.top]);
  const up = (change ?? 0) >= 0;
  const stroke = signed ? (up ? "var(--success)" : "var(--danger)") : "var(--accent)";
  const hp = hover === null ? null : points[hover];

  function onMove(e: PointerEvent<SVGRectElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
    setHover(nearestIndex(points, t0 + (t1 - t0) * f));
  }

  return (
    <Panel className="flex flex-col gap-3 p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-full sm:w-72">
          <SegmentedControl aria-label="Chart" value={view} onChange={setView} options={[{ value: "pnl", label: "PnL" }, { value: "value", label: "Value" }, { value: "calendar", label: "Calendar" }]} />
        </div>
        {view === "calendar" ? null : (
          <div className="w-full sm:ml-auto sm:w-64">
            <SegmentedControl aria-label="Window" value={win} onChange={setWin} options={PNL_WINDOWS.map((w) => ({ value: w, label: WINDOW_LABEL[w] }))} />
          </div>
        )}
      </div>
      {view === "calendar" ? (
        <PnlCalendar daily={summary.daily_pnl} />
      ) : (
        <>
          <p className="text-xs text-muted" aria-live="polite">
            {hp ? new Date(hp.t_ms).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }) : `${metric === "pnl" ? "PnL" : "Value change"} over ${WINDOW_LABEL[win]}`}{" "}
            <span className={clsx("font-num text-base font-semibold", signed ? ((hp?.value ?? change ?? 0) >= 0 ? "text-success" : "text-danger") : "text-foreground")}>
              {hp ? fmt(hp.value) : change === null ? "—" : signed ? fmt(change) : formatSignedUsdCompact(change)}
            </span>
          </p>
          <div ref={ref} className="w-full">
            {width === 0 ? <div className="h-[240px]" /> : points.length < 2 ? (
              <div className="flex h-[240px] items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted">No history for this window yet.</div>
            ) : (
              <svg width={width} height={H} role="img" aria-label={`${metric === "pnl" ? "PnL" : "Account value"} over ${WINDOW_LABEL[win]}`} className="block select-none">
                {ticks.map((t) => (
                  <g key={t}>
                    <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeDasharray={t === 0 ? undefined : "2 4"} />
                    <text x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end" fontSize="10" fill="var(--muted)" className="font-num">{fmt(t)}</text>
                  </g>
                ))}
                {[0, 0.5, 1].map((f, i) => (
                  <text key={f} x={x(t0 + (t1 - t0) * f)} y={H - 6} fontSize="10" fill="var(--muted)" textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}>{fmtT(t0 + (t1 - t0) * f, win)}</text>
                ))}
                <path d={linePath(points, x, y)} fill="none" stroke={stroke} strokeWidth="2" strokeLinejoin="round" />
                {hp ? (
                  <g pointerEvents="none">
                    <line x1={x(hp.t_ms)} x2={x(hp.t_ms)} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--foreground)" strokeOpacity="0.3" />
                    <circle cx={x(hp.t_ms)} cy={y(hp.value)} r="4" fill={stroke} stroke="var(--surface)" strokeWidth="2" />
                  </g>
                ) : null}
                <rect x={PAD.left} y={PAD.top} width={Math.max(0, width - PAD.left - PAD.right)} height={H - PAD.top - PAD.bottom} fill="transparent" onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} />
              </svg>
            )}
          </div>
          {metric === "value" ? <p className="text-[11px] text-muted">Value includes deposits and withdrawals, so transfers show as steps.</p> : null}
        </>
      )}
    </Panel>
  );
}
