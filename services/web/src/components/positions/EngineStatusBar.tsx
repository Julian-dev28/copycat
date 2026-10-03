"use client";

import { useEffect, useState } from "react";
import type { EngineStatus } from "@/lib/api/types";
import { formatAgo, formatSignedUsd, formatUsd } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";

export function EngineStatusBar({ status }: { status?: EngineStatus }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (!status) {
    return (
      <Panel className="flex items-center justify-center p-4 text-sm text-muted">Loading engine status…</Panel>
    );
  }

  const dayPnlTone = (status.day_pnl_usd ?? 0) >= 0 ? "text-success" : "text-danger";

  return (
    <Panel className="flex flex-wrap items-center gap-x-6 gap-y-3 p-4">
      <div className="flex items-center gap-2">
        <span className={["h-2.5 w-2.5 rounded-full", status.running ? "bg-success" : "bg-muted"].join(" ")} />
        <span className="text-sm font-medium">{status.running ? "Running" : "Stopped"}</span>
        {status.dry_run ? <Badge tone="warning">dry run</Badge> : <Badge tone="accent">live</Badge>}
        {status.halted_reason ? <Badge tone="danger">halted: {status.halted_reason}</Badge> : null}
      </div>

      <Stat label="Last cycle" value={formatAgo(status.last_cycle_ms, now)} />
      <Stat label="Equity" value={formatUsd(status.equity_usd)} />
      <Stat label="Day P&L" value={formatSignedUsd(status.day_pnl_usd)} valueClassName={dayPnlTone} />
      <Stat label="Open copies" value={String(status.positions.length)} />
    </Panel>
  );
}

function Stat({ label, value, valueClassName }: { label: string; value: string; valueClassName?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-muted">{label}</span>
      <span className={["font-num text-sm font-medium", valueClassName ?? ""].join(" ")}>{value}</span>
    </div>
  );
}
