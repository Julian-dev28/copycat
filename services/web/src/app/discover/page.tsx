"use client";

import { useState } from "react";
import { RequireToken } from "@/components/RequireToken";
import { DiscoveryForm } from "@/components/discover/DiscoveryForm";
import { DiscoveryProgress } from "@/components/discover/DiscoveryProgress";
import { DiscoveryTable } from "@/components/discover/DiscoveryTable";
import { Panel } from "@/components/ui/Panel";
import { useDiscoveryRun, useLatestDiscoveryRun, useStartDiscoveryRun } from "@/hooks/useDiscovery";
import { useAddLeader, useSettings } from "@/hooks/useSettings";

export default function DiscoverPage() {
  return (
    <RequireToken>
      <DiscoverPageContent />
    </RequireToken>
  );
}

function DiscoverPageContent() {
  const [startedRunId, setRunId] = useState<string | null>(null);
  const { data: latest } = useLatestDiscoveryRun();
  // Resume whatever run was last started (survives a page refresh) until a new one starts.
  const runId = startedRunId ?? latest?.run_id ?? null;
  const run = useDiscoveryRun(runId);
  const startRun = useStartDiscoveryRun();
  const { data: settings } = useSettings();
  const addLeader = useAddLeader();
  const [copyingAddress, setCopyingAddress] = useState<string | null>(null);

  const activeRun = run.data ?? latest;

  function handleStart(opts: { simEquityUsd: number; topN: number; useCurrentSettings: boolean }) {
    startRun.mutate(
      {
        sim_equity_usd: opts.simEquityUsd,
        top_n: opts.topN,
        settings: opts.useCurrentSettings ? settings : undefined,
      },
      { onSuccess: (res) => setRunId(res.run_id) },
    );
  }

  function handleCopy(address: string) {
    setCopyingAddress(address);
    addLeader.mutate(address, { onSettled: () => setCopyingAddress(null) });
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight">Discover</h1>
        <p className="text-sm text-muted">Find wallets worth copying, ranked by simulated copy performance.</p>
      </div>

      <DiscoveryForm onStart={handleStart} starting={startRun.isPending} error={startRun.error?.message} />

      {activeRun?.status === "running" ? <DiscoveryProgress run={activeRun} /> : null}

      {activeRun?.status === "failed" ? (
        <Panel className="p-5 text-sm text-danger">Run failed{activeRun.error ? `: ${activeRun.error}` : ""}.</Panel>
      ) : null}

      {activeRun?.status === "done" ? (
        <DiscoveryTable
          results={activeRun.results}
          leaderCount={settings?.leaders.length ?? 0}
          onCopy={handleCopy}
          copyingAddress={copyingAddress}
        />
      ) : null}
    </div>
  );
}
