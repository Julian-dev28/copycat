"use client";

import type { ReactNode } from "react";

export function OverrideRow({
  label,
  id,
  overridden,
  onToggle,
  inheritedLabel,
  children,
}: {
  label: string;
  id: string;
  overridden: boolean;
  onToggle: (overridden: boolean) => void;
  inheritedLabel: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:gap-4">
      <div className="flex items-center gap-2">
        <input
          id={id}
          type="checkbox"
          checked={overridden}
          onChange={(e) => onToggle(e.target.checked)}
          className="h-4 w-4 rounded border-border accent-[var(--accent)]"
        />
        <label htmlFor={id} className="text-sm text-foreground">
          {label}
        </label>
      </div>
      {overridden ? (
        <div className="w-full sm:w-56">{children}</div>
      ) : (
        <span className="font-num text-xs text-muted sm:w-56 sm:text-right">inherits: {inheritedLabel}</span>
      )}
    </div>
  );
}
