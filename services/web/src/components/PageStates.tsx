"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { ApiError, getApiBase } from "@/lib/api/client";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";

/**
 * Placeholder blocks shaped like the page's panels, so the layout doesn't
 * jump when data lands. `label` used to be sr-only: a screen reader heard
 * "Loading account", a sighted user on a slow connection just saw three
 * empty pulsing boxes for as long as the route's JS chunk took to arrive
 * (QA audit: "a bare skeleton for more than 2s, then the page"). It is now
 * plain visible text; `role="status"` still announces it, so the sr-only
 * duplicate is gone too.
 */
export function PageSkeleton({ label, rows = 3 }: { label: string; rows?: number }) {
  return (
    <div className="flex flex-col gap-6" role="status">
      <p className="flex items-center gap-2 text-sm text-muted">
        <Loader2 size={14} className="animate-spin" aria-hidden="true" /> {label}…
      </p>
      <div className="h-12 w-64 animate-pulse rounded-lg bg-surface-2" />
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-40 animate-pulse rounded-xl border border-border bg-surface" />
      ))}
    </div>
  );
}

/** Load failure with the reason in plain words and a retry. 401s never get here: RequireToken catches them. */
export function LoadError({ what, error, onRetry }: { what: string; error: unknown; onRetry?: () => void }) {
  const unreachable = error instanceof ApiError && error.status === 0;
  return (
    <Notice
      tone="danger"
      title={unreachable ? "Can't reach the copycat api" : `Couldn't load ${what}`}
      action={
        onRetry ? (
          <Button size="sm" onClick={onRetry}>
            <RefreshCw size={13} aria-hidden="true" />
            Retry
          </Button>
        ) : undefined
      }
    >
      {unreachable ? (
        <p>
          Nothing answered at <span className="font-num text-foreground">{getApiBase()}</span>. Start it with{" "}
          <span className="font-num text-foreground">make dev</span> or check NEXT_PUBLIC_COPYCAT_API.
        </p>
      ) : (
        <p>{error instanceof Error ? error.message : "Unknown error."}</p>
      )}
    </Notice>
  );
}
