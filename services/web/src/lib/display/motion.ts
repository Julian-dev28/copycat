/**
 * Motion rules that need JS (DESIGN.md 3.7 and 4). CSS handles most of it
 * (globals.css); this covers the bits a component decides at runtime.
 */

export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/** Durations in ms, mirrored from the CSS tokens for JS timers. */
export const DURATION = { instant: 80, fast: 140, base: 220, slow: 320, flash: 900 } as const;
/** Exits run at 0.75x the enter duration (DESIGN 3.7). */
export const exitDuration = (enterMs: number) => Math.round(enterMs * 0.75);

type MatchMedia = (q: string) => Pick<MediaQueryList, "matches">;

export function prefersReducedMotion(mm: MatchMedia | undefined = typeof window === "undefined" ? undefined : window.matchMedia?.bind(window)): boolean {
  try {
    return Boolean(mm?.(REDUCED_MOTION_QUERY).matches);
  } catch {
    return false;
  }
}

/** A JS-driven duration: 0 under reduced motion, except opacity fades which keep 80ms. */
export function motionDuration(ms: number, reduced: boolean, kind: "move" | "fade" = "move"): number {
  if (!reduced) return ms;
  return kind === "fade" ? Math.min(ms, DURATION.instant) : 0;
}

/** At most one value-change flash per cell per 2s, so a fast feed does not strobe (DESIGN 4.4). */
export const FLASH_THROTTLE_MS = 2000;

export type FlashDirection = "up" | "down";

/**
 * Decides whether a value change should flash. Pure: the caller keeps
 * `lastAt` and passes `now`. Returns null when nothing should flash.
 */
export function nextFlash(
  prev: number | null | undefined,
  next: number | null | undefined,
  lastAt: number | null,
  now: number,
): FlashDirection | null {
  if (prev == null || next == null || !Number.isFinite(prev) || !Number.isFinite(next) || prev === next) return null;
  if (lastAt != null && now - lastAt < FLASH_THROTTLE_MS) return null;
  return next > prev ? "up" : "down";
}
