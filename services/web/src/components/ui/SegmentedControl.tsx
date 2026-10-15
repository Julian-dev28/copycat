"use client";

import { clsx } from "clsx";
import { useRef, type CSSProperties, type KeyboardEvent } from "react";
import { nextRovingIndex } from "@/lib/display/rovingKeys";

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
  size?: "sm" | "md";
  className?: string;
}

/**
 * Radio-group segmented control (DESIGN 5): pill track on surface-2, one
 * thumb that slides (--dur-base, in-out) under the selected segment. Not
 * accent-filled: the accent is for the primary action. Keyboard: arrows,
 * Home, End (roving tabindex).
 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  disabled,
  size = "md",
  className,
  ...aria
}: SegmentedControlProps<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const idx = Math.max(0, options.findIndex((o) => o.value === value));
  const selected = options.some((o) => o.value === value);

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    if (disabled) return;
    const next = nextRovingIndex(e.key, idx, options.length);
    if (next === null) return;
    e.preventDefault();
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label={aria["aria-label"]}
      aria-disabled={disabled || undefined}
      onKeyDown={onKey}
      // grid, not flex: `flex-1 basis-0` items share the track equally but a shrink-to-fit
      // control then sized itself below its labels ("24h" rendered as "2…", 2026-10-16).
      // Equal 1fr tracks take the widest label's width in a w-auto control and split a w-full one.
      className={clsx("relative isolate grid w-full auto-cols-fr grid-flow-col rounded-sm border border-border bg-surface-2 p-1", className)}
      style={{ "--n": options.length, "--i": idx } as CSSProperties}
    >
      {selected ? (
        <span
          aria-hidden="true"
          className={clsx(
            "absolute inset-y-1 left-1 -z-10 rounded-sm bg-surface shadow-e1 dark:bg-surface-3",
            "w-[calc((100%-0.5rem)/var(--n))] translate-x-[calc(var(--i)*100%)]",
            "transition-transform duration-[var(--dur-base)] ease-in-out",
          )}
        />
      ) : null}
      {options.map((opt, i) => {
        const active = opt.value === value;
        return (
          <button
            key={opt.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active || (!selected && i === 0) ? 0 : -1}
            disabled={disabled}
            onClick={() => onChange(opt.value)}
            className={clsx(
              "min-w-0 truncate whitespace-nowrap rounded-sm font-medium transition-colors duration-[var(--dur-fast)]",
              size === "sm" ? "px-2 py-1 text-xs" : "px-2.5 py-1.5 text-xs sm:text-sm",
              "disabled:cursor-not-allowed disabled:opacity-40",
              active ? "text-fg" : "text-muted hover:text-fg",
            )}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/** Alias with the DESIGN.md name. */
export const Segmented = SegmentedControl;
