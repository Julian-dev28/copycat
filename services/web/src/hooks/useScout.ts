"use client";

import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { useAddLeader, usePatchSettings, useSettings } from "@/hooks/useSettings";
import { normAddr } from "@/lib/address";
import { MAX_LEADERS, type LeaderOverride, type Settings, type SettingsPatch } from "@/lib/api/types";
import { applySettingsPatch } from "@/lib/settings";
import { demoNowMs, demoScout, isApiTooOld, liveScout, type ScoutSource } from "@/lib/scout/api";
import { fixtureSettings } from "@/lib/scout/fixtures";
import type { ScoutSimTerms, WhatIfRequest } from "@/lib/scout/types";

/** `?demo=1` swaps the api for fixtures. Must render under a <Suspense> (useSearchParams). */
export function useScoutMode(): { demo: boolean; source: ScoutSource; enabled: boolean } {
  const sp = useSearchParams();
  const { hasToken, unauthorized } = useAuth();
  const demo = sp.get("demo") === "1";
  return { demo, source: demo ? demoScout : liveScout, enabled: demo || (hasToken && !unauthorized) };
}

const noRetryOnTooOld = (count: number, err: unknown) => !isApiTooOld(err) && count < 1;

export function useScoutTraders(apiQuery: string) {
  const { demo, source, enabled } = useScoutMode();
  return useQuery({
    queryKey: ["scout", "traders", demo, apiQuery],
    queryFn: () => source.traders(apiQuery),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    retry: noRetryOnTooOld,
  });
}

export function useScoutStatus() {
  const { demo, source, enabled } = useScoutMode();
  return useQuery({
    queryKey: ["scout", "status", demo],
    queryFn: () => source.status(),
    enabled,
    retry: noRetryOnTooOld,
    refetchInterval: (q) => (q.state.error ? false : q.state.data?.state === "running" ? 3_000 : 30_000),
  });
}

export function useScoutPresets() {
  const { demo, source, enabled } = useScoutMode();
  return useQuery({
    queryKey: ["scout", "presets", demo],
    queryFn: () => source.presets(),
    enabled,
    staleTime: 5 * 60_000,
    retry: noRetryOnTooOld,
  });
}

export function useScoutRefresh() {
  const { source } = useScoutMode();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => source.refresh(),
    onSuccess: (status, _v) => qc.setQueriesData({ queryKey: ["scout", "status"] }, status),
  });
}

export function useScoutProfile(address: string) {
  const { demo, source, enabled } = useScoutMode();
  return useQuery({
    queryKey: ["scout", "profile", demo, normAddr(address)],
    queryFn: () => source.profile(address),
    enabled,
    retry: noRetryOnTooOld,
    // building on demand: poll until ready; ready: positions go stale after 60s (spec 7.3)
    refetchInterval: (q) => (q.state.data?.kind === "building" ? 3_000 : 60_000),
  });
}

export const FILLS_PAGE = 50;

export function useScoutFills(address: string, active: boolean) {
  const { demo, source, enabled } = useScoutMode();
  return useInfiniteQuery({
    queryKey: ["scout", "fills", demo, normAddr(address)],
    queryFn: ({ pageParam }) => source.fills(address, pageParam, FILLS_PAGE),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => (last.length < FILLS_PAGE ? undefined : last[last.length - 1].time_ms),
    enabled: enabled && active,
    staleTime: 30_000,
    retry: noRetryOnTooOld,
  });
}

export function useScoutOrders(address: string, active: boolean) {
  const { demo, source, enabled } = useScoutMode();
  return useQuery({
    queryKey: ["scout", "orders", demo, normAddr(address)],
    queryFn: () => source.orders(address),
    enabled: enabled && active,
    staleTime: 30_000,
    retry: noRetryOnTooOld,
  });
}

export function useWhatIf(address: string) {
  const { source } = useScoutMode();
  return useMutation({ mutationFn: (body: WhatIfRequest) => source.whatIf(address, body) });
}

// ── custom wallets (v15) ─────────────────────────────────────────────────────

/** Every wallet added by hand (GET /api/scout/custom). */
export function useScoutCustom() {
  const { demo, source, enabled } = useScoutMode();
  return useQuery({
    queryKey: ["scout", "custom", demo],
    queryFn: () => source.customList(),
    enabled,
    staleTime: 30_000,
    retry: noRetryOnTooOld,
  });
}

/** What an add or remove changes: the board, its preset counts, the custom list and both profile views. */
const CUSTOM_DEPENDENTS = [["scout", "traders"], ["scout", "presets"], ["scout", "custom"], ["scout", "profile"], ["scout", "file", "profile"]];

function useInvalidateCustom() {
  const qc = useQueryClient();
  return () => Promise.all(CUSTOM_DEPENDENTS.map((queryKey) => qc.invalidateQueries({ queryKey })));
}

