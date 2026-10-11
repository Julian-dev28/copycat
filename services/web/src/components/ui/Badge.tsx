import { clsx } from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

/**
 * 20px chip, 11px mono uppercase, pill, soft bg + matching text (DESIGN 5).
 * Status is not PnL (DESIGN 3.4):
 * - accent: live / selected / "Copying"
 * - warn:   dry run, skipped, near-liq
 * - neutral: anything else
 * - danger: halted, error, liquidated only
 * - up / down: money only (rare on a badge)
 * Legacy tones: success -> up-ish ok green, warning -> warn.
 */
export type BadgeTone = "neutral" | "accent" | "warn" | "danger" | "up" | "down" | "success" | "warning";

export const BADGE_TONE: Record<BadgeTone, string> = {
  neutral: "bg-surface-2 text-muted border-border",
  accent: "bg-accent-soft text-accent border-accent/25",
  warn: "bg-warn-soft text-warn border-warn/25",
  warning: "bg-warn-soft text-warn border-warn/25",
  danger: "bg-danger-soft text-danger border-danger/25",
  up: "bg-up-soft text-up border-up/25",
  down: "bg-down-soft text-down border-down/25",
  success: "bg-surface-2 text-ok border-ok/25",
};

export interface BadgeProps extends Omit<HTMLAttributes<HTMLSpanElement>, "children"> {
  tone?: BadgeTone;
  /** Leading dot (live states). `pulse` animates it (stops under reduced motion). */
  dot?: boolean | "pulse";
  children: ReactNode;
}

export function Badge({ tone = "neutral", dot, children, className, ...rest }: BadgeProps) {
  return (
    <span
      className={clsx(
        "inline-flex h-5 items-center gap-1 whitespace-nowrap rounded-full border px-2 text-label leading-none",
        BADGE_TONE[tone],
        className,
      )}
      {...rest}
    >
      {dot ? <span aria-hidden="true" className={clsx("h-1.5 w-1.5 rounded-full bg-current", dot === "pulse" && "animate-pulse-live")} /> : null}
      {children}
    </span>
  );
}
