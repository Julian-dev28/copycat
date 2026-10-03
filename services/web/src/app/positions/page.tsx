"use client";

import { RequireToken } from "@/components/RequireToken";
import { useEngineStatus } from "@/hooks/useEngineStatus";
import { EngineStatusBar } from "@/components/positions/EngineStatusBar";
import { PositionsTable } from "@/components/positions/PositionsTable";
import { EventFeed } from "@/components/positions/EventFeed";
import { HaltButton } from "@/components/positions/HaltButton";

export default function PositionsPage() {
  return (
    <RequireToken>
      <PositionsPageContent />
    </RequireToken>
  );
}

function PositionsPageContent() {
  const { data: status, isError, error } = useEngineStatus();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Positions</h1>
          <p className="text-sm text-muted">What copycat is actually doing right now.</p>
        </div>
        <HaltButton />
      </div>

      <EngineStatusBar status={status} />

      {isError ? (
        <p className="text-sm text-danger">Couldn&apos;t load engine status{error instanceof Error ? `: ${error.message}` : ""}.</p>
      ) : null}

      <PositionsTable positions={status?.positions ?? []} />
      <EventFeed />
    </div>
  );
}
