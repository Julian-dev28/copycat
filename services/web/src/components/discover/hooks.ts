"use client";

import { useMemo } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSettingsMode } from "@/components/copy/hooks";
import type { StartDiscoveryRunBody } from "@/lib/api/types";
import { demoDiscovery, liveDiscovery, type DiscoverySource } from "./source";

let demoSource: DiscoverySource | null = null;

/** Demo-aware discovery source. Needs a <Suspense> above it (useSearchParams). */
export function useDiscoveryMode(): { demo: boolean; enabled: boolean; source: DiscoverySource } {
  const { demo, enabled } = useSettingsMode();
  const source = useMemo(() => {
    if (!demo) return liveDiscovery;
    demoSource ??= demoDiscovery();
    return demoSource;
  }, [demo]);
  return { demo, enabled, source };
}

export function useStartRun() {
  const { source } = useDiscoveryMode();
  return useMutation({ mutationFn: (body: StartDiscoveryRunBody) => source.start(body) });
}

export function useRun(runId: string | null) {
  const { demo, enabled, source } = useDiscoveryMode();
  return useQuery({
    queryKey: ["discoveryRun", demo, runId],
    queryFn: () => source.run(runId as string),
    enabled: enabled && Boolean(runId),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1500 : false),
  });
}

export function useLatestRun() {
  const { demo, enabled, source } = useDiscoveryMode();
  return useQuery({ queryKey: ["discoveryRun", demo, "latest"], queryFn: () => source.latest(), enabled, retry: false });
}
