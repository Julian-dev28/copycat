import { clsx } from "clsx";
import type { CSSProperties, ReactNode } from "react";

/**
 * Ticker strip (globals.css "Ticker"): the children are rendered twice and
 * the track slides left by one copy, so it loops without a seam. Edges fade
 * out, hover pauses, reduced motion shows it still. The duplicate copy is
 * `inert`: hidden from assistive tech AND out of the tab order (aria-hidden
 * alone hides it from screen readers but leaves its links tabbable, so a
 * keyboard user could land on an invisible duplicate link mid-tab-sequence;
 * caught by an axe scan, rule aria-hidden-focus).
 */
export function Marquee({ children, speedS = 60, className, label }: {
  children: ReactNode;
  /** Seconds for one full loop. */
  speedS?: number;
  className?: string;
  label: string;
}) {
  return (
    <div role="marquee" aria-label={label} className={clsx("marquee marquee-mask overflow-hidden", className)}>
      <div className="marquee-track flex w-max" style={{ "--marquee-s": `${speedS}s` } as CSSProperties}>
        <div className="flex shrink-0 items-center">{children}</div>
        <div className="flex shrink-0 items-center" aria-hidden="true" inert>{children}</div>
      </div>
    </div>
  );
}
