/**
 * Mirrors contracts.models.Settings.for_leader exactly: the book-wide
 * Settings merged with one leader's override (absent/null override field =
 * inherit). The engine computes this server-side too (EngineStatus.leaders[].effective)
 * — prefer that when it's available; this is the instant client-side
 * preview used on /copy before/without a status round-trip.
 */
import { normAddr } from "./address";
import type { Settings } from "./api/types";

export function effectiveSettingsForLeader(settings: Settings, leader: string): Settings {
  const override = settings.leader_overrides[normAddr(leader)];
  if (!override) return settings;

  const patch: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(override)) {
    if (value !== null && value !== undefined) patch[key] = value;
  }
  return { ...settings, ...patch };
}
