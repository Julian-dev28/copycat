"use client";

import type { EngineEvent } from "@/lib/api/types";
import { formatAgo, formatLeverage, formatUsd, shortenAddress } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { useEventStream } from "@/hooks/useEventStream";

const ACTION_TONE: Record<EngineEvent["action"], "accent" | "success" | "danger" | "warning" | "neutral"> = {
  baseline: "neutral",
  open: "success",
  add: "success",
  reduce: "warning",
  close: "accent",
  skip: "neutral",
  error: "danger",
  intent: "accent",
  halt: "danger",
  resume: "success",
};

export function EventFeed() {
  const { events, state } = useEventStream();

  return (
    <Panel>
      <PanelHeader
        title="Event feed"
        description="Live, newest first."
        action={<ConnectionBadge state={state} />}
      />
      <ul className="max-h-96 divide-y divide-border overflow-y-auto border-t border-border" aria-live="polite">
        {events.length === 0 ? (
          <li className="px-5 py-8 text-center text-sm text-muted">No events yet.</li>
        ) : (
          events.map((e, i) => (
            <li key={`${e.ts_ms}-${i}`} className="flex flex-wrap items-center gap-2 px-4 py-2.5 text-sm sm:px-5">
              <span className="font-num w-16 flex-shrink-0 text-xs text-muted">{formatAgo(e.ts_ms)}</span>
              <Badge tone={ACTION_TONE[e.action]}>{e.action}</Badge>
              {e.dry_run ? <Badge tone="warning">dry</Badge> : null}
              {e.coin ? <span className="font-num font-medium">{e.coin}</span> : null}
              {e.side ? <span className="text-muted">{e.side}</span> : null}
              {e.leader ? (
                <span className="font-num text-xs text-muted" title={e.leader}>
                  {shortenAddress(e.leader)}
                </span>
              ) : null}
              {e.notional_usd !== undefined && e.notional_usd !== null ? (
                <span className="font-num text-xs text-muted">{formatUsd(e.notional_usd)}</span>
              ) : null}
              {e.leverage ? <span className="font-num text-xs text-muted">{formatLeverage(e.leverage)}</span> : null}
              {e.reason ? <span className="text-xs text-muted">— {e.reason}</span> : null}
            </li>
          ))
        )}
      </ul>
    </Panel>
  );
}

function ConnectionBadge({ state }: { state: "idle" | "connecting" | "open" | "error" }) {
  if (state === "open") return <Badge tone="success">live</Badge>;
  if (state === "connecting") return <Badge tone="neutral">connecting…</Badge>;
  if (state === "error") return <Badge tone="danger">reconnecting…</Badge>;
  return null;
}
