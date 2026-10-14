/**
 * Deterministic Scout fixtures: a realistic board, trader files, fills,
 * orders, presets, status and what-if results, all shaped exactly like the
 * contract v3 models. Used by vitest and by the `?demo=1` mode, so the
 * pages render (and can be screenshotted) before the api routes land.
 *
 * Same seed + same `nowMs` = byte-identical output. Copy Fit values are
 * computed with the real spec formula (section 3) from the generated parts,
 * then capped by the generated flags, so the hover breakdown always adds up.
 */
import type { LeaderOverride, Settings } from "@/lib/api/types";
import type {
  AccountRisk, CoinStat, CopyFit, CurvePoint, LeaderFillView, OpenOrderWire, PnlTier, RoundTrip, ScoutPresetsWire,
  ScoutSimTerms, ScoutStatus, SizeTier, TradeStats, TraderPage, TraderPositionView, TraderProfile, TraderRow, TraderScore,
  TradingStyle, WhatIfRequest, WhatIfResult,
} from "./types";
import { hip3Share } from "./query";

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/** mulberry32: tiny, fast, good enough for fixtures, and the same on every JS engine. */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
}

const pick = <T>(r: () => number, xs: readonly T[]): T => xs[Math.floor(r() * xs.length) % xs.length];
const between = (r: () => number, lo: number, hi: number) => lo + (hi - lo) * r();
const round = (n: number, d = 2) => Math.round(n * 10 ** d) / 10 ** d;

function address(r: () => number): string {
  let s = "0x";
  for (let i = 0; i < 40; i++) s += "0123456789abcdef"[Math.floor(r() * 16)];
  return s;
}

const MARK: Record<string, number> = {
  BTC: 118_400, ETH: 4_420, SOL: 212.5, HYPE: 47.82, kPEPE: 0.01184, DOGE: 0.2611, SUI: 3.912, AVAX: 31.07,
  LINK: 23.41, ENA: 0.7012, FARTCOIN: 1.093, "xyz:TSLA": 431.2, "xyz:NVDA": 187.4, "xyz:XYZ100": 24_810, "xyz:GOLD": 3_871,
};
const COINS = Object.keys(MARK);

export const FIT_WEIGHTS: Record<string, number> = {
  sim: 0.4, sharpe: 0.15, drawdown: 0.1, consistency: 0.1, win_rate: 0.05, sample: 0.1, capacity: 0.05, recency: 0.05,
};

const NAMES = ["Kestrel", "slow_hands", "Driftwood", "basisboy", "Northpaw", "theta.gang", "Quietfox", "MERIDIAN", "ivy", "Halcyon"];

interface Seed {
  style: TradingStyle | null;
  flags: string[];
}

/** A few deliberate edge cases at fixed board positions, the rest random. */
const SPECIAL: Record<number, Seed> = {
  3: { style: "swing", flags: ["fills_truncated"] },
  7: { style: "intraday", flags: ["liquidated"] },
  11: { style: "algo", flags: ["hft"] },
  15: { style: "position", flags: ["too_few_trades"] },
  19: { style: "swing", flags: ["vault"] },
  23: { style: null, flags: ["inactive"] },
  27: { style: "intraday", flags: ["wallet_liquidated"] },   // real blowup, distinct from the sim cap at 7
  31: { style: "scalp", flags: ["coattail"] },
};

function sizeTier(av: number): SizeTier {
  if (av < 10_000) return "S";
  if (av < 100_000) return "M";
  if (av < 1_000_000) return "L";
  if (av < 10_000_000) return "XL";
  return "XXL";
}

function pnlTier(pnl: number): PnlTier {
  if (pnl < 0) return "losing";
  if (pnl < 100_000) return "up";
  if (pnl < 1_000_000) return "strong";
  return "elite";
}

/** Cumulative random walk from 0 that ends at `end`, `n` points over [start, stop]. */
function walk(r: () => number, n: number, startMs: number, stopMs: number, end: number, vol: number): CurvePoint[] {
  const steps: number[] = [0];
  for (let i = 1; i < n; i++) steps.push(steps[i - 1] + (r() - 0.5) * vol);
  const drift = (end - steps[n - 1]) / (n - 1);
  return steps.map((v, i) => ({ t_ms: Math.round(startMs + ((stopMs - startMs) * i) / (n - 1)), value: round(v + drift * i) }));
}

