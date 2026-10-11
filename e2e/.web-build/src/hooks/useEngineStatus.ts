"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { useAuth } from "@/context/AuthContext";

const STATUS_KEY = ["status"] as const;

/** Engine status (running, equity, positions, halt reason). Polled — not an SSE field. */
export function useEngineStatus() {
  const { hasToken } = useAuth();
  return useQuery({
    queryKey: STATUS_KEY,
    queryFn: api.getStatus,
    enabled: hasToken,
    refetchInterval: 4000,
  });
}

export function useHaltEngine() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.haltEngine,
    onSuccess: (settings) => {
      // The route flips Settings.enabled and returns the new Settings, not EngineStatus.
      qc.setQueryData(["settings"], settings);
      qc.invalidateQueries({ queryKey: STATUS_KEY });
    },
  });
}

/** POST /api/engine/close-all. Check isNotSupported(error) for an api that predates the route. */
export function useCloseAllCopies() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.closeAllCopies,
    onSettled: () => {
      qc.invalidateQueries({ queryKey: STATUS_KEY });
    },
  });
}
