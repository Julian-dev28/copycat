"use client";

import { clsx } from "clsx";
import type { CSSProperties } from "react";
import type { Vibe } from "@/lib/copyRecipe";
import { ticksAt, trackPct } from "@/lib/display/slider";

export interface SliderProps {
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step?: number;
  id?: string;
  disabled?: boolean;
  /** Formats the readout to the right of the slider, e.g. (v) => `${v}x`. */
  formatValue?: (value: number) => string;
  /** Optional plain-words read of the value ("spicy"); colors the fill by heat. */
  vibe?: (value: number) => Vibe;
  /** Tick labels drawn under the track at their real positions. */
  ticks?: number[];
  formatTick?: (value: number) => string;
  "aria-label"?: string;
}

/**
 * Heat is not PnL (DESIGN 3.4): calm and warm stay on the accent, hot is
 * --warn, max is --danger. The heat word sits next to the value, never alone.
 */
const HEAT_VAR: Record<Vibe["heat"], string> = {
  calm: "var(--accent)",
  warm: "var(--accent)",
  hot: "var(--warn)",
  max: "var(--danger)",
};

const HEAT_TEXT: Record<Vibe["heat"], string> = {
  calm: "text-muted",
  warm: "text-muted",
  hot: "text-warn",
  max: "text-danger",
};

/** Range slider: 4px track, accent fill, white thumb, mono readout with the heat word beside it. */
export function Slider({
  value,
  onChange,
  min,
  max,
  step = 1,
  id,
  disabled,
  formatValue = (v) => String(v),
  vibe,
  ticks,
  formatTick = (v) => String(v),
  ...aria
}: SliderProps) {
  const v = vibe?.(value);
  const style = {
    "--fill": `${trackPct(value, min, max)}%`,
    "--fill-color": v ? HEAT_VAR[v.heat] : "var(--accent)",
  } as CSSProperties;
  const marks = ticks ? ticksAt(ticks, min, max) : [];

  return (
    <div className="flex items-start gap-3">
      <div className="min-w-0 flex-1 pt-2.5">
        <input
          id={id}
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(Number(e.target.value))}
          className={clsx("block w-full", disabled && "cursor-not-allowed opacity-40")}
          style={style}
          aria-valuetext={v ? `${formatValue(value)}, ${v.label}` : formatValue(value)}
          {...aria}
        />
        {marks.length ? (
          <div aria-hidden="true" className="relative mx-2 mt-2 h-4">
            {marks.map((m) => (
              <span key={m.value} className="num-sm absolute -translate-x-1/2 text-muted" style={{ left: `${m.pct}%` }}>
                {formatTick(m.value)}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <span className="flex flex-shrink-0 items-center gap-1.5">
        {v ? <span className={clsx("text-xs font-medium", HEAT_TEXT[v.heat])}>{v.label}</span> : null}
        <span className="num min-w-14 rounded-lg border border-border bg-surface-2 px-2 py-1 text-right text-fg">{formatValue(value)}</span>
      </span>
    </div>
  );
}
