"use client";

import { useEffect, useState } from "react";
import { clsx } from "clsx";
import type { EngineStatus } from "@/lib/api/types";
import { formatAgo, formatUsd } from "@/lib/format";
import { dayPnlView } from "@/lib/engine/dayPnl";
import { AddressChip } from "@/components/ui/AddressChip";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";

/** No cycle for this long (poll_interval_s caps at 300s, default 5s) means the worker is stuck or dead. */
const STALE_MS = 5 * 60_000;

export function EngineStatusBar({ status, tradingEnabled }: { status?: EngineStatus; tradingEnabled?: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (!status) {
    return (
      <Panel className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-5" aria-busy="true" aria-label="Loading engine status">
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className="h-9 animate-pulse rounded-md bg-surface-2" />
        ))}
      </Panel>
    );
  }

  const enabled = tradingEnabled ?? status.enabled;
  const stale = status.last_cycle_ms !== null && status.last_cycle_ms !== undefined && now - status.last_cycle_ms > STALE_MS;
  const dayPnl = dayPnlView(status);
  const dayPnlTone = { up: "text-up", down: "text-down", flat: "text-foreground", muted: "text-muted" }[dayPnl.tone];

  return (
    <Panel className="flex flex-col gap-4 p-4 sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={clsx("h-2.5 w-2.5 rounded-full", status.running && !stale ? "bg-success" : stale ? "bg-warning" : "bg-muted")}
          aria-hidden="true"
        />
        <span className="text-sm font-semibold">{!status.running ? "Engine stopped" : stale ? "Engine stalled" : "Engine running"}</span>
        {enabled ? <Badge tone="success">trading on</Badge> : <Badge tone="neutral">trading off</Badge>}
        {status.dry_run ? <Badge tone="warning">dry run</Badge> : <Badge tone="danger">live orders</Badge>}
        {status.halted_reason ? <Badge tone="danger">halted: {status.halted_reason}</Badge> : null}
        {status.our_address ? (
          <span className="flex items-center gap-1 text-xs text-muted sm:ml-auto">
            account <AddressChip address={status.our_address} />
          </span>
        ) : null}
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-5">
        <Stat label="Equity" value={formatUsd(status.equity_usd)} />
        <Stat label="Available margin" value={formatUsd(status.available_margin_usd)} />
        <Stat
          label={dayPnl.reliable ? "Day P&L (UTC)" : "Day P&L (UTC), unverified"}
          value={dayPnl.text}
          hint={dayPnl.hint}
          valueClassName={dayPnlTone}
        />
        <Stat label="Open copies" value={String(status.positions.length)} />
        <Stat
          label="Last cycle"
          value={formatAgo(status.last_cycle_ms, now)}
          hint={status.cycle_ms ? `took ${status.cycle_ms} ms` : undefined}
          valueClassName={stale ? "text-warning" : undefined}
        />
      </dl>
    </Panel>
  );
}

function Stat({ label, value, hint, valueClassName }: { label: string; value: string; hint?: string; valueClassName?: string }) {
  return (
    <div className="flex min-w-0 flex-col">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={clsx("font-num truncate text-base font-semibold", valueClassName ?? "text-foreground")} title={hint}>
        {value}
      </dd>
    </div>
  );
}
