import { clsx } from "clsx";
import type { CSSProperties, ReactNode } from "react";
import { CatLogo } from "@/components/CatLogo";

/**
 * Empty state (DESIGN 5): small cat outline (brand at 40%), a headline with
 * at most one serif-italic word, one sentence, one primary action.
 * Example: <EmptyState title={<>Nothing <em>copied</em> yet</>} ... />
 * (an <em> in the title renders as the serif accent).
 */
export function EmptyState({
  title,
  body,
  action,
  className,
  compact,
}: {
  title: ReactNode;
  body?: ReactNode;
  action?: ReactNode;
  className?: string;
  /** Tighter padding for use inside a table or panel. */
  compact?: boolean;
}) {
  return (
    <div
      className={clsx("flex flex-col items-center text-center", compact ? "gap-2 px-4 py-6" : "gap-3 px-6 py-12", className)}
      style={{ "--cat-eye": "var(--bg)" } as CSSProperties}
    >
      <CatLogo size={compact ? 28 : 36} className="text-brand opacity-40" title="" />
      <h3 className="text-title text-fg [&_em]:font-serif [&_em]:font-normal [&_em]:italic">
        {title}
      </h3>
      {body ? <p className="max-w-sm text-body text-muted">{body}</p> : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