export function useAddCustomWallet() {
  const { source } = useScoutMode();
  const invalidate = useInvalidateCustom();
  return useMutation({ mutationFn: (address: string) => source.customAdd(address), onSuccess: () => invalidate() });
}

export function useRemoveCustomWallet() {
  const { source } = useScoutMode();
  const invalidate = useInvalidateCustom();
  return useMutation({ mutationFn: (address: string) => source.customRemove(address), onSuccess: () => invalidate() });
}

// ── sim terms (v16) ──────────────────────────────────────────────────────────

export function useScoutSimTerms() {
  const { demo, source, enabled } = useScoutMode();
  return useQuery({
    queryKey: ["scout", "sim-terms", demo],
    queryFn: () => source.simTerms(),
    enabled,
    staleTime: 30_000,
    retry: noRetryOnTooOld,
  });
}

/** Changing terms re-ranks the whole board: everything the toolbar/page show from it. */
const SIM_TERMS_DEPENDENTS = [["scout", "traders"], ["scout", "presets"], ["scout", "status"]];

export function useSetScoutSimTerms() {
  const { source } = useScoutMode();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (terms: ScoutSimTerms) => source.putSimTerms(terms),
    onSuccess: (terms) => {
      qc.setQueriesData({ queryKey: ["scout", "sim-terms"] }, terms);
      for (const queryKey of SIM_TERMS_DEPENDENTS) qc.invalidateQueries({ queryKey });
    },
  });
}

const DEMO_SETTINGS_KEY = ["scout", "demo-settings"] as const;

export interface ScoutBook {
  ready: boolean;
  leaders: string[];
  overrides: Record<string, LeaderOverride>;
  atCap: boolean;
  inBook: (address: string) => boolean;
  add: (address: string) => void;
  /** Address currently being added, for the button's pending state. */
  adding: string | null;
  addError: Error | null;
  saveOverride: (patch: SettingsPatch) => Promise<unknown>;
  savingOverride: boolean;
  saveError: Error | null;
}

/**
 * The user's book (Settings.leaders + overrides) for Scout's buttons. Live:
 * the shared settings query and mutations (optimistic, rolled back on error).
 * Demo: an in-memory copy seeded from fixtures, so "Add to book" works with
 * no api and never touches real settings.
 */
export function useScoutBook(): ScoutBook {
  const { demo } = useScoutMode();
  const qc = useQueryClient();
  const live = useSettings();
  const addLive = useAddLeader();
  const patchLive = usePatchSettings();
  const demoSettings = useQuery({
    queryKey: DEMO_SETTINGS_KEY,
    queryFn: () => fixtureSettings(demoNowMs()),
    enabled: demo,
    staleTime: Infinity,
    gcTime: Infinity,
  });
  const addDemo = useMutation<Settings, Error, string>({
    mutationFn: async (address) => {
      const cur = qc.getQueryData<Settings>(DEMO_SETTINGS_KEY) ?? fixtureSettings(demoNowMs());
      if (cur.leaders.length >= MAX_LEADERS) throw new Error(`you already copy ${MAX_LEADERS} traders, the most allowed`);
      const next = { ...cur, leaders: [...new Set([...cur.leaders, normAddr(address)])] };
      await new Promise((r) => setTimeout(r, 250));
      return next;
    },
    onSuccess: (s) => qc.setQueryData(DEMO_SETTINGS_KEY, s),
  });
  const patchDemo = useMutation<Settings, Error, SettingsPatch>({
    mutationFn: async (patch) => applySettingsPatch(qc.getQueryData<Settings>(DEMO_SETTINGS_KEY) ?? fixtureSettings(demoNowMs()), patch),
    onSuccess: (s) => qc.setQueryData(DEMO_SETTINGS_KEY, s),
  });
  const [adding, setAdding] = useState<string | null>(null);

  const settings = demo ? demoSettings.data : live.data;
  const add = demo ? addDemo : addLive;
  const patch = demo ? patchDemo : patchLive;

  return useMemo<ScoutBook>(() => {
    const leaders = settings?.leaders ?? [];
    return {
      ready: Boolean(settings),
      leaders,
      overrides: settings?.leader_overrides ?? {},
      atCap: leaders.length >= MAX_LEADERS,
      inBook: (a) => leaders.includes(normAddr(a)),
      add: (a) => {
        setAdding(normAddr(a));
        add.mutate(normAddr(a), { onSettled: () => setAdding(null) });
      },
      adding,
      addError: add.error,
      saveOverride: (p) => patch.mutateAsync(p),
      savingOverride: patch.isPending,
      saveError: patch.error,
    };
  }, [settings, add, patch, adding]);
}
