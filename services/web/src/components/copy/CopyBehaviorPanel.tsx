"use client";

import { useSyncedState } from "@/hooks/useSyncedState";
import type { Settings, SettingsPatch } from "@/lib/api/types";
import { MAX_LEVERAGE_CAP } from "@/lib/api/types";
import { Panel, PanelHeader, SettingRow } from "@/components/ui/Panel";
import { Slider } from "@/components/ui/Slider";
import { Switch } from "@/components/ui/Switch";
import { LiquidationHint } from "./LiquidationHint";
import { useDebouncedCallback } from "@/hooks/useDebouncedCallback";

export function CopyBehaviorPanel({
  settings,
  onPatch,
}: {
  settings: Settings;
  onPatch: (patch: SettingsPatch) => void;
}) {
  const [maxPositionLeverage, setMaxPositionLeverage] = useSyncedState(settings.max_position_leverage);
  const [maxWorseEntryPct, setMaxWorseEntryPct] = useSyncedState(settings.max_worse_entry_pct);


  const debouncedPatch = useDebouncedCallback((patch: SettingsPatch) => onPatch(patch), 350);

  return (
    <Panel>
      <PanelHeader title="Copy behavior" description="How closely a copy tracks each leader's position." />
      <SettingRow
        title="Maximum position leverage"
        description="Caps the leverage any single copied position can open at, across every sizing mode."
        htmlFor="max_position_leverage"
      >
        <Slider
          id="max_position_leverage"
          min={1}
          max={MAX_LEVERAGE_CAP}
          value={maxPositionLeverage}
          onChange={(v) => {
            setMaxPositionLeverage(v);
            debouncedPatch({ max_position_leverage: v });
          }}
          formatValue={(v) => `${v}x`}
        />
      </SettingRow>
      <SettingRow
        title="Include spot & staked assets"
        description="Count spot balances and staked HYPE toward the leader's equity when sizing proportional copies."
        htmlFor="include_spot_staked"
      >
        <div className="flex justify-end sm:justify-end">
          <Switch
            id="include_spot_staked"
            checked={settings.include_spot_staked}
            onChange={(v) => onPatch({ include_spot_staked: v })}
            label="Include spot & staked assets"
          />
        </div>
      </SettingRow>
      <SettingRow
        title="Only copy newly opened positions"
        description="Ignore a leader's positions that were already open when you started following them."
        htmlFor="only_new_positions"
      >
        <div className="flex justify-end sm:justify-end">
          <Switch
            id="only_new_positions"
            checked={settings.only_new_positions}
            onChange={(v) => onPatch({ only_new_positions: v })}
            label="Only copy newly opened positions"
          />
        </div>
      </SettingRow>
      <SettingRow
        title="Max worse entry"
        description="Skip a copy if your entry would land this much worse than the leader's, vs. mid at signal time."
        htmlFor="max_worse_entry_pct"
      >
        <Slider
          id="max_worse_entry_pct"
          min={0}
          max={100}
          value={maxWorseEntryPct}
          onChange={(v) => {
            setMaxWorseEntryPct(v);
            debouncedPatch({ max_worse_entry_pct: v });
          }}
          formatValue={(v) => `${v}%`}
        />
      </SettingRow>
      <div className="border-t border-border px-4 py-3 sm:px-5">
        <LiquidationHint leverage={maxPositionLeverage} marginMode={settings.margin_mode} />
      </div>
    </Panel>
  );
}
