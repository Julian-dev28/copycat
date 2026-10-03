"use client";

import { clsx } from "clsx";

export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

export interface SegmentedControlProps<T extends string> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  "aria-label": string;
  disabled?: boolean;
}

/** Radio-group-backed segmented control (Fixed margin / Fixed notional / Proportional, etc.). */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  disabled,
  ...aria
}: SegmentedControlProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={aria["aria-label"]}
      className="inline-flex w-full rounded-lg border border-border bg-surface-2 p-1"
    >
      {options.map((opt) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            className={clsx(
              "flex-1 whitespace-nowrap rounded-md px-2 py-1.5 text-xs font-medium transition-colors sm:text-sm",
              "disabled:cursor-not-allowed disabled:opacity-50",
              active ? "bg-accent text-accent-foreground shadow-sm" : "text-muted hover:text-foreground",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
