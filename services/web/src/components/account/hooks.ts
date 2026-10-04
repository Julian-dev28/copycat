"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState, useSyncExternalStore } from "react";
import { useScoutMode } from "@/hooks/useScout";
import { liveAccounts, type AccountSource } from "@/lib/account/api";
import { demoAccounts } from "@/lib/account/demo";
import { pickActive } from "@/lib/account/agent";
import { getManagerView, subscribeManager, type ManagerView } from "@/lib/account/managerStore";
import type { HistoryKind } from "@/lib/account/types";
import { isApiTooOld } from "@/lib/scout/api";

/** `?demo=1` swaps the api for the in-memory store. Needs a <Suspense> above it (useSearchParams). */
export function useAccountMode(): { demo: boolean; enabled: boolean; source: AccountSource } {
  const { demo, enabled } = useScoutMode();
  return { demo, enabled, source: demo ? demoAccounts : liveAccounts };
}

const retry = (n: number, err: unknown) => !isApiTooOld(err) && n < 1;
export const accountKeys = {
  all: (demo: boolean) => ["accounts", demo] as const,
  list: (demo: boolean) => ["accounts", demo, "list"] as const,
  summary: (demo: boolean, id: string) => ["accounts", demo, "summary", id] as const,
  history: (demo: boolean, id: string, kind: HistoryKind) => ["accounts", demo, "history", id, kind] as const,
};

export function useAccounts() {
  const { demo, enabled, source } = useAccountMode();
  return useQuery({ queryKey: accountKeys.list(demo), queryFn: () => source.list(), enabled, retry, refetchInterval: 60_000 });
}

/** GET /api/accounts/import-env: is the one-click .env migration available? Only asked when `ask`. */
export function useImportEnvStatus(ask: boolean) {
  const { demo, enabled, source } = useAccountMode();
  return useQuery({ queryKey: [...accountKeys.all(demo), "import-env"], queryFn: () => source.importEnvStatus(), enabled: enabled && ask, retry: false });
}

export function useActiveAccount() {
  const q = useAccounts();
  return { ...q, active: pickActive(q.data) };
}

export function useAccountSummary(id: string | null) {
  const { demo, enabled, source } = useAccountMode();
  return useQuery({
    queryKey: accountKeys.summary(demo, id ?? ""),
    queryFn: () => source.summary(id as string),
    enabled: enabled && Boolean(id),
    retry,
    refetchInterval: 30_000,
  });
}

export function useAccountHistory(id: string, kind: HistoryKind, active: boolean) {
  const { demo, enabled, source } = useAccountMode();
  return useQuery({
    queryKey: accountKeys.history(demo, id, kind),
    queryFn: () => source.history(id, kind),
    enabled: enabled && active,
    retry,
    staleTime: 20_000,
  });
}

/**
 * Runs one api call with local pending/error state. Used instead of
 * useMutation for anything carrying a secret: the mutation cache would keep
 * the variables (passphrase, keys) and the result (a created key) around.
 * Refreshes every account query on success.
 */
export function useAction() {
  const { demo } = useAccountMode();
  const qc = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const run = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
      setPending(true);
      setError(null);
      try {
        const out = await fn();
        void qc.invalidateQueries({ queryKey: accountKeys.all(demo) });
        return out;
      } catch (e) {
        setError(e);
        return undefined;
      } finally {
        setPending(false);
      }
    },
    [qc, demo],
  );
  return { run, pending, error, clearError: () => setError(null) };
}

const CLOSED: ManagerView = { view: "closed" };
export function useManagerView(): ManagerView {
  return useSyncExternalStore(subscribeManager, getManagerView, () => CLOSED);
}
