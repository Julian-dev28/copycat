"use client";

import { useSyncedState } from "@/hooks/useSyncedState";
import { useState } from "react";
import type { Settings, SettingsPatch } from "@/lib/api/types";
import { MAX_LEVERAGE_CAP } from "@/lib/api/types";
import { Panel, PanelHeader, SettingRow } from "@/components/ui/Panel";
import { Switch } from "@/components/ui/Switch";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Slider } from "@/components/ui/Slider";
import { Input } from "@/components/ui/Input";
import { LiquidationHint } from "./LiquidationHint";
import { EnableConfirmDialog } from "./EnableConfirmDialog";
import { useDebouncedCallback } from "@/hooks/useDebouncedCallback";
import { dailyLossLimitToStored, storedToDailyLossMagnitude } from "@/lib/sizing";

const SIZING_OPTIONS = [
  { value: "fixed_margin" as const, label: "Fixed margin" },
  { value: "fixed_notional" as const, label: "Fixed notional" },
  { value: "proportional" as const, label: "Proportional" },
];
const LEVERAGE_MODE_OPTIONS = [
  { value: "max" as const, label: "Max" },
  { value: "match" as const, label: "Match leader" },
  { value: "fixed" as const, label: "Fixed" },
];
const MARGIN_MODE_OPTIONS = [
  { value: "isolated" as const, label: "Isolated" },
  { value: "cross" as const, label: "Cross" },
];

