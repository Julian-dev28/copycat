/**
 * What-if request building for the trader file. The draft is what the form
 * holds (strings for numbers, so a half-typed "1." doesn't snap to 1); the
 * builder validates it against the contract bounds in contracts/models.py
 * (LeaderOverride + WhatIfRequest) and returns either a body or per-field
 * errors. Pure functions.
 */
import { normAddr } from "@/lib/address";
import { HL_MIN_ORDER_USD, MAX_LEVERAGE_CAP, type LeaderOverride, type LeverageMode, type MarginMode, type SettingsPatch, type SizingMode } from "@/lib/api/types";
import { compactOverride } from "@/lib/forLeader";
import type { WhatIfRequest } from "./types";

export interface WhatIfDraft {
  equity: string;
  sizing_mode: SizingMode | "";
  /** "allocation": invest this much at `target_leverage`, the Trade ticket's and the board's model. */
  allocation_usd: string;
  target_leverage: string;
  size_multiplier: string;
  fixed_margin_usd: string;
  fixed_notional_usd: string;
  leverage_mode: LeverageMode | "";
  leverage: string;
  margin_mode: MarginMode | "";
  max_worse_entry_pct: string;
}

export type WhatIfField = keyof WhatIfDraft;

/** Sim equity the form starts with when nothing better is known. */
export const DEFAULT_WHATIF_EQUITY = 1000;

function str(v: number | null | undefined): string {
  return v === null || v === undefined ? "" : String(v);
}

/** The board's sim terms, the shape the what-if seeds from (ScoutSimTerms without the flags it does not use). */
export interface WhatIfSeed {
  sim_equity_usd: number;
  allocation_usd: number;
  exposure_mode: "target" | "match";
  target_leverage?: number | null;
  margin_mode: MarginMode;
  max_worse_entry_pct: number;
}

/**
 * Draft from a stored override ("" = inherit the book-wide value). With no
 * override and the board's sim terms at hand, start FROM those terms: the
 * what-if then opens equal to the "Scout board sim" line and a leverage change
 * moves it. It used to open on the Settings defaults (proportional sizing on
 * this host), where leverage changes nothing and the two lines were never
 * comparable (Julien, 2026-10-16: "still does nothing").
 */
export function draftFromOverride(override: LeaderOverride | null | undefined, equity: number, seed?: WhatIfSeed | null): WhatIfDraft {
  const o = override ?? {};
  if (!override && seed) {
    return {
      equity: String(seed.sim_equity_usd),
      sizing_mode: "allocation",
      allocation_usd: str(seed.allocation_usd),
      target_leverage: seed.exposure_mode === "target" ? str(seed.target_leverage) : "",
      size_multiplier: "",
      fixed_margin_usd: "",
      fixed_notional_usd: "",
      leverage_mode: seed.exposure_mode === "match" ? "match" : "",
      leverage: "",
      margin_mode: seed.margin_mode,
      max_worse_entry_pct: str(seed.max_worse_entry_pct),
    };
  }
  return {
    equity: String(equity),
    sizing_mode: o.sizing_mode ?? "",
    allocation_usd: str(o.allocation_usd),
    target_leverage: str(o.target_leverage),
    size_multiplier: str(o.size_multiplier),
    fixed_margin_usd: str(o.fixed_margin_usd),
    fixed_notional_usd: str(o.fixed_notional_usd),
    leverage_mode: o.leverage_mode ?? "",
    leverage: str(o.leverage),
    margin_mode: o.margin_mode ?? "",
    max_worse_entry_pct: str(o.max_worse_entry_pct),
  };
}

type Bound = { min: number; max: number; int?: boolean; label: string };

const BOUNDS: Partial<Record<WhatIfField, Bound>> = {
  allocation_usd: { min: HL_MIN_ORDER_USD, max: 1e9, label: `Invest at least $${HL_MIN_ORDER_USD}` },
  target_leverage: { min: 1, max: MAX_LEVERAGE_CAP, int: true, label: `Leverage must be a whole number 1 to ${MAX_LEVERAGE_CAP}` },
  size_multiplier: { min: 0, max: 100, label: "Multiplier must be 0 to 100" },
  fixed_margin_usd: { min: 0.01, max: Infinity, label: "Margin must be at least $0.01" },
  fixed_notional_usd: { min: HL_MIN_ORDER_USD, max: Infinity, label: `Notional must be at least $${HL_MIN_ORDER_USD}` },
  leverage: { min: 1, max: MAX_LEVERAGE_CAP, int: true, label: `Leverage must be a whole number 1 to ${MAX_LEVERAGE_CAP}` },
  max_worse_entry_pct: { min: 0, max: 100, label: "Worse entry must be 0 to 100%" },
};

export type WhatIfBuild =
  | { ok: true; body: WhatIfRequest }
  | { ok: false; errors: Partial<Record<WhatIfField, string>> };

