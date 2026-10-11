"use client";

import { useEffect, useState } from "react";

/** Wall clock that re-renders every `intervalMs`, for "last active 4m ago" labels. Same pattern as EngineStatusBar. */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
