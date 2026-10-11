"use client";

import { useCallback, useSyncExternalStore } from "react";
import {
  DEFAULT_PNL_MODE,
  PNL_MODE_EVENT,
  PNL_MODE_STORAGE_KEY,
  readPnlMode,
  writePnlMode,
  type PnlMode,
} from "@/lib/display/pnlMode";

function subscribe(cb: () => void) {
  const onStorage = (e: StorageEvent) => {
    if (e.key === PNL_MODE_STORAGE_KEY) {
      // another tab changed it: apply here too
      document.documentElement.dataset.pnl = readPnlMode();
      cb();
    }
  };
  window.addEventListener(PNL_MODE_EVENT, cb);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(PNL_MODE_EVENT, cb);
    window.removeEventListener("storage", onStorage);
  };
}

/** The PnL color mode and its setter (stored per browser, applied as data-pnl on <html>). */
export function usePnlMode(): [PnlMode, (mode: PnlMode) => void] {
  const mode = useSyncExternalStore(subscribe, () => readPnlMode(), () => DEFAULT_PNL_MODE);
  const set = useCallback((m: PnlMode) => writePnlMode(m), []);
  return [mode, set];
}
