import { clsx } from "clsx";
import type { HTMLAttributes, ReactNode } from "react";

export function Panel({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={clsx("rounded-xl border border-border bg-surface", className)} {...rest} />;
}

export function PanelHeader({
  title,
  description,
  action,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-4 pt-4 pb-2 sm:px-5 sm:pt-5">
      <div>
        <h2 className="text-sm font-semibold tracking-wide text-foreground">{title}</h2>
        {description ? <p className="mt-0.5 text-xs text-muted">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

/**
 * A single "control row": title + description on the left, the control on
 * the right. This is the Hyperdash-style layout for every setting on /copy.
 */
export function SettingRow({
  title,
  description,
  htmlFor,
  children,
  className,
  inline,
}: {
  title: ReactNode;
  description?: ReactNode;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
  /** Keep the control beside the label on phones too (switches). */
  inline?: boolean;
}) {
  return (
    <div
      className={clsx(
        "flex gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:px-5",
        inline ? "flex-row items-center justify-between" : "flex-col",
        "border-t border-border first:border-t-0",
        className,
      )}
    >
      <label htmlFor={htmlFor} className="min-w-0 max-w-sm text-sm font-medium text-foreground">
        {title}
        {description ? <span className="mt-0.5 block text-xs font-normal text-muted">{description}</span> : null}
      </label>
      <div className={clsx(inline ? "flex-shrink-0" : "w-full", "sm:w-80 sm:flex-shrink-0")}>{children}</div>
    </div>
  );
}
