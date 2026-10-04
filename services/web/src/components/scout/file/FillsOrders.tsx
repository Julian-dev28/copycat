"use client";

import { clsx } from "clsx";
import { LoadError } from "@/components/PageStates";
import { Button } from "@/components/ui/Button";
import { CoinBadge } from "@/components/scout/bits";
import { formatPrice, formatSignedUsd, formatSize, formatUsd } from "@/lib/format";
import { useFileFills, useFileOrders } from "./hooks";
import { TD, TH } from "./PositionsTable";
import { when } from "./TripsTable";

function Head({ cols }: { cols: string[] }) {
  return (
    <thead>
      <tr className="border-b border-border">
        {cols.map((h) => (
          <th key={h} scope="col" className={TH}>
            {h}
          </th>
        ))}
      </tr>
    </thead>
  );
}

export function FillsTab({ address }: { address: string }) {
  const q = useFileFills(address, true);
  if (q.isError && !q.data) return <LoadError what="his fills" error={q.error} onRetry={() => q.refetch()} />;
  const fills = q.data?.pages.flat() ?? [];
  if (q.isPending) return <p className="p-4 text-sm text-muted">Loading fills…</p>;
  if (!fills.length) return <p className="p-4 text-sm text-muted">No fills cached for this trader.</p>;
  return (
    <div className="flex flex-col">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <Head cols={["Time", "Coin", "Dir", "Price", "Size", "Notional", "Closed PnL", "Fee"]} />
          <tbody>
            {fills.map((f, i) => (
              <tr key={`${f.time_ms}-${f.coin}-${i}`} className="border-b border-border/60 last:border-0">
                <td className={TD}>{when(f.time_ms)}</td>
                <td className="px-3 py-2">
                  <CoinBadge coin={f.coin} />
                </td>
                <td className={clsx(TD, "font-sans text-xs", f.side === "B" ? "text-success" : "text-danger")}>{f.dir}</td>
                <td className={TD}>{formatPrice(f.px)}</td>
                <td className={TD}>{formatSize(f.sz)}</td>
                <td className={TD}>{formatUsd(f.notional_usd, true)}</td>
                <td className={clsx(TD, f.closed_pnl_usd > 0 ? "text-success" : f.closed_pnl_usd < 0 ? "text-danger" : "text-muted")}>
                  {f.closed_pnl_usd ? formatSignedUsd(f.closed_pnl_usd) : "—"}
                </td>
                <td className={clsx(TD, "text-muted")}>{formatUsd(f.fee_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex justify-center p-3">
        {q.hasNextPage ? (
          <Button size="sm" onClick={() => q.fetchNextPage()} disabled={q.isFetchingNextPage}>
            {q.isFetchingNextPage ? "Loading…" : "Older fills"}
          </Button>
        ) : (
          <span className="text-xs text-muted">That is every cached fill.</span>
        )}
      </div>
    </div>
  );
}

export function OrdersTab({ address }: { address: string }) {
  const q = useFileOrders(address, true);
  if (q.isError) return <LoadError what="his open orders" error={q.error} onRetry={() => q.refetch()} />;
  if (!q.data) return <p className="p-4 text-sm text-muted">Loading open orders…</p>;
  if (!q.data.length) return <p className="p-4 text-sm text-muted">No open orders.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <Head cols={["Placed", "Coin", "Side", "Type", "Price", "Size", "Notional", "Flags"]} />
        <tbody>
          {q.data.map((o) => (
            <tr key={o.oid} className="border-b border-border/60 last:border-0">
              <td className={TD}>{when(o.time_ms)}</td>
              <td className="px-3 py-2">
                <CoinBadge coin={o.coin} />
              </td>
              <td className={clsx(TD, "font-sans text-xs uppercase", o.side === "buy" ? "text-success" : "text-danger")}>{o.side}</td>
              <td className={clsx(TD, "font-sans text-xs")}>{o.type}</td>
              <td className={TD}>{formatPrice(o.px)}</td>
              <td className={TD}>
                {formatSize(o.size)}
                {o.origSize > o.size ? <span className="text-[11px] text-muted"> / {formatSize(o.origSize)}</span> : null}
              </td>
              <td className={TD}>{formatUsd(o.notional, true)}</td>
              <td className={clsx(TD, "font-sans text-xs text-muted")}>
                {[o.reduceOnly ? "reduce only" : null, o.trigger].filter(Boolean).join(" · ") || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
