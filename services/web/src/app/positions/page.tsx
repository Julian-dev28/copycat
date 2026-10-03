"use client";

import { RequireToken } from "@/components/RequireToken";
import { useEngineStatus } from "@/hooks/useEngineStatus";
import { useSettings } from "@/hooks/useSettings";
import { EngineStatusBar } from "@/components/positions/EngineStatusBar";
import { PositionsTable } from "@/components/positions/PositionsTable";
import { EventFeed } from "@/components/positions/EventFeed";
import { HaltButton } from "@/components/positions/HaltButton";
import { CloseAllButton } from "@/components/positions/CloseAllButton";
import { EmptyAccountBanner } from "@/components/EmptyAccountBanner";
import { LoadError } from "@/components/PageStates";

export default function PositionsPage() {
  return (
    <RequireToken>
      <PositionsPageContent />
    </RequireToken>
  );
}

function PositionsPageContent() {
  const { data: status, isError, error, refetch } = useEngineStatus();
  const { data: settings } = useSettings();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Positions</h1>
          <p className="text-sm text-muted">What copycat is actually doing right now.</p>
        </div>
        <div className="flex flex-wrap items-start gap-2 sm:justify-end">
          <CloseAllButton openCopies={status?.positions.length ?? 0} />
          <HaltButton enabled={settings?.enabled} />
        </div>
      </div>

      {isError ? <LoadError what="engine status" error={error} onRetry={() => refetch()} /> : null}
      <EmptyAccountBanner status={status} settings={settings} />
      <EngineStatusBar status={status} tradingEnabled={settings?.enabled} />
      <PositionsTable positions={status?.positions ?? []} loading={!status && !isError} />
      <EventFeed />
    </div>
  );
}
