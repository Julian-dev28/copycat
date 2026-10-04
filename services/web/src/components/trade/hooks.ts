"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { useScoutMode } from "@/hooks/useScout";
import { apiProblem } from "@/lib/trade/apiState";
import { demoAccount, type DemoAccount } from "@/lib/trade/fixtures";
import { demoTrade, liveTrade, type TradeSource } from "@/lib/trade/source";
import type { TradeSettings, WalletCopyRequest, WalletStopRequest } from "@/lib/trade/types";

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
  return (settings: TradeSettings) => {
    qc.setQueryData(k.settings, settings);
    qc.invalidateQueries({ queryKey: k.status });
    qc.invalidateQueries({ queryKey: k.wallets });
  };
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
