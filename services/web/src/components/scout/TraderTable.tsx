"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { ArrowDown, ArrowUp, BookMarked } from "lucide-react";
import { AddressChip } from "@/components/ui/AddressChip";
import { CopyFitMeter } from "./CopyFitMeter";
import { Sparkline } from "./Sparkline";
import { TONE_TEXT } from "./TraderCard";
import { AddToBookButton, CoinBadges, scoutHref, StyleTag } from "./bits";
import type { ScoutBook } from "@/hooks/useScout";
import { formatAgo, formatPct, formatSignedPct } from "@/lib/format";
import type { SortKey, SortOrder } from "@/lib/scout/query";
import type { PnlWindow, TraderRow } from "@/lib/scout/types";
import { formatSignedUsdCompact, toneOf, WINDOW_LABEL, windowPerf } from "@/lib/scout/window";

/** Sortable columns and the order a first click asks for (what you'd want first). */
const COLS: { key: SortKey | null; label: string; first?: SortOrder; title?: string; align?: "left" | "right" }[] = [
  { key: null, label: "#", align: "right" },
  { key: null, label: "Trader", align: "left" },
  { key: "fit", label: "Copy Fit", first: "desc", align: "left" },
  { key: "sim_return", label: "If copied", first: "desc", title: "Sim return at your settings, 30d" },
  { key: "sim_dd", label: "Sim DD", first: "desc", title: "Sim max drawdown, 30d (closer to 0 is better)" },
  { key: "pnl", label: "PnL", first: "desc" },
  { key: "roi", label: "ROI", first: "desc" },
  { key: "sharpe", label: "Sharpe", first: "desc", title: "30d" },
  { key: "max_dd", label: "Max DD", first: "asc", title: "His 30d max drawdown" },
  { key: "win_rate", label: "Win %", first: "desc", title: "30d round trips" },
  { key: "trips", label: "Trips", first: "desc", title: "30d round trips" },
  { key: null, label: "Style", align: "left" },
  { key: null, label: "Top coins", align: "left" },
  { key: "last_active", label: "Active", first: "desc" },
  { key: null, label: "30d curve", align: "left" },
  { key: null, label: "" },
];

export function TraderTable({
  rows,
  window,
  sort,
  order,
  onSort,
  book,
  demo,
  nowMs,
}: {
  rows: TraderRow[];
  window: PnlWindow;
  sort: SortKey;
  order: SortOrder;
  onSort: (sort: SortKey, order: SortOrder) => void;
  book: ScoutBook;
  demo: boolean;
  nowMs: number;
}) {
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface">
      <table className="w-full min-w-[1180px] border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-xs text-muted">
            {COLS.map((c, i) => {
              const active = c.key !== null && c.key === sort;
              const label = c.key === "pnl" || c.key === "roi" ? `${c.label} ${WINDOW_LABEL[window]}` : c.label;
              return (
                <th
                  key={i}
                  scope="col"
                  aria-sort={active ? (order === "asc" ? "ascending" : "descending") : undefined}
                  className={clsx("whitespace-nowrap px-3 py-2.5 font-medium", c.align === "left" ? "text-left" : "text-right")}
                  title={c.title}
                >
                  {c.key ? (
                    <button
                      type="button"
                      onClick={() => onSort(c.key as SortKey, active ? (order === "desc" ? "asc" : "desc") : (c.first ?? "desc"))}
                      className={clsx("inline-flex items-center gap-1 hover:text-foreground", active && "text-foreground")}
                    >
                      {label}
                      {active ? order === "desc" ? <ArrowDown size={12} aria-hidden="true" /> : <ArrowUp size={12} aria-hidden="true" /> : null}
                    </button>
                  ) : (
                    label
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const perf = windowPerf(row, window);
            const inBook = row.in_book || book.inBook(row.address);
            const s = row.score;
            return (
              <tr key={row.address} className="border-b border-border/70 last:border-b-0 hover:bg-surface-2/50">
                <td className="font-num px-3 py-2.5 text-right text-xs text-muted">{i + 1}</td>
                <td className="px-3 py-2.5">
                  <div className="flex items-center gap-1.5">
                    <Link href={scoutHref(`/scout/${row.address}`, demo)} className="max-w-[9rem] truncate font-medium hover:text-accent">
                      {row.display_name ?? "Trader file"}
                    </Link>
                    {inBook ? <BookMarked size={12} className="text-accent" aria-label="In your book" /> : null}
                  </div>
                  <AddressChip address={row.address} />
                </td>
                <td className="w-40 px-3 py-2.5">
                  <CopyFitMeter fit={s.copy_fit} />
                </td>
                <td className={clsx("font-num px-3 py-2.5 text-right font-medium", TONE_TEXT[toneOf(s.sim_return_pct)])}>
                  {formatSignedPct(s.sim_return_pct)}
                </td>
                <td className="font-num px-3 py-2.5 text-right text-muted">{formatSignedPct(s.sim_max_drawdown_pct)}</td>
                <td className={clsx("font-num px-3 py-2.5 text-right", TONE_TEXT[toneOf(perf?.pnl_usd)])}>{formatSignedUsdCompact(perf?.pnl_usd)}</td>
                <td className={clsx("font-num px-3 py-2.5 text-right", TONE_TEXT[toneOf(perf?.roi_pct)])}>{formatSignedPct(perf?.roi_pct)}</td>
                <td className="font-num px-3 py-2.5 text-right">{row.risk_30d.sharpe?.toFixed(2) ?? "—"}</td>
                <td className="font-num px-3 py-2.5 text-right">{formatPct(row.risk_30d.max_drawdown_pct)}</td>
                <td className="font-num px-3 py-2.5 text-right">{formatPct(row.trades_30d.win_rate_pct, 0)}</td>
                <td className="font-num px-3 py-2.5 text-right">{row.trades_30d.trips}</td>
                <td className="px-3 py-2.5">
                  <StyleTag style={row.style} />
                </td>
                <td className="px-3 py-2.5">
                  <CoinBadges coins={row.top_coins} max={3} />
                </td>
                <td className="font-num whitespace-nowrap px-3 py-2.5 text-right text-xs text-muted">{formatAgo(row.last_fill_ms, nowMs)}</td>
                <td className="px-3 py-2.5">
                  <Sparkline points={row.pnl_spark_30d} width={96} height={28} className="w-24" />
                </td>
                <td className="px-3 py-2.5 text-right">
                  <AddToBookButton address={row.address} book={book} inBook={inBook} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
