/**
 * Pure merge of a SettingsPatch into a Settings object, matching the api's
 * PATCH /api/settings semantics exactly (docs/ARCHITECTURE.md: "leader_overrides
 * replace per leader; null clears one"). Used to build the optimistic cache
 * update in useSettings.ts so the UI reflects a save instantly, and rolls
 * back cleanly if the server rejects it.
 */
import type { LeaderOverride, Settings, SettingsPatch } from "./api/types";

export function applySettingsPatch(current: Settings, patch: SettingsPatch): Settings {
  const { leader_overrides, ...rest } = patch;
  const next: Settings = { ...current, ...rest };

  if (leader_overrides) {
    const merged: Record<string, LeaderOverride> = { ...current.leader_overrides };
    for (const [address, override] of Object.entries(leader_overrides)) {
      if (override === null) {
        delete merged[address];
      } else {
        merged[address] = override;
      }
    }
    next.leader_overrides = merged;
  }

  return next;
}

/** True when the settings would place real orders. */
export function isLiveTrading(s: Pick<Settings, "enabled" | "dry_run">): boolean {
  return s.enabled && !s.dry_run;
}

/**
 * A patch needs the "trade with real money?" confirm when it moves the book
 * from not-live to live, whichever switch does it: enabling with dry run
 * already off, or turning dry run off while already enabled, or both at once.
 */
/**
 * Audit L9: dry run blocks the exits of REAL copies too (the engine places no
 * orders at all), so turning it on while real copies are open leaves those
 * leveraged positions unmanaged. True when `patch` would do exactly that.
 */
export function patchStrandsCopies(current: Settings, patch: SettingsPatch, openRealCopies: number): boolean {
  return openRealCopies > 0 && !current.dry_run && applySettingsPatch(current, patch).dry_run === true;
}

export function patchGoesLive(current: Settings, patch: SettingsPatch): boolean {
  return !isLiveTrading(current) && isLiveTrading(applySettingsPatch(current, patch));
}
