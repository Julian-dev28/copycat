"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { Settings, SettingsPatch } from "@/lib/api/types";
import { applySettingsPatch } from "@/lib/settings";
import { useAuth } from "@/context/AuthContext";

const SETTINGS_KEY = ["settings"] as const;

export function useSettings() {
  const { hasToken } = useAuth();
  return useQuery({
    queryKey: SETTINGS_KEY,
    queryFn: api.getSettings,
    enabled: hasToken,
  });
}

interface MutationContext {
  previous?: Settings;
}

/** PATCH with optimistic apply + rollback on error. See lib/settings.ts for the merge rule. */
export function usePatchSettings() {
  const qc = useQueryClient();
  return useMutation<Settings, Error, SettingsPatch, MutationContext>({
    mutationFn: (patch) => api.patchSettings(patch),
    onMutate: async (patch) => {
      await qc.cancelQueries({ queryKey: SETTINGS_KEY });
      const previous = qc.getQueryData<Settings>(SETTINGS_KEY);
      if (previous) {
        qc.setQueryData<Settings>(SETTINGS_KEY, applySettingsPatch(previous, patch));
      }
      return { previous };
    },
    onError: (_err, _patch, context) => {
      if (context?.previous) qc.setQueryData(SETTINGS_KEY, context.previous);
    },
    onSuccess: (data) => {
      qc.setQueryData(SETTINGS_KEY, data);
    },
  });
}

export function useAddLeader() {
  const qc = useQueryClient();
  return useMutation<Settings, Error, string, MutationContext>({
    mutationFn: (address) => api.addLeader(address),
    onMutate: async (address) => {
      await qc.cancelQueries({ queryKey: SETTINGS_KEY });
      const previous = qc.getQueryData<Settings>(SETTINGS_KEY);
      if (previous && previous.leaders.length < 10 && !previous.leaders.includes(address.toLowerCase())) {
        qc.setQueryData<Settings>(SETTINGS_KEY, {
          ...previous,
          leaders: [...previous.leaders, address.toLowerCase()],
        });
      }
      return { previous };
    },
    onError: (_err, _address, context) => {
      if (context?.previous) qc.setQueryData(SETTINGS_KEY, context.previous);
    },
    onSuccess: (data) => qc.setQueryData(SETTINGS_KEY, data),
  });
}

export function useRemoveLeader() {
  const qc = useQueryClient();
  return useMutation<Settings, Error, string, MutationContext>({
    mutationFn: (address) => api.removeLeader(address),
    onMutate: async (address) => {
      await qc.cancelQueries({ queryKey: SETTINGS_KEY });
      const previous = qc.getQueryData<Settings>(SETTINGS_KEY);
      if (previous) {
        const { [address]: _dropped, ...restOverrides } = previous.leader_overrides;
        qc.setQueryData<Settings>(SETTINGS_KEY, {
          ...previous,
          leaders: previous.leaders.filter((a) => a !== address),
          leader_overrides: restOverrides,
        });
      }
      return { previous };
    },
    onError: (_err, _address, context) => {
      if (context?.previous) qc.setQueryData(SETTINGS_KEY, context.previous);
    },
    onSuccess: (data) => qc.setQueryData(SETTINGS_KEY, data),
  });
}
