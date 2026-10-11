"use client";

import { useSyncExternalStore } from "react";
import { prefersReducedMotion, REDUCED_MOTION_QUERY } from "@/lib/display/motion";

function subscribe(cb: () => void) {
  if (typeof window === "undefined" || !window.matchMedia) return () => {};
  const mq = window.matchMedia(REDUCED_MOTION_QUERY);
  mq.addEventListener?.("change", cb);
  return () => mq.removeEventListener?.("change", cb);
}

/** True when the OS asks for reduced motion. SSR renders as "reduced" so nothing animates before hydration. */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, () => prefersReducedMotion(), () => true);
}
