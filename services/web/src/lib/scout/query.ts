/**
 * Scout board state <-> URL <-> api query string. Pure functions only.
 *
 * The board's state lives in the page URL (shareable, survives refresh,
 * back button works). Three projections of one BoardState:
 *   - parseBoardState(searchParams)   URL -> state (validates every field)
 *   - boardStateToSearch(state)       state -> URL (only non-default fields)
 *   - boardStateToApiQuery(state)     state -> GET /api/scout/traders query,
 *                                     the params in spec section 5
 * plus applyBoardQuery(rows, state), the same filter/sort semantics run
 * client side, used by ?demo=1 so the fixture board reacts to every control.
 */
import { normAddr } from "@/lib/address";
import { PNL_WINDOWS, TRADING_STYLES, type PnlWindow, type ScoutPresets, type TraderRow, type TradingStyle } from "./types";
import { windowPerf } from "./window";

export type SortKey =
  | "fit"
  | "sim_return"
  | "sim_dd"
  | "pnl"
  | "roi"
  | "account_value"
  | "sharpe"
  | "max_dd"
  | "win_rate"
  | "trips"
  | "last_active"
  | "volume";

export const SORT_KEYS: SortKey[] = [
  "fit", "sim_return", "sim_dd", "pnl", "roi", "account_value", "sharpe", "max_dd", "win_rate", "trips", "last_active", "volume",
];

export type SortOrder = "asc" | "desc";
export type PnlUnit = "usd" | "pct";
export type BoardView = "cards" | "table";

/** The sort menu: each entry is a (sort, order) pair phrased as what you want first. */
export const SORT_OPTIONS: { sort: SortKey; order: SortOrder; label: string }[] = [
  { sort: "fit", order: "desc", label: "Best Copy Fit" },
  { sort: "sim_return", order: "desc", label: "Best return if copied" },
  { sort: "roi", order: "desc", label: "Highest ROI" },
  { sort: "pnl", order: "desc", label: "Highest PnL" },
  { sort: "account_value", order: "desc", label: "Largest account" },
  { sort: "account_value", order: "asc", label: "Smallest account" },
  { sort: "last_active", order: "desc", label: "Recently active" },
  { sort: "max_dd", order: "asc", label: "Smallest drawdown" },
  { sort: "sharpe", order: "desc", label: "Best Sharpe" },
  { sort: "win_rate", order: "desc", label: "Best win rate" },
  { sort: "trips", order: "desc", label: "Most trades" },
  { sort: "volume", order: "desc", label: "Most volume" },
];

export interface BoardState {
  window: PnlWindow;
  sort: SortKey;
  order: SortOrder;
  /** "all", "hip3", "custom" (hand-added wallets) or "coin:<COIN>". */
  preset: string;
  coins: string[];
  minAv: number | null;
  maxAv: number | null;
  minPnl: number | null;
  maxPnl: number | null;
  styles: TradingStyle[];
  minFit: number;
  maxFit: number;
  maxDd: number | null;
  minTrips: number | null;
  activeWithinH: number | null;
  hideFlagged: boolean;
  q: string;
  /** UI only, never sent to the api. */
  unit: PnlUnit;
  view: BoardView;
  limit: number;
}

export const PAGE_SIZE = 60;
export const MAX_LIMIT = 200;

export const DEFAULT_BOARD: BoardState = {
  window: "30d",
  sort: "fit",
  order: "desc",
  preset: "all",
  coins: [],
  minAv: null,
  maxAv: null,
  minPnl: null,
  maxPnl: null,
  styles: [],
  minFit: 0,
  maxFit: 100,
  maxDd: null,
  minTrips: null,
  activeWithinH: null,
  hideFlagged: false,
  q: "",
  unit: "usd",
  view: "cards",
  limit: PAGE_SIZE,
};

/** Flags that `hide_flagged` drops (spec section 5). */
export const HIDE_FLAGS = ["liquidated", "hft", "vault", "inactive"];

const COIN_RE = /^[A-Za-z0-9]{1,12}(:[A-Za-z0-9]{1,16})?$/;

