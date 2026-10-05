/**
 * Trade endpoints with two interchangeable sources, like lib/scout/api.ts:
 *   liveTrade: HTTP to services/api (bearer token, 401 handling in apiFetch)
 *   demoTrade(acct): an in-memory book over the fixtures, for `?demo=1`
 */
import { apiFetch } from "@/lib/api/client";
import { normAddr } from "@/lib/address";
import type { EngineEvent } from "@/lib/api/types";
import { demoNowMs } from "@/lib/scout/api";
import { demoFileRow } from "@/lib/scout/file/fixtures";
import { fixtureProfile, fixtureRows } from "@/lib/scout/fixtures";
import { apiProblem } from "./apiState";
import { normalizeApiPreview } from "./apiPreview";
import { applyCoinFilter } from "./coinFilter";
import { demoWalletHistory } from "./demoEvents";
import { profileIndex } from "./equityIndex";
import { demoSettings, demoStatus, leaderPositions, VOLUME_24H, DEMO_EQUITY, walletTerms, type DemoAccount } from "./fixtures";
import { walletsFromStatus } from "./markets";
import { localPreview } from "./preview";
import { localProjection, normalizeProjection, projectionQueryString, type ProjectionResult } from "./projection";
import type { TicketPreview } from "./ticket";
import type { ProjectionQuery, TradeOverride, TradeSettings, TradeStatus, WalletCopyRequest, WalletPosition, WalletStopRequest } from "./types";
import { forWallet, normalizeEvents, pageOf } from "./walletEvents";

export interface TradeSource {
  settings(): Promise<TradeSettings>;
  status(): Promise<TradeStatus>;
  wallets(): Promise<WalletPosition[]>;
  copy(address: string, body: WalletCopyRequest): Promise<TradeSettings>;
  stop(address: string, body: WalletStopRequest): Promise<TradeSettings>;
  preview(address: string, body: WalletCopyRequest): Promise<TicketPreview>;
  /** Book-wide setting change (only_new_positions from the ticket). */
  patch(patch: Partial<TradeSettings>): Promise<TradeSettings>;
  /** v8 lifecycle: no new opens/adds while paused; exits are still mirrored. */
  pause(address: string): Promise<unknown>;
  resume(address: string): Promise<unknown>;
  /** v8: a stopped wallet moves to Archived (kept for its history). */
  archive(address: string): Promise<unknown>;
  /** v8 per-wallet log, newest first. `fallback` true: the api has no route, this is the shared tail filtered. */
  events(address: string, opts: { limit: number; beforeMs?: number }): Promise<{ events: EngineEvent[]; fallback: boolean }>;
  /** v8 backtest of his last 30 days on these terms (202 = building). */
  projection(address: string, q: ProjectionQuery): Promise<ProjectionResult>;
}

/** How much of the shared event tail the pre-v8 fallback reads. */
export const FALLBACK_EVENTS = 500;

const enc = (a: string) => encodeURIComponent(normAddr(a));
const post = (body: unknown) => ({ method: "POST", body: JSON.stringify(body) });

export const liveTrade: TradeSource = {
  settings: () => apiFetch<TradeSettings>("/api/settings"),
  status: () => apiFetch<TradeStatus>("/api/status"),
  wallets: async () => {
    try {
      // Archived rows ride along (older apis ignore the param and send what they have).
      return await apiFetch<WalletPosition[]>("/api/wallets?include=archived");
    } catch (err) {
      // An api from before GET /api/wallets: rebuild the rows from status + settings.
      if (apiProblem(err) !== "too_old") throw err;
      const [status, settings] = await Promise.all([liveTrade.status(), liveTrade.settings()]);
      return walletsFromStatus(status, settings);
    }
  },
  copy: (a, body) => apiFetch<TradeSettings>(`/api/wallets/${enc(a)}/copy`, post(body)),
  stop: (a, body) => apiFetch<TradeSettings>(`/api/wallets/${enc(a)}/stop`, post(body)),
  preview: async (a, body) => normalizeApiPreview(await apiFetch<unknown>(`/api/wallets/${enc(a)}/preview`, post(body))),
  patch: (patch) => apiFetch<TradeSettings>("/api/settings", { method: "PATCH", body: JSON.stringify(patch) }),
  pause: (a) => apiFetch<unknown>(`/api/wallets/${enc(a)}/pause`, { method: "POST" }),
  resume: (a) => apiFetch<unknown>(`/api/wallets/${enc(a)}/resume`, { method: "POST" }),
  archive: (a) => apiFetch<unknown>(`/api/wallets/${enc(a)}/archive`, { method: "POST" }),
  events: async (a, { limit, beforeMs }) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (beforeMs !== undefined) q.set("before_ms", String(beforeMs));
    try {
      return { events: normalizeEvents(await apiFetch<unknown>(`/api/wallets/${enc(a)}/events?${q}`)), fallback: false };
    } catch (err) {
      if (apiProblem(err) !== "too_old") throw err;
      // Pre-v8: the shared tail, filtered to this wallet, paged client-side.
      const tail = normalizeEvents(await apiFetch<unknown>(`/api/events?limit=${FALLBACK_EVENTS}`));
      return { events: pageOf(forWallet(tail, a), limit, beforeMs), fallback: true };
    }
  },
  projection: async (a, q) => normalizeProjection(await apiFetch<unknown>(`/api/wallets/${enc(a)}/projection?${projectionQueryString(q)}`), q, normAddr(a)),
};

