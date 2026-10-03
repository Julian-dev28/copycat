"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { StartDiscoveryRunBody } from "@/lib/api/types";
import { useAuth } from "@/context/AuthContext";

export function useStartDiscoveryRun() {
  return useMutation({
    mutationFn: (body: StartDiscoveryRunBody) => api.startDiscoveryRun(body),
  });
}

/** Polls a run while it's in progress; stops polling once done/failed. */
export function useDiscoveryRun(runId: string | null) {
  const { hasToken } = useAuth();
  return useQuery({
    queryKey: ["discoveryRun", runId],
    queryFn: () => api.getDiscoveryRun(runId as string),
    enabled: hasToken && Boolean(runId),
    refetchInterval: (query) => (query.state.data?.status === "running" ? 1500 : false),
  });
}

export function useLatestDiscoveryRun() {
  const { hasToken } = useAuth();
  return useQuery({
    queryKey: ["discoveryRun", "latest"],
    queryFn: api.getLatestDiscoveryRun,
    enabled: hasToken,
    retry: false,
  });
}