/** Caps Copy Fit applies after the weighted sum (spec section 3), shared with applySimTerms below
 * so a terms-driven recompute caps exactly the way the original fixture did. */
function applyFitCaps(rawValue: number, flags: string[]): { value: number; caps: string[] } {
  let value = rawValue;
  const caps: string[] = [];
  if (flags.includes("inactive")) { value = 0; caps.push("inactive"); }
  if (flags.includes("liquidated")) { value = Math.min(value, 20); caps.push("liquidated"); }
  if (flags.includes("too_few_trades")) { value = Math.min(value, 40); caps.push("too_few_trades"); }
  if (flags.includes("hft")) { value = Math.min(value, 50); caps.push("hft"); }
  if (flags.includes("vault")) { value = Math.min(value, 50); caps.push("vault"); }
  if (flags.includes("fills_truncated")) caps.push("fills_truncated");
  return { value, caps };
}

function copyFit(r: () => number, flags: string[], trips: number, lastFillAgoH: number, cohort: number, quality: number): CopyFit {
  const q = (spread: number) => Math.min(1, Math.max(0, quality + (r() - 0.5) * spread));
  const parts: Record<string, number> = {
    sim: round(q(0.35), 3),
    sharpe: round(q(0.5), 3),
    drawdown: round(q(0.6), 3),
    consistency: round(q(0.5), 3),
    win_rate: round(q(0.6), 3),
    sample: round(Math.min(1, Math.log10(1 + trips) / Math.log10(51)), 3),
    capacity: round(between(r, 0.55, 1), 3),
    recency: round(lastFillAgoH <= 24 ? 1 : Math.max(0, 1 - (lastFillAgoH - 24) / (6 * 24)), 3),
  };
  const raw = 100 * Object.entries(FIT_WEIGHTS).reduce((a, [k, w]) => a + w * parts[k], 0);
  const { value, caps } = applyFitCaps(raw, flags);
  return { value: round(value, 1), parts, weights: { ...FIT_WEIGHTS }, caps, cohort_size: cohort };
}

/** The reference terms a fixture board (and a fresh install) starts at: contracts/models.py
 * ScoutSimTerms() field defaults, hand-mirrored (no codegen fixture generator exists). */
export const DEFAULT_SIM_TERMS: ScoutSimTerms = {
  use_live_settings: false,
  sim_equity_usd: 1_000,
  allocation_usd: 100,
  exposure_mode: "target",
  target_leverage: 3,
  leverage_mode: "fixed",
  leverage: 3,
  margin_mode: "isolated",
  max_worse_entry_pct: 10,
  small_account_mode: "concentrate",
};

/**
 * Demo stand-in for a Scout board re-sim at new terms (not a real sim; the real one
 * re-runs services/discovery/discovery/sim.py). Scales each row's sim return/drawdown/
 * fees/skips by a leverage+allocation+equity factor shaped like fixtureWhatIf's `k`
 * below, recomputes only the "sim" slice of Copy Fit from the new return, re-applies
 * the same caps, and re-sorts -- enough for the e2e demo lane to see the terms control
 * actually change the note AND the order, deterministically.
 */
export function applySimTerms(rows: TraderRow[], terms: ScoutSimTerms): TraderRow[] {
  const lev = terms.exposure_mode === "target" ? terms.target_leverage : terms.leverage;
  const k = Math.max(0.2, Math.min(4, (lev / 10) * (terms.allocation_usd / 100) ** 0.4 * (1_000 / terms.sim_equity_usd) ** 0.2));
  const allocFactor = Math.max(0.3, Math.min(3, 100 / terms.allocation_usd));   // smaller allocation: more min-order skips
  const next = rows.map((row) => {
    const s = row.score;
    const simRet = round(s.sim_return_pct * k, 2);
    const simDd = round(s.sim_max_drawdown_pct * Math.max(1, Math.abs(k) * 0.8), 2);
    const skipped = Math.max(0, Math.round(s.sim_skipped_min_order * allocFactor));
    const copies = Math.max(0, s.sim_copies + s.sim_skipped_min_order - skipped);
    const capacity = round((copies / Math.max(1, copies + skipped)) * 100, 1);
    const fit = s.copy_fit;
    let score: TraderScore = {
      ...s, sim_return_pct: simRet, sim_max_drawdown_pct: simDd, sim_copies: copies,
      sim_skipped_min_order: skipped, sim_copy_capacity_pct: capacity,
    };
    if (fit) {
      const simPart = round(Math.max(0, Math.min(1, 0.5 + simRet / 120)), 3);
      const parts: Record<string, number> = { ...fit.parts, sim: simPart };
      const raw = 100 * Object.entries(FIT_WEIGHTS).reduce((a, [key, w]) => a + w * parts[key], 0);
      const { value, caps } = applyFitCaps(raw, row.flags);
      score = { ...score, copy_fit: { ...fit, value: round(value, 1), parts, caps } };
    }
    return { ...row, score };
  });
  return next.sort((a, b) => (b.score.copy_fit?.value ?? 0) - (a.score.copy_fit?.value ?? 0) || a.address.localeCompare(b.address));
}

