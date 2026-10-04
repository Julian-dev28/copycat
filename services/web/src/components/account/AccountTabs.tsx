"use client";

import { clsx } from "clsx";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useState, type KeyboardEvent } from "react";
import { PositionsTable } from "@/components/scout/file/PositionsTable";
import { TripsTable } from "@/components/scout/file/TripsTable";
import { useFileProfile } from "@/components/scout/file/hooks";
import { Panel } from "@/components/ui/Panel";
import { accountErrorText } from "@/lib/account/errors";
import type { AccountSummary, TradingAccount } from "@/lib/account/types";
import { formatUsd } from "@/lib/format";
import { BalancesHistory, FillsHistory, OrdersHistory, TransfersHistory } from "./HistoryTables";
import { useAccountMode } from "./hooks";

const TABS = ["Positions", "Balances", "Orders", "Fills", "Trades", "Transfers", "Copytrade"] as const;
type Tab = (typeof TABS)[number];

/** Positions and round trips come from the Scout file for this address (same reconstruction Scout shows for leaders). */
function FromFile({ account, what }: { account: TradingAccount; what: "positions" | "trades" }) {
  const q = useFileProfile(account.address);
  if (q.isError) return <p role="alert" className="p-4 text-sm text-danger">{accountErrorText(q.error, what)}</p>;
  if (!q.data) return <p className="p-4 text-sm text-muted">Loading {what}…</p>;
  if (q.data.kind === "building") return <p className="p-4 text-sm text-muted">Reading this account from Hyperliquid… ({q.data.status.done}/{q.data.status.total})</p>;
  const p = q.data.profile;
  return what === "positions" ? <PositionsTable positions={p.positions} asOfMs={p.positions_as_of_ms} /> : <TripsTable trips={p.recent_trips} />;
}

function Copytrade({ summary }: { summary: AccountSummary }) {
  const { demo } = useAccountMode();
  const active = summary.account.active;
  return (
    <div className="flex flex-col gap-3 p-4 text-sm">
      <p className="text-muted">
        {active
          ? <>copycat has <span className="font-num font-semibold text-foreground">{formatUsd(summary.balances.copytrade_usd)}</span> of margin in copies on this account.</>
          : "copycat only copies on the active account. Activate this one from the wallet manager to copy with it."}
      </p>
      <Link href={`/portfolio${demo ? "?demo=1" : ""}`} className="inline-flex w-fit items-center gap-1 font-medium text-accent hover:underline">
        Your wallets and copies in Portfolio <ArrowRight size={14} aria-hidden="true" />
      </Link>
    </div>
  );
}

export function AccountTabs({ summary }: { summary: AccountSummary }) {
  const [tab, setTab] = useState<Tab>("Positions");
  const account = summary.account;

  function onKey(e: KeyboardEvent<HTMLDivElement>) {
    const i = TABS.indexOf(tab);
    const next = e.key === "ArrowRight" ? TABS[(i + 1) % TABS.length] : e.key === "ArrowLeft" ? TABS[(i - 1 + TABS.length) % TABS.length] : null;
    if (!next) return;
    e.preventDefault();
    setTab(next);
    document.getElementById(`acct-tab-${next}`)?.focus();
  }

  return (
    <Panel>
      <div role="tablist" aria-label="Account history" onKeyDown={onKey} className="flex overflow-x-auto border-b border-border px-2">
        {TABS.map((t) => (
          <button
            key={t}
            id={`acct-tab-${t}`}
            type="button"
            role="tab"
            aria-selected={tab === t}
            aria-controls="acct-tabpanel"
            tabIndex={tab === t ? 0 : -1}
            onClick={() => setTab(t)}
            className={clsx("-mb-px border-b-2 px-3 py-2.5 text-sm font-medium whitespace-nowrap", tab === t ? "border-accent text-foreground" : "border-transparent text-muted hover:text-foreground")}
          >
            {t}
          </button>
        ))}
      </div>
      <div id="acct-tabpanel" role="tabpanel" aria-labelledby={`acct-tab-${tab}`}>
        {tab === "Positions" ? <FromFile account={account} what="positions" /> : null}
        {tab === "Trades" ? <FromFile account={account} what="trades" /> : null}
        {tab === "Balances" ? <BalancesHistory account={account} /> : null}
        {tab === "Orders" ? <OrdersHistory account={account} /> : null}
        {tab === "Fills" ? <FillsHistory account={account} /> : null}
        {tab === "Transfers" ? <TransfersHistory account={account} /> : null}
        {tab === "Copytrade" ? <Copytrade summary={summary} /> : null}
      </div>
    </Panel>
  );
}
