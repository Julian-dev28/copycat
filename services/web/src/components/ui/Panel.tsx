import { clsx } from "clsx";
import type { CSSProperties, HTMLAttributes, ReactNode } from "react";

/**
 * Panel / card (DESIGN 5, v2 "terminal"): flat surface, 3px radius, 1px
 * hairline, no shadow. `interactive` (clickable cards): hover brightens the
 * border and the fill, no lift. `enter` fades it in once on first paint
 * (index = 40ms stagger); otherwise it reveals on first scroll into view.
 */
export interface PanelProps extends HTMLAttributes<HTMLElement> {
  interactive?: boolean;
  /** Stagger index for the first-paint entrance (0-3). Omit for no entrance. */
  enter?: number;
  /** Fade in on first scroll into view (components/shell/Reveal.tsx). Default on; off for panels that must never blink (dialogs, sticky ticket). */
  reveal?: boolean;
  /** Render as a different element, e.g. "article" for one card in a list of independent items (screen readers get a landmark to navigate by). Default "div". */
  as?: "div" | "article" | "section";
}

export function Panel({ className, interactive, enter, reveal = true, style, as: Tag = "div", ...rest }: PanelProps) {
  return (
    <Tag
      data-enter={enter === undefined ? undefined : ""}
      data-reveal={reveal && enter === undefined ? "" : undefined}
      style={enter === undefined ? style : ({ ...style, "--enter-i": Math.min(enter, 3) } as CSSProperties)}
      className={clsx(
        "rounded-lg border border-border bg-surface",
        interactive && "transition-[border-color,background-color] duration-[var(--dur-fast)] hover:border-border-strong hover:bg-surface-2/60",
        className,
      )}
      {...rest}
    />
  );
}

/** Alias: a card is a panel. */
export const Card = Panel;

export function PanelHeader({
  title,
  description,
  action,
  meta,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  /** Mono label on the right ("UPDATED 12s AGO"). */
  meta?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-4 px-4 pt-4 pb-1 sm:px-5 sm:pt-5">
      <div className="min-w-0">
        <h2 className="text-heading text-fg">{title}</h2>
        {description ? <p className="mt-0.5 text-small text-muted">{description}</p> : null}
      </div>
      {meta ? <span className="text-label mt-1 flex-shrink-0 text-muted">{meta}</span> : null}
      {action}
    </div>
  );
}

/**
 * A single "control row": title + description on the left, the control on
 * the right. Every setting on /settings uses it.
 */
export function SettingRow({
  title,
  description,
  htmlFor,
  children,
  className,
  inline,
  valueClassName,
}: {
  title: ReactNode;
  description?: ReactNode;
  htmlFor?: string;
  children: ReactNode;
  className?: string;
  /** Keep the control beside the label on phones too (switches). */
  inline?: boolean;
  /** Replaces the value column's default `sm:w-80`: a 3-option SegmentedControl with a longer
   * label (e.g. "Fixed notional") truncates at 320px even on a wide screen (QA audit: "Fixed
   * notio…", "Match trad…"). Pass a wider width for those; every other row keeps the default so
   * the page's controls still line up in one column. */
  valueClassName?: string;
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
      <label htmlFor={htmlFor} className="min-w-0 max-w-sm text-sm font-medium text-fg">
        {title}
        {description ? <span className="mt-0.5 block text-xs font-normal text-muted">{description}</span> : null}
      </label>
      <div className={clsx(inline ? "flex-shrink-0" : "w-full", valueClassName ?? "sm:w-80", "sm:flex-shrink-0")}>{children}</div>
    </div>
  );
}
