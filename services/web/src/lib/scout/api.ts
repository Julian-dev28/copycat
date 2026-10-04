/**
 * Scout endpoints (spec section 8), with two interchangeable sources:
 *   - liveScout: HTTP to services/api through apiFetch (bearer token, 401 handling)
 *   - demoScout: the deterministic fixtures, for `?demo=1` (no api, no token)
 * Both return the same shapes, so hooks and components never branch on mode.
 */
import { apiFetch, ApiError, isNotSupported } from "@/lib/api/client";
import { normAddr } from "@/lib/address";
import { applyBoardQuery, normalizePresets, parseBoardState, type BoardState } from "./query";
import { normalizeOrders, type OpenOrderView } from "./labels";
import {
  fixtureFills, fixtureOrders, fixturePage, fixturePresets, fixtureProfile, fixtureRows, fixtureStatus, fixtureWhatIf,
} from "./fixtures";
import type { LeaderFillView, ScoutPresets, ScoutStatus, TraderPage, TraderProfile, TraderRow, WhatIfRequest, WhatIfResult } from "./types";

/** A trader file is either ready, or being built on demand (202 + ScoutStatus, spec 7.3). */
export type ProfileResult = { kind: "ready"; profile: TraderProfile } | { kind: "building"; status: ScoutStatus };

export interface ScoutSource {
  traders(query: string): Promise<TraderPage>;
  profile(address: string): Promise<ProfileResult>;
  fills(address: string, beforeMs: number | null, limit: number): Promise<LeaderFillView[]>;
  orders(address: string): Promise<OpenOrderView[]>;
  whatIf(address: string, body: WhatIfRequest): Promise<WhatIfResult>;
  presets(): Promise<ScoutPresets>;
  status(): Promise<ScoutStatus>;
  refresh(): Promise<ScoutStatus>;
}

const enc = (a: string) => encodeURIComponent(normAddr(a));

function isProfile(x: unknown): x is TraderProfile {
  return Boolean(x && typeof x === "object" && "row" in x && "account" in x);
}

export const liveScout: ScoutSource = {
  traders: (query) => apiFetch<TraderPage>(`/api/scout/traders?${query}`),
  profile: async (address) => {
    const res = await apiFetch<unknown>(`/api/scout/traders/${enc(address)}`);
    if (isProfile(res)) return { kind: "ready", profile: res };
    if (res && typeof res === "object" && "state" in res) return { kind: "building", status: res as ScoutStatus };
    throw new ApiError(500, "the api returned something that is not a trader file");
  },
  fills: (address, beforeMs, limit) => {
    const p = new URLSearchParams({ limit: String(limit) });
    if (beforeMs !== null) p.set("before_ms", String(beforeMs));
    return apiFetch<LeaderFillView[]>(`/api/scout/traders/${enc(address)}/fills?${p}`);
  },
  orders: async (address) => normalizeOrders(await apiFetch<unknown>(`/api/scout/traders/${enc(address)}/orders`)),
  whatIf: (address, body) =>
    apiFetch<WhatIfResult>(`/api/scout/traders/${enc(address)}/what-if`, { method: "POST", body: JSON.stringify(body) }),
  presets: async () => normalizePresets(await apiFetch<unknown>("/api/scout/presets")),
  status: () => apiFetch<ScoutStatus>("/api/scout/status"),
  refresh: () => apiFetch<ScoutStatus>("/api/scout/refresh", { method: "POST" }),
};

// ── demo ─────────────────────────────────────────────────────────────────────

let demoNow: number | null = null;
let demoRowsCache: TraderRow[] | null = null;

/** Demo clock, frozen at first use so the fixtures stay stable for the session. */
export function demoNowMs(): number {
  if (demoNow === null) demoNow = Math.floor(Date.now() / 60_000) * 60_000;
  return demoNow;
}

function demoRows(): TraderRow[] {
  if (!demoRowsCache) demoRowsCache = fixtureRows(demoNowMs());
  return demoRowsCache;
}

function demoRow(address: string): TraderRow {
  const row = demoRows().find((r) => r.address === normAddr(address));
  if (!row) throw new ApiError(404, "no trader with that address in the demo board");
  return row;
}

const later = <T>(v: T, ms = 0) => new Promise<T>((resolve) => setTimeout(() => resolve(v), ms));

export const demoScout: ScoutSource = {
  traders: (query) => {
    const state: BoardState = parseBoardState(new URLSearchParams(query));
    const { rows, total } = applyBoardQuery(demoRows(), state, demoNowMs());
    return later(fixturePage(rows, total, demoNowMs()));
  },
  profile: (address) => later({ kind: "ready" as const, profile: fixtureProfile(demoRow(address), demoNowMs()) }),
  fills: (address, beforeMs, limit) => later(fixtureFills(demoRow(address), demoNowMs(), beforeMs, limit)),
  orders: (address) => later(normalizeOrders(fixtureOrders(demoRow(address), demoNowMs()))),
  whatIf: (address, body) => later(fixtureWhatIf(fixtureProfile(demoRow(address), demoNowMs()), body), 350),
  presets: () => later(normalizePresets(fixturePresets(demoRows()))),
  status: () => later(fixtureStatus(demoNowMs())),
  refresh: () => later({ ...fixtureStatus(demoNowMs()), state: "running" as const, stage: "stats" as const, done: 40, total: 280, eta_s: 1260 }),
};

/**
 * True when the api is reachable but cannot serve Scout: 404/405 (a build
 * that predates /api/scout/*) or 503 (the route exists but the discovery
 * service behind it is not running yet).
 */
export function isApiTooOld(err: unknown): boolean {
  return isNotSupported(err) || (err instanceof ApiError && err.status === 503);
}
