import { clsx } from "clsx";

/**
 * Loading placeholder: surface-2 block with a 1.4s shimmer sweep (static
 * under reduced motion). aria-hidden: pair it with a visually hidden
 * "Loading…" or aria-busy on the region.
 */
export function Skeleton({ className, rounded = "md" }: { className?: string; rounded?: "sm" | "md" | "full" }) {
  return (
    <span
      aria-hidden="true"
      className={clsx(
        "block animate-shimmer bg-[length:200%_100%]",
        "bg-[linear-gradient(90deg,var(--surface-2)_0%,var(--surface-3)_50%,var(--surface-2)_100%)]",
        rounded === "full" ? "rounded-full" : rounded === "sm" ? "rounded" : "rounded-lg",
        className ?? "h-4 w-full",
      )}
    />
  );
}

/** N text-line skeletons, last one shorter. */
export function SkeletonLines({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <span role="status" aria-label="Loading" className={clsx("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={clsx("h-3.5", i === lines - 1 ? "w-2/3" : "w-full")} />
      ))}
    </span>
  );
}
