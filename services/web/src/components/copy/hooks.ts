"use client";

import { useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTradeMode } from "@/components/trade/hooks";
import type { Settings, SettingsPatch } from "@/lib/api/types";
import { applySettingsPatch } from "@/lib/settings";
import { demoSettingsSource, liveSettingsSource, type SettingsSource } from "./settingsSource";

/**
 * /settings data, demo-aware. Live keys are the app-wide ["settings"] /
 * ["status"] (Halt, Close all and Trade write those); demo keys are per demo
 * account. Needs a <Suspense> above it (useSearchParams via useTradeMode).
 */
export function useSettingsMode(): { demo: boolean; enabled: boolean; source: SettingsSource; keys: { settings: readonly unknown[]; status: readonly unknown[] } } {
  const { demo, acct, source: trade, enabled } = useTradeMode();
  const source = useMemo(() => (demo ? demoSettingsSource(trade) : liveSettingsSource), [demo, trade]);
  const keys = useMemo(
    () => (demo
      ? { settings: ["settings", "demo", acct] as const, status: ["status", "demo", acct] as const }
      : { settings: ["settings"] as const, status: ["status"] as const }),
    [demo, acct],
  );
  return { demo, enabled, source, keys };
}

export function useModeSettings() {
  const { enabled, source, keys } = useSettingsMode();
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => source.settings(),
    enabled,
    refetchInterval: 10_000,
    refetchOnWindowFocus: true,
  });
}

export function useModeStatus() {
  const { enabled, source, keys } = useSettingsMode();
  return useQuery({ queryKey: keys.status, queryFn: () => source.status(), enabled, refetchInterval: 4000 });
}

interface Ctx {
  previous?: Settings;
}

/** One optimistic settings write (apply now, roll back on error, take the server's answer). */
function useSettingsWrite<V>(run: (s: SettingsSource, v: V) => Promise<Settings>, optimistic: (s: Settings, v: V) => Settings) {
  const qc = useQueryClient();
  const { source, keys } = useSettingsMode();
  return useMutation<Settings, Error, V, Ctx>({
    mutationFn: (v) => run(source, v),
    onMutate: async (v) => {
      await qc.cancelQueries({ queryKey: keys.settings });
      const previous = qc.getQueryData<Settings>(keys.settings);
      if (previous) qc.setQueryData<Settings>(keys.settings, optimistic(previous, v));
      return { previous };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData(keys.settings, ctx.previous);
    },
    onSuccess: (data) => qc.setQueryData(keys.settings, data),
  });
}

export function useModePatchSettings() {
  return useSettingsWrite<SettingsPatch>((s, p) => s.patch(p), applySettingsPatch);
}

export function useModeAddLeader() {
  return useSettingsWrite<string>(
    (s, a) => s.addLeader(a),
    (prev, a) => (prev.leaders.includes(a) ? prev : { ...prev, leaders: [...prev.leaders, a] }),
  );
}

export function useModeRemoveLeader() {
  return useSettingsWrite<string>(
    (s, a) => s.removeLeader(a),
    (prev, a) => {
      const { [a]: _gone, ...rest } = prev.leader_overrides;
      return { ...prev, leaders: prev.leaders.filter((x) => x !== a), leader_overrides: rest };
    },
  );
}
