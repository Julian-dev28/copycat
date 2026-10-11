"use client";

import { useId } from "react";
import { buildDualSparkline } from "@/lib/scout/spark";
import type { CurvePoint } from "@/lib/scout/types";
import { formatSignedUsdCompact } from "@/lib/scout/window";

/**
 * 30d sparkline: his PnL (neutral line, green/red fill to zero) and, when
 * given, your copy-sim equity (accent line). Both rebased to 0 at the window
 * start and each scaled to its own largest move (see buildDualSparkline): a
 * shape glyph for "did the copy track him", not a chart. Exact numbers live
 * on the trader file.
 */
export function Sparkline({
  points,
  sim = [],
  width = 240,
  height = 48,
  label = "30 day PnL",
  className,
}: {
  points: CurvePoint[];
  sim?: CurvePoint[];
  width?: number;
  height?: number;
  label?: string;
  className?: string;
}) {
  const id = useId().replace(/:/g, "");
  const s = buildDualSparkline(points, sim, width, height, 3);
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
  const aria =
    `${label}: his PnL ${formatSignedUsdCompact(s.his.change)}` +
    (s.sim ? `, your copy ${formatSignedUsdCompact(s.sim.change)}` : "") +
    " over the window. Lines show shape, each on its own scale.";
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={className}
      style={{ height }}
      role="img"
      aria-label={aria}
    >
      <title>{aria}</title>
      <defs>
        <clipPath id={up}>
          <rect x="0" y="0" width={width} height={Math.max(0, s.zeroY)} />
        </clipPath>
        <clipPath id={down}>
          <rect x="0" y={s.zeroY} width={width} height={Math.max(0, height - s.zeroY)} />
        </clipPath>
      </defs>
      <line x1="0" x2={width} y1={s.zeroY} y2={s.zeroY} stroke="var(--faint)" strokeOpacity="0.5" strokeWidth="1" strokeDasharray="2 4" vectorEffect="non-scaling-stroke" />
      <path d={s.his.area} fill="var(--up)" opacity="0.14" clipPath={`url(#${up})`} />
      <path d={s.his.area} fill="var(--down)" opacity="0.14" clipPath={`url(#${down})`} />
      <path d={s.his.path} fill="none" stroke="var(--fg-soft)" strokeOpacity="0.8" strokeWidth="1.25" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      {s.sim ? (
        <path d={s.sim.path} fill="none" stroke="var(--accent)" strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      ) : null}
    </svg>
  );
}

/** Two-swatch key for the card sparkline. */
export function SparkLegend({ hasSim }: { hasSim: boolean }) {
  return (
    <div className="flex items-center gap-3 text-[10px] text-muted">
      <span className="inline-flex items-center gap-1">
        <span className="h-0.5 w-3 rounded bg-muted" aria-hidden="true" />
        his PnL
      </span>
      {hasSim ? (
        <span className="inline-flex items-center gap-1">
          <span className="h-0.5 w-3 rounded bg-accent" aria-hidden="true" />
          your copy
        </span>
      ) : null}
      <span className="ml-auto">30d, shape only</span>
    </div>
  );
}
