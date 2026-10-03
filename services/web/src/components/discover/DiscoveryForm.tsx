"use client";

import { useState } from "react";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

export function DiscoveryForm({
  onStart,
  starting,
  error,
}: {
  onStart: (opts: { simEquityUsd: number; topN: number; useCurrentSettings: boolean }) => void;
  starting: boolean;
  error?: string | null;
}) {
  const [simEquityUsd, setSimEquityUsd] = useState(1000);
  const [topN, setTopN] = useState(25);
  const [useCurrentSettings, setUseCurrentSettings] = useState(true);

  return (
    <Panel>
      <PanelHeader
        title="Run a discovery scan"
        description="Simulates copying the current Hyperliquid leaderboard at your settings, then ranks who'd have been worth following."
      />
      <form
        className="flex flex-col gap-4 border-t border-border px-4 py-4 sm:px-5"
        onSubmit={(e) => {
          e.preventDefault();
          onStart({ simEquityUsd, topN, useCurrentSettings });
        }}
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium text-foreground">Simulated equity ($)</span>
            <Input
              type="number"
              min={10}
              step={100}
              value={simEquityUsd}
              onChange={(e) => setSimEquityUsd(Number(e.target.value))}
            />
          </label>
          <label className="flex flex-col gap-1.5 text-sm">
            <span className="font-medium text-foreground">Top N candidates</span>
            <Input type="number" min={1} max={200} value={topN} onChange={(e) => setTopN(Number(e.target.value))} />
          </label>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={useCurrentSettings}
            onChange={(e) => setUseCurrentSettings(e.target.checked)}
            className="h-4 w-4 rounded border-border accent-[var(--accent)]"
          />
          Simulate with my current /copy settings (sizing, leverage, margin mode)
        </label>
        {error ? <p className="text-sm text-danger">{error}</p> : null}
        <div>
          <Button type="submit" variant="primary" disabled={starting}>
            {starting ? "Starting…" : "Start discovery run"}
          </Button>
        </div>
      </form>
    </Panel>
  );
}