// ── demo ─────────────────────────────────────────────────────────────────────

interface DemoBook {
  settings: TradeSettings;
  stopping: Set<string>;
  /** Out of the book: the frozen row (realized PnL at stop), status stopped or archived. */
  done: Map<string, WalletPosition>;
  /** Events the demo actions appended (stop, pause...), per wallet. */
  log: Map<string, EngineEvent[]>;
  /** First projection ask per wallet: a wallet Scout doesn't track "builds" for a few seconds. */
  building: Map<string, number>;
}

const books = new Map<DemoAccount, DemoBook>();

function book(acct: DemoAccount): DemoBook {
  let b = books.get(acct);
  if (!b) {
    b = { settings: demoSettings(acct), stopping: new Set(), done: new Map(), log: new Map(), building: new Map() };
    books.set(acct, b);
  }
  return b;
}

const later = <T>(v: T, ms = 120) => new Promise<T>((resolve) => setTimeout(() => resolve(v), ms));

/** Test hook: forget every demo book. */
export function resetDemoBooks(): void {
  books.clear();
}

/** Append a demo event (newest first). */
function logEvent(b: DemoBook, a: string, e: Omit<EngineEvent, "leader" | "dry_run">): void {
  b.log.set(a, [{ ...e, leader: a, dry_run: true }, ...(b.log.get(a) ?? [])]);
}

/** Take a wallet out of the book: its row freezes with what it realized, status stopped. */
function finishStop(b: DemoBook, acct: DemoAccount, a: string): void {
  const nowMs = demoNowMs();
  const live = demoStatus(b.settings, acct, nowMs, b.stopping).wallets.find((w) => w.address === a);
  b.stopping.delete(a);
  b.settings.leaders = b.settings.leaders.filter((x) => x !== a);
  const { [a]: _gone, ...rest } = b.settings.leader_overrides;
  b.settings.leader_overrides = rest;
  if (live) {
    const pnl = live.unrealized_pnl_usd + live.realized_pnl_usd - live.fees_usd;
    b.done.set(a, {
      ...live, in_book: false, status: "stopped", stopping: false, open_copies: 0, margin_used_usd: 0, exposure_usd: 0,
      unrealized_pnl_usd: 0, realized_pnl_usd: live.realized_pnl_usd + live.unrealized_pnl_usd, pnl_usd: pnl,
    });
  }
}