export function buildWhatIfRequest(d: WhatIfDraft): WhatIfBuild {
  const errors: Partial<Record<WhatIfField, string>> = {};
  const override: LeaderOverride = {};

  const equity = Number(d.equity);
  if (d.equity.trim() === "" || !Number.isFinite(equity) || equity <= 0) errors.equity = "Equity must be above $0";
  else if (equity > 1e9) errors.equity = "Equity looks wrong (over $1B)";

  if (d.sizing_mode) override.sizing_mode = d.sizing_mode;
  if (d.leverage_mode) override.leverage_mode = d.leverage_mode;
  if (d.margin_mode) override.margin_mode = d.margin_mode;

  for (const [field, bound] of Object.entries(BOUNDS) as [WhatIfField, Bound][]) {
    const raw = d[field].trim();
    if (raw === "") continue;
    const n = Number(raw);
    if (!Number.isFinite(n) || n < bound.min || n > bound.max || (bound.int && !Number.isInteger(n))) {
      errors[field] = bound.label;
      continue;
    }
    (override as Record<string, number>)[field] = n;
  }

  // Only send the size field the chosen mode reads, so a leftover value from
  // another mode can't land in a saved override.
  const mode = override.sizing_mode;
  if (mode && mode !== "fixed_margin") delete override.fixed_margin_usd;
  if (mode && mode !== "fixed_notional") delete override.fixed_notional_usd;
  if (mode && mode !== "proportional") delete override.size_multiplier;
  if (mode !== "allocation") {
    delete override.allocation_usd;
    delete override.target_leverage;
  } else {
    // invest $X at Nx: the leverage is the target, not a leverage_mode
    if (d.allocation_usd.trim() === "") errors.allocation_usd = `Invest at least $${HL_MIN_ORDER_USD}`;
    if (override.target_leverage != null) override.exposure_mode = "target";
    delete override.leverage_mode;
    delete override.leverage;
  }
  if (override.leverage_mode && override.leverage_mode !== "fixed") delete override.leverage;

  if (Object.keys(errors).length) return { ok: false, errors };
  return { ok: true, body: { sim_equity_usd: equity, override: compactOverride(override) } };
}

/** PATCH /api/settings body that stores the draft as this leader's override; an empty override clears it. */
export function overrideSettingsPatch(address: string, override: LeaderOverride): SettingsPatch {
  const compact = compactOverride(override);
  return { leader_overrides: { [normAddr(address)]: Object.keys(compact).length ? compact : null } };
}

/** True when the draft's override differs from what is stored (equity is not part of an override). */
export function overrideDiffers(draftOverride: LeaderOverride, stored: LeaderOverride | null | undefined): boolean {
  const a = compactOverride(draftOverride);
  const b = compactOverride(stored);
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of keys) if ((a as Record<string, unknown>)[k] !== (b as Record<string, unknown>)[k]) return true;
  return false;
}

/** Short field names for the "changed from saved" chips. */
export const WHATIF_FIELD_LABEL: Record<WhatIfField, string> = {
  equity: "Equity",
  sizing_mode: "Sizing",
  allocation_usd: "Invest",
  target_leverage: "Leverage x",
  size_multiplier: "Multiplier",
  fixed_margin_usd: "Margin per trade",
  fixed_notional_usd: "Notional per trade",
  leverage_mode: "Leverage",
  leverage: "Leverage x",
  margin_mode: "Margin mode",
  max_worse_entry_pct: "Max worse entry",
};

const FIELD_ORDER = Object.keys(WHATIF_FIELD_LABEL) as WhatIfField[];

function same(a: string, b: string): boolean {
  const x = a.trim();
  const y = b.trim();
  if (x === y) return true;
  // "10" and "10.0" are the same number; "" (inherit) never equals a number
  if (x === "" || y === "") return false;
  const nx = Number(x);
  const ny = Number(y);
  return Number.isFinite(nx) && Number.isFinite(ny) && nx === ny;
}

/**
 * Inputs where the draft differs from the saved settings it was seeded from
 * (the stored override plus the default sim equity), in form order. Drives
 * the "changed" marks on the what-if form and the chips on its result line.
 */
export function changedFields(draft: WhatIfDraft, saved: WhatIfDraft): WhatIfField[] {
  return FIELD_ORDER.filter((f) => !same(draft[f], saved[f]));
}

/** True when the draft no longer matches the draft a result was computed from. */
export function draftStale(draft: WhatIfDraft, ran: WhatIfDraft | null): boolean {
  return ran !== null && changedFields(draft, ran).length > 0;
}

/** Settings' sizing modes in a word, for the "Global default (proportional)" option label. */
export const SIZING_WORD: Record<string, string> = {
  proportional: "proportional",
  fixed_margin: "fixed margin",
  fixed_notional: "fixed notional",
  allocation: "allocation",
};

/**
 * Why a what-if can leave the curve where it was: under proportional sizing a
 * copy's size is their exposure ratio times your sleeve, so leverage changes
 * margin and liquidation risk, not the size, and the curve only moves when a
 * copy gets liquidated. Julien ran 1x and 20x on a proportional global default
 * and saw the same +4.2% (2026-10-16). Null when sizing is not proportional or
 * not known.
 */
export function leverageNote(draftSizing: SizingMode | "", globalSizing: string | null | undefined): string | null {
  const effective = draftSizing || globalSizing || "";
  if (effective !== "proportional") return null;
  const via = draftSizing ? "" : " (your Settings default)";
  return `Proportional sizing${via} mirrors their exposure ratio, so leverage changes margin and liquidation risk, not each copy's size: the curve only moves when a copy gets liquidated. Pick Fixed margin or Fixed notional to size by leverage.`;
}
