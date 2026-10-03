"use client";

import { useState } from "react";
import { ChevronDown, X } from "lucide-react";
import { clsx } from "clsx";
import type { LeaderOverride, LeaderStatus, Settings } from "@/lib/api/types";
import { formatLeverage, formatUsd, shortenAddress } from "@/lib/format";
import { effectiveSettingsForLeader } from "@/lib/forLeader";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { LeaderOverridePanel } from "./LeaderOverridePanel";

export function LeaderRow({
  address,
  settings,
  liveStatus,
  onRemove,
  onOverrideChange,
  removing,
}: {
  address: string;
  settings: Settings;
  liveStatus?: LeaderStatus;
  onRemove: () => void;
  onOverrideChange: (override: LeaderOverride | null) => void;
  removing?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const effective = liveStatus?.effective ?? effectiveSettingsForLeader(settings, address);
  const hasOverride = Boolean(settings.leader_overrides[address]);

  return (
    <div className="border-t border-border first:border-t-0">
      <div className="flex items-center gap-3 px-4 py-3 sm:px-5">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls={`override-${address}`}
          className="flex flex-1 items-center gap-3 text-left"
        >
          <ChevronDown
            size={16}
            className={clsx("flex-shrink-0 text-muted transition-transform", expanded && "rotate-180")}
            aria-hidden="true"
          />
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <span className="font-num text-sm font-medium text-foreground" title={address}>
                {shortenAddress(address)}
              </span>
              {hasOverride ? <Badge tone="accent">override</Badge> : null}
              {liveStatus && !liveStatus.read_ok ? <Badge tone="danger">read failed</Badge> : null}
            </div>
            <div className="font-num flex flex-wrap gap-x-3 text-xs text-muted">
              <span>equity {formatUsd(liveStatus?.equity_usd ?? null)}</span>
              <span>{liveStatus?.open_positions ?? 0} open</span>
              <span>
                {effective.sizing_mode.replace("_", " ")} · {effective.leverage_mode} ·{" "}
                {effective.leverage_mode === "fixed" ? formatLeverage(effective.leverage) : ""}
              </span>
            </div>
          </div>
        </button>
        <Button
          variant="ghost"
          size="sm"
          onClick={onRemove}
          disabled={removing}
          aria-label={`Remove ${address}`}
        >
          <X size={14} />
        </Button>
      </div>
      {expanded ? (
        <div id={`override-${address}`} className="bg-surface-2/40 px-4 pb-3 sm:px-5">
          <LeaderOverridePanel settings={settings} address={address} onChange={onOverrideChange} />
        </div>
      ) : null}
    </div>
  );
}
