"use client";

/**
 * Built on the native <dialog> element: free focus trap, Esc-to-close, and
 * ::backdrop, instead of reimplementing a modal or pulling in a library.
 * DESIGN 5 Dialogs: glass e3, 16px radius, max 480px, 24px padding; the
 * panel scales .98 -> 1 and the backdrop fades (globals.css `ui-dialog`).
 * Destructive dialogs: put `autoFocus` on the Cancel button so focus starts
 * there, and use <Button variant="danger-solid"> for the confirm.
 */
import { clsx } from "clsx";
import { useEffect, useId, useRef, type ReactNode } from "react";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  /** max width: sm 400, md 480 (default), lg 640. */
  size?: "sm" | "md" | "lg";
}

const WIDTH = { sm: "w-[min(25rem,calc(100vw-2rem))]", md: "w-[min(30rem,calc(100vw-2rem))]", lg: "w-[min(40rem,calc(100vw-2rem))]" };

export function Dialog({ open, onClose, title, description, children, footer, size = "md" }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  // The native `close` event also fires after a programmatic el.close() (open -> false),
  // a tick later. Reporting that as a user close ran the parent's cancel handler after
  // it had already moved on: the Trade ticket's "Tighter liquidation" confirm opened
  // "Copy with real money?", then this stale close wiped the confirm chain and shut
  // it again, so "Copy at this leverage anyway" did nothing (2026-10-15).
  const wantOpen = useRef(open);

  useEffect(() => {
    wantOpen.current = open;   // set before el.close() below, so its queued close event reads false
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={() => {
        if (wantOpen.current) onClose();   // a close the user made (Esc, backdrop); not the echo of open=false
      }}
      onCancel={onClose}
      // a click on the backdrop lands on the <dialog> itself: cancel
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      aria-labelledby={titleId}
      className={clsx(
        "ui-dialog glass m-0 max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-2xl border border-border p-0 text-fg",
        "fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2",
        WIDTH[size],
      )}
    >
      <div className="p-6">
        <h2 id={titleId} className="text-title text-fg">
          {title}
        </h2>
        {description ? <div className="mt-2 text-body text-muted">{description}</div> : null}
        {children ? <div className="mt-4 text-body">{children}</div> : null}
        {footer ? <div className="mt-6 flex flex-wrap justify-end gap-2">{footer}</div> : null}
      </div>
    </dialog>
  );
}
