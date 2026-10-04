"use client";

import { ChevronDown, Plus } from "lucide-react";
import { useNow } from "@/hooks/useNow";
import { agentView } from "@/lib/account/agent";
import { isTooOld } from "@/lib/account/errors";
import { openWalletManager } from "@/lib/account/managerStore";
import { shortenAddress } from "@/lib/format";
import { AgentDot } from "./bits";
import { useAccountMode, useActiveAccount } from "./hooks";
import { WalletManager } from "./WalletManager";

/** Nav chip: active account label, short address, agent dot. Opens the wallet manager. Also mounts the manager. */
export function AccountSwitcher() {
  const { active, data, isError, error } = useActiveAccount();
  const { enabled } = useAccountMode();
  const now = useNow();
  const tooOld = isError && isTooOld(error);
  const hasAny = Boolean(data?.length);

  let body: React.ReactNode;
  if (active) {
    const v = agentView(active, now);
    body = (
      <>
        <AgentDot account={active} nowMs={now} />
        <span className="hidden max-w-24 truncate font-medium min-[480px]:inline">{active.label}</span>
        <span className="hidden font-num text-muted lg:inline">{shortenAddress(active.address, 4, 4)}</span>
        <span className="sr-only">, trading agent {v.label}</span>
        <ChevronDown size={13} className="text-muted" aria-hidden="true" />
      </>
    );
  } else if (tooOld || !enabled) {
    body = null;
  } else {
    body = (
      <>
        <Plus size={13} aria-hidden="true" />
        <span className="hidden font-medium min-[480px]:inline">{hasAny ? "Choose account" : "Add wallet"}</span>
      </>
    );
  }

  return (
    <>
      {body ? (
        <button
          type="button"
          onClick={() => openWalletManager()}
          aria-label={active ? `Active trading account ${active.label}. Open wallet manager` : "Open wallet manager"}
          className="flex h-8 items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-2.5 text-xs hover:border-accent/60"
        >
          {body}
        </button>
      ) : null}
      <WalletManager />
    </>
  );
}
