"use client";

import { clsx } from "clsx";
import type { CSSProperties } from "react";
import type { Vibe } from "@/lib/copyRecipe";

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
  /** Optional plain-words read of the value ("spicy"), colors the fill by heat. */
  vibe?: (value: number) => Vibe;
  "aria-label"?: string;
}

const HEAT_VAR: Record<Vibe["heat"], string> = {
  calm: "var(--success)",
  warm: "var(--accent)",
  hot: "var(--warning)",
  max: "var(--danger)",
};

const HEAT_TEXT: Record<Vibe["heat"], string> = {
  calm: "text-success",
  warm: "text-accent",
  hot: "text-warning",
  max: "text-danger",
};

/** Range slider with an accent fill and a boxed mono readout, used for every "N x" / "%" row. */
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
  ...aria
}: SliderProps) {
  const pct = max > min ? ((value - min) / (max - min)) * 100 : 0;
  const v = vibe?.(value);
  const style = {
    "--fill": `${Math.min(100, Math.max(0, pct))}%`,
    "--fill-color": v ? HEAT_VAR[v.heat] : "var(--accent)",
  } as CSSProperties;

  return (
    <div className="flex items-center gap-3">
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className={clsx("min-w-0 flex-1", disabled && "opacity-50")}
        style={style}
        aria-valuetext={v ? `${formatValue(value)}, ${v.label}` : formatValue(value)}
        {...aria}
      />
      <span className="flex w-20 flex-shrink-0 flex-col items-end leading-tight">
        <span className="font-num rounded-md border border-border bg-surface-2 px-2 py-0.5 text-sm tabular-nums text-foreground">
          {formatValue(value)}
        </span>
        {v ? <span className={clsx("mt-0.5 text-[11px] font-medium", HEAT_TEXT[v.heat])}>{v.label}</span> : null}
      </span>
    </div>
  );
}
