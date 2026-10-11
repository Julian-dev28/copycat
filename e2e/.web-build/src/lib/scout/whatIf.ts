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

/** Draft from a stored override ("" = inherit the book-wide value). */
export function draftFromOverride(override: LeaderOverride | null | undefined, equity: number): WhatIfDraft {
  const o = override ?? {};
  return {
    equity: String(equity),
    sizing_mode: o.sizing_mode ?? "",
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
