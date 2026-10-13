import { Loader2 } from "lucide-react";
import type { DiscoveryRun } from "@/lib/api/types";
import { Panel } from "@/components/ui/Panel";
import { clamp } from "@/lib/sizing";
import { formatUsd } from "@/lib/format";

export function DiscoveryProgress({ run }: { run: DiscoveryRun }) {
  const pct = run.candidates > 0 ? clamp(Math.round((run.scored / run.candidates) * 100), 0, 100) : 0;

  return (
    <Panel className="flex flex-col gap-3 p-5">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Loader2 size={16} className="animate-spin text-accent" aria-hidden="true" />
        Scanning the leaderboard…
      </div>
      <div
        className="h-2 w-full overflow-hidden rounded-sm bg-surface-2"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label="Discovery progress"
      >
        <div className="h-full rounded-sm bg-accent transition-all" style={{ width: `${pct}%` }} />
      </div>
      <p className="font-num text-xs text-muted">
        {run.scored} / {run.candidates || "?"} wallets scored · simulating {formatUsd(run.sim_equity_usd)} per wallet
      </p>
    </Panel>
  );
}
