"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { Check, Loader2, Plus, RefreshCw, ServerCrash } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { useScoutMode, useScoutRefresh, useScoutStatus, type ScoutBook } from "@/hooks/useScout";
import { formatAgo } from "@/lib/format";
import { coinLabel, isStale, STYLE_META } from "@/lib/scout/labels";
import type { CoinStat, TradingStyle } from "@/lib/scout/types";
import { MAX_LEADERS } from "@/lib/api/types";

/** href that keeps `?demo=1` when the board is in demo mode. */
export function scoutHref(path: string, demo: boolean): string {
  return demo ? `${path}${path.includes("?") ? "&" : "?"}demo=1` : path;
}

export function StyleTag({ style }: { style: TradingStyle | null | undefined }) {
  if (!style) return <span className="text-xs text-muted">style n/a</span>;
  const meta = STYLE_META[style];
  return (
    <span
      title={meta.hint}
      className={clsx(
        "inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium",
        style === "algo" ? "border-warning/40 text-warning" : "border-border text-foreground",
      )}
    >
      {meta.label}
    </span>
  );
}

export function CoinBadge({ coin, title }: { coin: string; title?: string }) {
  const { name, dex } = coinLabel(coin);
  return (
    <span
      title={title ?? coin}
      className="inline-flex items-center gap-1 rounded-md bg-surface-2 px-1.5 py-0.5 text-[11px] font-medium text-foreground"
    >
      {dex ? <span className="font-num text-[9px] uppercase text-accent">{dex}</span> : null}
      <span className="font-num">{name}</span>
    </span>
  );
}

export function CoinBadges({ coins, max = 4 }: { coins: CoinStat[]; max?: number }) {
  if (!coins.length) return <span className="text-xs text-muted">no trades in 30d</span>;
  const shown = coins.slice(0, max);
  const total = coins.reduce((a, c) => a + c.volume_usd, 0);
  return (
    <span className="flex flex-wrap items-center gap-1">
      {shown.map((c) => (
        <CoinBadge key={c.coin} coin={c.coin} title={`${c.coin}: ${total > 0 ? Math.round((c.volume_usd / total) * 100) : 0}% of his 30d volume`} />
      ))}
      {coins.length > max ? <span className="text-[11px] text-muted">+{coins.length - max}</span> : null}
    </span>
  );
}

/** "Add to book" / "In book". Disabled when already in the book or the book is full (10). */
export function AddToBookButton({
  address,
  book,
  inBook,
  size = "sm",
  className,
}: {
  address: string;
  book: ScoutBook;
  inBook: boolean;
  size?: "sm" | "md";
  className?: string;
}) {
  const adding = book.adding === address.toLowerCase();
  if (inBook) {
    return (
      <Button size={size} variant="secondary" disabled className={clsx("!opacity-100", className)} aria-label="Already in your book">
        <Check size={13} className="text-success" aria-hidden="true" />
        In book
      </Button>
    );
  }
  const full = book.atCap;
  return (
    <Button
      size={size}
      variant="primary"
      className={className}
      disabled={!book.ready || full || adding}
      title={full ? `Your book is full (${MAX_LEADERS} leaders). Remove one on /copy first.` : undefined}
      onClick={(e) => {
        e.stopPropagation();
        book.add(address);
      }}
    >
      {adding ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Plus size={13} aria-hidden="true" />}
      {full ? "Book full" : adding ? "Adding…" : "Add to book"}
    </Button>
  );
}

/** "refreshed 12m ago · 280 ranked" with live progress while a refresh runs, plus a Refresh button. */
export function RefreshBadge({ cohort, nowMs, asOfMs }: { cohort?: number; nowMs: number; asOfMs?: number }) {
  const status = useScoutStatus();
  const refresh = useScoutRefresh();
  const s = status.data;
  const running = s?.state === "running";
  const pct = s && s.total > 0 ? Math.round((s.done / s.total) * 100) : 0;
  const lastOk = s?.last_ok_ms ?? asOfMs ?? null;
  const stale = isStale(lastOk, s?.next_due_ms, nowMs);

  let text: ReactNode;
  if (status.isError) text = <span className="text-muted">refresh status unavailable</span>;
  else if (!s) text = <span className="text-muted">checking…</span>;
  else if (running)
    text = (
      <span className="text-foreground">
        refreshing {s.stage ?? ""} {pct}%{s.eta_s ? ` · ~${Math.max(1, Math.round(s.eta_s / 60))}m left` : ""}
      </span>
    );
  else if (s.state === "failed") text = <span className="text-danger" title={s.error ?? undefined}>last refresh failed</span>;
  else text = <span className={stale ? "text-warning" : "text-muted"}>refreshed {formatAgo(lastOk, nowMs)}{stale ? " (stale)" : ""}</span>;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1">
        <span
          className={clsx(
            "h-1.5 w-1.5 rounded-full",
            running ? "animate-pulse bg-accent" : s?.state === "failed" ? "bg-danger" : stale ? "bg-warning" : "bg-success",
          )}
          aria-hidden="true"
        />
        {text}
        {cohort ? <span className="text-muted">· {cohort} ranked</span> : null}
      </span>
      {running ? (
        <span className="h-1 w-24 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
          <span className="block h-full bg-accent transition-[width]" style={{ width: `${pct}%` }} />
        </span>
      ) : null}
      {!status.isError ? (
        <Button size="sm" variant="ghost" disabled={running || refresh.isPending} onClick={() => refresh.mutate()} title="Start a refresh now">
          <RefreshCw size={12} className={running || refresh.isPending ? "animate-spin" : ""} aria-hidden="true" />
          Refresh
        </Button>
      ) : null}
      {refresh.isError ? <span className="text-danger">{refresh.error.message}</span> : null}
    </div>
  );
}

export function ApiTooOld({ what }: { what: string }) {
  const { demo } = useScoutMode();
  return (
    <Notice
      tone="warning"
      title="Scout is not available on this api yet"
      action={
        demo ? undefined : (
          <Link href="?demo=1" className="text-sm font-medium text-accent underline-offset-2 hover:underline">
            Open the demo
          </Link>
        )
      }
    >
      <p>
        The api answered 404 or 503 for {what}: this build predates Scout, or discovery is not running. Pull and restart
        services/api and services/discovery to get{" "}
        <span className="font-num text-foreground">/api/scout/*</span>. Meanwhile the demo board shows the page with sample data.
      </p>
    </Notice>
  );
}

export function DemoBanner() {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-dashed border-accent/40 bg-accent-soft/40 px-3 py-1.5 text-xs text-muted">
      <ServerCrash size={13} className="text-accent" aria-hidden="true" />
      <span>
        <span className="font-semibold text-foreground">Demo data.</span> Sample traders, no api calls. Add to book only changes this tab.
      </span>
    </div>
  );
}
