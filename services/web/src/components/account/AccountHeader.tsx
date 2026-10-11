"use client";

import { RefreshCw, Wallet } from "lucide-react";
import { AddressChip } from "@/components/ui/AddressChip";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { useNow } from "@/hooks/useNow";
import { agentView, canRefresh } from "@/lib/account/agent";
import { openWalletManager } from "@/lib/account/managerStore";
import type { AccountSummary } from "@/lib/account/types";
import { formatAgo, formatSignedUsd, formatUsd } from "@/lib/format";
import { startRefresh } from "./AccountRow";
import { AgentBadge, KindBadge } from "./bits";

export function AccountHeader({ summary }: { summary: AccountSummary }) {
  const now = useNow();
  const { account, balances } = summary;
  const v = agentView(account, now);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="truncate text-xl font-bold tracking-tight">{account.label}</h1>
            <KindBadge kind={account.kind} />
            <AgentBadge account={account} nowMs={now} />
          </div>
          <AddressChip address={account.address} className="-ml-0.5" />
          <div className="mt-2 flex flex-wrap items-baseline gap-x-3">
            <span className="font-num text-3xl font-bold tracking-tight">{formatUsd(balances.total_usd)}</span>
            <span className={`font-num text-sm ${summary.unrealized_pnl_usd >= 0 ? "text-success" : "text-danger"}`}>
              {formatSignedUsd(summary.unrealized_pnl_usd)} open
            </span>
            <span className="text-xs text-muted">account value · updated {formatAgo(summary.as_of_ms, now)}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => openWalletManager()}>
            <Wallet size={14} aria-hidden="true" /> Accounts
          </Button>
        </div>
      </div>
      {canRefresh(v) && v.hint ? (
        <Notice
          tone={v.tone === "danger" ? "danger" : "warning"}
          title={`Trading agent: ${v.label}`}
          action={
            <Button size="sm" onClick={() => startRefresh(account)}>
              <RefreshCw size={13} aria-hidden="true" /> Refresh agent
            </Button>
          }
        >
          {v.hint}
        </Notice>
      ) : null}
    </div>
  );
}
