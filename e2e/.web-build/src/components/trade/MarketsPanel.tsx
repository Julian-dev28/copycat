"use client";

import { useState } from "react";
import Link from "next/link";
import { Search, Telescope } from "lucide-react";
import { EmptyState, Input, Panel, SegmentedControl, Skeleton, Tabs } from "@/components/ui";
import { buildMarkets, type MarketTab } from "@/lib/trade/markets";
import { extractAddress } from "@/lib/trade/pasteAddress";
import type { TraderRow } from "@/lib/scout/types";
import { MarketRow } from "./MarketRow";

const TABS: { id: MarketTab; label: string }[] = [
  { id: "mine", label: "My copies" },
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
          <h2 className="text-heading text-fg">Markets</h2>
          <span className="text-xs text-muted">every trader is a market</span>
        </div>
        <Input
          leading={<Search size={13} aria-hidden="true" />}
          placeholder="Name, or paste any 0x address"
          aria-label="Search traders"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onPaste={(e) => {
            // A pasted address (or explorer link) opens that wallet right away, on Scout or not.
            const a = extractAddress(e.clipboardData.getData("text"));
            if (!a) return;
            e.preventDefault();
            setQ(a);
            onSelect(a);
          }}
          onKeyDown={(e) => {
            const a = e.key === "Enter" ? extractAddress(q) : null;
            if (a) onSelect(a);
          }}
        />
        <Tabs
          aria-label="Trader lists"
          idBase="markets"
          value={tab}
          onChange={(id) => {
            setTab(id);
            setLimit(PAGE);
          }}
          items={TABS.map((t) => ({ id: t.id, label: t.label, count: t.id === "mine" && leaders.length ? leaders.length : undefined }))}
        />
      </div>

      {/* Each tab's `aria-controls` names this element (`${base}-panel-${id}`, see
          ui/Tabs.tsx): without it the id has nothing to point to and axe flags
          every tab button (aria-valid-attr-value, critical). One div serves
          as the panel for whichever tab is active; its content (the sticky
          sub-header, list and "show more") already changes with `tab`. */}
      <div
        id={`markets-panel-${tab}`}
        role="tabpanel"
        aria-labelledby={`markets-tab-${tab}`}
        tabIndex={0}
        className="max-h-[22rem] min-h-0 flex-1 overflow-y-auto md:max-h-[34rem] xl:max-h-none"
      >
        <div className="sticky top-0 z-10 grid grid-cols-[minmax(0,1fr)_3.5rem_3.5rem_2rem] items-center gap-2 border-b border-border bg-surface-2 px-3 py-1.5 text-label text-muted">
          <span>Trader</span>
          <span className="text-right" title="Equity index: 100 thirty days ago, deposits and withdrawals removed">Index</span>
          <span className="col-span-2 flex justify-end">
            <SegmentedControl
              size="sm"
              aria-label="Change window"
              className="!w-auto"
              options={[
                { value: "24h", label: "24h" },
                { value: "7d", label: "7d" },
              ]}
              value={change}
              onChange={setChange}
            />
          </span>
        </div>
        {error ? <p className="p-3 text-xs text-danger">{error}</p> : null}
        {loading && !rows.length ? (
          <ul aria-busy="true" aria-label="Loading traders" className="flex flex-col gap-3 p-3">
            {Array.from({ length: 8 }, (_, i) => (
              <li key={i} className="flex items-center gap-2">
                <Skeleton className="h-6 w-6" rounded="full" />
                <Skeleton className="h-4 flex-1" />
                <Skeleton className="h-4 w-12" />
              </li>
            ))}
          </ul>
        ) : null}
        {!loading && !items.length ? (
          <EmptyState
            compact
            title={tab === "mine" && !q ? <>No copies <em>yet</em></> : <>No <em>match</em></>}
            body={tab === "mine" && !q ? "Pick a trader from Top." : "Paste any 0x address to open it."}
            action={
              <Link href={scoutHref} className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline">
                <Telescope size={12} aria-hidden="true" /> Find one in Scout
              </Link>
            }
          />
        ) : null}
        <ul aria-label={`${TABS.find((t) => t.id === tab)?.label} list`}>
          {shown.map((m) => (
            <MarketRow
              key={m.address}
              m={m}
              selected={m.address === selected}
              change={change}
              onSelect={(a) => {
                // Pin the tab the user picked from, so copying a wallet doesn't flip the list to "My copies".
                if (tabChoice === null) setTab(tab);
                onSelect(a);
              }}
            />
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
