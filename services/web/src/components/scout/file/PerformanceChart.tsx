"use client";

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { clsx } from "clsx";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Switch } from "@/components/ui/Switch";
import { formatSignedPct, formatUsd } from "@/lib/format";
import { linePath, linearScale, niceTicks, timeExtent, valueExtent } from "@/lib/scout/spark";
import { PNL_WINDOWS, type PnlWindow, type TraderProfile } from "@/lib/scout/types";
import { chartData, nearestIndex, WINDOW_LABEL, type ChartMetric } from "@/lib/scout/window";
import { formatSignedUsdCompact } from "@/lib/scout/window";

const H = 260;
const PAD = { top: 12, right: 12, bottom: 26, left: 56 };
const SERIES_COLOR = { his: "var(--muted)", sim: "var(--accent)" } as const;

function fmtValue(v: number, unit: "usd" | "pct", signed: boolean): string {
  if (unit === "pct") return formatSignedPct(v, Math.abs(v) < 10 ? 1 : 0);
  return signed ? formatSignedUsdCompact(v) : formatUsd(v, true);
}

function fmtTime(t: number, w: PnlWindow, long = false): string {
  const d = new Date(t);
  if (w === "1d") return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
  if (w === "all" && !long) return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", ...(long ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}) });
}

/** Width of the plot's container, tracked with a ResizeObserver (state is set in the observer callback, not the effect body). */
function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(640);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const next = Math.round(entries[0].contentRect.width);
      if (next > 0) setW(next);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

