/**
 * Trade endpoints with two interchangeable sources, like lib/scout/api.ts:
 *   liveTrade: HTTP to services/api (bearer token, 401 handling in apiFetch)
 *   demoTrade(acct): an in-memory book over the fixtures, for `?demo=1`
 */
import { apiFetch } from "@/lib/api/client";
import { normAddr } from "@/lib/address";
import { demoNowMs } from "@/lib/scout/api";
import { apiProblem } from "./apiState";
import { normalizeApiPreview } from "./apiPreview";
import { demoSettings, demoStatus, leaderPositions, VOLUME_24H, DEMO_EQUITY, type DemoAccount } from "./fixtures";
import { walletsFromStatus } from "./markets";
import { localPreview } from "./preview";
import type { TicketPreview } from "./ticket";
import type { TradeSettings, TradeStatus, WalletCopyRequest, WalletPosition, WalletStopRequest } from "./types";

export interface TradeSource {
  settings(): Promise<TradeSettings>;
  status(): Promise<TradeStatus>;
  wallets(): Promise<WalletPosition[]>;
  copy(address: string, body: WalletCopyRequest): Promise<TradeSettings>;
  stop(address: string, body: WalletStopRequest): Promise<TradeSettings>;
  preview(address: string, body: WalletCopyRequest): Promise<TicketPreview>;
  /** Book-wide setting change (only_new_positions from the ticket). */
  patch(patch: Partial<TradeSettings>): Promise<TradeSettings>;
}

const enc = (a: string) => encodeURIComponent(normAddr(a));
const post = (body: unknown) => ({ method: "POST", body: JSON.stringify(body) });

export const liveTrade: TradeSource = {
  settings: () => apiFetch<TradeSettings>("/api/settings"),
  status: () => apiFetch<TradeStatus>("/api/status"),
  wallets: async () => {
    try {
      return await apiFetch<WalletPosition[]>("/api/wallets");
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
};

// ── demo ─────────────────────────────────────────────────────────────────────

interface DemoBook {
  settings: TradeSettings;
  stopping: Set<string>;
}

const books = new Map<DemoAccount, DemoBook>();

function book(acct: DemoAccount): DemoBook {
  let b = books.get(acct);
  if (!b) {
    b = { settings: demoSettings(), stopping: new Set() };
    books.set(acct, b);
  }
  return b;
}

const later = <T>(v: T, ms = 120) => new Promise<T>((resolve) => setTimeout(() => resolve(v), ms));

/** Test hook: forget every demo book. */
export function resetDemoBooks(): void {
  books.clear();
}

export function demoTrade(acct: DemoAccount): TradeSource {
  const snap = () => demoStatus(book(acct).settings, acct, demoNowMs(), book(acct).stopping);
  return {
    settings: () => later(structuredClone(book(acct).settings), 60),
    status: () => later(snap().status),
    wallets: () => later(snap().wallets),
    copy: (address, body) => {
      const b = book(acct);
      const a = normAddr(address);
      const s = b.settings;
      const prev = s.leader_overrides[a];
      if (!s.leaders.includes(a) && s.leaders.length >= 25) return Promise.reject(new Error("the book is full (25 wallets)"));
      s.leaders = s.leaders.includes(a) ? s.leaders : [...s.leaders, a];
      s.leader_overrides = {
        ...s.leader_overrides,
        [a]: {
          ...prev,
          sizing_mode: "allocation",
          allocation_usd: body.allocation_usd,
          exposure_mode: body.exposure_mode,
          target_leverage: body.exposure_mode === "target" ? body.target_leverage ?? 5 : prev?.target_leverage ?? null,
          margin_mode: body.margin_mode ?? prev?.margin_mode ?? null,
          max_worse_entry_pct: body.max_worse_entry_pct ?? prev?.max_worse_entry_pct ?? null,
          small_account_mode: body.small_account_mode ?? prev?.small_account_mode ?? null,
          invested_ms: prev?.invested_ms ?? demoNowMs(),
        },
      };
      b.stopping.delete(a);
      return later(structuredClone(s), 350);
    },
    stop: (address, body) => {
      const b = book(acct);
      const a = normAddr(address);
      b.stopping.add(a);
      if (body.close_positions) {
        // Closing takes a cycle or two on a real engine; then the wallet leaves the book.
        setTimeout(() => {
          b.stopping.delete(a);
          b.settings.leaders = b.settings.leaders.filter((x) => x !== a);
          const { [a]: _gone, ...rest } = b.settings.leader_overrides;
          b.settings.leader_overrides = rest;
        }, 2_500);
      }
      return later(structuredClone(b.settings), 300);
    },
    patch: (patch) => {
      const b = book(acct);
      b.settings = { ...b.settings, ...patch };
      return later(structuredClone(b.settings), 150);
    },
    preview: (address, body) => {
      const s = book(acct).settings;
      const { equity, positions } = leaderPositions(normAddr(address), demoNowMs());
      const st = snap().status;
      const p = localPreview({
        allocationUsd: body.allocation_usd, mode: body.exposure_mode, targetLeverage: body.target_leverage ?? 5,
        marginMode: body.margin_mode ?? s.margin_mode, smallMode: body.small_account_mode ?? s.small_account_mode ?? "concentrate",
        leaderEquityUsd: equity, positions, volume24hUsd: VOLUME_24H, maxOrderVolumePct: s.max_order_volume_pct,
        ourEquityUsd: st.equity_usd ?? DEMO_EQUITY[acct],
        otherExposureUsd: st.positions.filter((c) => c.leader !== normAddr(address)).reduce((x, c) => x + c.notional_usd, 0),
      });
      return later({ ...p, source: "api" as const }, 220);
    },
  };
}
