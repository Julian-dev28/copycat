"use client";

import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useScoutMode } from "@/hooks/useScout";
import { apiProblem } from "@/lib/trade/apiState";
import { demoAccount, type DemoAccount } from "@/lib/trade/fixtures";
import { demoTrade, liveTrade, type TradeSource } from "@/lib/trade/source";
import type { ProjectionQuery, TradeSettings, WalletCopyRequest, WalletStopRequest } from "@/lib/trade/types";
import { EVENTS_PAGE, nextBefore } from "@/lib/trade/walletEvents";

const demoSources = new Map<DemoAccount, TradeSource>();

/** `?demo=1` (plus `&acct=small|large`) swaps the api for the in-memory book. Needs a <Suspense> above it. */
export function useTradeMode(): { demo: boolean; acct: DemoAccount; source: TradeSource; enabled: boolean } {
  const { demo, enabled } = useScoutMode();
  const acct = demoAccount(useSearchParams().get("acct"));
  let source = liveTrade;
  if (demo) {
    source = demoSources.get(acct) ?? demoTrade(acct);
    demoSources.set(acct, source);
  }
  return { demo, acct, source, enabled };
}

/** Live keys are shared with the rest of the app (["settings"], ["status"]) so every page agrees. */
function keys(demo: boolean, acct: DemoAccount) {
  const d = ["trade", "demo", acct] as const;
  return {
    settings: demo ? [...d, "settings"] : ["settings"],
    status: demo ? [...d, "status"] : ["status"],
    wallets: demo ? [...d, "wallets"] : ["trade", "wallets"],
    preview: demo ? [...d, "preview"] : ["trade", "preview"],
    events: demo ? [...d, "events"] : ["trade", "events"],
    projection: demo ? [...d, "projection"] : ["trade", "projection"],
  };
}

const noRetryWhenTooOld = (n: number, err: unknown) => apiProblem(err) !== "too_old" && apiProblem(err) !== "unauthorized" && n < 1;

export function useTradeSettings() {
  const { demo, acct, source, enabled } = useTradeMode();
  return useQuery({ queryKey: keys(demo, acct).settings, queryFn: () => source.settings(), enabled, refetchInterval: 10_000 });
}

export function useTradeStatus() {
  const { demo, acct, source, enabled } = useTradeMode();
  return useQuery({ queryKey: keys(demo, acct).status, queryFn: () => source.status(), enabled, refetchInterval: 4_000 });
}

export function useWallets() {
  const { demo, acct, source, enabled } = useTradeMode();
  return useQuery({
    queryKey: keys(demo, acct).wallets,
    queryFn: () => source.wallets(),
    enabled,
    refetchInterval: 4_000,
    retry: noRetryWhenTooOld,
  });
}

function useInvalidateBook() {
  const { demo, acct } = useTradeMode();
  const qc = useQueryClient();
  const k = keys(demo, acct);
  return (result: unknown) => {
    // Most wallet routes answer the new Settings; archive answers the WalletPosition.
    if (result && typeof result === "object" && "leaders" in result) qc.setQueryData(k.settings, result as TradeSettings);
    else qc.invalidateQueries({ queryKey: k.settings });
    qc.invalidateQueries({ queryKey: k.status });
    qc.invalidateQueries({ queryKey: k.wallets });
    qc.invalidateQueries({ queryKey: k.events });
  };
}

export type LifecycleAction = "pause" | "resume" | "archive";

/** Pause / Resume / Archive one wallet (v8). */
export function useWalletLifecycle() {
  const { source } = useTradeMode();
  const done = useInvalidateBook();
  return useMutation({
    mutationFn: ({ address, action }: { address: string; action: LifecycleAction }) => source[action](address),
    onSuccess: done,
  });
}

/** One wallet's log, newest first, paged by before_ms. Polls the first page in demo; live adds SSE on top. */
export function useWalletEvents(address: string | null, active: boolean) {
  const { demo, acct, source, enabled } = useTradeMode();
  return useInfiniteQuery({
    queryKey: [...keys(demo, acct).events, address],
    queryFn: ({ pageParam }) => source.events(address!, { limit: EVENTS_PAGE, beforeMs: pageParam }),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (last) => nextBefore(last.events, EVENTS_PAGE),
    enabled: enabled && active && Boolean(address),
    refetchInterval: demo && active ? 4_000 : false,
    retry: noRetryWhenTooOld,
  });
}

/** The 30-day backtest for a ticket; polls every 3s while the api says it is building (202). */
export function useWalletProjection(address: string | null, q: ProjectionQuery | null) {
  const { demo, acct, source, enabled } = useTradeMode();
  const key = q ? JSON.stringify(q) : null;
  const debounced = useDebounced(key, 400);
  return useQuery({
    queryKey: [...keys(demo, acct).projection, address, debounced],
    queryFn: () => source.projection(address!, JSON.parse(debounced!) as ProjectionQuery),
    enabled: enabled && Boolean(address && debounced),
    placeholderData: keepPreviousData,
    staleTime: 60_000,
    refetchInterval: (query) => (query.state.data?.kind === "building" ? 3_000 : false),
    retry: noRetryWhenTooOld,
  });
}

export function useCopyWallet() {
  const { source } = useTradeMode();
  const done = useInvalidateBook();
  return useMutation({
    mutationFn: ({ address, body }: { address: string; body: WalletCopyRequest }) => source.copy(address, body),
    onSuccess: done,
  });
}

export function useStopWallet() {
  const { source } = useTradeMode();
  const done = useInvalidateBook();
  return useMutation({
    mutationFn: ({ address, body }: { address: string; body: WalletStopRequest }) => source.stop(address, body),
    onSuccess: done,
  });
}

export function usePatchTradeSettings() {
  const { source } = useTradeMode();
  const done = useInvalidateBook();
  return useMutation({ mutationFn: (patch: Partial<TradeSettings>) => source.patch(patch), onSuccess: done });
}

/** `value`, but only after it stopped changing for `ms`. setState runs in the timer, not the effect body. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [out, setOut] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setOut(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return out;
}

/** The engine's own preview for a ticket, debounced. Null body = nothing to preview. */
export function useWalletPreview(address: string | null, body: WalletCopyRequest | null) {
  const { demo, acct, source, enabled } = useTradeMode();
  const key = body ? JSON.stringify(body) : null;
  const debouncedKey = useDebounced(key, 300);
  const settled = debouncedKey === key;
  const q = useQuery({
    queryKey: [...keys(demo, acct).preview, address, debouncedKey],
    queryFn: () => source.preview(address!, JSON.parse(debouncedKey!) as WalletCopyRequest),
    enabled: enabled && Boolean(address && debouncedKey),
    placeholderData: keepPreviousData,
    staleTime: 10_000,
    retry: noRetryWhenTooOld,
  });
  return { ...q, settled };
}
