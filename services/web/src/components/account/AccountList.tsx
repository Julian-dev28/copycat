"use client";

import { Link2, Plus } from "lucide-react";
import { useNow } from "@/hooks/useNow";
import { accountErrorText, isTooOld } from "@/lib/account/errors";
import { openWalletManager } from "@/lib/account/managerStore";
import { AccountRow } from "./AccountRow";
import { AgentBanner, ErrorLine } from "./bits";
import { useAccounts } from "./hooks";

function AddCard({ icon, title, body, onClick }: { icon: React.ReactNode; title: string; body: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex flex-1 items-start gap-3 rounded-xl border border-border bg-surface-2 p-3 text-left transition-colors hover:border-accent/60 hover:bg-accent-soft/40"
    >
      <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent">{icon}</span>
      <span>
        <span className="block text-sm font-semibold">{title}</span>
        <span className="mt-0.5 block text-xs text-muted">{body}</span>
      </span>
    </button>
  );
}

export function AccountList() {
  const q = useAccounts();
  const now = useNow();
  const accounts = q.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      {q.isError ? (
        <ErrorLine>{isTooOld(q.error) ? "api too old: this api build has no /api/accounts. Update services/api and restart it." : accountErrorText(q.error)}</ErrorLine>
      ) : null}
      {q.isPending && !q.isError ? <div className="h-24 animate-pulse rounded-xl bg-surface-2" role="status" aria-label="Loading accounts" /> : null}
      {q.isSuccess && !accounts.length ? (
        <p className="rounded-xl border border-dashed border-border p-4 text-center text-sm text-muted">
          No trading accounts yet. Create a fresh wallet, or connect one you already use on Hyperliquid.
        </p>
      ) : null}
      {accounts.length ? (
        <ul className="flex flex-col gap-2" aria-label="Your trading accounts">
          {accounts.map((a) => (
            <AccountRow key={a.id} account={a} nowMs={now} />
          ))}
        </ul>
      ) : null}
      <div className="flex flex-col gap-2 sm:flex-row">
        <AddCard icon={<Plus size={16} />} title="Create a new wallet" body="copycat makes one for you. Back up the key, deposit, trade." onClick={() => openWalletManager({ view: "create" })} />
        <AddCard icon={<Link2 size={16} />} title="Connect an existing wallet" body="Sign with MetaMask or Rabby, or paste an API wallet key." onClick={() => openWalletManager({ view: "connect" })} />
      </div>
      <AgentBanner />
    </div>
  );
}