export function PerformanceChart({
  profile,
  simLabel,
}: {
  profile: TraderProfile;
  /** Set when a what-if result replaced the saved-settings sim curve. */
  simLabel?: string;
}) {
  const [metric, setMetric] = useState<ChartMetric>("pnl");
  const [win, setWin] = useState<PnlWindow>("30d");
  const [overlay, setOverlay] = useState(true);
  const [hoverT, setHoverT] = useState<number | null>(null);
  const [ref, width] = useWidth<HTMLDivElement>();

  const data = chartData(profile, metric, win, overlay);
  const series = data.series
    .filter((s) => s.points.length >= 2)
    .map((s) => (s.key === "sim" && simLabel ? { ...s, label: simLabel } : s));
  const all = series.map((s) => s.points);
  const [t0, t1] = timeExtent(all);
  const [lo, hi] = valueExtent(all, metric === "pnl" || overlay);
  const padV = (hi - lo || Math.abs(hi) || 1) * 0.08;
  const ticks = niceTicks(lo - padV, hi + padV, 4);
  const yDomain: [number, number] = [Math.min(lo - padV, ticks[0] ?? lo), Math.max(hi + padV, ticks[ticks.length - 1] ?? hi)];
  const x = linearScale([t0, t1], [PAD.left, width - PAD.right]);
  const y = linearScale(yDomain, [H - PAD.bottom, PAD.top]);
  const xTicks = t1 > t0 ? [0, 0.25, 0.5, 0.75, 1].map((f) => t0 + (t1 - t0) * f) : [];
  const signed = metric === "pnl" || data.unit === "pct";

  const hover =
    hoverT === null
      ? null
      : series.map((s) => {
          const i = nearestIndex(s.points, hoverT);
          return { ...s, point: s.points[i] };
        });
  const hoverX = hover && hover[0]?.point ? x(hover[0].point.t_ms) : null;

  function onMove(e: PointerEvent<SVGRectElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const px = PAD.left + ((e.clientX - box.left) / box.width) * (width - PAD.left - PAD.right);
    const f = (px - PAD.left) / Math.max(1, width - PAD.left - PAD.right);
    setHoverT(t0 + (t1 - t0) * Math.min(1, Math.max(0, f)));
  }

  function onKey(e: KeyboardEvent<SVGSVGElement>) {
    const base = series[0]?.points;
    if (!base?.length) return;
    const cur = hoverT === null ? base.length - 1 : nearestIndex(base, hoverT);
    const step = e.shiftKey ? 10 : 1;
    if (e.key === "ArrowLeft") setHoverT(base[Math.max(0, cur - step)].t_ms);
    else if (e.key === "ArrowRight") setHoverT(base[Math.min(base.length - 1, cur + step)].t_ms);
    else if (e.key === "Escape") setHoverT(null);
    else return;
    e.preventDefault();
  }

  const lastSim = series.find((s) => s.key === "sim")?.points.at(-1);
  const lastHis = series.find((s) => s.key === "his")?.points.at(-1);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="w-full sm:w-56">
          <SegmentedControl
            aria-label="Chart metric"
            options={[
              { value: "pnl", label: "PnL" },
              { value: "value", label: "Account value" },
            ]}
            value={metric}
            onChange={setMetric}
          />
        </div>
        <div className="w-full sm:w-64">
          <SegmentedControl
            aria-label="Chart window"
            options={PNL_WINDOWS.map((w) => ({ value: w, label: WINDOW_LABEL[w] }))}
            value={win}
            onChange={setWin}
          />
        </div>
        <label htmlFor="chart-overlay" className="flex items-center gap-2 text-xs text-muted sm:ml-auto">
          <Switch id="chart-overlay" checked={overlay} onChange={setOverlay} label="Overlay your copy" />
          Overlay your copy (as % return)
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs" aria-label="Legend">
        {series.map((s) => (
          <span key={s.key} className="inline-flex items-center gap-1.5 text-muted">
            <svg width="16" height="6" aria-hidden="true">
              <line x1="0" x2="16" y1="3" y2="3" stroke={SERIES_COLOR[s.key]} strokeWidth="2" strokeLinecap="round" strokeDasharray={s.key === "his" ? undefined : undefined} />
            </svg>
            <span className="text-foreground">{s.label}</span>
            <span className="font-num">
              {s.key === "his" && lastHis ? fmtValue(lastHis.value, data.unit, signed) : null}
              {s.key === "sim" && lastSim ? fmtValue(lastSim.value, data.unit, signed) : null}
            </span>
          </span>
        ))}
      </div>

      <div ref={ref} className="relative w-full">
        {series.length === 0 ? (
          <div className="flex h-[260px] items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted">
            No {metric === "pnl" ? "PnL" : "account value"} history for this window.
          </div>
        ) : (
          <svg
            width={width}
            height={H}
            role="img"
            tabIndex={0}
            onKeyDown={onKey}
            onBlur={() => setHoverT(null)}
            aria-label={`${series.map((s) => `${s.label} ${s.points.length ? fmtValue(s.points[s.points.length - 1].value, data.unit, signed) : ""}`).join(", ")} over ${WINDOW_LABEL[win]}. Arrow keys read values.`}
            className="block select-none rounded-lg focus-visible:outline-2"
          >
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeWidth={t === 0 ? 1.25 : 1} strokeDasharray={t === 0 ? undefined : "2 4"} />
                <text x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="font-num" fontSize="10" fill="var(--muted)">
                  {fmtValue(t, data.unit, signed)}
                </text>
              </g>
            ))}
            {xTicks.map((t, i) => (
              <text
                key={t}
                x={x(t)}
                y={H - 8}
                textAnchor={i === 0 ? "start" : i === xTicks.length - 1 ? "end" : "middle"}
                fontSize="10"
                fill="var(--muted)"
                className={clsx(i % 2 === 1 && width < 480 && "hidden")}
              >
                {fmtTime(t, win)}
              </text>
            ))}
            {series.map((s) => (
              <path
                key={s.key}
                d={linePath(s.points, x, y)}
                fill="none"
                stroke={SERIES_COLOR[s.key]}
                strokeWidth={s.key === "sim" ? 2 : 1.75}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}
            {hoverX !== null && hover ? (
              <g pointerEvents="none">
                <line x1={hoverX} x2={hoverX} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--foreground)" strokeOpacity="0.35" strokeWidth="1" />
                {hover.map((h) =>
                  h.point ? (
                    <circle key={h.key} cx={x(h.point.t_ms)} cy={y(h.point.value)} r="4" fill={SERIES_COLOR[h.key]} stroke="var(--surface)" strokeWidth="2" />
                  ) : null,
                )}
              </g>
            ) : null}
            <rect
              x={PAD.left}
              y={PAD.top}
              width={Math.max(0, width - PAD.left - PAD.right)}
              height={H - PAD.top - PAD.bottom}
              fill="transparent"
              onPointerMove={onMove}
              onPointerDown={onMove}
              onPointerLeave={() => setHoverT(null)}
            />
          </svg>
        )}
        {hover && hoverX !== null && hover[0]?.point ? (
          <div
            className="pointer-events-none absolute top-2 z-10 min-w-40 rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-lg"
            style={hoverX > width / 2 ? { right: width - hoverX + 12 } : { left: hoverX + 12 }}
            role="status"
          >
            <div className="mb-1 text-muted">{fmtTime(hover[0].point.t_ms, win, true)}</div>
            {hover.map((h) =>
              h.point ? (
                <div key={h.key} className="flex items-center justify-between gap-3">
                  <span className="inline-flex items-center gap-1.5 text-muted">
                    <span className="inline-block h-0.5 w-3 rounded" style={{ background: SERIES_COLOR[h.key] }} />
                    {h.label}
                  </span>
                  <span className="font-num font-semibold text-foreground">{fmtValue(h.point.value, data.unit, signed)}</span>
                </div>
              ) : null,
            )}
          </div>
        ) : null}
      </div>
      {data.notes.length ? (
        <ul className="flex flex-col gap-0.5 text-[11px] text-muted">
          {data.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
