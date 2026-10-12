"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { ArrowRight } from "lucide-react";
import { AddressChip } from "@/components/ui/AddressChip";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { Pnl } from "@/components/ui/Pnl";
import { CopyFitMeter } from "./CopyFitMeter";
import { SparkLegend, Sparkline } from "./Sparkline";
import { AddToBookButton, CoinBadges, scoutHref, StyleTag } from "./bits";
import type { ScoutBook } from "@/hooks/useScout";
import { formatAgo, formatPct, formatUsd } from "@/lib/format";
import { LABELS } from "@/lib/labels";
import { flagText, SIZE_TIER_HINT, visibleFlags } from "@/lib/scout/labels";
import type { PnlUnit } from "@/lib/scout/query";
import type { PnlWindow, TraderRow, TraderScore } from "@/lib/scout/types";
import { formatSignedUsdCompact, WINDOW_LABEL, windowPerf } from "@/lib/scout/window";

/** The window PnL as <Pnl>: $ (compact) or ROI %, sign + color from the user's PnL mode. */
export function WindowPnl({ row, window, unit, arrow, className }: { row: TraderRow; window: PnlWindow; unit: PnlUnit; arrow?: boolean; className?: string }) {
  const p = windowPerf(row, window);
  return unit === "pct" ? (
    <Pnl value={p?.roi_pct} format="pct" arrow={arrow} className={className} />
  ) : (
    <Pnl value={p?.pnl_usd} format={formatSignedUsdCompact} arrow={arrow} className={className} />
  );
}

/** "If you copied" line: the sim return plus its dip, or why the sim shows nothing. */
export function IfCopied({ s, className }: { s: TraderScore; className?: string }) {
  if (s.sim_copies === 0) {
    return (
      <span className={clsx("text-xs text-muted", className)} title="The sim replays the last 30 days at your settings; this trader opened nothing it could copy.">
        No copy opened in the 30d sim
      </span>
    );
  }
  return (
    <span className={clsx("inline-flex items-baseline gap-2 text-xs", className)}>
      <Pnl value={s.sim_return_pct} format="pct" className="num font-medium" />
      <span className="num-sm text-muted" title="Largest peak-to-trough dip of the simulated copy">
        max dip {formatPct(Math.abs(s.sim_max_drawdown_pct))}
      </span>
    </span>
  );
}

export function TraderCard({
  row,
  rank,
  window,
  unit,
  book,
  demo,
  nowMs,
}: {
  row: TraderRow;
  rank: number;
  window: PnlWindow;
  unit: PnlUnit;
  book: ScoutBook;
  demo: boolean;
  nowMs: number;
}) {
  const inBook = row.in_book || book.inBook(row.address);
  const href = scoutHref(`/scout/${row.address}`, demo);
  const s = row.score;
  const flags = visibleFlags(row.flags);

  return (
    <Panel interactive className={clsx("group/card relative flex flex-col gap-4 p-4 sm:p-5", inBook && "border-accent/40")}>
      <header className="flex items-start gap-3">
        <span className="num-sm mt-1 w-5 flex-shrink-0 text-right text-muted">{rank}</span>
        {/* fixed height whether or not they have a display name, so rows line up across the grid */}
        <div className="flex min-h-10 min-w-0 flex-1 flex-col justify-center">
          {row.display_name ? <div className="truncate text-heading text-fg">{row.display_name}</div> : null}
          <AddressChip address={row.address} strong={!row.display_name} className="relative z-10" />
        </div>
        {inBook ? (
          <Badge tone="accent" dot className="flex-shrink-0">
            {LABELS.copying}
          </Badge>
        ) : null}
      </header>

      <div className="flex flex-wrap items-center gap-1.5 pl-8">
        <StyleTag style={row.style} />
        <Badge title={SIZE_TIER_HINT[row.size_tier]}>{row.size_tier}</Badge>
        <span className="text-xs text-muted">active {formatAgo(row.last_fill_ms, nowMs)}</span>
      </div>

      <dl className="grid grid-cols-2 gap-3">
        <div className="min-w-0">
          <dt className="text-label text-muted">PnL {WINDOW_LABEL[window]}</dt>
          <dd className="mt-1">
            <WindowPnl row={row} window={window} unit={unit} arrow className="num-lg" />
          </dd>
        </div>
        <div className="min-w-0 text-right">
          <dt className="text-label text-muted">Equity</dt>
          <dd className="num-lg mt-1 text-fg">{formatUsd(row.account_value_usd, true)}</dd>
        </div>
      </dl>

      <div className="flex flex-col gap-1.5">
        <Sparkline points={row.pnl_spark_30d} sim={row.sim_spark_30d} className="w-full" height={48} />
        <SparkLegend hasSim={row.sim_spark_30d.length >= 2} />
      </div>

      <CopyFitMeter fit={s.copy_fit} className="relative z-10" />

      <CoinBadges coins={row.top_coins} />

      <div className="mt-auto flex items-end justify-between gap-3 border-t border-border pt-3">
        <div className="min-w-0 leading-tight">
          <div className="text-label text-muted">If you copied, 30d</div>
          <IfCopied s={s} className="mt-1" />
          {flags.length ? (
            <div className="mt-1.5 truncate text-[11px] text-warn" title={flags.map(flagText).join("; ")}>
              {flagText(flags[0])}
              {flags.length > 1 ? ` +${flags.length - 1}` : ""}
            </div>
          ) : null}
        </div>
        <AddToBookButton address={row.address} book={book} inBook={inBook} variant="secondary" className="relative z-10 flex-shrink-0" />
      </div>

      <Link
        href={href}
        className="inline-flex w-fit items-center gap-1 text-xs font-medium text-muted transition-colors after:absolute after:inset-0 after:rounded-xl after:content-[''] hover:text-fg"
      >
        Open trader
        <ArrowRight size={12} className="transition-transform duration-[var(--dur-fast)] group-hover/card:translate-x-0.5" aria-hidden="true" />
      </Link>
    </Panel>
  );
}
