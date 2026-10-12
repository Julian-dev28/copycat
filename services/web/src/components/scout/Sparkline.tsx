"use client";

import { useId } from "react";
import { CHART } from "@/components/ui/chartStyle";
import { buildDualSparkline } from "@/lib/scout/spark";
import type { CurvePoint } from "@/lib/scout/types";
import { formatSignedUsdCompact } from "@/lib/scout/window";

/**
 * 30d sparkline in the shared chart style (DESIGN 5 Charts): their PnL as a
 * thin --fg-soft line with the up/down area to zero, and, when given, your
 * copy-sim equity as the thicker --accent line. Both rebased to 0 at the
 * window start and each scaled to its own largest move (buildDualSparkline):
 * a shape glyph for "did the copy track them", not a chart. Exact numbers
 * live on the trader page.
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
        <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-border text-[11px] text-muted">no curve yet</div>
      </div>
    );
  }
  const up = `${id}-up`;
  const down = `${id}-down`;
  const aria =
    `${label}: their PnL ${formatSignedUsdCompact(s.his.change)}` +
    (s.sim ? `, your copy ${formatSignedUsdCompact(s.sim.change)}` : "") +
    " over the window. Lines show shape, each on its own scale.";
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className={className} style={{ height }} role="img" aria-label={aria}>
      <title>{aria}</title>
      <defs>
        <clipPath id={up}>
          <rect x="0" y="0" width={width} height={Math.max(0, s.zeroY)} />
        </clipPath>
        <clipPath id={down}>
          <rect x="0" y={s.zeroY} width={width} height={Math.max(0, height - s.zeroY)} />
        </clipPath>
      </defs>
      <line x1="0" x2={width} y1={s.zeroY} y2={s.zeroY} {...CHART.zero} />
      <path d={s.his.area} {...CHART.areaUp} clipPath={`url(#${up})`} />
      <path d={s.his.area} {...CHART.areaDown} clipPath={`url(#${down})`} />
      <path d={s.his.path} {...CHART.theirLine} />
      {s.sim ? <path d={s.sim.path} {...CHART.yourLine} /> : null}
    </svg>
  );
}

/** Two-swatch key for the card sparkline, drawn with the same strokes as the lines. */
export function SparkLegend({ hasSim }: { hasSim: boolean }) {
  return (
    <div className="flex items-center gap-3 text-[11px] text-muted">
      <span className="inline-flex items-center gap-1.5">
        <svg width="14" height="4" aria-hidden="true">
          <line x1="1" x2="13" y1="2" y2="2" {...CHART.theirLine} />
        </svg>
        their PnL
      </span>
      {hasSim ? (
        <span className="inline-flex items-center gap-1.5">
          <svg width="14" height="4" aria-hidden="true">
            <line x1="1" x2="13" y1="2" y2="2" {...CHART.yourLine} />
          </svg>
          your copy
        </span>
      ) : null}
      <span className="ml-auto">30d, shape only</span>
    </div>
  );
}
