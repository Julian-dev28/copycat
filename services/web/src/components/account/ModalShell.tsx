"use client";

/**
 * Wide native <dialog> for the wallet manager. Same platform base as
 * ui/Dialog (focus trap, Esc, ::backdrop), plus: a header slot with a back
 * button, full-height sheet on phones, and `locked` to refuse Esc/backdrop
 * while a one-time secret is on screen.
 */
import { ArrowLeft, X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode, type SyntheticEvent } from "react";

export function ModalShell({
  open, onClose, title, onBack, locked, children, lockedHint,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  onBack?: () => void;
  locked?: boolean;
  lockedHint?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  const latest = useRef({ open, locked, onClose });
  // Every render: keep the element in step with `open` (a close we did not
  // drive, e.g. Chrome's double-Esc close watcher, is undone on the next render).
  useEffect(() => {
    latest.current = { open, locked, onClose };
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  });

  // The native close event, whoever caused it: reopen while locked, else sync our state.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onNativeClose = () => {
      const { open: wantOpen, locked: isLocked, onClose: close } = latest.current;
      if (!wantOpen) return;
      if (isLocked) el.showModal();
      else close();
    };
    el.addEventListener("close", onNativeClose);
    return () => el.removeEventListener("close", onNativeClose);
  }, []);

  function onCancel(e: SyntheticEvent) {
    e.preventDefault(); // we decide whether Esc closes
    if (!locked) onClose();
  }

  return (
    <dialog
      ref={ref}
      onCancel={onCancel}
      onClick={(e) => {
        if (e.target === e.currentTarget && !locked) onClose(); // backdrop click
      }}
      aria-labelledby={titleId}
      className={[
        "m-0 max-h-[100dvh] w-full max-w-none overflow-y-auto border-border bg-surface p-0 text-foreground",
        "fixed inset-0 h-[100dvh] sm:inset-auto sm:top-1/2 sm:left-1/2 sm:h-auto sm:max-h-[90dvh] sm:w-[min(36rem,calc(100vw-2rem))]",
        "sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-xl sm:border",
        "backdrop:bg-black/60 backdrop:backdrop-blur-[2px]",
      ].join(" ")}
    >
      <div className="sticky top-0 z-10 flex items-center gap-2 border-b border-border bg-surface/95 px-4 py-3 backdrop-blur sm:px-5">
        {onBack ? (
          <button type="button" onClick={onBack} aria-label="Back" className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-foreground">
            <ArrowLeft size={16} />
          </button>
        ) : null}
        <h2 id={titleId} className="min-w-0 flex-1 truncate text-base font-semibold">
          {title}
        </h2>
        <button
          type="button"
          onClick={onClose}
          disabled={locked}
          aria-label="Close"
          title={locked ? lockedHint : "Close"}
          className="rounded-lg p-1.5 text-muted hover:bg-surface-2 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
        >
          <X size={16} />
        </button>
      </div>
      <div className="p-4 sm:p-5">{children}</div>
    </dialog>
  );
}
