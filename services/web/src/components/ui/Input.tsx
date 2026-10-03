import { clsx } from "clsx";
import type { InputHTMLAttributes, ReactNode } from "react";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Unit shown inside the field before the value, e.g. "$". */
  leading?: ReactNode;
  /** Unit shown inside the field after the value, e.g. "x" or "%". */
  trailing?: ReactNode;
}

const base = [
  "w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-foreground",
  "placeholder:text-muted focus-visible:outline-2 focus-visible:outline-[var(--focus-ring)]",
  "disabled:cursor-not-allowed disabled:opacity-50",
];

export function Input({ className, leading, trailing, type, ...rest }: InputProps) {
  const numeric = type === "number";
  if (leading === undefined && trailing === undefined) {
    return <input type={type} className={clsx(base, numeric && "font-num tabular-nums", className)} {...rest} />;
  }
  return (
    <div className={clsx("relative", className)}>
      {leading !== undefined ? (
        <span className="pointer-events-none absolute inset-y-0 left-3 flex items-center text-sm text-muted">{leading}</span>
      ) : null}
      <input
        type={type}
        className={clsx(base, numeric && "font-num tabular-nums", leading !== undefined && "pl-7", trailing !== undefined && "pr-9")}
        {...rest}
      />
      {trailing !== undefined ? (
        <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm text-muted">{trailing}</span>
      ) : null}
    </div>
  );
}