function num(v: string | null): number | null {
  if (v === null || v.trim() === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

export function isPreset(p: string): boolean {
  if (p === "all" || p === "hip3" || p === "custom") return true;
  return p.startsWith("coin:") && COIN_RE.test(p.slice(5));
}

/** URL -> state. Unknown or malformed values fall back to the default, never throw. */
export function parseBoardState(sp: URLSearchParams): BoardState {
  const s: BoardState = { ...DEFAULT_BOARD, coins: [], styles: [] };
  const w = sp.get("window");
  if (w && (PNL_WINDOWS as string[]).includes(w)) s.window = w as PnlWindow;
  const sort = sp.get("sort");
  if (sort && (SORT_KEYS as string[]).includes(sort)) s.sort = sort as SortKey;
  const order = sp.get("order");
  if (order === "asc" || order === "desc") s.order = order;
  const preset = sp.get("preset");
  if (preset && isPreset(preset)) s.preset = preset;
  s.coins = [...new Set(sp.getAll("coin").filter((c) => COIN_RE.test(c)))];
  s.minAv = num(sp.get("min_av"));
  s.maxAv = num(sp.get("max_av"));
  s.minPnl = num(sp.get("min_pnl"));
  s.maxPnl = num(sp.get("max_pnl"));
  s.styles = [...new Set(sp.getAll("style").filter((x): x is TradingStyle => (TRADING_STYLES as string[]).includes(x)))];
  const minFit = num(sp.get("min_fit"));
  const maxFit = num(sp.get("max_fit"));
  s.minFit = minFit === null ? 0 : clamp(Math.round(minFit), 0, 100);
  s.maxFit = maxFit === null ? 100 : clamp(Math.round(maxFit), 0, 100);
  if (s.minFit > s.maxFit) [s.minFit, s.maxFit] = [s.maxFit, s.minFit];
  const dd = num(sp.get("max_dd"));
  s.maxDd = dd === null ? null : Math.max(0, dd);
  const trips = num(sp.get("min_trips"));
  s.minTrips = trips === null ? null : Math.max(0, Math.round(trips));
  const act = num(sp.get("active_within_h"));
  s.activeWithinH = act === null || act <= 0 ? null : Math.round(act);
  s.hideFlagged = sp.get("hide_flagged") === "1" || sp.get("hide_flagged") === "true";
  s.q = (sp.get("q") ?? "").trim().slice(0, 64);
  if (sp.get("unit") === "pct") s.unit = "pct";
  const view = sp.get("view");
  if (view === "table" || view === "cards") s.view = view;
  const limit = num(sp.get("limit"));
  if (limit !== null) s.limit = clamp(Math.round(limit), 1, MAX_LIMIT);
  return s;
}

function setNum(p: URLSearchParams, key: string, v: number | null) {
  if (v !== null && Number.isFinite(v)) p.set(key, String(v));
}

/** The filter + sort params shared by the page URL and the api query. Fixed key order. */
function filterParams(s: BoardState): URLSearchParams {
  const p = new URLSearchParams();
  p.set("window", s.window);
  p.set("sort", s.sort);
  p.set("order", s.order);
  p.set("preset", s.preset);
  for (const c of s.coins) p.append("coin", c);
  setNum(p, "min_av", s.minAv);
  setNum(p, "max_av", s.maxAv);
  setNum(p, "min_pnl", s.minPnl);
  setNum(p, "max_pnl", s.maxPnl);
  for (const st of s.styles) p.append("style", st);
  if (s.minFit > 0) p.set("min_fit", String(s.minFit));
  if (s.maxFit < 100) p.set("max_fit", String(s.maxFit));
  setNum(p, "max_dd", s.maxDd);
  setNum(p, "min_trips", s.minTrips);
  setNum(p, "active_within_h", s.activeWithinH);
  if (s.hideFlagged) p.set("hide_flagged", "true");
  if (s.q) p.set("q", s.q);
  return p;
}

/** state -> GET /api/scout/traders?... (spec section 5). Defaults are sent explicitly so the cache key is stable. */
export function boardStateToApiQuery(s: BoardState): string {
  const p = filterParams(s);
  p.set("limit", String(clamp(s.limit, 1, MAX_LIMIT)));
  p.set("offset", "0");
  return p.toString();
}

/** state -> page URL query, dropping every default so a clean board has a clean URL. */
export function boardStateToSearch(s: BoardState, extra?: Record<string, string>): string {
  const p = filterParams(s);
  const d = filterParams(DEFAULT_BOARD);
  for (const key of ["window", "sort", "order", "preset"]) {
    if (p.get(key) === d.get(key)) p.delete(key);
  }
  if (p.get("hide_flagged") === "true") p.set("hide_flagged", "1");
  if (s.unit !== DEFAULT_BOARD.unit) p.set("unit", s.unit);
  if (s.view !== DEFAULT_BOARD.view) p.set("view", s.view);
  if (s.limit !== DEFAULT_BOARD.limit) p.set("limit", String(s.limit));
  for (const [k, v] of Object.entries(extra ?? {})) p.set(k, v);
  return p.toString();
}

/** How many filter controls differ from default (the "Filters (3)" count). Presets, window and sort are not filters. */
export function countActiveFilters(s: BoardState): number {
  let n = 0;
  if (s.minAv !== null || s.maxAv !== null) n++;
  if (s.minPnl !== null || s.maxPnl !== null) n++;
  if (s.styles.length) n++;
  if (s.minFit > 0 || s.maxFit < 100) n++;
  if (s.maxDd !== null) n++;
  if (s.minTrips !== null) n++;
  if (s.activeWithinH !== null) n++;
  if (s.hideFlagged) n++;
  if (s.coins.length) n++;
  if (s.q) n++;
  return n;
}

export interface FilterChip {
  key: string;
  label: string;
  /** The patch that removes just this filter. */
  clear: Partial<BoardState>;
}

const compactUsd = (v: number) => {
  const a = Math.abs(v);
  const t = a >= 1e6 ? `${Number((a / 1e6).toFixed(1))}M` : a >= 1e3 ? `${Number((a / 1e3).toFixed(1))}k` : `${Number(a.toFixed(0))}`;
  return `${v < 0 ? "-" : ""}$${t}`;
};

function range(lo: number | null, hi: number | null, fmt: (v: number) => string): string {
  if (lo !== null && hi !== null) return `${fmt(lo)} to ${fmt(hi)}`;
  return lo !== null ? `at least ${fmt(lo)}` : `at most ${fmt(hi as number)}`;
}

/**
 * One removable chip per active filter, in the same order and grouping as
 * countActiveFilters (so the chip count equals the "Filters (n)" badge).
 */
export function activeFilterChips(s: BoardState, styleLabel: (st: TradingStyle) => string = (st) => st): FilterChip[] {
  const out: FilterChip[] = [];
  if (s.minAv !== null || s.maxAv !== null) out.push({ key: "av", label: `Account ${range(s.minAv, s.maxAv, compactUsd)}`, clear: { minAv: null, maxAv: null } });
  if (s.minPnl !== null || s.maxPnl !== null) out.push({ key: "pnl", label: `PnL ${range(s.minPnl, s.maxPnl, compactUsd)}`, clear: { minPnl: null, maxPnl: null } });
  if (s.styles.length) out.push({ key: "styles", label: s.styles.map(styleLabel).join(", "), clear: { styles: [] } });
  if (s.minFit > 0 || s.maxFit < 100) out.push({ key: "fit", label: `Copy Fit ${s.minFit} to ${s.maxFit}`, clear: { minFit: 0, maxFit: 100 } });
  if (s.maxDd !== null) out.push({ key: "dd", label: `Max DD at most ${s.maxDd}%`, clear: { maxDd: null } });
  if (s.minTrips !== null) out.push({ key: "trips", label: `${s.minTrips}+ trips`, clear: { minTrips: null } });
  if (s.activeWithinH !== null) out.push({ key: "active", label: `Active in ${s.activeWithinH >= 48 ? `${Math.round(s.activeWithinH / 24)}d` : `${s.activeWithinH}h`}`, clear: { activeWithinH: null } });
  if (s.hideFlagged) out.push({ key: "flagged", label: "Hide flagged", clear: { hideFlagged: false } });
  if (s.coins.length) out.push({ key: "coins", label: `Trades ${s.coins.join(", ")}`, clear: { coins: [] } });
  if (s.q) out.push({ key: "q", label: `"${s.q}"`, clear: { q: "" } });
  return out;
}

/** Clears filters, keeps window, sort, preset and the UI toggles. */
export function clearFilters(s: BoardState): BoardState {
  return {
    ...DEFAULT_BOARD,
    window: s.window, sort: s.sort, order: s.order, preset: s.preset, unit: s.unit, view: s.view, coins: [], styles: [],
  };
}

/**
 * Tolerant read of GET /api/scout/presets. Reads the v3.1 contract shape
 * ({coins: string[], coin_counts, hip3_count, total}) and the pre-v3.1
 * draft ({coins: [{coin, traders}], hip3}); anything else degrades to "no
 * chips", never a crash. Malformed coin names are dropped.
 */
export function normalizePresets(raw: unknown): ScoutPresets {
  const out: ScoutPresets = { coins: [], hip3: 0, total: 0, departed: 0, departedLiquidated: 0, custom: 0 };
  if (!raw || typeof raw !== "object") return out;
  const r = raw as Record<string, unknown>;
  const count = (v: unknown) => (typeof v === "number" && Number.isFinite(v) && v >= 0 ? v : 0);
  out.hip3 = count(r.hip3_count ?? r.hip3);
  out.total = count(r.total);
  out.departed = count(r.departed_30d ?? r.departed);
  out.departedLiquidated = count(r.departed_liquidated_30d ?? r.departedLiquidated);
  out.custom = count(r.custom);
  const counts = r.coin_counts && typeof r.coin_counts === "object" ? (r.coin_counts as Record<string, unknown>) : {};
  const seen = new Set<string>();
  for (const c of Array.isArray(r.coins) ? r.coins : []) {
    let coin: string | null = null;
    let traders = 0;
    if (typeof c === "string") {
      coin = c;
      traders = count(counts[c]);
    } else if (c && typeof c === "object" && typeof (c as { coin?: unknown }).coin === "string") {
      coin = (c as { coin: string }).coin;
      traders = count((c as { traders?: unknown }).traders ?? counts[coin]);
    }
    if (coin && COIN_RE.test(coin) && !seen.has(coin)) {
      seen.add(coin);
      out.coins.push({ coin, traders });
    }
  }
  return out;
}

// ── client-side mirror of the server query (demo mode) ─────────────────────

export function hip3Share(row: TraderRow): number {
  const total = row.top_coins.reduce((a, c) => a + c.volume_usd, 0);
  if (total <= 0) return 0;
  return row.top_coins.filter((c) => c.coin.startsWith("xyz:")).reduce((a, c) => a + c.volume_usd, 0) / total;
}

function sortValue(row: TraderRow, key: SortKey, w: PnlWindow): number | null {
  const perf = windowPerf(row, w);
  switch (key) {
    case "fit": return row.score.copy_fit?.value ?? null;
    case "sim_return": return row.score.sim_return_pct;
    case "sim_dd": return row.score.sim_max_drawdown_pct;
    case "pnl": return perf?.pnl_usd ?? null;
    case "roi": return perf?.roi_pct ?? null;
    case "account_value": return row.account_value_usd;
    case "sharpe": return row.risk_30d.sharpe ?? null;
    case "max_dd": return row.risk_30d.max_drawdown_pct ?? null;
    case "win_rate": return row.trades_30d.win_rate_pct ?? null;
    case "trips": return row.trades_30d.trips;
    case "last_active": return row.last_fill_ms ?? null;
    case "volume": return perf?.volume_usd ?? null;
  }
}

export function applyBoardQuery(rows: TraderRow[], s: BoardState, nowMs: number): { rows: TraderRow[]; total: number } {
  const q = s.q.toLowerCase();
  const filtered = rows.filter((r) => {
    const perf = windowPerf(r, s.window);
    if (s.preset === "hip3" && hip3Share(r) < 0.5) return false;
    if (s.preset === "custom" && !r.custom) return false;
    if (s.preset.startsWith("coin:") && r.top_coins[0]?.coin !== s.preset.slice(5)) return false;
    if (s.coins.length && !s.coins.every((c) => r.top_coins.some((tc) => tc.coin === c))) return false;
    if (s.minAv !== null && r.account_value_usd < s.minAv) return false;
    if (s.maxAv !== null && r.account_value_usd > s.maxAv) return false;
    if (s.minPnl !== null && (perf?.pnl_usd ?? -Infinity) < s.minPnl) return false;
    if (s.maxPnl !== null && (perf?.pnl_usd ?? Infinity) > s.maxPnl) return false;
    if (s.styles.length && (!r.style || !s.styles.includes(r.style))) return false;
    const fit = r.score.copy_fit?.value ?? 0;
    if (fit < s.minFit || fit > s.maxFit) return false;
    if (s.maxDd !== null && (r.risk_30d.max_drawdown_pct ?? Infinity) > s.maxDd) return false;
    if (s.minTrips !== null && r.trades_30d.trips < s.minTrips) return false;
    if (s.activeWithinH !== null && (!r.last_fill_ms || nowMs - r.last_fill_ms > s.activeWithinH * 3_600_000)) return false;
    if (s.hideFlagged && r.flags.some((f) => HIDE_FLAGS.includes(f.split(":")[0]))) return false;
    if (q && !normAddr(r.address).startsWith(q) && !(r.display_name ?? "").toLowerCase().includes(q)) return false;
    return true;
  });
  const dir = s.order === "asc" ? 1 : -1;
  const sorted = [...filtered].sort((a, b) => {
    const va = sortValue(a, s.sort, s.window);
    const vb = sortValue(b, s.sort, s.window);
    // nulls always last, whichever direction
    if (va === null && vb === null) return a.address.localeCompare(b.address);
    if (va === null) return 1;
    if (vb === null) return -1;
    return va === vb ? a.address.localeCompare(b.address) : (va - vb) * dir;
  });
  return { rows: sorted.slice(0, s.limit), total: sorted.length };
}

/**
 * Filter-field text -> number. Accepts "10000", "10k", "$1.5M", "1,000",
 * "-5k". "" -> null (no filter). Anything else -> undefined (reject, keep
 * the previous value).
 */
export function parseAmount(text: string): number | null | undefined {
  const t = text.trim().replace(/[,_$\s]/g, "");
  if (t === "") return null;
  const m = /^(-?\d*\.?\d+)([kKmMbB]?)$/.exec(t);
  if (!m) return undefined;
  const mult = { "": 1, k: 1e3, m: 1e6, b: 1e9 }[m[2].toLowerCase() as "" | "k" | "m" | "b"];
  return Number(m[1]) * mult;
}
