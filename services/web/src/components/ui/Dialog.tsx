"use client";

/**
 * Built on the native <dialog> element: free focus trap, Esc-to-close, and
 * ::backdrop, instead of reimplementing a modal from scratch or pulling in
 * a dialog library for something the platform already does.
 */
import { useEffect, useId, useRef, type ReactNode } from "react";

export interface DialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
}

export function Dialog({ open, onClose, title, description, children, footer }: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={onClose}
      aria-labelledby={titleId}
      className={[
        "m-0 w-[min(28rem,calc(100vw-2rem))] rounded-xl border border-border bg-surface p-0 text-foreground",
        "fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2",
        "backdrop:bg-black/60",
      ].join(" ")}
    >
      <div className="p-5">
        <h2 id={titleId} className="text-base font-semibold">
          {title}
        </h2>
        {description ? <div className="mt-2 text-sm text-muted">{description}</div> : null}
        {children ? <div className="mt-4">{children}</div> : null}
        {footer ? <div className="mt-5 flex justify-end gap-2">{footer}</div> : null}
      </div>
    </dialog>
  );
}
