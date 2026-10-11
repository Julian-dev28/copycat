"use client";

import { useState } from "react";
import { ChevronDown, X } from "lucide-react";
import { clsx } from "clsx";
import type { LeaderOverride, LeaderStatus, Settings } from "@/lib/api/types";
import { formatAgo, formatUsd } from "@/lib/format";
import { effectiveSettingsForLeader, hasActiveOverride } from "@/lib/forLeader";
import { AddressChip } from "@/components/ui/AddressChip";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { LeaderOverridePanel } from "./LeaderOverridePanel";
import { leaderTerms } from "./leaderTerms";

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
  const hasOverride = hasActiveOverride(settings.leader_overrides[address]);
  const panelId = `override-${address}`;
  const terms = leaderTerms(effective);

  return (
    <div className="border-t border-border first:border-t-0">
      <div className="flex items-start gap-2 px-4 py-3 sm:items-center sm:gap-3 sm:px-5">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls={panelId}
          aria-label={`${expanded ? "Hide" : "Show"} overrides for ${address}`}
          className="mt-0.5 rounded-md p-1 text-muted hover:bg-surface-2 hover:text-foreground sm:mt-0"
        >
          <ChevronDown size={16} className={clsx("transition-transform", expanded && "rotate-180")} aria-hidden="true" />
        </button>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <AddressChip address={address} strong />
            {hasOverride ? <Badge tone="accent">override</Badge> : null}
            {liveStatus && !liveStatus.read_ok ? <Badge tone="danger">read failed</Badge> : null}
            {liveStatus?.owned_coins.length ? (
              <Badge tone="success">copying {liveStatus.owned_coins.join(", ")}</Badge>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            tabIndex={-1}
            className="font-num flex flex-wrap gap-x-3 gap-y-0.5 text-left text-xs text-muted"
          >
            <span>equity {formatUsd(liveStatus?.equity_usd ?? null, true)}</span>
            <span>{liveStatus?.open_positions ?? 0} open</span>
            <span>{terms.sizing}</span>
            <span
              className={terms.capped ? "text-warning" : undefined}
              title={terms.capped ? "Settings > Copy behavior > Maximum position leverage caps every copy" : undefined}
            >
              {terms.leverage}
            </span>
            {liveStatus?.last_read_ms ? <span>read {formatAgo(liveStatus.last_read_ms)}</span> : null}
          </button>
        </div>
        <Button variant="ghost" size="sm" onClick={onRemove} disabled={removing} aria-label={`Stop copying ${address}`} title="Stop copying">
          <X size={14} aria-hidden="true" />
        </Button>
      </div>
      {expanded ? (
        <div id={panelId} className="border-t border-border bg-surface-2/40 px-4 pb-3 sm:px-5 sm:pl-14">
          <p className="pt-3 text-xs text-muted">Tick a setting to override it for this trader only. Unticked rows follow the global value.</p>
          <LeaderOverridePanel settings={settings} address={address} onChange={onOverrideChange} />
        </div>
      ) : null}
    </div>
  );
}
