"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { useModeStatus } from "@/components/copy/hooks";
import { CoinBadge } from "@/components/scout/bits";
import { TD, TH } from "@/components/scout/file/PositionsTable";
import { AddressChip } from "@/components/ui/AddressChip";
import { TableScroll } from "@/components/ui/Table";
import { isEngineAccount, mergeAccountPositions } from "@/lib/account/positions";
import type { TradingAccount } from "@/lib/account/types";
import { formatPct, formatPrice, formatSignedPct, formatSignedUsd, formatSize, formatUsd } from "@/lib/format";
import { liqTone } from "@/lib/scout/labels";
import type { TraderPositionView } from "@/lib/scout/types";

const LIQ_TEXT = { ok: "text-success", warn: "text-warning", danger: "text-danger", none: "text-muted" } as const;

/** Positions tab: the account's own positions plus copycat's copies, with where each came from. */
export function AccountPositions({ account, own, asOfMs, demo }: { account: TradingAccount; own: TraderPositionView[]; asOfMs: number; demo: boolean }) {
  const status = useModeStatus().data;
  const engine = isEngineAccount(account.address, status?.our_address, demo, Boolean(account.active));
  const rows = mergeAccountPositions(own, status?.positions ?? [], engine);
  if (!rows.length) return <p className="p-4 text-sm text-muted">No open positions.</p>;
  return (
    <div className="flex flex-col">
      <TableScroll label="Positions">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              {["Source", "Coin", "Lev", "Size", "Notional", "Entry", "Mark", "uPnL (ROE)", "Liq px", "To liq", "Margin"].map((h) => (
                <th key={h} scope="col" className={TH}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.coin} className="border-b border-border/60 last:border-0">
                <td className="px-3 py-2 text-xs whitespace-nowrap">
                  {p.source === "copycat" && p.leader ? (
                    <Link href={`/?w=${p.leader}${demo ? "&demo=1" : ""}`} className="inline-flex items-center gap-1 text-accent hover:underline" title="Open this trader on Trade">
                      copycat → <AddressChip address={p.leader} />
                    </Link>
                  ) : (
                    <span className="text-muted">Manual</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <span className="flex items-center gap-1.5">
                    <CoinBadge coin={p.coin} />
                    <span className="text-[11px] font-semibold text-muted uppercase">{p.side}</span>
                  </span>
                </td>
                <td className={TD}>
                  {p.leverage}x <span className="text-[11px] text-muted">{p.is_cross ? "cross" : "iso"}</span>
                </td>
                <td className={TD}>{formatSize(p.size)}</td>
                <td className={TD}>{formatUsd(p.notional_usd, true)}</td>
                <td className={TD}>{formatPrice(p.entry_px)}</td>
                <td className={TD}>{formatPrice(p.mark_px)}</td>
                <td className={clsx(TD, p.unrealized_pnl_usd >= 0 ? "text-up" : "text-down")}>
                  {formatSignedUsd(p.unrealized_pnl_usd)} <span className="text-[11px]">({formatSignedPct(p.roe_pct)})</span>
                </td>
                <td className={TD}>{p.liquidation_px ? formatPrice(p.liquidation_px) : "n/a"}</td>
                <td className={clsx(TD, "font-semibold", LIQ_TEXT[liqTone(p.liq_distance_pct)])}>{formatPct(p.liq_distance_pct)}</td>
                <td className={TD}>{formatUsd(p.margin_usd, true)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </TableScroll>
      <p className="px-3 py-2 text-[11px] text-muted">
        As of {new Date(asOfMs).toLocaleTimeString("en-US", { hour12: false })}. copycat rows come from the engine&apos;s copies; Manual is everything else on this account.
      </p>
    </div>
  );
}
