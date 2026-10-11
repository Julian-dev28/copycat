"use client";

import { clsx } from "clsx";

export interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  id?: string;
  disabled?: boolean;
  label?: string;
  /**
   * State words shown beside the switch so state is never color-only
   * (DESIGN 5: real-money toggles), e.g. ["Live", "Off"]. Pass true for ["On", "Off"].
   */
  stateText?: boolean | [on: string, off: string];
}

/**
 * Accessible toggle: a real checkbox with role="switch" under the hood.
 * Track 36x20 (off surface-3, on accent), white 16px thumb that slides
 * --dur-base in-out. Focus ring on the track.
 */
export function Switch({ checked, onChange, id, disabled, label, stateText }: SwitchProps) {
  const words = stateText === true ? ["On", "Off"] : stateText || null;
  return (
    <span className="inline-flex items-center gap-2">
      <label
        htmlFor={id}
        className={clsx(
          "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full transition-colors duration-[var(--dur-base)] ease-in-out",
          checked ? "bg-accent" : "bg-surface-3 ring-1 ring-border-strong ring-inset",
          disabled && "cursor-not-allowed opacity-40",
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
          className="peer absolute inset-0 h-full w-full cursor-pointer appearance-none rounded-full opacity-0 disabled:cursor-not-allowed"
        />
        <span
          aria-hidden="true"
          className={clsx(
            "pointer-events-none ml-0.5 inline-block h-4 w-4 rounded-full bg-white shadow-e1 transition-transform duration-[var(--dur-base)] ease-in-out",
            checked ? "translate-x-4" : "translate-x-0",
          )}
        />
        <span
          aria-hidden="true"
          className="pointer-events-none absolute -inset-0.5 rounded-full outline-2 outline-offset-1 outline-transparent peer-focus-visible:outline-[var(--accent)] peer-focus-visible:outline"
        />
      </label>
      {words ? (
        <span aria-hidden="true" className={clsx("text-label w-8", checked ? "text-fg" : "text-muted")}>
          {checked ? words[0] : words[1]}
        </span>
      ) : null}
    </span>
  );
}
