"use client";

import { useState } from "react";
import { RequireToken } from "@/components/RequireToken";
import { DiscoveryForm } from "@/components/discover/DiscoveryForm";
import { DiscoveryProgress } from "@/components/discover/DiscoveryProgress";
import { DiscoveryTable } from "@/components/discover/DiscoveryTable";
import { Panel } from "@/components/ui/Panel";
import { Notice } from "@/components/ui/Notice";
import { LoadError } from "@/components/PageStates";
import { ApiError } from "@/lib/api/client";
import { Radar } from "lucide-react";
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
  const { data: latest, isLoading: latestLoading, error: latestError } = useLatestDiscoveryRun();
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
        <p className="text-sm text-muted">Find wallets worth copying, ranked by how copying them would have gone.</p>
      </div>

      <DiscoveryForm
        onStart={handleStart}
        starting={startRun.isPending}
        running={activeRun?.status === "running"}
        error={startRun.error?.message}
      />

      {!activeRun && !latestLoading && latestError && !(latestError instanceof ApiError && latestError.status === 404) ? (
        <LoadError what="the last discovery run" error={latestError} />
      ) : null}

      {!activeRun && !latestLoading && (!latestError || (latestError instanceof ApiError && latestError.status === 404)) ? (
        <Panel className="flex flex-col items-center gap-2 px-5 py-10 text-center">
          <Radar size={28} className="text-accent" aria-hidden="true" />
          <p className="text-sm font-semibold">No scans yet</p>
          <p className="max-w-md text-sm text-muted">
            Start one above. copycat pulls the leaderboard, replays each wallet&apos;s last 30 days as if you&apos;d copied it,
            and ranks them. 25 wallets takes about a minute.
          </p>
        </Panel>
      ) : null}

      {activeRun?.status === "running" ? <DiscoveryProgress run={activeRun} /> : null}

      {activeRun?.status === "failed" ? (
        <Notice tone="danger" title="Discovery run failed">
          {activeRun.error ?? "No reason given. Check the api log."}
        </Notice>
      ) : null}

      {addLeader.isError ? (
        <Notice tone="danger" title="Couldn't add that leader">
          {addLeader.error.message}
        </Notice>
      ) : null}

      {activeRun?.status === "done" ? (
        <DiscoveryTable
          results={activeRun.results}
          leaderCount={settings?.leaders.length ?? 0}
          leaders={settings?.leaders ?? []}
          simEquityUsd={activeRun.sim_equity_usd}
          onCopy={handleCopy}
          copyingAddress={copyingAddress}
        />
      ) : null}
    </div>
  );
}
