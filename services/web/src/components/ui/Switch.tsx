"use client";

import { clsx } from "clsx";

export interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  id?: string;
  disabled?: boolean;
  label?: string;
}

/** Accessible toggle: a real checkbox under the hood, visually a switch. */
export function Switch({ checked, onChange, id, disabled, label }: SwitchProps) {
  return (
    <label
      htmlFor={id}
      className={clsx(
        "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors",
        checked ? "bg-accent" : "bg-surface-2 border border-border",
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
        className="peer absolute inset-0 h-full w-full cursor-pointer appearance-none opacity-0"
      />
      <span
        className={clsx(
          "pointer-events-none inline-block h-4.5 w-4.5 translate-x-0.5 rounded-full bg-white shadow transition-transform",
          checked && "translate-x-5.5",
        )}
        style={{ transform: checked ? "translateX(22px)" : "translateX(2px)" }}
      />
      <span
        className={clsx(
          "pointer-events-none absolute inset-0 rounded-full ring-2 ring-transparent",
          "peer-focus-visible:ring-[var(--focus-ring)]",
        )}
      />
    </label>
  );
}
