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
import { demoFileRow } from "./file/fixtures";
import {
  fixtureFills, fixtureOrders, fixturePage, fixturePresets, fixtureProfile, fixtureRows, fixtureStatus, fixtureWhatIf,
} from "./fixtures";
import type {
  CustomWallet, LeaderFillView, ScoutPresets, ScoutStatus, TraderPage, TraderProfile, TraderRow, WhatIfRequest, WhatIfResult,
} from "./types";

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
  /** v15: wallets added by hand (scored and simmed like the top 300, kept through refreshes). */
  customList(): Promise<CustomWallet[]>;
  customAdd(address: string): Promise<CustomWallet>;
  customRemove(address: string): Promise<void>;
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
  customList: () => apiFetch<CustomWallet[]>("/api/scout/custom"),
  customAdd: (address) =>
    apiFetch<CustomWallet>("/api/scout/custom", { method: "POST", body: JSON.stringify({ address: normAddr(address) }) }),
  customRemove: (address) => apiFetch<void>(`/api/scout/custom/${enc(address)}`, { method: "DELETE" }),
};

// ── demo ─────────────────────────────────────────────────────────────────────

let demoNow: number | null = null;
let demoRowsCache: TraderRow[] | null = null;

/** Demo clock, frozen at first use so the fixtures stay stable for the session. */
export function demoNowMs(): number {
  if (demoNow === null) demoNow = Math.floor(Date.now() / 60_000) * 60_000;
  return demoNow;
}

/**
 * Demo custom wallets: in memory for the session, never sent anywhere. An
 * address already on the fixture board is just marked `custom`; any other
 * valid address gets a deterministic row (the trader file's demoFileRow) so
 * the board row and the file exist at once, like the api after its build.
 */
const DEMO_CUSTOM_KEY = "copycat.demo.custom";
let demoCustomCache: Map<string, number> | null = null;   // address -> added_ms

/** The session's demo custom wallets. sessionStorage so a reload keeps them; absent or blocked storage = none. */
function demoCustom(): Map<string, number> {
  if (demoCustomCache) return demoCustomCache;
  demoCustomCache = new Map();
  try {
    const raw = typeof sessionStorage === "undefined" ? null : sessionStorage.getItem(DEMO_CUSTOM_KEY);
    for (const [a, t] of Object.entries(JSON.parse(raw ?? "{}") as Record<string, unknown>)) {
      if (typeof t === "number") demoCustomCache.set(normAddr(a), t);
    }
  } catch {
    /* no storage, or junk in it: start empty */
  }
  return demoCustomCache;
}

function saveDemoCustom(): void {
  try {
    sessionStorage.setItem(DEMO_CUSTOM_KEY, JSON.stringify(Object.fromEntries(demoCustom())));
  } catch {
    /* storage blocked: the in-memory map still works for this page */
  }
}

/** Test hook: forget every demo custom wallet. */
export function resetDemoCustom(): void {
  demoCustomCache = new Map();
  saveDemoCustom();
}

function demoRows(): TraderRow[] {
  if (!demoRowsCache) demoRowsCache = fixtureRows(demoNowMs());
  const custom = demoCustom();
  if (!custom.size) return demoRowsCache;
  const onBoard = new Set(demoRowsCache.map((r) => r.address));
  return [
    ...demoRowsCache.map((r) => (custom.has(r.address) ? { ...r, custom: true } : r)),
    ...[...custom.keys()].filter((a) => !onBoard.has(a)).map((a) => ({ ...demoFileRow(a, demoNowMs()), custom: true })),
  ];
}

function demoCustomView(address: string): CustomWallet {
  return { address, added_ms: demoCustom().get(address) ?? 0, on_board: true, queued: false };
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
  customList: () => later([...demoCustom().keys()].map(demoCustomView)),
  customAdd: (address) => {
    const a = normAddr(address);
    if (!demoCustom().has(a)) {
      demoCustom().set(a, Date.now());
      saveDemoCustom();
    }
    return later(demoCustomView(a), 200);
  },
  customRemove: (address) => {
    demoCustom().delete(normAddr(address));
    saveDemoCustom();
    return later(undefined);
  },
};

/**
 * True when the api is reachable but cannot serve Scout: 404/405 (a build
 * that predates /api/scout/*) or 503 (the route exists but the discovery
 * service behind it is not running yet).
 */
export function isApiTooOld(err: unknown): boolean {
  return isNotSupported(err) || (err instanceof ApiError && err.status === 503);
}
