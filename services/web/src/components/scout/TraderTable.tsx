"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { ArrowDown, ArrowUp } from "lucide-react";
import { AddressChip } from "@/components/ui/AddressChip";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { Pnl } from "@/components/ui/Pnl";
import { TABLE, TableScroll } from "@/components/ui/Table";
import { CopyFitMeter } from "./CopyFitMeter";
import { Sparkline } from "./Sparkline";
import { AddToBookButton, CoinBadges, scoutHref, StyleTag } from "./bits";
import type { ScoutBook } from "@/hooks/useScout";
import { formatAgo, formatPct, formatUsd } from "@/lib/format";
import { LABELS } from "@/lib/labels";
import { coattailText, liquidationText } from "@/lib/scout/labels";
import type { SortKey, SortOrder } from "@/lib/scout/query";
import type { PnlWindow, TraderRow } from "@/lib/scout/types";
import { formatSignedUsdCompact, WINDOW_LABEL, windowPerf } from "@/lib/scout/window";

const ACCOUNT_VALUE_HINT =
  "Account value from Hyperliquid's leaderboard: includes unrealized PnL, main perps dex. " +
  "A wallet's HIP-3-only equity on another dex may not be included.";
const PNL_HINT = "Hyperliquid's own PnL for this window. Excludes deposits and withdrawals, so it reflects trading result, not transfers.";
const CAPACITY_HINT = "Share of their 30d opens the sim could actually execute at your settings and equity.";

/** Sortable columns and the order a first click asks for (what you'd want first). */
const COLS: { key: SortKey | null; label: string; first?: SortOrder; title?: string; align?: "left" | "right" }[] = [
  { key: null, label: "Trader", align: "left" },
  { key: "fit", label: "Copy Fit", first: "desc", align: "left" },
  { key: "sim_return", label: "If copied", first: "desc", title: "Sim return at your settings, 30d" },
  { key: "sim_dd", label: "Sim dip", first: "desc", title: "Largest dip of the simulated copy, 30d" },
  { key: null, label: "Capacity", align: "right", title: CAPACITY_HINT },
  { key: "pnl", label: "PnL", first: "desc", title: PNL_HINT },
  { key: "roi", label: "ROI", first: "desc", title: PNL_HINT },
  { key: "account_value", label: "Equity", first: "desc", title: ACCOUNT_VALUE_HINT },
  { key: "sharpe", label: "Sharpe", first: "desc", title: "30d" },
  { key: "max_dd", label: "Max DD", first: "asc", title: "Their 30d max drawdown" },
  { key: "win_rate", label: "Win %", first: "desc", title: "30d round trips" },
  { key: "trips", label: "Trips", first: "desc", title: "30d round trips" },
  { key: null, label: "Style", align: "left" },
  { key: null, label: "Top coins", align: "left" },
  { key: "last_active", label: "Active", first: "desc" },
  { key: null, label: "30d curve", align: "left" },
  { key: null, label: "" },
];