export const FIXTURE_COHORT = 280;
export const FIXTURE_ROWS = 36;
export const FIXTURE_SIM_EQUITY = 1000;

function makeRow(i: number, nowMs: number): TraderRow {
  const r = rng(1000 + i);
  const special = SPECIAL[i];
  const quality = Math.max(0.05, 0.92 - i * 0.022 + (r() - 0.5) * 0.12);
  const style: TradingStyle | null = special ? special.style : pick(r, ["swing", "swing", "swing", "intraday", "intraday", "position", "scalp"] as const);
  const flags = special ? [...special.flags] : [];
  const av = special?.flags.includes("inactive") ? 640 : round(10 ** between(r, 4.1, 7.3), 0);
  const roi30 = round((quality - 0.35) * between(r, 18, 70), 2);
  const pnl30 = round((av * roi30) / 100, 0);
  const perf = [
    { window: "1d" as const, roi_pct: round(roi30 * between(r, -0.2, 0.25), 2) },
    { window: "7d" as const, roi_pct: round(roi30 * between(r, 0.05, 0.5), 2) },
    { window: "30d" as const, roi_pct: roi30 },
    { window: "all" as const, roi_pct: round(roi30 * between(r, 1.5, 9), 2) },
  ].map((p) => ({
    ...p,
    pnl_usd: p.window === "30d" ? pnl30 : round((av * p.roi_pct) / 100, 0),
    volume_usd: round(av * between(r, 0.4, 14) * (p.window === "1d" ? 0.05 : p.window === "7d" ? 0.3 : p.window === "30d" ? 1 : 9), 0),
  }));
  const lastFillAgoH = flags.includes("inactive") ? 9 * 24 : style === "algo" ? 0.02 : between(r, 0.05, i % 5 === 4 ? 70 : 20);
  const trips = flags.includes("too_few_trades") ? 3 : style === "algo" ? 1800 : Math.round(between(r, 8, style === "scalp" ? 400 : 120));
  const wins = Math.round(trips * Math.min(0.9, Math.max(0.2, 0.32 + quality * 0.4 + (r() - 0.5) * 0.1)));
  const longTrips = Math.round(trips * between(r, 0.3, 0.8));
  const median = style === "algo" ? 0.03 : style === "scalp" ? between(r, 0.05, 0.24) : style === "intraday" ? between(r, 1, 20) : style === "swing" ? between(r, 26, 150) : between(r, 170, 600);
  const trades_30d: TradeStats = {
    window: "30d", trips, wins, long_trips: longTrips, short_trips: trips - longTrips,
    win_rate_pct: trips ? round((wins / trips) * 100, 1) : null,
    avg_hold_h: round(median * between(r, 1, 1.6), 2), median_hold_h: round(median, 2),
    opens_per_day: round(style === "algo" ? between(r, 140, 400) : trips / 30 * between(r, 1, 2.2), 2),
  };
  const nCoins = 2 + Math.floor(r() * 4);
  const hip3Heavy = i % 6 === 2;
  const pool = hip3Heavy ? ["xyz:TSLA", "xyz:NVDA", "xyz:XYZ100", "xyz:GOLD", "BTC"] : COINS.filter((c) => !c.startsWith("xyz:") || r() < 0.15);
  const coinsSet = new Set<string>();
  while (coinsSet.size < nCoins) coinsSet.add(pick(r, pool));
  const totalVol = perf[2].volume_usd;
  let left = 1;
  const top_coins: CoinStat[] = [...coinsSet].map((coin, k) => {
    const share = k === nCoins - 1 ? left : left * between(r, 0.45, 0.75);
    left -= share;
    return { coin, volume_usd: round(totalVol * share, 0), pnl_usd: round(pnl30 * share * between(r, 0.3, 1.6), 0), trips: Math.max(1, Math.round(trips * share)) };
  });
  const start = nowMs - 30 * DAY;
  const pnl_spark_30d = walk(r, 48, start, nowMs, pnl30, Math.max(200, Math.abs(pnl30) * 0.18 + av * 0.01));
  const simRet = flags.includes("liquidated") ? -38.5 : round((quality - 0.4) * between(r, 15, 40), 2);
  const sim_spark_30d = walk(r, 48, start, nowMs, (FIXTURE_SIM_EQUITY * simRet) / 100, 30).map((p) => ({ ...p, value: round(FIXTURE_SIM_EQUITY + p.value) }));
  const addr = address(r);
  const display_name = i % 4 === 1 ? NAMES[(i >> 2) % NAMES.length] : null;
  const fit = copyFit(r, flags, trips, lastFillAgoH, FIXTURE_COHORT, quality);
  const simCopies = flags.includes("too_few_trades") ? 3 : Math.round(trips * between(r, 0.5, 0.95));
  // index 15 ("too_few_trades") must keep a near-100% capacity so it never triggers a low-capacity
  // note alongside the sample-size cap; everyone else gets occasional skips.
  const skipped = flags.includes("too_few_trades") ? 0 : Math.round(simCopies * between(r, 0, 0.35));
  const walletLiquidated = flags.includes("wallet_liquidated");
  const coattail = flags.includes("coattail");
  const score: TraderScore = {
    address: addr, display_name, account_value_usd: av, pnl_30d_usd: pnl30, roi_30d_pct: roi30, pnl_all_time_usd: perf[3].pnl_usd,
    volume_30d_usd: totalVol, fills_30d: trips * 3, opens_per_day: trades_30d.opens_per_day, median_hold_h: trades_30d.median_hold_h,
    coins: top_coins.map((c) => c.coin), sim_return_pct: simRet,
    sim_max_drawdown_pct: flags.includes("liquidated") ? -61.2 : -round(between(r, 2, 28), 1),
    sim_liquidations: flags.includes("liquidated") ? 1 : 0, sim_copies: simCopies, sim_skipped_min_order: skipped,
    sim_fees_usd: round(simCopies * between(r, 0.02, 0.2), 2), score: round(simRet / 8, 2), flags: [...flags],
    sim_copy_capacity_pct: round((simCopies / Math.max(1, simCopies + skipped)) * 100, 1), copy_fit: fit, style, last_fill_ms: Math.round(nowMs - lastFillAgoH * HOUR),
    liquidations_30d: walletLiquidated ? 2 : 0,
    last_liquidation_ms: walletLiquidated ? Math.round(nowMs - 11 * 24 * HOUR) : null,
    sim_capacity_note: skipped > 0 ? "58% of skipped opens: under the $10.50 minimum order at your size" : null,
    coattail_leader: coattail ? address(rng(2000)) : null,
    coattail_share_pct: coattail ? 68.0 : null,
  };
  return {
    address: addr, display_name, account_value_usd: av, size_tier: sizeTier(av), pnl_tier: pnlTier(perf[3].pnl_usd), style,
    last_fill_ms: score.last_fill_ms, perf,
    risk_30d: {
      window: "30d", max_drawdown_pct: round(between(r, 3, 35) * (1.4 - quality), 1),
      sharpe: round((quality - 0.3) * between(r, 2, 6), 2), sortino: round((quality - 0.3) * between(r, 3, 9), 2),
      profitable_days_pct: round(35 + quality * 40 + (r() - 0.5) * 10, 1), days: 30,
    },
    trades_30d, top_coins, pnl_spark_30d, sim_spark_30d, score, in_book: false, flags,
  };
}

