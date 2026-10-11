"use client";

import { useSyncExternalStore } from "react";
import { demoQuery } from "@/lib/shell/nav";

const noopSubscribe = () => () => {};

/**
 * "?demo=1[&acct=..]" when demo mode is on, else "". Read at render without
 * useSearchParams (no Suspense needed); client navigation re-renders the shell.
 */
export function useDemoQuery(): string {
  return useSyncExternalStore(noopSubscribe, () => demoQuery(window.location.search), () => "");
}

/** false during SSR/hydration, true on the client. */
export function useMounted(): boolean {
  return useSyncExternalStore(noopSubscribe, () => true, () => false);
}
