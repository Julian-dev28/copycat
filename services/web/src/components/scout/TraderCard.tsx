"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { BookMarked } from "lucide-react";
import { AddressChip } from "@/components/ui/AddressChip";
import { CopyFitMeter } from "./CopyFitMeter";
import { SparkLegend, Sparkline } from "./Sparkline";
import { AddToBookButton, CoinBadges, scoutHref, StyleTag } from "./bits";
import type { ScoutBook } from "@/hooks/useScout";
import { formatAgo, formatSignedPct, formatUsd } from "@/lib/format";
import { FLAG_TEXT } from "@/lib/scout/labels";
import type { PnlUnit } from "@/lib/scout/query";
import type { PnlWindow, TraderRow } from "@/lib/scout/types";
import { pnlFigure, WINDOW_LABEL } from "@/lib/scout/window";

export const TONE_TEXT = { up: "text-success", down: "text-danger", flat: "text-muted" } as const;

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
  const pnl = pnlFigure(row, window, unit);
  const inBook = row.in_book || book.inBook(row.address);
  const href = scoutHref(`/scout/${row.address}`, demo);
  const s = row.score;
  const flags = row.flags.filter((f) => f !== "fills_truncated");

  return (
    <article
      className={clsx(
        "group/card relative flex flex-col gap-3 rounded-xl border bg-surface p-4 transition-colors hover:border-accent/50",
        inBook ? "border-accent/40" : "border-border",
      )}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="font-num mt-0.5 w-6 flex-shrink-0 text-right text-xs text-muted">{rank}</span>
          {/* fixed height whether or not he has a display name, so every card's rows line up across the grid */}
          <div className="flex min-h-10 min-w-0 flex-col justify-center">
            {row.display_name ? <div className="truncate text-sm font-semibold text-foreground">{row.display_name}</div> : null}
            <AddressChip address={row.address} strong={!row.display_name} className="relative z-10" />
          </div>
        </div>
        {inBook ? (
          <span className="inline-flex flex-shrink-0 items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent">
            <BookMarked size={11} aria-hidden="true" />
            Copying
          </span>
        ) : null}
      </header>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 pl-8 text-xs text-muted">
        <StyleTag style={row.style} />
        <span title="Size tier by account value">{row.size_tier}</span>
        <span aria-hidden="true">·</span>
        <span>active {formatAgo(row.last_fill_ms, nowMs)}</span>
      </div>

      <div className="pl-8">
        <CoinBadges coins={row.top_coins} />
      </div>

      <dl className="grid grid-cols-2 gap-3">
        <div>
          <dt className="text-[11px] text-muted">PnL {WINDOW_LABEL[window]}</dt>
          <dd className={clsx("font-num text-lg font-semibold leading-tight", TONE_TEXT[pnl.tone])}>{pnl.text}</dd>
        </div>
        <div className="text-right">
          <dt className="text-[11px] text-muted">Equity</dt>
          <dd className="font-num text-lg font-semibold leading-tight text-foreground">{formatUsd(row.account_value_usd, true)}</dd>
        </div>
      </dl>

      <div className="flex flex-col gap-1">
        <Sparkline points={row.pnl_spark_30d} sim={row.sim_spark_30d} className="w-full" height={44} />
        <SparkLegend hasSim={row.sim_spark_30d.length >= 2} />
      </div>

      <CopyFitMeter fit={s.copy_fit} className="relative z-10" />

      <Link
        href={href}
        className="text-xs font-medium text-muted after:absolute after:inset-0 after:rounded-xl after:content-[''] hover:text-accent"
      >
        Open trader file →
      </Link>

      <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
        <div className="min-w-0 text-xs leading-tight">
          <div className="text-muted">If you copied (30d)</div>
          <div className="font-num">
            <span className={clsx("font-semibold", s.sim_return_pct >= 0 ? "text-up" : "text-down")}>
              {formatSignedPct(s.sim_return_pct)}
            </span>
            <span className="text-muted"> · DD {formatSignedPct(s.sim_max_drawdown_pct)}</span>
          </div>
          {flags.length ? (
            <div className="mt-1 truncate text-[11px] text-warning" title={flags.map((f) => FLAG_TEXT[f] ?? f).join("; ")}>
              {FLAG_TEXT[flags[0]] ?? flags[0]}
              {flags.length > 1 ? ` +${flags.length - 1}` : ""}
            </div>
          ) : null}
        </div>
        <AddToBookButton address={row.address} book={book} inBook={inBook} className="relative z-10" />
      </div>
    </article>
  );
}
