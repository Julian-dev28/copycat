import { clsx } from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

/**
 * Table styles (DESIGN 5 Tables) as class constants plus a scroll wrapper,
 * so pages keep their own <table> markup and just swap classes:
 *
 *   <TableScroll><table className={TABLE.table}>
 *     <thead><tr><th className={TABLE.th}>Coin</th><th className={TABLE.thNum}>PnL</th></tr></thead>
 *     <tbody><tr className={TABLE.tr}><td className={TABLE.td}>ETH</td><td className={TABLE.tdNum}>…</td></tr></tbody>
 *   </table></TableScroll>
 *
 * Header: surface-2, sticky, label style. Rows 36px, hover surface-3, never
 * move. Numbers right-aligned mono. Selected row: 2px inset accent bar.
 * Overflow: scrolls inside its panel with a right-edge fade; first column
 * sticky (`TABLE.stickyFirst` on the first th/td). Under 640px, tables with
 * more than 5 columns should render stacked cards instead (page decision).
 */
export const TABLE = {
  table: "w-full border-separate border-spacing-0 text-sm",
  th: "sticky top-0 z-[1] whitespace-nowrap border-b border-border bg-surface-2 px-3 py-2 text-left text-label text-muted first:pl-4 last:pr-4",
  thNum: "sticky top-0 z-[1] whitespace-nowrap border-b border-border bg-surface-2 px-3 py-2 text-right text-label text-muted first:pl-4 last:pr-4",
  tr: "group/row transition-colors duration-[var(--dur-fast)] hover:bg-surface-3",
  trSelected: "bg-surface-3 shadow-[inset_2px_0_0_var(--accent)]",
  td: "h-9 whitespace-nowrap border-b border-border px-3 py-2 text-left text-fg-soft first:pl-4 last:pr-4",
  tdNum: "num h-9 whitespace-nowrap border-b border-border px-3 py-2 text-right text-fg-soft first:pl-4 last:pr-4",
  stickyFirst: "sticky left-0 z-[2] bg-surface group-hover/row:bg-surface-3",
} as const;

/** Horizontal scroll container with the right-edge fade cue. Focusable so keyboard users can scroll it. */
export function TableScroll({ children, className, label, ...rest }: HTMLAttributes<HTMLDivElement> & { children: ReactNode; label?: string }) {
  return (
    <div
      role={label ? "region" : undefined}
      aria-label={label}
      tabIndex={label ? 0 : undefined}
      className={clsx("scroll-fade-x relative w-full overflow-x-auto overscroll-x-contain", className)}
      {...rest}
    >
      {children}
    </div>
  );
}
