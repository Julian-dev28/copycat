"use client";

import { useReducer } from "react";
import { accountErrorText } from "@/lib/account/errors";
import { canClose, createReducer, initialCreate } from "@/lib/account/createFlow";
import { closeWalletManager, openWalletManager, type ManagerView } from "@/lib/account/managerStore";
import { AccountList } from "./AccountList";
import { ConnectWallet } from "./ConnectWallet";
import { CreateForm } from "./CreateForm";
import { FundPanel } from "./FundPanel";
import { useAccountMode, useAccounts, useAction, useManagerView } from "./hooks";
import { KeyReveal } from "./KeyReveal";
import { ModalShell } from "./ModalShell";
import { RefreshAgentForm } from "./RefreshAgentForm";

const TITLES: Record<ManagerView["view"], string> = {
  closed: "", list: "Trading accounts", create: "Create a wallet", connect: "Connect a wallet", refresh: "Refresh trading agent",
};

/**
 * The wallet manager dialog, mounted once (in the nav). The create flow's
 * reducer lives here so the dialog can refuse to close while a one-time key
 * is unsaved, and so every exit resets it (dropping the key).
 */
export function WalletManager() {
  const view = useManagerView();
  const { source } = useAccountMode();
  const accounts = useAccounts();
  const [create, dispatch] = useReducer(createReducer, initialCreate);
  const createAct = useAction();
  const locked = view.view === "create" && !canClose(create);

  function leave(next: ManagerView | null) {
    if (locked) return;
    dispatch({ type: "close" });
    createAct.clearError();
    if (next) openWalletManager(next as Exclude<ManagerView, { view: "closed" }>);
    else closeWalletManager();
  }

  async function onCreate(label: string, passphrase: string) {
    const res = await createAct.run(() => source.create({ label, passphrase }));
    if (res) dispatch({ type: "created", res });
  }

  const refreshAcc = view.view === "refresh" ? accounts.data?.find((a) => a.id === view.accountId) : undefined;
  const title = view.view === "create" && create.step === "fund" ? "Fund your wallet" : view.view === "create" && create.step === "reveal" ? "Save your private key" : TITLES[view.view];

  return (
    <ModalShell
      open={view.view !== "closed"}
      onClose={() => leave(null)}
      onBack={view.view !== "list" && view.view !== "closed" && !locked ? () => leave({ view: "list" }) : undefined}
      title={title}
      locked={locked}
      lockedHint="Tick “I saved my key” first"
    >
      {view.view === "list" ? <AccountList /> : null}
      {view.view === "create" && create.step === "form" ? (
        <CreateForm onSubmit={onCreate} pending={createAct.pending} error={accountErrorText(createAct.error, "create-wallet")} />
      ) : null}
      {view.view === "create" && create.step === "reveal" ? <KeyReveal state={create} dispatch={dispatch} /> : null}
      {view.view === "create" && create.step === "fund" ? (
        <FundPanel account={create.account} needsAgent={create.account.agent_status !== "active"} onRefreshAgent={() => leave({ view: "refresh", accountId: create.account.id })} />
      ) : null}
      {view.view === "connect" ? (
        <ConnectWallet key={`${view.tab}-${view.refresh?.address}`} initialTab={view.tab} refresh={view.refresh} onClose={() => leave(null)} />
      ) : null}
      {view.view === "refresh" ? (
        refreshAcc ? <RefreshAgentForm account={refreshAcc} onDone={() => leave({ view: "list" })} /> : <p className="text-sm text-muted">Loading the account…</p>
      ) : null}
    </ModalShell>
  );
}
