"use client";

import { useInfiniteQuery, useMutation, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { useScoutMode } from "@/hooks/useScout";
import { normAddr } from "@/lib/address";
import { demoNowMs, isApiTooOld } from "@/lib/scout/api";
import { demoFile, liveFile, type FileSource } from "@/lib/scout/file/source";
import type { WhatIfRequest } from "@/lib/scout/types";

export const FILLS_PAGE = 50;

function useFileSource(): { demo: boolean; enabled: boolean; source: FileSource } {
  const { demo, enabled } = useScoutMode();
  const source = useMemo(() => (demo ? demoFile(demoNowMs()) : liveFile), [demo]);
  return { demo, enabled, source };
}

const retry = (count: number, err: unknown) => !isApiTooOld(err) && count < 1;

export function useFileProfile(address: string) {
  const { demo, enabled, source } = useFileSource();
  return useQuery({
    queryKey: ["scout", "file", "profile", demo, normAddr(address)],
    queryFn: () => source.profile(address),
    enabled,
    retry,
    refetchInterval: (q) => (q.state.error ? false : q.state.data?.kind === "building" ? 3_000 : 60_000),
  });
}

export function useFileFills(address: string, active: boolean) {
  const { demo, enabled, source } = useFileSource();
  return useInfiniteQuery({
    queryKey: ["scout", "file", "fills", demo, normAddr(address)],
    queryFn: ({ pageParam }) => source.fills(address, pageParam, FILLS_PAGE),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => (last.length < FILLS_PAGE ? undefined : last[last.length - 1].time_ms),
    enabled: enabled && active,
    staleTime: 30_000,
    retry,
  });
}

export function useFileOrders(address: string, active: boolean) {
  const { demo, enabled, source } = useFileSource();
  return useQuery({
    queryKey: ["scout", "file", "orders", demo, normAddr(address)],
    queryFn: () => source.orders(address),
    enabled: enabled && active,
    staleTime: 30_000,
    retry,
  });
}

export function useFileWhatIf(address: string) {
  const { source } = useFileSource();
  return useMutation({ mutationFn: (body: WhatIfRequest) => source.whatIf(address, body) });
}

export function useFingerprint(address: string, active: boolean) {
  const { demo, enabled, source } = useFileSource();
  return useQuery({
    queryKey: ["scout", "file", "fingerprint", demo, normAddr(address)],
    queryFn: () => source.fingerprint(address),
    enabled: enabled && active,
    retry,
    staleTime: 5 * 60_000,
    refetchInterval: (q) => (q.state.data?.kind === "building" ? 3_000 : false),
  });
}

export function useTheses(address: string, active: boolean) {
  const { demo, enabled, source } = useFileSource();
  return useQuery({
    queryKey: ["scout", "file", "theses", demo, normAddr(address)],
    queryFn: () => source.theses(address),
    enabled: enabled && active,
    retry,
    staleTime: 60_000,
  });
}
