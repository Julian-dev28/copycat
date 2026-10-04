/**
 * Trader-file data source. Live: the shared liveScout routes plus the
 * Strategy routes (GET .../fingerprint, GET .../thesis). Demo: fixtures that
 * accept any valid address, so a pasted 0x link works under `?demo=1`.
 */
import { apiFetch, ApiError } from "@/lib/api/client";
import { isValidAddress, normAddr } from "@/lib/address";
import { liveScout, type ProfileResult } from "../api";
import { fixtureFills, fixtureOrders, fixtureProfile, fixtureWhatIf } from "../fixtures";
import { normalizeOrders, type OpenOrderView } from "../labels";
import type { LeaderFillView, ScoutStatus, StrategyFingerprint, Thesis, WhatIfRequest, WhatIfResult } from "../types";
import { demoFileRow, fixtureFingerprint, fixtureTheses } from "./fixtures";

export type FingerprintResult = { kind: "ready"; fingerprint: StrategyFingerprint } | { kind: "building"; status: ScoutStatus };

export interface FileSource {
  profile(address: string): Promise<ProfileResult>;
  fills(address: string, beforeMs: number | null, limit: number): Promise<LeaderFillView[]>;
  orders(address: string): Promise<OpenOrderView[]>;
  whatIf(address: string, body: WhatIfRequest): Promise<WhatIfResult>;
  fingerprint(address: string): Promise<FingerprintResult>;
  theses(address: string): Promise<Thesis[]>;
}

/** A 200 fingerprint or a 202 ScoutStatus body (apiFetch returns both as JSON). */
export function parseFingerprint(res: unknown): FingerprintResult {
  if (res && typeof res === "object" && "trips_analyzed" in res && "examples" in res) {
    return { kind: "ready", fingerprint: res as StrategyFingerprint };
  }
  if (res && typeof res === "object" && "state" in res) return { kind: "building", status: res as ScoutStatus };
  throw new ApiError(500, "the api returned something that is not a strategy fingerprint");
}

const enc = (a: string) => encodeURIComponent(normAddr(a));

export const liveFile: FileSource = {
  profile: liveScout.profile,
  fills: liveScout.fills,
  orders: liveScout.orders,
  whatIf: liveScout.whatIf,
  fingerprint: async (a) => parseFingerprint(await apiFetch<unknown>(`/api/scout/traders/${enc(a)}/fingerprint`)),
  theses: async (a) => {
    const res = await apiFetch<unknown>(`/api/scout/traders/${enc(a)}/thesis`);
    return Array.isArray(res) ? (res as Thesis[]) : [];
  },
};

const later = <T>(v: T, ms = 0) => new Promise<T>((resolve) => setTimeout(() => resolve(v), ms));

function demoAddr(a: string): string {
  if (!isValidAddress(a)) throw new ApiError(404, "not a 0x address");
  return normAddr(a);
}

/** Demo source; `nowMs` is the frozen demo clock. */
export function demoFile(nowMs: number): FileSource {
  const row = (a: string) => demoFileRow(demoAddr(a), nowMs);
  return {
    profile: async (a) => later({ kind: "ready" as const, profile: fixtureProfile(row(a), nowMs) }),
    fills: async (a, before, limit) => later(fixtureFills(row(a), nowMs, before, limit)),
    orders: async (a) => later(normalizeOrders(fixtureOrders(row(a), nowMs))),
    whatIf: async (a, body) => later(fixtureWhatIf(fixtureProfile(row(a), nowMs), body), 350),
    fingerprint: async (a) => later({ kind: "ready" as const, fingerprint: fixtureFingerprint(demoAddr(a), nowMs) }),
    theses: async (a) => later(fixtureTheses(demoAddr(a), nowMs)),
  };
}

/** What-if failures in plain words; 409 means another what-if is running (1 concurrent). */
export function whatIfErrorText(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "The simulator is busy with another what-if. Try again in a few seconds.";
    if (err.status === 422) return `The api rejected these settings: ${err.message}`;
    if (err.status === 0) return err.message;
  }
  return err instanceof Error ? err.message : "What-if failed.";
}

export function isBusy(err: unknown): boolean {
  return err instanceof ApiError && err.status === 409;
}