/** The whole fixture board, sorted by Copy Fit like the api's default. */
export function fixtureRows(nowMs: number): TraderRow[] {
  const rows = Array.from({ length: FIXTURE_ROWS }, (_, i) => makeRow(i, nowMs));
  return rows.sort((a, b) => (b.score.copy_fit?.value ?? 0) - (a.score.copy_fit?.value ?? 0) || a.address.localeCompare(b.address));
}

/** Demo settings: the top two rows are already in the book. */
export function fixtureSettings(nowMs: number): Settings {
  const rows = fixtureRows(nowMs);
  return {
    contract_version: 3, enabled: false, dry_run: true, leaders: [rows[0].address, rows[4].address],
    sizing_mode: "fixed_margin", fixed_margin_usd: 5, fixed_notional_usd: 10.5, size_multiplier: 1, sleeve_frac: 1,
    leverage_mode: "max", leverage: 20, max_position_leverage: 50, margin_mode: "isolated", include_spot_staked: false,
    only_new_positions: false, max_worse_entry_pct: 10, min_order_bump: true, daily_loss_limit_usd: 0, max_open_copies: 10,
    poll_interval_s: 5, leader_overrides: {},
  };
}

export function fixturePage(rows: TraderRow[], total: number, nowMs: number): TraderPage {
  return {
    as_of_ms: nowMs - 12 * 60_000, refresh_id: "demo-refresh", settings_hash: "demo", cohort_size: FIXTURE_COHORT, total, rows,
    sim_equity_usd: FIXTURE_SIM_EQUITY,
  };
}

