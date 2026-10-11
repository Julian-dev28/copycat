"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { linePath, linearScale, niceTicks, timeExtent, valueExtent } from "@/lib/scout/spark";
import { PNL_WINDOWS, type PnlWindow, type TraderProfile } from "@/lib/scout/types";
import { nearestIndex, WINDOW_LABEL } from "@/lib/scout/window";
import { invertSeries } from "@/lib/trade/direction";
import { formatIndex, profileIndex } from "@/lib/trade/equityIndex";
import type { TradeDirection } from "@/lib/trade/types";
import { ChangeText } from "./bits";

const H = 240;
const PAD = { top: 12, right: 52, bottom: 24, left: 8 };

function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(560);
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

function fmtTime(t: number, w: PnlWindow, long = false): string {
  const d = new Date(t);
  if (w === "1d") return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
  if (w === "all" && !long) return d.toLocaleDateString("en-US", { month: "short", year: "2-digit" });
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", ...(long ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}) });
}

export function IndexChart({ profile, direction = "copy" }: { profile: TraderProfile; direction?: TradeDirection }) {
  const [win, setWin] = useState<PnlWindow>("30d");
  const [hoverI, setHoverI] = useState<number | null>(null);
  const [ref, width] = useWidth();
  const gid = useId().replace(/:/g, "");
  const data = profileIndex(profile, win);
  const pts = data.points;
  const up = (data.changePct ?? 0) >= 0;
  const color = up ? "var(--success)" : "var(--danger)";

  const [t0, t1] = timeExtent([pts]);
  // Counter: overlay what trading against him did over the same window (his index, inverted).
  const counter = direction === "counter" ? invertSeries(pts) : [];
  const [lo, hi] = valueExtent(counter.length ? [pts, counter] : [pts], false);
  const padV = (hi - lo || hi || 1) * 0.08;
  const ticks = niceTicks(lo - padV, hi + padV, 4);
  const yDom: [number, number] = [Math.min(lo - padV, ticks[0] ?? lo), Math.max(hi + padV, ticks.at(-1) ?? hi)];
  const x = linearScale([t0, t1], [PAD.left, width - PAD.right]);
  const y = linearScale(yDom, [H - PAD.bottom, PAD.top]);
  const path = linePath(pts, x, y);
  const area = pts.length ? `${path} L${x(t1)} ${H - PAD.bottom} L${x(t0)} ${H - PAD.bottom} Z` : "";
  const hover = hoverI !== null ? pts[hoverI] : null;
  const shown = hover ?? pts.at(-1) ?? null;
  const fromStart = shown && pts.length ? (shown.value / pts[0].value - 1) * 100 : null;

  function onMove(e: PointerEvent<SVGRectElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width));
    setHoverI(nearestIndex(pts, t0 + (t1 - t0) * f));
  }
  function onKey(e: KeyboardEvent<SVGSVGElement>) {
    if (!pts.length) return;
    const cur = hoverI ?? pts.length - 1;
    const step = e.shiftKey ? 10 : 1;
    if (e.key === "ArrowLeft") setHoverI(Math.max(0, cur - step));
    else if (e.key === "ArrowRight") setHoverI(Math.min(pts.length - 1, cur + step));
    else if (e.key === "Escape") setHoverI(null);
    else return;
    e.preventDefault();
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-baseline gap-2 text-sm" aria-live="polite">
          <span className="font-num text-lg font-semibold">{formatIndex(shown?.value)}</span>
          <ChangeText pct={fromStart} />
          <span className="text-xs text-muted">{hover ? fmtTime(hover.t_ms, win, true) : `over ${WINDOW_LABEL[win]}`}</span>
        </div>
        <div className="w-56">
          <SegmentedControl aria-label="Chart window" options={PNL_WINDOWS.map((w) => ({ value: w, label: WINDOW_LABEL[w] }))} value={win} onChange={setWin} />
        </div>
      </div>
      {counter.length ? (
        <p className="flex items-center gap-3 text-[11px] text-muted">
          <span className="flex items-center gap-1"><span className="inline-block h-0.5 w-4" style={{ background: color }} /> his index</span>
          <span className="flex items-center gap-1"><span className="inline-block h-0 w-4 border-t-2 border-dashed border-accent" /> countering him (inverted)</span>
        </p>
      ) : null}
      <div ref={ref} className="relative w-full">
        {pts.length < 2 ? (
          <div className="flex h-[240px] items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted">
            No history for this window yet.
          </div>
        ) : (
          <svg
            width={width}
            height={H}
            role="img"
            tabIndex={0}
            onKeyDown={onKey}
            onBlur={() => setHoverI(null)}
            aria-label={`Equity index over ${WINDOW_LABEL[win]}: ${formatIndex(pts[0].value)} to ${formatIndex(pts.at(-1)?.value)}. Arrow keys read values.`}
            className="block select-none rounded-lg"
          >
            <defs>
              <linearGradient id={`g${gid}`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity="0.22" />
                <stop offset="100%" stopColor={color} stopOpacity="0" />
              </linearGradient>
            </defs>
            {ticks.map((t) => (
              <g key={t}>
                <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeDasharray="2 4" />
                <text x={width - PAD.right + 6} y={y(t)} dy="0.32em" fontSize="10" fill="var(--muted)" className="font-num">
                  {formatIndex(t)}
                </text>
              </g>
            ))}
            {[0, 0.5, 1].map((f, i) => (
              <text key={f} x={PAD.left + (width - PAD.left - PAD.right) * f} y={H - 6} fontSize="10" fill="var(--muted)" textAnchor={i === 0 ? "start" : i === 2 ? "end" : "middle"}>
                {fmtTime(t0 + (t1 - t0) * f, win)}
              </text>
            ))}
            <path d={area} fill={`url(#g${gid})`} />
            <path d={path} fill="none" stroke={color} strokeWidth="1.75" strokeLinejoin="round" />
            {counter.length ? (
              <path d={linePath(counter, x, y)} fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeDasharray="5 3" strokeLinejoin="round" data-testid="counter-overlay" />
            ) : null}
            {hover ? (
              <g pointerEvents="none">
                <line x1={x(hover.t_ms)} x2={x(hover.t_ms)} y1={PAD.top} y2={H - PAD.bottom} stroke="var(--foreground)" strokeOpacity="0.35" />
                <line x1={PAD.left} x2={width - PAD.right} y1={y(hover.value)} y2={y(hover.value)} stroke="var(--foreground)" strokeOpacity="0.2" strokeDasharray="3 3" />
                <circle cx={x(hover.t_ms)} cy={y(hover.value)} r="3.5" fill={color} stroke="var(--surface)" strokeWidth="1.5" />
                <rect x={width - PAD.right + 2} y={y(hover.value) - 9} width={PAD.right - 4} height="18" rx="4" fill="var(--foreground)" />
                <text x={width - PAD.right + 6} y={y(hover.value)} dy="0.32em" fontSize="10" fill="var(--background)" className="font-num">
                  {formatIndex(hover.value)}
                </text>
              </g>
            ) : null}
            <rect x={PAD.left} y={PAD.top} width={Math.max(0, width - PAD.left - PAD.right)} height={H - PAD.top - PAD.bottom} fill="transparent" onPointerMove={onMove} onPointerLeave={() => setHoverI(null)} />
          </svg>
        )}
      </div>
    </div>
  );
}