export function demoTrade(acct: DemoAccount): TradeSource {
  const snap = () => demoStatus(book(acct).settings, acct, demoNowMs(), book(acct).stopping);
  const setPaused = (address: string, paused: boolean) => {
    const b = book(acct);
    const a = normAddr(address);
    if (!b.settings.leaders.includes(a)) return Promise.reject(new Error("not in the book"));
    const prev = b.settings.leader_overrides[a] ?? {};
    b.settings.leader_overrides = { ...b.settings.leader_overrides, [a]: { ...prev, paused } };
    logEvent(b, a, { ts_ms: demoNowMs(), action: paused ? "halt" : "resume", reason: paused ? "wallet paused: no new copies; exits still followed" : "wallet resumed" });
    return later(structuredClone(b.settings), 250);
  };
  return {
    settings: () => later(structuredClone(book(acct).settings), 60),
    status: () => later(snap().status),
    wallets: () => later([...snap().wallets, ...[...book(acct).done.values()].map((w) => structuredClone(w))]),
    copy: (address, body) => {
      const b = book(acct);
      const a = normAddr(address);
      const s = b.settings;
      const prev = s.leader_overrides[a];
      if (!s.leaders.includes(a) && s.leaders.length >= 25) return Promise.reject(new Error("the book is full (25 wallets)"));
      s.leaders = s.leaders.includes(a) ? s.leaders : [...s.leaders, a];
      // global: the Settings tab as-is, any override cleared (we keep only when it was first invested, and a pause).
      const terms: TradeOverride = body.settings_source === "global"
        ? { invested_ms: prev?.invested_ms ?? demoNowMs(), paused: prev?.paused ?? null }
        : {
            ...prev,
            sizing_mode: "allocation",
            allocation_usd: body.allocation_usd,
            exposure_mode: body.exposure_mode,
            target_leverage: body.exposure_mode === "target" ? body.target_leverage ?? 5 : null,
            leverage_mode: body.leverage_mode ?? null,
            margin_mode: body.margin_mode ?? null,
            max_worse_entry_pct: body.max_worse_entry_pct ?? null,
            small_account_mode: body.small_account_mode ?? null,
            only_new_positions: body.only_new_positions ?? null,
            trade_direction: body.trade_direction ?? null,
            coin_allowlist: body.coin_allowlist ?? null,
            coin_blocklist: body.coin_blocklist ?? null,
            invested_ms: prev?.invested_ms ?? demoNowMs(),
          };
      s.leader_overrides = { ...s.leader_overrides, [a]: terms };
      b.stopping.delete(a);
      b.done.delete(a);
      return later(structuredClone(s), 350);
    },
    stop: (address, body) => {
      const b = book(acct);
      const a = normAddr(address);
      b.stopping.add(a);
      logEvent(b, a, { ts_ms: demoNowMs(), action: "skip", reason: body.close_positions ? "stop wallet: closing its copies" : "stop wallet: open copies follow him out" });
      // Closing takes a cycle or two on a real engine; running out takes until he exits (sped up here).
      setTimeout(() => finishStop(b, acct, a), body.close_positions ? 2_500 : 8_000);
      return later(structuredClone(b.settings), 300);
    },
    patch: (patch) => {
      const b = book(acct);
      b.settings = { ...b.settings, ...patch };
      return later(structuredClone(b.settings), 150);
    },
    pause: (address) => setPaused(address, true),
    resume: (address) => setPaused(address, false),
    archive: (address) => {
      const b = book(acct);
      const a = normAddr(address);
      const w = b.done.get(a);
      if (!w || w.status !== "stopped") return Promise.reject(new Error("only a stopped wallet can be archived"));
      b.done.set(a, { ...w, status: "archived", archived_ms: demoNowMs() });
      return later({ ok: true }, 200);
    },
    events: (address, { limit, beforeMs }) => {
      const b = book(acct);
      const a = normAddr(address);
      const nowMs = demoNowMs();
      const s = b.settings;
      const o = s.leader_overrides[a];
      const done = b.done.get(a);
      const invested = o?.invested_ms ?? done?.invested_ms ?? null;
      const history = invested
        ? demoWalletHistory(a, leaderPositions(a, nowMs).positions, walletTerms(s, a), invested, Math.min(nowMs, done?.archived_ms ?? nowMs))
        : [];
      const all = [...(b.log.get(a) ?? []), ...history];
      return later({ events: pageOf(all, limit, beforeMs), fallback: false }, 180);
    },
    projection: (address, q) => {
      const b = book(acct);
      const a = normAddr(address);
      const nowMs = demoNowMs();
      // A wallet Scout doesn't track (a pasted address) builds for ~4s, like the api's 202.
      const onBoard = fixtureRows(nowMs).some((r) => r.address === a);
      if (!onBoard) {
        const first = b.building.get(a) ?? Date.now();
        b.building.set(a, first);
        if (Date.now() - first < 4_000) return later<ProjectionResult>({ kind: "building", note: "Reading his last 30 days from Hyperliquid." }, 200);
      }
      const prof = fixtureProfile(demoFileRow(a, nowMs), nowMs);
      const idx = profileIndex(prof, "30d");
      const gross = prof.positions.reduce((x, p) => x + Math.abs(p.notional_usd), 0);
      const proj = localProjection({
        address: a, index: idx.points, allocationUsd: q.allocation_usd, direction: q.trade_direction, mode: q.exposure_mode,
        targetLeverage: q.target_leverage, hisLeverage: prof.row.account_value_usd > 0 ? gross / prof.row.account_value_usd : null,
      });
      return later<ProjectionResult>({ kind: "ready", projection: { ...proj, copies: 12 + (a.charCodeAt(5) % 20), skipped: a.charCodeAt(7) % 4, note: null } }, 260);
    },
    preview: (address, body) => {
      const s = book(acct).settings;
      const { equity, positions } = leaderPositions(normAddr(address), demoNowMs());
      const st = snap().status;
      const t = walletTerms(s, address, body);
      const p = localPreview({
        allocationUsd: t.allocationUsd, mode: t.mode, targetLeverage: t.targetLeverage, marginMode: t.marginMode, smallMode: t.smallMode,
        leaderEquityUsd: equity, positions, volume24hUsd: VOLUME_24H, maxOrderVolumePct: s.max_order_volume_pct,
        ourEquityUsd: st.equity_usd ?? DEMO_EQUITY[acct], maxPositionLeverage: s.max_position_leverage,
        otherExposureUsd: st.positions.filter((c) => c.leader !== normAddr(address)).reduce((x, c) => x + c.notional_usd, 0),
      });
      return later({ ...applyCoinFilter(p, t.allow, t.block), source: "api" as const }, 220);
    },
  };
}