/** The first header cell sticks both ways (top and left), above the sticky first column. */
const STICKY_TH = TABLE.th.replace("z-[1]", "left-0 z-[3]");

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
    <Panel className="overflow-hidden">
      <TableScroll label="Trader board">
        <table className={clsx(TABLE.table, "min-w-[1200px]")}>
          <thead>
            <tr>
              {COLS.map((c, i) => {
                const active = c.key !== null && c.key === sort;
                const label = c.key === "pnl" || c.key === "roi" ? `${c.label} ${WINDOW_LABEL[window]}` : c.label;
                return (
                  <th
                    key={i}
                    scope="col"
                    aria-sort={active ? (order === "asc" ? "ascending" : "descending") : undefined}
                    className={i === 0 ? STICKY_TH : c.align === "left" ? TABLE.th : TABLE.thNum}
                    title={c.title}
                  >
                    {c.key ? (
                      <button
                        type="button"
                        onClick={() => onSort(c.key as SortKey, active ? (order === "desc" ? "asc" : "desc") : (c.first ?? "desc"))}
                        className={clsx("inline-flex items-center gap-1 uppercase transition-colors hover:text-fg", active && "text-fg")}
                      >
                        {label}
                        {active ? order === "desc" ? <ArrowDown size={11} aria-hidden="true" /> : <ArrowUp size={11} aria-hidden="true" /> : null}
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
              const href = scoutHref(`/scout/${row.address}`, demo);
              const liqText = liquidationText(s, nowMs);
              const coText = coattailText(s);
              const isVault = row.flags.some((f) => f.split(":")[0] === "vault");
              return (
                <tr key={row.address} className={clsx(TABLE.tr, inBook && "shadow-[inset_2px_0_0_var(--accent)]")}>
                  <td className={clsx(TABLE.td, TABLE.stickyFirst, "py-2")}>
                    <div className="flex items-center gap-3">
                      <span className="num-sm w-5 text-right text-muted">{i + 1}</span>
                      <div className="flex min-w-0 flex-col">
                        <Link href={href} className="max-w-[11rem] truncate font-medium text-fg hover:text-accent">
                          {row.display_name ?? "Open trader"}
                          <span className="sr-only"> {row.address}</span>
                        </Link>
                        <span className="flex flex-wrap items-center gap-1.5">
                          <AddressChip address={row.address} />
                          {inBook ? <Badge tone="accent">{LABELS.copying}</Badge> : null}
                          {isVault ? <Badge tone="warn" title="A vault: PnL is pooled across depositors, not yours alone">Vault</Badge> : null}
                        </span>
                        {liqText ? (
                          <span className="text-[11px] font-medium text-danger" title="The wallet's own real Hyperliquid liquidation, not the copy-sim's">
                            {liqText}
                          </span>
                        ) : null}
                        {coText ? (
                          <span
                            className="max-w-[11rem] truncate text-[11px] text-warn"
                            title={`${coText}. Heuristic, not certain: may share no real relationship.`}
                          >
                            {coText}
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </td>
                  <td className={clsx(TABLE.td, "w-44 min-w-44")}>
                    <CopyFitMeter fit={s.copy_fit} showParts={false} />
                  </td>
                  <td className={TABLE.tdNum}>
                    {s.sim_copies === 0 ? <span className="text-muted" title="No copy opened in the 30d sim">none</span> : <Pnl value={s.sim_return_pct} format="pct" />}
                  </td>
                  <td className={clsx(TABLE.tdNum, "text-muted")}>{formatPct(Math.abs(s.sim_max_drawdown_pct))}</td>
                  <td className={clsx(TABLE.tdNum, "text-muted")} title={s.sim_capacity_note ?? undefined}>
                    {s.sim_copy_capacity_pct === null || s.sim_copy_capacity_pct === undefined ? "—" : formatPct(s.sim_copy_capacity_pct, 0)}
                  </td>
                  <td className={TABLE.tdNum}>
                    <Pnl value={perf?.pnl_usd} format={formatSignedUsdCompact} />
                  </td>
                  <td className={TABLE.tdNum}>
                    <Pnl value={perf?.roi_pct} format="pct" />
                  </td>
                  <td className={clsx(TABLE.tdNum, "text-muted")}>{formatUsd(row.account_value_usd, true)}</td>
                  <td className={TABLE.tdNum}>{row.risk_30d.sharpe?.toFixed(2) ?? "—"}</td>
                  <td className={TABLE.tdNum}>{formatPct(Math.abs(row.risk_30d.max_drawdown_pct ?? Number.NaN))}</td>
                  <td className={TABLE.tdNum}>{formatPct(row.trades_30d.win_rate_pct, 0)}</td>
                  <td className={TABLE.tdNum}>{row.trades_30d.trips}</td>
                  <td className={TABLE.td}>
                    <StyleTag style={row.style} />
                  </td>
                  <td className={clsx(TABLE.td, "min-w-40")}>
                    <CoinBadges coins={row.top_coins} max={3} />
                  </td>
                  <td className={clsx(TABLE.tdNum, "text-muted")}>{formatAgo(row.last_fill_ms, nowMs)}</td>
                  <td className={TABLE.td}>
                    <Sparkline points={row.pnl_spark_30d} sim={row.sim_spark_30d} width={96} height={28} className="w-24" />
                  </td>
                  <td className={clsx(TABLE.td, "text-right")}>
                    <AddToBookButton address={row.address} book={book} inBook={inBook} variant="secondary" />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </TableScroll>
    </Panel>
  );
}
