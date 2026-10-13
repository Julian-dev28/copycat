"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { Check, Loader2, Plus, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { useScoutMode, useScoutRefresh, useScoutStatus, type ScoutBook } from "@/hooks/useScout";
import { formatAgo } from "@/lib/format";
import { LABELS } from "@/lib/labels";
import { MAX_LEADERS } from "@/lib/api/types";
import { coinLabel, dexHint, isStale, STYLE_META } from "@/lib/scout/labels";
import type { CoinStat, TradingStyle } from "@/lib/scout/types";

/** href that keeps `?demo=1` when the board is in demo mode. */
export function scoutHref(path: string, demo: boolean): string {
  return demo ? `${path}${path.includes("?") ? "&" : "?"}demo=1` : path;
}

/** Trade with this trader preselected (Trade reads `?w=`). */
export function copyOnTradeHref(address: string, demo: boolean): string {
  return scoutHref(`/?w=${address.toLowerCase()}`, demo);
}

/**
 * Page title in the display style (DESIGN 3.5): one serif-italic word max,
 * passed as an <em> in `title`. One h1 per page.
 */
export function PageTitle({ title, description, aside }: { title: ReactNode; description?: ReactNode; aside?: ReactNode }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-display text-fg [&_em]:font-serif [&_em]:font-normal [&_em]:italic [&_em]:tracking-normal">{title}</h1>
        {description ? <p className="mt-2 max-w-2xl text-body text-muted">{description}</p> : null}
      </div>
      {aside ? <div className="flex-shrink-0">{aside}</div> : null}
    </div>
  );
}

export function StyleTag({ style }: { style: TradingStyle | null | undefined }) {
  if (!style) return <Badge>style n/a</Badge>;
  const meta = STYLE_META[style];
  return (
    <Badge tone={style === "algo" ? "warn" : "neutral"} title={meta.hint}>
      {meta.label}
    </Badge>
  );
}

/** Long / short is not good / bad (DESIGN 3.4): neutral text with a glyph, never up/down color. */
export function SideTag({ side }: { side: "long" | "short" | "buy" | "sell" }) {
  const up = side === "long" || side === "buy";
  const word = side.charAt(0).toUpperCase() + side.slice(1);
  return (
    <span className="inline-flex items-center gap-0.5 whitespace-nowrap text-xs font-medium text-fg-soft">
      <span aria-hidden="true" className="text-muted">
        {up ? "↗" : "↘"}
      </span>
      {word}
    </span>
  );
}

export function CoinBadge({ coin, title }: { coin: string; title?: string }) {
  const { name, dex } = coinLabel(coin);
  return (
    <span
      title={title ?? (dex ? `${coin}: ${dexHint(dex)}` : coin)}
      className="inline-flex h-5 items-center gap-1 rounded-sm border border-border bg-surface-2 px-2 text-[11px] font-medium text-fg"
    >
      {dex ? <span className="font-num text-[9px] uppercase text-muted">{dex}</span> : null}
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
      {shown.map((c) => {
        const { dex } = coinLabel(c.coin);
        const share = `${total > 0 ? Math.round((c.volume_usd / total) * 100) : 0}% of their 30d volume`;
        return <CoinBadge key={c.coin} coin={c.coin} title={`${c.coin}: ${share}${dex ? `. ${dexHint(dex)}` : ""}`} />;
      })}
      {coins.length > max ? <span className="num-sm text-muted">+{coins.length - max}</span> : null}
    </span>
  );
}

/** "Add to copies" / "Copying". Disabled when already copied or the copies list is full. */
export function AddToBookButton({
  address,
  book,
  inBook,
  size = "sm",
  variant = "primary",
  className,
}: {
  address: string;
  book: ScoutBook;
  inBook: boolean;
  size?: "sm" | "md";
  variant?: "primary" | "secondary";
  className?: string;
}) {
  const adding = book.adding === address.toLowerCase();
  if (inBook) {
    return (
      <Button size={size} variant="secondary" disabled className={clsx("!opacity-100", className)} aria-label="Already copying">
        <Check size={13} className="text-ok" aria-hidden="true" />
        {LABELS.copying}
      </Button>
    );
  }
  const full = book.atCap;
  return (
    <Button
      size={size}
      variant={variant}
      className={className}
      disabled={!book.ready || full || adding}
      title={full ? LABELS.copiesFull(MAX_LEADERS) : undefined}
      onClick={(e) => {
        e.stopPropagation();
        book.add(address);
      }}
    >
      {adding ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Plus size={13} aria-hidden="true" />}
      {full ? "Copies full" : adding ? "Adding…" : "Add to copies"}
    </Button>
  );
}

/** Sim freshness chip: "refreshed 12m ago · 280 ranked", live progress while a refresh runs, plus Refresh. */
export function RefreshBadge({ cohort, nowMs, asOfMs }: { cohort?: number; nowMs: number; asOfMs?: number }) {
  const status = useScoutStatus();
  const refresh = useScoutRefresh();
  const s = status.data;
  const running = s?.state === "running";
  const pct = s && s.total > 0 ? Math.round((s.done / s.total) * 100) : 0;
  const lastOk = s?.last_ok_ms ?? asOfMs ?? null;
  const stale = isStale(lastOk, s?.next_due_ms, nowMs);

  let text: ReactNode;
  let dot = "bg-ok";
  if (status.isError) {
    text = "refresh status unavailable";
    dot = "bg-faint";
  } else if (!s) {
    text = "checking…";
    dot = "bg-faint";
  } else if (running) {
    text = (
      <>
        refreshing {s.stage ?? ""} <span className="font-num">{pct}%</span>
        {s.eta_s ? <span className="text-muted"> · ~{Math.max(1, Math.round(s.eta_s / 60))}m left</span> : null}
      </>
    );
    dot = "bg-accent animate-pulse-live";
  } else if (s.state === "failed") {
    text = <span title={s.error ?? undefined}>last refresh failed</span>;
    dot = "bg-danger";
  } else {
    text = (
      <>
        refreshed {formatAgo(lastOk, nowMs)}
        {stale ? <span className="text-warn"> (stale)</span> : null}
      </>
    );
    if (stale) dot = "bg-warn";
  }

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="inline-flex min-h-8 items-center gap-2 rounded-sm border border-border bg-surface px-3 py-1 text-fg-soft shadow-e1" role="status">
        <span className={clsx("h-1.5 w-1.5 flex-shrink-0 rounded-full", dot)} aria-hidden="true" />
        <span>{text}</span>
        {cohort ? <span className="text-muted">· {cohort} ranked</span> : null}
        {running ? (
          <span className="h-1 w-16 overflow-hidden rounded-sm bg-surface-3" aria-hidden="true">
            <span className="block h-full bg-accent transition-[width] duration-[var(--dur-base)]" style={{ width: `${pct}%` }} />
          </span>
        ) : null}
      </span>
      {!status.isError ? (
        <Button
          size="sm"
          variant="ghost"
          disabled={running || refresh.isPending}
          onClick={() => refresh.mutate()}
          title={running ? "A refresh is already running" : "Start a full refresh now (about 40 to 60 minutes)"}
        >
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
        The api answered 404 or 503 for {what}: this build predates Scout, or discovery is not running. Pull and restart services/api and
        services/discovery to get <span className="font-num text-fg">/api/scout/*</span>. Meanwhile the demo board shows the page with sample
        data.
      </p>
    </Notice>
  );
}
