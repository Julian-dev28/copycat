"use client";

import { clsx } from "clsx";
import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { nextRovingIndex } from "@/lib/display/rovingKeys";

export interface TabItem<T extends string> {
  id: T;
  label: ReactNode;
  /** Small mono count after the label. */
  count?: number;
  disabled?: boolean;
}

/**
 * Tabs (DESIGN 4/5): a tablist whose accent underline slides between tabs
 * (--dur-base, in-out). Arrows / Home / End move and select (automatic
 * activation). Render the active panel with <TabPanel> using the same ids.
 * Tabs are measured by the browser (each tab is its own width), so the
 * underline is drawn per tab and cross-fades its scale instead of moving.
 */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  idBase,
  className,
  ...aria
}: {
  items: TabItem<T>[];
  value: T;
  onChange: (id: T) => void;
  /** Prefix for tab/panel ids; pass the same to <TabPanel>. */
  idBase?: string;
  className?: string;
  "aria-label": string;
}) {
  const auto = useId();
  const base = idBase ?? auto;
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const idx = Math.max(0, items.findIndex((t) => t.id === value));

  function onKey(e: KeyboardEvent) {
    const next = nextRovingIndex(e.key, idx, items.length, (i) => Boolean(items[i].disabled));
    if (next === null) return;
    e.preventDefault();
    onChange(items[next].id);
    refs.current[next]?.focus();
  }

  return (
    <div
      role="tablist"
      aria-label={aria["aria-label"]}
      onKeyDown={onKey}
      className={clsx("scroll-fade-x flex items-center gap-1 border-b border-border", className)}
    >
      {items.map((t, i) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            id={`${base}-tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={`${base}-panel-${t.id}`}
            tabIndex={active ? 0 : -1}
            disabled={t.disabled}
            onClick={() => onChange(t.id)}
            className={clsx(
              "relative flex-shrink-0 whitespace-nowrap px-3 pt-2 pb-2.5 text-sm font-medium transition-colors duration-[var(--dur-fast)]",
              "rounded-t-lg focus-visible:-outline-offset-2 disabled:opacity-40",
              active ? "text-fg" : "text-muted hover:text-fg",
            )}
          >
            {t.label}
            {t.count !== undefined ? <span className="num-sm ml-1.5 text-muted">{t.count}</span> : null}
            <span
              aria-hidden="true"
              className={clsx(
                "absolute inset-x-2 -bottom-px h-0.5 origin-center rounded-full bg-accent",
                "transition-[scale,opacity] duration-[var(--dur-base)] ease-in-out",
                active ? "scale-x-100 opacity-100" : "scale-x-0 opacity-0",
              )}
            />
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ idBase, id, children, className }: { idBase: string; id: string; children: ReactNode; className?: string }) {
  return (
    <div role="tabpanel" id={`${idBase}-panel-${id}`} aria-labelledby={`${idBase}-tab-${id}`} tabIndex={0} className={clsx("focus-visible:outline-offset-4", className)}>
      {children}
    </div>
  );
}
