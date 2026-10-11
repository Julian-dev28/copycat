import { clsx } from "clsx";
import type { ReactNode } from "react";

/**
 * Stat tile (DESIGN 5): mono uppercase label, num-lg value, optional num-sm
 * sub-line. Put several in <StatGroup> to share one panel with vertical
 * hairlines instead of separate boxes. For signed money pass <Pnl> as value.
 */
export function Stat({
  label,
  value,
  sub,
  size = "lg",
  className,
  info,
}: {
  label: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  size?: "lg" | "xl" | "md";
  className?: string;
  /** Optional <Tooltip> trigger next to the label. */
  info?: ReactNode;
}) {
  return (
    <div className={clsx("flex min-w-0 flex-col gap-1", className)}>
      <dt className="text-label flex items-center gap-1 text-muted">
        {label}
        {info}
      </dt>
      <dd className={clsx("truncate text-fg", size === "xl" ? "num-xl" : size === "lg" ? "num-lg" : "num")}>{value}</dd>
      {sub ? <dd className="num-sm truncate text-muted">{sub}</dd> : null}
    </div>
  );
}

/** A row of stats in one panel, split by hairlines; wraps to 2 columns on phones. */
export function StatGroup({ children, className, columns = 4 }: { children: ReactNode; className?: string; columns?: 2 | 3 | 4 | 5 | 6 }) {
  const cols = { 2: "sm:grid-cols-2", 3: "sm:grid-cols-3", 4: "sm:grid-cols-4", 5: "sm:grid-cols-5", 6: "sm:grid-cols-3 lg:grid-cols-6" }[columns];
  return (
    <dl
      className={clsx(
        // gap-px over a border-colored track draws the hairlines between tiles
        "grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-border bg-border shadow-e1",
        "[&>*]:bg-surface [&>*]:px-4 [&>*]:py-3 sm:[&>*]:px-5",
        cols,
        className,
      )}
    >
      {children}
    </dl>
  );
}
