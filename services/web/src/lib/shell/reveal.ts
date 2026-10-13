/**
 * Scroll reveal timing (pure). Elements that come into view in the same
 * observer batch are staggered so a grid of cards cascades instead of
 * popping in at once; the stagger is capped so the last card never waits long.
 */
export const REVEAL_STEP_MS = 40;
export const REVEAL_MAX_MS = 200;

export function revealDelays(count: number, step = REVEAL_STEP_MS, max = REVEAL_MAX_MS): number[] {
  return Array.from({ length: Math.max(0, count) }, (_, i) => Math.min(i * step, max));
}
