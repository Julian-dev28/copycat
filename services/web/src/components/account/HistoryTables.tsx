"use client";

import { clsx } from "clsx";
import { ArrowDownLeft, ArrowLeftRight, ArrowUpRight } from "lucide-react";
import type { ReactNode } from "react";
import { CoinBadge } from "@/components/scout/bits";
import { TD, TH } from "@/components/scout/file/PositionsTable";
import { when } from "@/components/scout/file/TripsTable";
import { accountErrorText } from "@/lib/account/errors";
import { normalizeBalances, normalizeFills, normalizeOrderRows, normalizeTransfers, orderStatusLabel, transferLabel } from "@/lib/account/history";
import type { HistoryKind, TradingAccount } from "@/lib/account/types";
import { formatNumber, formatPrice, formatSignedUsd, formatSize, formatUsd, shortenAddress } from "@/lib/format";
import { useAccountHistory } from "./hooks";

function Table({ cols, children }: { cols: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            {cols.map((c) => <th key={c} scope="col" className={TH}>{c}</th>)}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

const ROW = "border-b border-border/60 last:border-0";
const Empty = ({ children }: { children: ReactNode }) => <p className="p-4 text-sm text-muted">{children}</p>;

/** Loads one history kind and hands the raw rows to `render`; owns loading/error/too-old. */
function History({ account, kind, render }: { account: TradingAccount; kind: HistoryKind; render: (raw: unknown) => ReactNode }) {
  const q = useAccountHistory(account.id, kind, true);
  if (q.isError) return <p role="alert" className="p-4 text-sm text-danger">{accountErrorText(q.error, `account ${kind} history`)}</p>;
  if (q.isPending) return <Empty>Loading {kind}…</Empty>;
  return <>{render(q.data)}</>;
}

export function FillsHistory({ account }: { account: TradingAccount }) {
  return (
    <History account={account} kind="fills" render={(raw) => {
      const fills = normalizeFills(raw);
      if (!fills.length) return <Empty>No fills yet.</Empty>;
      return (
        <Table cols={["Time", "Coin", "Dir", "Price", "Size", "Notional", "Closed PnL", "Fee"]}>
          {fills.map((f, i) => (
            <tr key={`${f.time_ms}-${i}`} className={ROW}>
              <td className={TD}>{when(f.time_ms)}</td>
              <td className="px-3 py-2"><CoinBadge coin={f.coin} /></td>
              <td className={clsx(TD, "font-sans text-xs", f.side === "B" ? "text-success" : "text-danger")}>{f.dir}</td>
              <td className={TD}>{formatPrice(f.px)}</td>
              <td className={TD}>{formatSize(f.sz)}</td>
              <td className={TD}>{formatUsd(f.notional_usd, true)}</td>
              <td className={clsx(TD, f.closed_pnl_usd > 0 ? "text-up" : f.closed_pnl_usd < 0 ? "text-down" : "text-muted")}>{f.closed_pnl_usd ? formatSignedUsd(f.closed_pnl_usd) : "—"}</td>
              <td className={clsx(TD, "text-muted")}>{formatUsd(f.fee_usd)}</td>
            </tr>
          ))}
        </Table>
      );
    }} />
  );
}

export function OrdersHistory({ account }: { account: TradingAccount }) {
  return (
    <History account={account} kind="orders" render={(raw) => {
      const orders = normalizeOrderRows(raw);
      if (!orders.length) return <Empty>No orders in the last 30 days.</Empty>;
      return (
        <Table cols={["Placed", "Coin", "Side", "Type", "Price", "Size", "Notional", "Status", "Flags"]}>
          {orders.map((o) => (
            <tr key={o.oid} className={ROW}>
              <td className={TD}>{when(o.time_ms)}</td>
              <td className="px-3 py-2"><CoinBadge coin={o.coin} /></td>
              <td className={clsx(TD, "font-sans text-xs uppercase", o.side === "buy" ? "text-success" : "text-danger")}>{o.side}</td>
              <td className={clsx(TD, "font-sans text-xs")}>{o.type}</td>
              <td className={TD}>{formatPrice(o.px)}</td>
              <td className={TD}>{formatSize(o.origSize || o.size)}</td>
              <td className={TD}>{formatUsd(o.notional, true)}</td>
              <td className={clsx(TD, "font-sans text-xs", o.status === "filled" ? "text-success" : o.status === "open" ? "text-foreground" : "text-muted")}>{orderStatusLabel(o.status)}</td>
              <td className={clsx(TD, "font-sans text-xs text-muted")}>{[o.reduceOnly ? "reduce only" : null, o.trigger].filter(Boolean).join(" · ") || "—"}</td>
            </tr>
          ))}
        </Table>
      );
    }} />
  );
}

const DIR_ICON = { in: ArrowDownLeft, out: ArrowUpRight, internal: ArrowLeftRight } as const;

export function TransfersHistory({ account }: { account: TradingAccount }) {
  return (
    <History account={account} kind="transfers" render={(raw) => {
      const rows = normalizeTransfers(raw, account.address);
      if (!rows.length) return <Empty>No deposits, withdrawals or transfers yet.</Empty>;
      return (
        <Table cols={["Time", "Type", "Amount", "Counterparty"]}>
          {rows.map((t, i) => {
            const Icon = DIR_ICON[t.direction];
            return (
              <tr key={`${t.time_ms}-${i}`} className={ROW}>
                <td className={TD}>{when(t.time_ms)}</td>
                <td className="px-3 py-2 text-xs whitespace-nowrap">
                  <span className="inline-flex items-center gap-1.5">
                    <Icon size={13} className={t.direction === "in" ? "text-success" : t.direction === "out" ? "text-danger" : "text-muted"} aria-hidden="true" />
                    {transferLabel(t.type)}
                  </span>
                </td>
                <td className={clsx(TD, t.direction === "in" ? "text-success" : t.direction === "out" ? "text-danger" : "")}>
                  {t.direction === "in" ? "+" : t.direction === "out" ? "-" : ""}{formatUsd(t.amount_usd)}
                </td>
                <td className={clsx(TD, "text-muted")} title={t.counterparty ?? undefined}>{t.counterparty ? shortenAddress(t.counterparty) : "—"}</td>
              </tr>
            );
          })}
        </Table>
      );
    }} />
  );
}

export function BalancesHistory({ account }: { account: TradingAccount }) {
  return (
    <History account={account} kind="balances" render={(raw) => {
      const rows = normalizeBalances(raw);
      if (!rows.length) return <Empty>No spot balances.</Empty>;
      return (
        <Table cols={["Coin", "Total", "In orders", "Available", "USD value"]}>
          {rows.map((b) => (
            <tr key={b.coin} className={ROW}>
              <td className="px-3 py-2"><CoinBadge coin={b.coin} /></td>
              <td className={TD}>{formatNumber(b.total)}</td>
              <td className={clsx(TD, "text-muted")}>{b.hold ? formatNumber(b.hold) : "—"}</td>
              <td className={TD}>{formatNumber(b.total - b.hold)}</td>
              <td className={TD}>{b.usd_value === null ? "—" : formatUsd(b.usd_value)}</td>
            </tr>
          ))}
        </Table>
      );
    }} />
  );
}