export function EngineControlsPanel({
  settings,
  onPatch,
}: {
  settings: Settings;
  onPatch: (patch: SettingsPatch) => void;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [leverage, setLeverage] = useSyncedState(settings.leverage);
  const [fixedMargin, setFixedMargin] = useSyncedState(settings.fixed_margin_usd);
  const [fixedNotional, setFixedNotional] = useSyncedState(settings.fixed_notional_usd);
  const [sizeMultiplier, setSizeMultiplier] = useSyncedState(settings.size_multiplier);
  const [sleeveFrac, setSleeveFrac] = useSyncedState(Math.round(settings.sleeve_frac * 100));
  const [lossLimit, setLossLimit] = useSyncedState(storedToDailyLossMagnitude(settings.daily_loss_limit_usd));
  const [maxOpenCopies, setMaxOpenCopies] = useSyncedState(settings.max_open_copies);


  const debouncedPatch = useDebouncedCallback((patch: SettingsPatch) => onPatch(patch), 350);
  const lossLimitEnabled = lossLimit > 0;

  function handleEnabledToggle(next: boolean) {
    if (next && !settings.dry_run) {
      setConfirmOpen(true);
      return;
    }
    onPatch({ enabled: next });
  }

  return (
    <Panel>
      <PanelHeader title="Engine" description="What the copy engine is allowed to do, and how it sizes new copies." />

      <SettingRow
        title="Trading enabled"
        description="Real money. When on and dry run is off, the engine places live orders on Hyperliquid."
        htmlFor="enabled"
      >
        <div className="flex justify-end">
          <Switch id="enabled" checked={settings.enabled} onChange={handleEnabledToggle} label="Trading enabled" />
        </div>
      </SettingRow>

      <SettingRow
        title="Dry run"
        description="Engine reads real positions and logs what it would do, but places no orders."
        htmlFor="dry_run"
      >
        <div className="flex justify-end">
          <Switch
            id="dry_run"
            checked={settings.dry_run}
            onChange={(v) => onPatch({ dry_run: v })}
            label="Dry run"
          />
        </div>
      </SettingRow>

      <SettingRow title="Sizing mode" description="How a new copy's size is decided." htmlFor="sizing_mode">
        <SegmentedControl
          aria-label="Sizing mode"
          options={SIZING_OPTIONS}
          value={settings.sizing_mode}
          onChange={(v) => onPatch({ sizing_mode: v })}
        />
      </SettingRow>

      {settings.sizing_mode === "fixed_margin" ? (
        <SettingRow title="Fixed margin" description="Margin posted per new copy, at the resolved leverage.">
          <Input
            type="number"
            min={0.01}
            step={0.5}
            value={fixedMargin}
            onChange={(e) => {
              const v = Number(e.target.value);
              setFixedMargin(v);
              debouncedPatch({ fixed_margin_usd: v });
            }}
          />
        </SettingRow>
      ) : null}

      {settings.sizing_mode === "fixed_notional" ? (
        <SettingRow title="Fixed notional" description="Flat position size per new copy, independent of leverage.">
          <Input
            type="number"
            min={10.5}
            step={1}
            value={fixedNotional}
            onChange={(e) => {
              const v = Number(e.target.value);
              setFixedNotional(v);
              debouncedPatch({ fixed_notional_usd: v });
            }}
          />
        </SettingRow>
      ) : null}

      {settings.sizing_mode === "proportional" ? (
        <>
          <SettingRow title="Size multiplier" description="Scales the proportional copy size up or down.">
            <Input
              type="number"
              min={0}
              max={100}
              step={0.1}
              value={sizeMultiplier}
              onChange={(e) => {
                const v = Number(e.target.value);
                setSizeMultiplier(v);
                debouncedPatch({ size_multiplier: v });
              }}
            />
          </SettingRow>
          <SettingRow
            title="Equity sleeve"
            description="Share of your equity available to split across leaders in proportional mode."
          >
            <Slider
              min={0}
              max={100}
              value={sleeveFrac}
              onChange={(v) => {
                setSleeveFrac(v);
                debouncedPatch({ sleeve_frac: v / 100 });
              }}
              formatValue={(v) => `${v}%`}
            />
          </SettingRow>
        </>
      ) : null}

      <SettingRow title="Leverage mode" description="How the leverage for a new copy is resolved." htmlFor="leverage_mode">
        <SegmentedControl
          aria-label="Leverage mode"
          options={LEVERAGE_MODE_OPTIONS}
          value={settings.leverage_mode}
          onChange={(v) => onPatch({ leverage_mode: v })}
        />
      </SettingRow>

      {settings.leverage_mode === "fixed" ? (
        <SettingRow title="Leverage" description="The fixed leverage used for every new copy.">
          <>
            <Slider
              min={1}
              max={MAX_LEVERAGE_CAP}
              value={leverage}
              onChange={(v) => {
                setLeverage(v);
                debouncedPatch({ leverage: v });
              }}
              formatValue={(v) => `${v}x`}
            />
            <LiquidationHint leverage={leverage} marginMode={settings.margin_mode} />
          </>
        </SettingRow>
      ) : null}

      <SettingRow title="Margin mode" description="Isolated-only markets are forced isolated regardless of this." htmlFor="margin_mode">
        <SegmentedControl
          aria-label="Margin mode"
          options={MARGIN_MODE_OPTIONS}
          value={settings.margin_mode}
          onChange={(v) => onPatch({ margin_mode: v })}
        />
      </SettingRow>

      <SettingRow
        title="Daily loss limit"
        description="Halts new opens/adds once today's PnL drops this far. Off disables the limit."
        htmlFor="daily_loss_limit_toggle"
      >
        <div className="flex items-center justify-end gap-3">
          <Switch
            id="daily_loss_limit_toggle"
            checked={lossLimitEnabled}
            onChange={(on) => {
              const v = on ? Math.max(lossLimit, 50) : 0;
              setLossLimit(v);
              onPatch({ daily_loss_limit_usd: dailyLossLimitToStored(v) });
            }}
            label="Daily loss limit enabled"
          />
          {lossLimitEnabled ? (
            <Input
              type="number"
              min={0}
              step={10}
              className="w-28"
              aria-label="Daily loss limit in dollars"
              value={lossLimit}
              onChange={(e) => {
                const v = Number(e.target.value);
                setLossLimit(v);
                debouncedPatch({ daily_loss_limit_usd: dailyLossLimitToStored(v) });
              }}
            />
          ) : null}
        </div>
      </SettingRow>

      <SettingRow title="Max open copies" description="Caps how many positions can be open across all leaders at once." htmlFor="max_open_copies">
        <Input
          id="max_open_copies"
          type="number"
          min={1}
          max={50}
          value={maxOpenCopies}
          onChange={(e) => {
            const v = Number(e.target.value);
            setMaxOpenCopies(v);
            debouncedPatch({ max_open_copies: v });
          }}
        />
      </SettingRow>

      <EnableConfirmDialog
        open={confirmOpen}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          onPatch({ enabled: true });
          setConfirmOpen(false);
        }}
      />
    </Panel>
  );
}
