"use client";

import { X } from "lucide-react";
import { clsx } from "clsx";
import { useEffect, useId, useRef, type ReactNode } from "react";

export interface DrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  /** Pinned under the scroll area (action bar). */
  footer?: ReactNode;
  /** Accessible name of the close button. */
  closeLabel?: string;
}

/**
 * Sheet: a right-side drawer on desktop, a bottom sheet on phones. Native
 * <dialog> for the focus trap + Esc; glass e3; slides in 16px over
 * --dur-slow (globals.css `ui-sheet`).
 */
export function Drawer({ open, onClose, title, children, footer, closeLabel = "Close" }: DrawerProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const wantOpen = useRef(open);   // see Dialog: ignore the native close event that echoes open=false
  const titleId = useId();

  useEffect(() => {
    wantOpen.current = open;
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={() => {
        if (wantOpen.current) onClose();
      }}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      aria-labelledby={titleId}
      className={clsx(
        "ui-sheet glass m-0 max-h-none max-w-none border-border p-0 text-fg",
        // phone: bottom sheet
        "fixed inset-x-0 top-auto bottom-0 h-auto max-h-[85dvh] w-full rounded-t-2xl border-t pb-[env(safe-area-inset-bottom)]",
        // sm+: right drawer
        "sm:top-0 sm:right-0 sm:left-auto sm:h-full sm:max-h-none sm:w-full sm:max-w-sm sm:rounded-none sm:rounded-l-2xl sm:border-t-0 sm:border-l sm:pb-0",
      )}
    >
      <div className="flex h-full max-h-[inherit] flex-col">
        <div className="flex items-center justify-between gap-3 px-5 py-4">
          <h2 id={titleId} className="text-heading">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={closeLabel}
            className="grid h-8 w-8 place-items-center rounded-sm text-muted transition-colors hover:bg-surface-2 hover:text-fg"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-5">{children}</div>
        {footer ? <div className="border-t border-border px-5 py-3">{footer}</div> : null}
      </div>
    </dialog>
  );
}

/** DESIGN.md name. */
export const Sheet = Drawer;
