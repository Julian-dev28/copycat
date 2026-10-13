"use client";

import Link from "next/link";
import { FileText } from "lucide-react";
import { AddressChip } from "@/components/ui/AddressChip";
import { StyleTag } from "@/components/scout/bits";
import { formatAgo, formatUsd, shortenAddress } from "@/lib/format";
import { formatIndex, rowQuote } from "@/lib/trade/equityIndex";
import type { TraderRow } from "@/lib/scout/types";
import { CatAvatar } from "./CatAvatar";
import { FitPill } from "./MarketRow";
import { ChangeText, Stat } from "./bits";

export function WalletHeader({ address, row, nowMs, fileHref, inBook, onScout = true }: { address: string; row: TraderRow | null; nowMs: number; fileHref: string; inBook: boolean; onScout?: boolean }) {
  const q = row ? rowQuote(row) : null;
  return (
    <div id="wallet-header" className="flex scroll-mt-20 flex-col gap-3">
      <div className="flex min-w-0 items-center gap-3">
        <CatAvatar address={address} size={40} />
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h1 className="truncate text-lg font-bold tracking-tight">{row?.display_name ?? shortenAddress(address)}</h1>
            {inBook ? <span className="rounded-sm bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent">Copying</span> : null}
            {!onScout ? <span className="rounded-sm bg-surface-2 px-2 py-0.5 text-[11px] font-medium text-muted" title="Opened from a pasted address">Not on Scout</span> : null}
          </div>
          <AddressChip address={address} />
        </div>
      </div>
      <div className="flex flex-wrap items-end gap-x-5 gap-y-2">
        <Stat label="Index">
          <span className="font-num text-base font-semibold">{formatIndex(q?.price)}</span>
        </Stat>
        <Stat label="24h">
          <ChangeText pct={q?.change24hPct} />
        </Stat>
        <Stat label="7d">
          <ChangeText pct={q?.change7dPct} />
        </Stat>
        <Stat label="Copy Fit">
          <FitPill value={row?.score.copy_fit?.value} />
        </Stat>
        <Stat label="Style">
          <StyleTag style={row?.style} />
        </Stat>
        <Stat label="Equity">
          <span className="font-num">{formatUsd(row?.account_value_usd, true)}</span>
        </Stat>
        <Stat label="Last trade">
          <span className="font-num text-muted">{formatAgo(row?.last_fill_ms, nowMs)}</span>
        </Stat>
        <Link href={fileHref} className="inline-flex items-center gap-1 self-center text-xs font-medium text-accent hover:underline">
          <FileText size={13} aria-hidden="true" /> Trader file
        </Link>
      </div>
    </div>
  );
}