export function fixturePresets(rows: TraderRow[]): ScoutPresetsWire {
  const counts = new Map<string, number>();
  for (const r of rows) {
    const c = r.top_coins[0]?.coin;
    if (c) counts.set(c, (counts.get(c) ?? 0) + 1);
  }
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 6);
  return {
    refresh_id: "demo-refresh",
    coins: top.map(([coin]) => coin),
    coin_counts: Object.fromEntries(top),
    hip3_count: rows.filter((r) => hip3Share(r) >= 0.5).length,
    total: rows.length,
    // demo values so the survivorship note (user_consensus P1 #7) is visible in ?demo=1 too
    departed_30d: 11,
    departed_liquidated_30d: 3,
    custom: rows.filter((r) => r.custom).length,
  };
}

export function fixtureStatus(nowMs: number): ScoutStatus {
  return { refresh_id: "demo-refresh", state: "idle", stage: null, done: 280, total: 280, eta_s: null, last_ok_ms: nowMs - 12 * 60_000, next_due_ms: nowMs + 48 * 60_000, error: null };
}

function fillsFor(row: TraderRow, nowMs: number, count: number, beforeMs: number): LeaderFillView[] {
  const r = rng(hashStr(row.address) ^ Math.floor(beforeMs / HOUR));
  const gap = row.style === "algo" ? 60_000 : row.style === "scalp" ? 20 * 60_000 : row.style === "intraday" ? 2 * HOUR : 9 * HOUR;
  const coins = row.top_coins.length ? row.top_coins.map((c) => c.coin) : ["BTC"];
  const out: LeaderFillView[] = [];
  let t = Math.min(beforeMs - 1, nowMs);
  const floor = nowMs - 30 * DAY;
  for (let i = 0; i < count && t > floor; i++) {
    t -= Math.round(gap * between(r, 0.2, 1.8));
    const coin = pick(r, coins);
    const px = round((MARK[coin] ?? 10) * between(r, 0.94, 1.04), MARK[coin] < 1 ? 6 : 2);
    const notional = round(row.account_value_usd * between(r, 0.01, 0.3), 2);
    const side = r() < 0.5 ? "B" : "A";
    const closing = r() < 0.45;
    const dir = closing ? (side === "B" ? "Close Short" : "Close Long") : side === "B" ? "Open Long" : "Open Short";
    // A closing fill is liquidated roughly 1 in 40 times (deterministic per address/clock): rare
    // enough to look real, common enough that demo mode exercises the liquidation badge.
    const liq = closing && r() < 0.025;
    out.push({
      time_ms: t, coin, side, dir, px, sz: round(notional / px, 4), notional_usd: notional,
      closed_pnl_usd: closing ? round(notional * between(r, -0.04, 0.07), 2) : 0, fee_usd: round(notional * 0.00035, 4),
      liquidation: liq,
    });
  }
  return out;
}

/** One page of fills before `beforeMs`, newest first (GET .../fills?before_ms=&limit=). */
export function fixtureFills(row: TraderRow, nowMs: number, beforeMs: number | null, limit: number): LeaderFillView[] {
  return fillsFor(row, nowMs, limit, beforeMs ?? nowMs + 1);
}

