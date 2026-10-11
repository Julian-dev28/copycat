"use client";

import { clsx } from "clsx";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";
import { useSyncExternalStore } from "react";
import { toasts, type Toast } from "@/lib/display/toastStore";

export { toast } from "@/lib/display/toastStore";

const ICON = { info: Info, success: CheckCircle2, error: AlertCircle } as const;
const ICON_TONE = { info: "text-accent", success: "text-ok", error: "text-danger" } as const;
const EMPTY: Toast[] = [];

/**
 * Renders the toast queue bottom-right (above the mobile tab bar). Glass e3,
 * icon + one line + optional action. role="status" for info/success,
 * role="alert" for errors. Hover or focus pauses auto-dismiss. Mounted once
 * in providers.tsx; call `toast(...)` from anywhere.
 */
export function Toaster() {
  const items = useSyncExternalStore(toasts.subscribe, toasts.get, () => EMPTY);
  return (
    <div
      aria-label="Notifications"
      className="pointer-events-none fixed inset-x-0 bottom-[calc(var(--tabbar-h)+env(safe-area-inset-bottom)+0.75rem)] z-[70] flex flex-col items-center gap-2 px-4 sm:inset-x-auto sm:right-4 sm:bottom-4 sm:items-end"
    >
      {items.map((t) => {
        const Icon = ICON[t.tone];
        return (
          <div
            key={t.id}
            role={t.tone === "error" ? "alert" : "status"}
            onMouseEnter={() => toasts.pause(t.id)}
            onMouseLeave={() => toasts.resume(t.id)}
            onFocus={() => toasts.pause(t.id)}
            onBlur={() => toasts.resume(t.id)}
            className="ui-toast glass pointer-events-auto flex w-full max-w-sm items-center gap-3 rounded-xl border border-border py-2.5 pr-2 pl-3.5 text-sm text-fg"
          >
            <Icon size={16} className={clsx("flex-shrink-0", ICON_TONE[t.tone])} aria-hidden="true" />
            <p className="min-w-0 flex-1">{t.message}</p>
            {t.action ? (
              <button
                type="button"
                onClick={() => {
                  t.action?.onClick();
                  toasts.dismiss(t.id);
                }}
                className="flex-shrink-0 rounded-full px-2.5 py-1 text-xs font-medium text-accent hover:bg-surface-2"
              >
                {t.action.label}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => toasts.dismiss(t.id)}
              aria-label="Dismiss"
              className="grid h-7 w-7 flex-shrink-0 place-items-center rounded-full text-muted hover:bg-surface-2 hover:text-fg"
            >
              <X size={14} aria-hidden="true" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
