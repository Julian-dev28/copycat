"use client";

import { clsx } from "clsx";

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
  "aria-label"?: string;
}

/** A labeled range slider with a mono readout, used for every "N x" / "%" row on /copy. */
export function Slider({
  value,
  onChange,
  min,
  max,
  step = 1,
  id,
  disabled,
  formatValue = (v) => String(v),
  ...aria
}: SliderProps) {
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
        className={clsx(disabled && "opacity-50")}
        aria-valuetext={formatValue(value)}
        {...aria}
      />
      <span className="font-num w-16 flex-shrink-0 text-right text-sm tabular-nums text-foreground">
        {formatValue(value)}
      </span>
    </div>
  );
}
