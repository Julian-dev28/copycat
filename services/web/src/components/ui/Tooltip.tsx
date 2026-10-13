import { clsx } from "clsx";
import { Info } from "lucide-react";
import type { ReactNode } from "react";

/**
 * CSS-only tooltip: shows on hover and on keyboard focus of the trigger,
 * linked with aria-describedby so screen readers read it. Use for short
 * explanations ("Growth of $100 since tracking began, deposits removed") and
 * for why a button is disabled. No JS, no portal; keep text to a sentence.
 */
export function Tooltip({
  content,
  children,
  side = "top",
  className,
  id,
}: {
  content: ReactNode;
  /** The trigger. Must be focusable (a button or link) for keyboard users; see <InfoTip>. */
  children: ReactNode;
  side?: "top" | "bottom";
  className?: string;
  /** Stable id for aria-describedby on the trigger. */
  id: string;
}) {
  return (
    <span className={clsx("group/tip relative inline-flex", className)}>
      {children}
      <span
        role="tooltip"
        id={id}
        className={clsx(
          "pointer-events-none absolute left-1/2 z-50 w-max max-w-64 -translate-x-1/2 rounded-lg border border-border bg-surface-3 px-2.5 py-1.5",
          "text-xs font-normal normal-case tracking-normal text-fg-soft shadow-e2",
          "invisible opacity-0 transition-opacity duration-[var(--dur-fast)]",
          "group-hover/tip:visible group-hover/tip:opacity-100 group-focus-within/tip:visible group-focus-within/tip:opacity-100",
          side === "top" ? "bottom-full mb-1.5" : "top-full mt-1.5",
        )}
      >
        {content}
      </span>
    </span>
  );
}

/** A small focusable (i) trigger with a tooltip, for labels and column headers. */
export function InfoTip({ id, content, label = "More info" }: { id: string; content: ReactNode; label?: string }) {
  return (
    <Tooltip id={id} content={content}>
      <button
        type="button"
        aria-label={label}
        aria-describedby={id}
        className="grid h-4 w-4 place-items-center rounded-sm text-muted transition-colors hover:text-fg"
      >
        <Info size={12} aria-hidden="true" />
      </button>
    </Tooltip>
  );
}
