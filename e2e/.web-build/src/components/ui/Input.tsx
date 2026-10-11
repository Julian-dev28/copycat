import { clsx } from "clsx";
import type { InputHTMLAttributes, ReactNode } from "react";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  /** Unit shown inside the field before the value, e.g. "$". */
  leading?: ReactNode;
  /** Unit shown inside the field after the value, e.g. "x" or "%". */
  trailing?: ReactNode;
  /** Mark the field invalid (danger border; pair with an error message + aria-describedby). */
  invalid?: boolean;
}

/** The field box. With units, the ring is drawn on this wrapper only (DESIGN 5: one focus ring). */
const FIELD = [
  "rounded-lg border bg-surface-2 text-sm text-fg transition-[border-color,box-shadow] duration-[var(--dur-fast)]",
  "hover:border-border-strong",
];
const RING = "focus-within:border-accent focus-within:outline-2 focus-within:outline-offset-1 focus-within:outline-[var(--accent)]";
const INNER = "w-full bg-transparent py-2 text-fg placeholder:text-muted outline-none focus-visible:outline-none disabled:cursor-not-allowed";

/** Text/number input with optional units. `className` goes on the outer element. */
export function Input({ className, leading, trailing, type, invalid, ...rest }: InputProps) {
  const numeric = type === "number" || rest.inputMode === "decimal" || rest.inputMode === "numeric";
  const tone = invalid ? "border-danger" : "border-border";
  if (leading === undefined && trailing === undefined) {
    return (
      <input
        type={type}
        aria-invalid={invalid || undefined}
        className={clsx(
          FIELD,
          tone,
          "w-full px-3 py-2 placeholder:text-muted focus-visible:border-accent disabled:cursor-not-allowed disabled:opacity-40",
          numeric && "font-num tabular-nums",
          className,
        )}
        {...rest}
      />
    );
  }
  return (
    <div className={clsx(FIELD, tone, RING, "flex items-center gap-1.5 px-3 has-[:disabled]:opacity-40", className)}>
      {leading !== undefined ? <span className="num-sm pointer-events-none flex-shrink-0 text-muted">{leading}</span> : null}
      <input type={type} aria-invalid={invalid || undefined} className={clsx(INNER, numeric && "font-num tabular-nums")} {...rest} />
      {trailing !== undefined ? <span className="num-sm pointer-events-none flex-shrink-0 text-muted">{trailing}</span> : null}
    </div>
  );
}
