/**
 * Mirrors contracts.models.Settings.for_leader exactly: the book-wide
 * Settings merged with one leader's override (absent/null override field =
 * inherit). The engine computes this server-side too (EngineStatus.leaders[].effective)
 * — prefer that when it's available; this is the instant client-side
 * preview used on /copy before/without a status round-trip.
 */
import { normAddr } from "./address";
import type { LeaderOverride, Settings } from "./api/types";

export function effectiveSettingsForLeader(settings: Settings, leader: string): Settings {
  const override = settings.leader_overrides[normAddr(leader)];
  if (!override) return settings;

  const patch: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(override)) {
    if (value !== null && value !== undefined) patch[key] = value;
  }
  return { ...settings, ...patch };
}

/**
 * The api returns unset override fields as null, the UI deletes them
 * (undefined). Both mean "inherit the book-wide value".
 */
export function isOverrideSet(value: unknown): boolean {
  return value !== null && value !== undefined;
}

/** True when an override has at least one field that actually overrides. */
export function hasActiveOverride(override: LeaderOverride | null | undefined): boolean {
  return Boolean(override) && Object.values(override as object).some(isOverrideSet);
}

/** Drops null/undefined fields so a draft holds only real overrides. */
export function compactOverride(override: LeaderOverride | null | undefined): LeaderOverride {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(override ?? {})) if (isOverrideSet(v)) out[k] = v;
  return out as LeaderOverride;
}