export function fixtureOrders(row: TraderRow, nowMs: number): OpenOrderWire[] {
  const r = rng(hashStr(row.address) + 7);
  const n = row.flags.includes("inactive") ? 0 : Math.floor(r() * 5);
  return Array.from({ length: n }, (_, k) => {
    const coin = pick(r, row.top_coins.map((c) => c.coin).concat("BTC"));
    const trigger = k % 3 === 2;
    const side = r() < 0.5 ? "B" : "A";
    const px = round((MARK[coin] ?? 10) * (side === "B" ? between(r, 0.9, 0.99) : between(r, 1.01, 1.1)), (MARK[coin] ?? 10) < 1 ? 6 : 2);
    const sz = round((row.account_value_usd * 0.05) / px, 3);
    return {
      oid: 100_000 + k, coin, side, order_type: trigger ? "Stop Market" : "Limit", limit_px: px, sz, orig_sz: sz,
      notional_usd: round(px * sz, 2), reduce_only: trigger, is_trigger: trigger, trigger_px: trigger ? px : null,
      trigger_condition: trigger ? "Price below" : null, tif: trigger ? null : "Gtc",
      time_ms: nowMs - Math.round(between(r, 0.1, 40) * HOUR),
    } satisfies OpenOrderWire;
  });
}

