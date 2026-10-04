"use client";

import { useState } from "react";
import Link from "next/link";
import { clsx } from "clsx";
import { Search, Telescope } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { Input } from "@/components/ui/Input";
import { buildMarkets, type MarketTab } from "@/lib/trade/markets";
import type { TraderRow } from "@/lib/scout/types";
import { MarketRow } from "./MarketRow";

const TABS: { id: MarketTab; label: string }[] = [
  { id: "mine", label: "My wallets" },
  { id: "top", label: "Top" },
  { id: "all", label: "All" },
];
const PAGE = 60;

export function MarketsPanel({
  rows,
  leaders,
  selected,
  onSelect,
  loading,
  error,
  scoutHref,
}: {
  rows: TraderRow[];
  leaders: string[];
  selected: string | null;
  onSelect: (address: string) => void;
  loading: boolean;
  error: string | null;
  scoutHref: string;
}) {
  const [tabChoice, setTab] = useState<MarketTab | null>(null);
  const [q, setQ] = useState("");
  const [change, setChange] = useState<"24h" | "7d">("24h");
  const [limit, setLimit] = useState(PAGE);
  const tab = tabChoice ?? (leaders.length ? "mine" : "top");
  const items = buildMarkets(rows, leaders, tab, q);
  const shown = items.slice(0, limit);

  return (
    <Panel className="flex min-h-0 flex-col overflow-hidden xl:h-full">
      <div className="flex flex-col gap-2 border-b border-border p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Markets</h2>
          <span className="text-[11px] text-muted">every wallet is a market</span>
        </div>
        <Input
          leading={<Search size={13} aria-hidden="true" />}
          placeholder="Name or 0x address"
          aria-label="Search wallets"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <div role="tablist" aria-label="Wallet lists" className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => {
                setTab(t.id);
                setLimit(PAGE);
              }}
              className={clsx(
                "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                tab === t.id ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2 hover:text-foreground",
              )}
            >
              {t.label}
              {t.id === "mine" && leaders.length ? <span className="font-num ml-1 text-[10px]">{leaders.length}</span> : null}
            </button>
          ))}
        </div>
      </div>

      <div className="max-h-[22rem] min-h-0 flex-1 overflow-y-auto md:max-h-[34rem] xl:max-h-none">
        <div className="sticky top-0 z-10 grid grid-cols-[minmax(0,1fr)_4rem_3.75rem_2.25rem] gap-2 border-b border-border bg-surface px-3 py-1.5 text-[10px] font-medium uppercase tracking-wide text-muted">
          <span>Wallet</span>
          <span className="text-right" title="Equity index: 100 thirty days ago, deposits and withdrawals removed">Index</span>
          <button
            type="button"
            className="text-right uppercase hover:text-foreground"
            onClick={() => setChange(change === "24h" ? "7d" : "24h")}
            title="Switch between 24h and 7d change"
          >
            {change} ⇄
          </button>
          <span className="text-right" title="Copy Fit, 0-100">Fit</span>
        </div>
        {error ? <p className="p-3 text-xs text-danger">{error}</p> : null}
        {loading && !rows.length ? (
          <ul aria-busy="true" aria-label="Loading wallets">
            {Array.from({ length: 8 }, (_, i) => (
              <li key={i} className="mx-3 my-2 h-8 animate-pulse rounded-md bg-surface-2" />
            ))}
          </ul>
        ) : null}
        {!loading && !items.length ? (
          <div className="flex flex-col items-center gap-2 p-5 text-center text-xs text-muted">
            {tab === "mine" && !q ? "You're not copying anyone yet. Pick a wallet from Top." : "No wallet matches."}
            <Link href={scoutHref} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
              <Telescope size={12} aria-hidden="true" /> Find one in Scout
            </Link>
          </div>
        ) : null}
        <ul aria-label={`${TABS.find((t) => t.id === tab)?.label} list`}>
          {shown.map((m) => (
            <MarketRow key={m.address} m={m} selected={m.address === selected} change={change} onSelect={onSelect} />
          ))}
        </ul>
        {items.length > shown.length ? (
          <button type="button" onClick={() => setLimit(limit + PAGE)} className="w-full py-2 text-xs font-medium text-accent hover:underline">
            Show {Math.min(PAGE, items.length - shown.length)} more of {items.length - shown.length}
          </button>
        ) : null}
      </div>
    </Panel>
  );
}
