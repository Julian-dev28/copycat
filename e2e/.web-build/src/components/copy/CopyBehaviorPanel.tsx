"use client";

import { useSyncedState } from "@/hooks/useSyncedState";
import type { Settings, SettingsPatch } from "@/lib/api/types";
import { MAX_LEVERAGE_CAP } from "@/lib/api/types";
import { Panel, PanelHeader, SettingRow } from "@/components/ui/Panel";
import { Slider } from "@/components/ui/Slider";
import { Switch } from "@/components/ui/Switch";
import { LiquidationHint } from "./LiquidationHint";
import { fixedLeverageCap } from "./leverageCap";
import { useDebouncedCallback } from "@/hooks/useDebouncedCallback";
import { leverageVibe, worseEntryVibe } from "@/lib/copyRecipe";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { CoinChips } from "@/components/trade/CoinChips";
import { COMMON_COINS } from "@/lib/trade/coinFilter";
import { DIRECTION_META } from "@/lib/trade/direction";

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
  const fixedCap = fixedLeverageCap({ ...settings, max_position_leverage: maxPositionLeverage });

  return (
    <Panel>
      <PanelHeader title="Copy behavior" description="How closely each copy tracks the trader." />
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
          formatValue={(v) => `${v} x`}
          vibe={leverageVibe}
        />
        {fixedCap?.capped ? (
          <p data-testid="max-leverage-caps-fixed" className="mt-1.5 text-xs font-medium text-warning">
            Below your fixed leverage ({fixedCap.set}x), so new copies open at {fixedCap.effective}x.
          </p>
        ) : null}
      </SettingRow>
      <SettingRow
        title="Include spot & staked assets"
        description="Count spot balances and staked HYPE toward the trader's equity when sizing proportional copies."
        htmlFor="include_spot_staked"
        inline
      >
        <div className="flex justify-end">
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
        description="Ignore a trader's positions that were already open when you started following them."
        htmlFor="only_new_positions"
        inline
      >
        <div className="flex justify-end">
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
        description="Skip a copy if your entry would land this much worse than the trader's, vs. mid at signal time."
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
          formatValue={(v) => `${v} %`}
          vibe={worseEntryVibe}
        />
      </SettingRow>
      {settings.trade_direction !== undefined ? (
        <>
          <SettingRow
            title="Default direction"
            description={`${DIRECTION_META[settings.trade_direction].line} Each wallet can pick its own in the Trade ticket.`}
            htmlFor="trade_direction"
          >
            <SegmentedControl<"copy" | "counter">
              aria-label="Default direction"
              options={[{ value: "copy", label: "Copy" }, { value: "counter", label: "Counter" }]}
              value={settings.trade_direction}
              onChange={(v) => onPatch({ trade_direction: v })}
            />
          </SettingRow>
          <SettingRow
            title="Only these coins"
            description="When set, new copies open only on these coins. Empty: any coin. A wallet's own list replaces this one."
          >
            <CoinChips label="Only these coins (all wallets)" value={settings.coin_allowlist ?? []} onChange={(v) => onPatch({ coin_allowlist: v })} hisCoins={[]} allCoins={COMMON_COINS} placeholder="Any coin" />
          </SettingRow>
          <SettingRow
            title="Never these coins"
            description="New copies never open on these coins. Exits are always followed, whatever the lists say."
          >
            <CoinChips label="Never these coins (all wallets)" value={settings.coin_blocklist ?? []} onChange={(v) => onPatch({ coin_blocklist: v })} hisCoins={[]} allCoins={COMMON_COINS} placeholder="None" tone="danger" />
          </SettingRow>
        </>
      ) : null}
      <div className="border-t border-border px-4 py-3 sm:px-5">
        <LiquidationHint leverage={maxPositionLeverage} marginMode={settings.margin_mode} />
      </div>
    </Panel>
  );
}