export function fixtureProfile(row: TraderRow, nowMs: number): TraderProfile {
  const r = rng(hashStr(row.address));
  const perf = Object.fromEntries(row.perf.map((p) => [p.window, p]));
  const pnl_curve = {
    "1d": walk(r, 25, nowMs - DAY, nowMs, perf["1d"].pnl_usd, row.account_value_usd * 0.004),
    "7d": walk(r, 43, nowMs - 7 * DAY, nowMs, perf["7d"].pnl_usd, row.account_value_usd * 0.008),
    "30d": row.pnl_spark_30d,
    all: walk(r, 120, nowMs - 420 * DAY, nowMs, perf.all.pnl_usd, row.account_value_usd * 0.03),
  };
  // value_t = today's value - PnL still to come - transfers still to come.
  // With `steps`, a 15% withdrawal at 40% of the series and a 10% deposit at
  // 75%, so the all-time value chart shows transfer steps like a real one.
  const valueFrom = (pts: CurvePoint[], steps: boolean) => {
    const av = row.account_value_usd;
    const end = pts[pts.length - 1].value;
    const transfers = steps ? [{ at: Math.floor(pts.length * 0.4), amt: -0.15 * av }, { at: Math.floor(pts.length * 0.75), amt: 0.1 * av }] : [];
    return pts.map((p, k) => {
      const later = transfers.filter((x) => x.at > k).reduce((a, x) => a + x.amt, 0);
      return { t_ms: p.t_ms, value: round(Math.max(0, av - (end - p.value) - later), 0) };
    });
  };
  const value_curve = { "1d": valueFrom(pnl_curve["1d"], false), "7d": valueFrom(pnl_curve["7d"], false), "30d": valueFrom(pnl_curve["30d"], false), all: valueFrom(pnl_curve.all, true) };
  const simEnd = (FIXTURE_SIM_EQUITY * row.score.sim_return_pct) / 100;
  const sim_curve = walk(r, 30 * 24 + 1, nowMs - 30 * DAY, nowMs, simEnd, 6).map((p) => ({ t_ms: p.t_ms, value: round(Math.max(1, FIXTURE_SIM_EQUITY + p.value), 2) }));
  const today = Math.floor(nowMs / DAY) * DAY;
  const daily_pnl: CurvePoint[] = [];
  for (let d = 364; d >= 0; d--) {
    if (r() < 0.12) continue; // flat / no-trade days are simply absent
    daily_pnl.push({ t_ms: today - d * DAY, value: round(row.account_value_usd * (r() - 0.46 + (row.score.copy_fit?.value ?? 50) / 1000) * 0.03, 0) });
  }
  const nPos = row.flags.includes("inactive") ? 0 : 1 + Math.floor(r() * 5);
  const positions: TraderPositionView[] = [];
  const used = new Set<string>();
  for (let k = 0; k < nPos; k++) {
    const coin = k < row.top_coins.length ? row.top_coins[k].coin : pick(r, COINS);
    if (used.has(coin)) continue;
    used.add(coin);
    const side = r() < 0.62 ? "long" : "short";
    const lev = pick(r, [3, 5, 10, 10, 20, 25, 40]);
    const mark = MARK[coin] ?? 10;
    const entry = round(mark * between(r, 0.92, 1.06), mark < 1 ? 6 : 2);
    const notional = round(row.account_value_usd * between(r, 0.08, 0.9), 0);
    const size = round(notional / mark, 4) * (side === "long" ? 1 : -1);
    const upnl = round((mark - entry) * size, 0);
    const isCross = r() < 0.6;
    const liqDist = round(between(r, 4, 70) / Math.sqrt(lev / 3), 1);
    const liq = isCross && r() < 0.25 ? null : round(side === "long" ? mark * (1 - liqDist / 100) : mark * (1 + liqDist / 100), mark < 1 ? 6 : 2);
    positions.push({
      coin, side, size, notional_usd: notional, entry_px: entry, mark_px: mark, unrealized_pnl_usd: upnl,
      roe_pct: round((upnl / (notional / lev)) * 100, 1), leverage: lev, is_cross: isCross, liquidation_px: liq,
      liq_distance_pct: liq === null ? null : liqDist, margin_usd: round(notional / lev, 0), funding_since_open_usd: round(-notional * between(r, -0.002, 0.006), 2),
    });
  }
  const long = positions.filter((p) => p.side === "long").reduce((a, p) => a + p.notional_usd, 0);
  const short = positions.filter((p) => p.side === "short").reduce((a, p) => a + p.notional_usd, 0);
  const spot = round(row.account_value_usd * between(r, 0, 0.2), 0);
  const staked = r() < 0.4 ? round(row.account_value_usd * between(r, 0, 0.1), 0) : 0;
  const liqs = positions.map((p) => p.liq_distance_pct).filter((x): x is number => x !== null && x !== undefined);
  const account: AccountRisk = {
    perps_usd: row.account_value_usd, spot_usd: spot, staked_usd: staked,
    account_leverage: round((long + short) / Math.max(1, row.account_value_usd), 2),
    margin_usage_pct: round((positions.reduce((a, p) => a + p.margin_usd, 0) / Math.max(1, row.account_value_usd)) * 100, 1),
    nearest_liq_pct: liqs.length ? Math.min(...liqs) : null, long_notional_usd: long, short_notional_usd: short,
    long_bias_pct: long + short > 0 ? round((long / (long + short)) * 100, 1) : null,
    unrealized_pnl_usd: positions.reduce((a, p) => a + p.unrealized_pnl_usd, 0),
  };
  const t7 = row.trades_30d;
  const trades: TradeStats[] = [
    { ...t7, window: "7d", trips: Math.round(t7.trips / 4), wins: Math.round(t7.wins / 4), long_trips: Math.round(t7.long_trips / 4), short_trips: Math.round(t7.trips / 4) - Math.round(t7.long_trips / 4) },
    t7,
  ];
  const risk = [
    { ...row.risk_30d, window: "7d" as const, days: 7, max_drawdown_pct: round((row.risk_30d.max_drawdown_pct ?? 5) * 0.6, 1) },
    row.risk_30d,
    { ...row.risk_30d, window: "all" as const, days: 365, max_drawdown_pct: round((row.risk_30d.max_drawdown_pct ?? 5) * 1.7, 1), sharpe: round((row.risk_30d.sharpe ?? 1) * 0.8, 2) },
  ];
  const recent_trips: RoundTrip[] = [];
  let tc = nowMs - HOUR;
  const holdBase = row.trades_30d.median_hold_h ?? 10;
  for (let k = 0; k < Math.min(60, row.trades_30d.trips); k++) {
    const coin = pick(r, row.top_coins.length ? row.top_coins.map((c) => c.coin) : ["BTC"]);
    const hold = round(holdBase * between(r, 0.3, 2.2), 2);
    const closed = Math.round(tc);
    const opened = Math.round(closed - hold * HOUR);
    tc = opened - between(r, 0.1, 1) * hold * HOUR;
    const side = r() < 0.6 ? "long" : "short";
    const mark = MARK[coin] ?? 10;
    const entry = round(mark * between(r, 0.93, 1.05), mark < 1 ? 6 : 2);
    const win = r() < (row.trades_30d.win_rate_pct ?? 50) / 100;
    const move = between(r, 0.002, 0.05) * (win ? 1 : -1) * (side === "long" ? 1 : -1);
    const maxN = round(row.account_value_usd * between(r, 0.02, 0.5), 0);
    const gross = round(maxN * Math.abs(move) * (win ? 1 : -1), 2);
    const fee = round(maxN * 0.0007, 2);
    // Funding scales with hold time (HL settles roughly hourly); sign is a coin flip, same
    // order of magnitude as the live `funding_since_open_usd` fixture a few lines up.
    const funding = round(maxN * between(r, -0.0006, 0.0006) * (hold / 24), 2);
    const net = round(gross - fee + funding, 2);
    recent_trips.push({ coin, side, opened_ms: opened, closed_ms: closed, hold_h: hold, entry_px: entry, exit_px: round(entry * (1 + move), mark < 1 ? 6 : 2), max_notional_usd: maxN, gross_pnl_usd: gross, fee_usd: fee, funding_usd: funding, net_pnl_usd: net, win: net > 0 });
  }
  const coins: CoinStat[] = [...row.top_coins];
  for (const c of COINS) {
    if (coins.length >= 9) break;
    if (!coins.some((x) => x.coin === c) && r() < 0.3) coins.push({ coin: c, volume_usd: round(row.perf[2].volume_usd * between(r, 0.001, 0.02), 0), pnl_usd: round(between(r, -0.01, 0.01) * row.account_value_usd, 0), trips: 1 + Math.floor(r() * 4) });
  }
  return {
    row, account, positions, positions_as_of_ms: nowMs - 20_000, pnl_curve, value_curve, sim_curve, daily_pnl, risk, trades,
    longest_win_streak_days: 2 + Math.floor((row.score.copy_fit?.value ?? 40) / 9), coins, recent_trips,
    recent_fills: fixtureFills(row, nowMs, null, 50),
  };
}

