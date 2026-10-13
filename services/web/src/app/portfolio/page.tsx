"use client";

import { Suspense } from "react";
import { useRouter } from "next/navigation";
import { RequireToken } from "@/components/RequireToken";
import { EngineStatusBar } from "@/components/positions/EngineStatusBar";
import { PositionsTable } from "@/components/positions/PositionsTable";
import { EventFeed } from "@/components/positions/EventFeed";
import { HaltButton } from "@/components/positions/HaltButton";
import { CloseAllButton } from "@/components/positions/CloseAllButton";
import { EmptyAccountBanner } from "@/components/EmptyAccountBanner";
import { LoadError, PageSkeleton } from "@/components/PageStates";
import { PendingMcpPlans } from "@/components/mcp/PendingMcpPlans";
import { YourWallets } from "@/components/trade/YourWallets";
import { useTradeMode, useTradeSettings, useTradeStatus, useWallets } from "@/components/trade/hooks";
import { withDemo } from "@/components/trade/bits";
import { useNow } from "@/hooks/useNow";
import type { EngineStatus, Settings } from "@/lib/api/types";
import { problemText } from "@/lib/trade/apiState";

export default function PortfolioPage() {
  return (
    <Suspense fallback={<PageSkeleton label="Loading portfolio" />}>
      <PortfolioGate />
    </Suspense>
  );
}

function PortfolioGate() {
  const { demo } = useTradeMode();
  return demo ? <Portfolio /> : (
    <RequireToken>
      <Portfolio />
    </RequireToken>
  );
}

/** Everything copycat holds right now: per wallet, per position, and the engine's log. Was /positions. */
function Portfolio() {
  const { demo, acct } = useTradeMode();
  const router = useRouter();
  const statusQ = useTradeStatus();
  const settings = useTradeSettings();
  const wallets = useWallets();
  const status = statusQ.data as EngineStatus | undefined;
  const s = settings.data as Settings | undefined;
  const nowMs = useNow();
  const open = (a: string) => router.push(withDemo(`/?w=${a}`, demo, acct));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Portfolio</h1>
          <p className="text-sm text-muted">What copycat holds right now, per wallet and per position.</p>
        </div>
        {!demo ? (
          <div className="flex flex-wrap items-start gap-2 sm:justify-end">
            <CloseAllButton openCopies={status?.positions.length ?? 0} />
            <HaltButton enabled={s?.enabled} />
          </div>
        ) : null}
      </div>
      {statusQ.isError ? <LoadError what="engine status" error={statusQ.error} onRetry={() => statusQ.refetch()} /> : null}
      <PendingMcpPlans enabled={!demo} />
      <EmptyAccountBanner status={status} settings={s} />
      <EngineStatusBar status={status} tradingEnabled={s?.enabled} lossLimitOn={(s?.daily_loss_limit_usd ?? 0) < 0} />
      <YourWallets
        wallets={wallets.data ?? []}
        settings={settings.data}
        names={{}}
        selected={null}
        loading={wallets.isLoading}
        error={wallets.error ? problemText(wallets.error, "wallets") : null}
        onAdjust={open}
        nowMs={nowMs}
        empty={<p className="text-sm text-muted">No copies yet. Copy a trader from the Trade page.</p>}
      />
      <PositionsTable positions={status?.positions ?? []} loading={!status && !statusQ.isError} nowMs={nowMs} />
      {!demo ? <EventFeed /> : null}
    </div>
  );
}
