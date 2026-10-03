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
