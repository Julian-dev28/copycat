/**
 * POST /api/wallets/{a}/preview (contract WalletPreview) -> the ticket's
 * TicketPreview. The one place that knows the wire field names, so a
 * contract tweak is a one-file change. Tolerant: a missing field becomes
 * null/0 rather than a crash, and the ticket keeps the local numbers for
 * anything the api leaves out.
 */
import type { CopyStatus, LiqEstimate, PlannedCopy, TicketPreview } from "./ticket";

type Obj = Record<string, unknown>;

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);
const first = (o: Obj, keys: string[]): unknown => keys.map((k) => o[k]).find((v) => v !== undefined && v !== null);

function status(o: Obj, notional: number): CopyStatus {
  const s = String(first(o, ["status", "action"]) ?? "").toLowerCase();
  if (s.startsWith("skip") || notional <= 0) return "skipped";
  // contract v5 WalletPreviewSlice: copy | trimmed | bump | skip ("trimmed" = cut by the allocation cap, still copied)
  if (s.startsWith("bump") || s.startsWith("round")) return "bumped";
  return "copy";
}

function copy(raw: unknown): PlannedCopy | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Obj;
  const coin = str(o.coin);
  if (!coin) return null;
  const notional = num(first(o, ["notional_usd", "copy_notional_usd", "our_notional_usd"])) ?? 0;
  const leverage = num(first(o, ["leverage", "exchange_leverage", "our_leverage"])) ?? 1;
  const st = status(o, notional);
  return {
    coin,
    side: o.side === "short" ? "short" : "long",
    hisNotionalUsd: Math.abs(num(first(o, ["his_notional_usd", "leader_notional_usd"])) ?? 0),
    hisLeverage: num(first(o, ["his_leverage", "leader_leverage"])) ?? leverage,
    notionalUsd: st === "skipped" ? 0 : notional,
    leverage,
    marginUsd: num(first(o, ["margin_usd", "our_margin_usd"])) ?? (st === "skipped" ? 0 : notional / Math.max(1, leverage)),
    status: st,
    reason: str(first(o, ["reason", "skip_reason", "note"])),
    cycles: Math.max(1, Math.round(num(first(o, ["cycles", "fill_cycles", "est_cycles"])) ?? 1)),
  };
}

function liq(o: Obj): LiqEstimate {
  const pct = num(first(o, ["liq_distance_pct", "liquidation_distance_pct", "adverse_move_pct"]));
  if (pct === null) return { kind: "unknown" };
  if (o.margin_mode === "cross") return { kind: "cross", pct };
  return { kind: "isolated", pct, leverage: num(first(o, ["liq_leverage", "target_leverage", "max_leverage"])) ?? 1 };
}

export function normalizeApiPreview(raw: unknown): TicketPreview {
  const o = (raw && typeof raw === "object" ? raw : {}) as Obj;
  const list = first(o, ["slices", "copies", "planned"]);
  const copies = (Array.isArray(list) ? list : []).map(copy).filter((c): c is PlannedCopy => c !== null);
  const live = copies.filter((c) => c.status !== "skipped");
  const maxCycles = num(first(o, ["max_cycles"])) ?? live.reduce((m, c) => Math.max(m, c.cycles), 1);
  const hisEq = num(o.his_equity_usd);
  const hisGross = num(o.his_gross_notional_usd);
  const hisLev = hisEq && hisEq > 0 && hisGross !== null ? hisGross / hisEq : null;
  const alloc = num(o.allocation_usd) ?? 0;
  const L = num(o.target_leverage);
  const target = o.exposure_mode === "target" && L ? alloc * L : hisLev !== null ? alloc * hisLev : 0;
  return {
    copies,
    copied: num(first(o, ["copied", "n_copied", "copies_count"])) ?? live.length,
    total: num(first(o, ["total", "n_positions", "his_positions"])) ?? copies.length,
    exposureUsd: num(first(o, ["planned_notional_usd", "exposure_usd"])) ?? live.reduce((a, c) => a + c.notionalUsd, 0),
    marginUsd: num(first(o, ["planned_margin_usd", "margin_usd"])) ?? live.reduce((a, c) => a + c.marginUsd, 0),
    targetExposureUsd: num(first(o, ["target_exposure_usd"])) ?? target,
    hisLeverage: num(first(o, ["his_leverage"])) ?? hisLev,
    fullBookUsd: num(first(o, ["min_allocation_for_full_book", "full_book_usd"])),
    liq: liq(o),
    liquidityCapped: Boolean(first(o, ["multi_cycle", "liquidity_capped"])) || maxCycles > 1,
    maxCycles,
    notes: Array.isArray(o.notes) ? o.notes.filter((n): n is string => typeof n === "string") : [],
    source: "api",
  };
}

/** The api preview, with anything it left blank filled from the local estimate. */
export function mergePreview(api: TicketPreview | null | undefined, local: TicketPreview): TicketPreview {
  if (!api) return local;
  return {
    ...api,
    copies: api.copies.length || !local.copies.length ? api.copies : local.copies,
    targetExposureUsd: api.targetExposureUsd || local.targetExposureUsd,
    hisLeverage: api.hisLeverage ?? local.hisLeverage,
    fullBookUsd: api.fullBookUsd ?? local.fullBookUsd,
    liq: api.liq.kind === "unknown" ? local.liq : api.liq,
  };
}
