/** Typed confirmation for "Close all copies" on /positions. */
export const CLOSE_ALL_PHRASE = "CLOSE";

/** Exact match only: no trimming, no case folding. A real-money action should take deliberate typing. */
export function closeAllConfirmed(typed: string): boolean {
  return typed === CLOSE_ALL_PHRASE;
}
