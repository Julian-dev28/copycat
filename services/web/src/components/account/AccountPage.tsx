"use client";

import { Link2, Plus } from "lucide-react";
import { LoadError, PageSkeleton } from "@/components/PageStates";
import { Button } from "@/components/ui/Button";
import { Notice } from "@/components/ui/Notice";
import { Panel } from "@/components/ui/Panel";
import { CatLogo } from "@/components/CatLogo";
import { isTooOld } from "@/lib/account/errors";
import { openWalletManager, setManagerView } from "@/lib/account/managerStore";
import { isEmptyAccount } from "@/lib/account/summary";
import { AccountChart } from "./AccountChart";
import { AccountHeader } from "./AccountHeader";
import { AccountTabs } from "./AccountTabs";
import { AgentBanner } from "./bits";
import { EquityBreakdown } from "./EquityBreakdown";
import { FundingBar } from "./FundingBar";
import { FundPanel } from "./FundPanel";
import { useAccountSummary, useActiveAccount } from "./hooks";
import { StatGroups } from "./StatGroups";

function TooOld() {
  return (
    <Notice tone="warning" title="api too old">
      This api build has no <span className="font-num text-foreground">/api/accounts</span> routes yet. Update services/api and restart it.
    </Notice>
  );
}

function NoAccount({ any }: { any: boolean }) {
  return (
    <Panel className="mx-auto flex max-w-lg flex-col items-center gap-4 p-8 text-center">
      <CatLogo size={44} className="text-accent" />
      <div>
        <h1 className="text-lg font-semibold">{any ? "No active trading account" : "Set up a trading account"}</h1>
        <p className="mt-1 text-sm text-muted">
          {any ? "Pick which account copycat trades." : "copycat needs a Hyperliquid account to trade. Make a fresh one, or connect one you already use."}
        </p>
      </div>
      {any ? (
        <Button variant="primary" onClick={() => openWalletManager()}>Choose an account</Button>
      ) : (
        <div className="flex flex-col gap-2 sm:flex-row">
          <Button variant="primary" onClick={() => setManagerView({ view: "create" })}>
            <Plus size={15} aria-hidden="true" /> Create a new wallet
          </Button>
          <Button onClick={() => setManagerView({ view: "connect" })}>
            <Link2 size={15} aria-hidden="true" /> Connect an existing wallet
          </Button>
        </div>
      )}
      <AgentBanner />
    </Panel>
  );
}

export function AccountPage() {
  const accounts = useActiveAccount();
  const active = accounts.active;
  const summary = useAccountSummary(active?.id ?? null);

  if (accounts.isError) return isTooOld(accounts.error) ? <TooOld /> : <LoadError what="your accounts" error={accounts.error} onRetry={() => accounts.refetch()} />;
  if (accounts.isPending) return <PageSkeleton label="Loading account" />;
  if (!active) return <NoAccount any={Boolean(accounts.data?.length)} />;
  if (summary.isError) return isTooOld(summary.error) ? <TooOld /> : <LoadError what="the account summary" error={summary.error} onRetry={() => summary.refetch()} />;
  if (!summary.data) return <PageSkeleton label="Loading account" />;

  const s = summary.data;
  return (
    <div className="flex flex-col gap-5">
      <AccountHeader summary={s} />
      <FundingBar summary={s} />
      {isEmptyAccount(s) ? (
        <Panel className="p-4 sm:p-5">
          <FundPanel account={s.account} needsAgent={s.account.agent_status !== "active"} onRefreshAgent={() => setManagerView({ view: "refresh", accountId: s.account.id })} />
        </Panel>
      ) : (
        <>
          <EquityBreakdown balances={s.balances} />
          <StatGroups summary={s} />
          <AccountChart summary={s} />
          <AccountTabs summary={s} />
        </>
      )}
    </div>
  );
}
