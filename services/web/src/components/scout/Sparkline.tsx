"use client";

import { useId } from "react";
import { buildSparkline } from "@/lib/scout/spark";
import type { CurvePoint } from "@/lib/scout/types";
import { formatSignedUsdCompact } from "@/lib/scout/window";

/**
 * 30d PnL sparkline, rebased to 0 at the window start. The line is green
 * above zero and red below (two clip rects split at the zero line), with a
 * faint area to the zero line. A shape glyph, not a chart: no axis, the
 * exact numbers live on the trader file.
 */
export function Sparkline({
  points,
  width = 240,
  height = 48,
  label = "30 day PnL",
  className,
}: {
  points: CurvePoint[];
  width?: number;
  height?: number;
  label?: string;
  className?: string;
}) {
  const id = useId().replace(/:/g, "");
  const s = buildSparkline(points, width, height, 3);
  if (!s) {
    return (
      <div className={className} style={{ height }}>
        <div className="flex h-full items-center justify-center rounded-md border border-dashed border-border text-[11px] text-muted">
          no curve yet
        </div>
      </div>
    );
  }
  const up = `${id}-up`;
  const down = `${id}-down`;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={className}
      style={{ height }}
      role="img"
      aria-label={`${label}: ${formatSignedUsdCompact(s.change)} over the window`}
    >
      <defs>
        <clipPath id={up}>
          <rect x="0" y="0" width={width} height={Math.max(0, s.zeroY)} />
        </clipPath>
        <clipPath id={down}>
          <rect x="0" y={s.zeroY} width={width} height={Math.max(0, height - s.zeroY)} />
        </clipPath>
      </defs>
      <line x1="0" x2={width} y1={s.zeroY} y2={s.zeroY} stroke="var(--border)" strokeWidth="1" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
      <path d={s.area} fill="var(--success)" opacity="0.12" clipPath={`url(#${up})`} />
      <path d={s.area} fill="var(--danger)" opacity="0.12" clipPath={`url(#${down})`} />
      <path d={s.path} fill="none" stroke="var(--success)" strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" clipPath={`url(#${up})`} vectorEffect="non-scaling-stroke" />
      <path d={s.path} fill="none" stroke="var(--danger)" strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" clipPath={`url(#${down})`} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
