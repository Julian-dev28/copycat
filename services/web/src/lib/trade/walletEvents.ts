/**
 * The per-wallet log: GET /api/wallets/{a}/events?limit=&before_ms=, newest
 * first, paged by before_ms, merged with live SSE events for that wallet.
 * Pre-v8 apis have no route: then the drawer reads the shared /api/events
 * tail and filters it here. Pure, unit-tested.
 */
import { normAddr } from "@/lib/address";
import type { EngineEvent } from "@/lib/api/types";

export const EVENTS_PAGE = 50;

/** The route answers a list, or { events: [...] }; anything else is no events. */
export function normalizeEvents(raw: unknown): EngineEvent[] {
  const list = Array.isArray(raw) ? raw : raw && typeof raw === "object" && Array.isArray((raw as { events?: unknown }).events) ? (raw as { events: unknown[] }).events : [];
  return list.filter((e): e is EngineEvent => Boolean(e) && typeof e === "object" && typeof (e as EngineEvent).ts_ms === "number" && typeof (e as EngineEvent).action === "string");
}

/** before_ms for the next page, or undefined when this page was the last. */
export function nextBefore(page: EngineEvent[], limit = EVENTS_PAGE): number | undefined {
  if (page.length < limit) return undefined;
  return Math.min(...page.map((e) => e.ts_ms));
}

export const eventKey = (e: EngineEvent): string => `${e.ts_ms}:${e.action}:${e.leader ?? ""}:${e.coin ?? ""}:${e.reason ?? ""}`;

export function forWallet(events: EngineEvent[], address: string): EngineEvent[] {
  const a = normAddr(address);
  return events.filter((e) => e.leader && normAddr(e.leader) === a);
}

/** Live + paged, one wallet, deduped, newest first. */
export function mergeEvents(live: EngineEvent[], pages: EngineEvent[][], address: string): EngineEvent[] {
  const seen = new Set<string>();
  const out: EngineEvent[] = [];
  for (const e of [...forWallet(live, address), ...pages.flat()]) {
    const k = eventKey(e);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(e);
  }
  return out.sort((a, b) => b.ts_ms - a.ts_ms);
}

/** One page of a client-side filtered list (the pre-v8 fallback and the demo). */
export function pageOf(events: EngineEvent[], limit: number, beforeMs?: number): EngineEvent[] {
  return [...events]
    .sort((a, b) => b.ts_ms - a.ts_ms)
    .filter((e) => beforeMs === undefined || e.ts_ms < beforeMs)
    .slice(0, limit);
}

export type EventKind = "open" | "add" | "reduce" | "close" | "skip" | "other";
export type EventFilter = "all" | "trades" | "skips";

export function eventKind(e: EngineEvent): EventKind {
  return e.action === "open" || e.action === "add" || e.action === "reduce" || e.action === "close" || e.action === "skip" ? e.action : "other";
}

export function matchesFilter(e: EngineEvent, f: EventFilter): boolean {
  const k = eventKind(e);
  if (f === "trades") return k === "open" || k === "add" || k === "reduce" || k === "close";
  if (f === "skips") return k === "skip";
  return true;
}

const VERB: Record<EventKind, string> = { open: "Opened", add: "Added to", reduce: "Reduced", close: "Closed", skip: "Skipped", other: "" };

/** "Opened BTC short" / "Skipped ETH: filtered: on Never these coins". */
export function eventLine(e: EngineEvent): string {
  const k = eventKind(e);
  const what = [e.coin, e.side].filter(Boolean).join(" ");
  if (k === "other") return [e.action, what].filter(Boolean).join(" ");
  if (k === "skip") return `${VERB.skip}${what ? ` ${what}` : ""}${e.reason ? `: ${e.reason}` : ""}`;
  return `${VERB[k]} ${what}`.trim();
}
