"use client";

import { useState, type KeyboardEvent } from "react";
import { clsx } from "clsx";
import { Panel } from "@/components/ui/Panel";
import { truncationNotice } from "@/lib/scout/labels";
import type { TraderProfile } from "@/lib/scout/types";
import { FillsTab, OrdersTab } from "./FillsOrders";
import { PositionsTable } from "./PositionsTable";
import { StrategyTab } from "./StrategyTab";
import { TripsTable } from "./TripsTable";

const TABS = [
  { id: "positions", label: "Positions" },
  { id: "trips", label: "Round trips" },
  { id: "fills", label: "Fills" },
  { id: "orders", label: "Open orders" },
  { id: "strategy", label: "Strategy" },
] as const;
type TabId = (typeof TABS)[number]["id"];

export function FileTabs({ profile }: { profile: TraderProfile }) {
  const [tab, setTab] = useState<TabId>("positions");
  const address = profile.row.address;
  const notice = truncationNotice(profile.row.flags, profile.row.score.fills_30d);

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const i = TABS.findIndex((t) => t.id === tab);
    const next = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : null;
    if (next === null) return;
    e.preventDefault();
    const t = TABS[(next + TABS.length) % TABS.length];
    setTab(t.id);
    document.getElementById(`file-tab-${t.id}`)?.focus();
  }

  return (
    <div className="flex flex-col gap-3">
      <div role="tablist" aria-label="Trader file sections" onKeyDown={onKey} className="flex gap-1 overflow-x-auto border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.id}
            id={`file-tab-${t.id}`}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            aria-controls={`file-panel-${t.id}`}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            className={clsx(
              "-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm",
              tab === t.id ? "border-accent font-semibold text-foreground" : "border-transparent text-muted hover:text-foreground",
            )}
          >
            {t.label}
            {t.id === "positions" && profile.positions.length ? <span className="ml-1 font-num text-xs text-muted">{profile.positions.length}</span> : null}
          </button>
        ))}
      </div>
      <div id={`file-panel-${tab}`} role="tabpanel" aria-labelledby={`file-tab-${tab}`}>
        {tab === "strategy" ? (
          <StrategyTab address={address} />
        ) : (
          <Panel className="overflow-hidden">
            {tab === "positions" ? <PositionsTable positions={profile.positions} asOfMs={profile.positions_as_of_ms} /> : null}
            {tab === "trips" ? (
              <TripsTable trips={profile.recent_trips} openPositions={profile.positions} truncationNotice={notice} />
            ) : null}
            {tab === "fills" ? <FillsTab address={address} truncationNotice={notice} /> : null}
            {tab === "orders" ? <OrdersTab address={address} /> : null}
          </Panel>
        )}
      </div>
    </div>
  );
}
