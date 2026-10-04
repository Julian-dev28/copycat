"use client";

import { clsx } from "clsx";
import { Pencil, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { AddressChip } from "@/components/ui/AddressChip";
import { Button } from "@/components/ui/Button";
import { agentView, canRefresh } from "@/lib/account/agent";
import { openWalletManager } from "@/lib/account/managerStore";
import type { TradingAccount } from "@/lib/account/types";
import { ActivateButton } from "./ActivateButton";
import { AgentBadge, KindBadge } from "./bits";
import { RemoveConfirm, RenameForm } from "./RowEditors";

/** Created wallets renew with the passphrase; connected ones by signing or pasting again. */
export function startRefresh(a: TradingAccount): void {
  if (a.kind === "created") openWalletManager({ view: "refresh", accountId: a.id });
  else openWalletManager({ view: "connect", tab: a.kind === "connected_key" ? "key" : "sign", refresh: { label: a.label, address: a.address } });
}

export function AccountRow({ account, nowMs }: { account: TradingAccount; nowMs: number }) {
  const [mode, setMode] = useState<"view" | "rename" | "remove">("view");
  const v = agentView(account, nowMs);

  return (
    <li className={clsx("flex flex-col gap-2 rounded-xl border p-3", account.active ? "border-accent/50 bg-accent-soft/40" : "border-border bg-surface")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="truncate text-sm font-semibold">{account.label}</span>
            {account.active ? <span className="rounded-full bg-accent px-1.5 py-px text-[10px] font-bold tracking-wide text-accent-foreground uppercase">Active</span> : null}
            <KindBadge kind={account.kind} />
          </div>
          <AddressChip address={account.address} className="-ml-0.5" />
        </div>
        <AgentBadge account={account} nowMs={nowMs} />
      </div>
      {v.hint && v.status !== "active" ? <p className="text-[11px] text-muted">{v.hint}</p> : null}

      {mode === "rename" ? <RenameForm account={account} onDone={() => setMode("view")} /> : null}
      {mode === "remove" ? <RemoveConfirm account={account} onDone={() => setMode("view")} /> : null}
      {mode === "view" ? (
        <div className="flex flex-wrap gap-1.5">
          {account.active ? null : <ActivateButton account={account} />}
          {canRefresh(v) ? (
            <Button size="sm" onClick={() => startRefresh(account)}>
              <RefreshCw size={12} aria-hidden="true" /> Refresh agent
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={() => setMode("rename")}>
            <Pencil size={12} aria-hidden="true" /> Rename
          </Button>
          <Button size="sm" variant="ghost" className="text-danger" onClick={() => setMode("remove")}>
            <Trash2 size={12} aria-hidden="true" /> Remove
          </Button>
        </div>
      ) : null}
    </li>
  );
}