/**
 * Demo what-if: deterministic in the request, plausible in direction (more
 * leverage = bigger swings, more equity = fewer min-order skips). It is a
 * stand-in for the real sim and the UI labels it as demo data.
 */
export function fixtureWhatIf(profile: TraderProfile, req: WhatIfRequest): WhatIfResult {
  const o: LeaderOverride = req.override;
  const levFactor = o.leverage_mode === "fixed" && o.leverage ? o.leverage / 20 : o.leverage_mode === "match" ? 0.6 : 1;
  const sizeFactor = o.sizing_mode === "proportional" ? (o.size_multiplier ?? 1) * 0.8 : o.sizing_mode === "fixed_notional" ? (o.fixed_notional_usd ?? 10.5) / 20 : (o.fixed_margin_usd ?? 5) / 5;
  const k = Math.max(0.05, Math.min(6, levFactor * sizeFactor * (1000 / req.sim_equity_usd) ** 0.3));
  const base = profile.sim_curve[0]?.value ?? FIXTURE_SIM_EQUITY;
  const sim_curve = profile.sim_curve.map((p) => ({ t_ms: p.t_ms, value: round(req.sim_equity_usd * Math.max(0.01, 1 + ((p.value / base - 1) * k)), 2) }));
  const last = sim_curve[sim_curve.length - 1]?.value ?? req.sim_equity_usd;
  let peak = -Infinity;
  let dd = 0;
  for (const p of sim_curve) {
    peak = Math.max(peak, p.value);
    dd = Math.min(dd, (p.value / peak - 1) * 100);
  }
  const s = profile.row.score;
  const skipped = Math.max(0, Math.round(s.sim_skipped_min_order * (1000 / req.sim_equity_usd)));
  return {
    sim_curve,
    score: {
      ...s, copy_fit: null, sim_return_pct: round((last / req.sim_equity_usd - 1) * 100, 2), sim_max_drawdown_pct: round(dd, 1),
      sim_liquidations: dd <= -90 ? 1 : 0, sim_skipped_min_order: skipped, sim_fees_usd: round(s.sim_fees_usd * k, 2),
      sim_copy_capacity_pct: round((s.sim_copies / Math.max(1, s.sim_copies + skipped)) * 100, 1),
    },
  };
}
