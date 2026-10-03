"use client";

import { clsx } from "clsx";

export interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  id?: string;
  disabled?: boolean;
  label?: string;
}

/**
 * Accessible toggle: a real checkbox under the hood, visually a switch.
 * Track 44x24 with a 2px border in both states (so it never changes size),
 * thumb 16px: off at x=2, on at x=44-4-16-2=22 -> translate-x-5 (20px) from 2px.
 */
export function Switch({ checked, onChange, id, disabled, label }: SwitchProps) {
  return (
    <label
      htmlFor={id}
      className={clsx(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 transition-colors",
        checked ? "border-accent bg-accent" : "border-border bg-surface-2",
        disabled && "cursor-not-allowed opacity-50",
      )}
    >
      <input
        id={id}
        type="checkbox"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="peer absolute inset-0 h-full w-full cursor-pointer appearance-none opacity-0 disabled:cursor-not-allowed"
      />
      <span
        aria-hidden="true"
        className={clsx(
          "pointer-events-none ml-0.5 inline-block h-4 w-4 rounded-full shadow transition-transform",
          checked ? "translate-x-5 bg-accent-foreground" : "translate-x-0 bg-muted",
        )}
      />
      <span
        aria-hidden="true"
        className="pointer-events-none absolute -inset-0.5 rounded-full ring-2 ring-transparent peer-focus-visible:ring-[var(--focus-ring)]"
      />
    </label>
  );
}
