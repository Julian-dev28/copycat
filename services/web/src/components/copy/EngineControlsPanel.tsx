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
import { fixedLeverageCap } from "./leverageCap";
import { EnableConfirmDialog } from "./EnableConfirmDialog";
import { useDebouncedCallback } from "@/hooks/useDebouncedCallback";
import { dailyLossLimitToStored, storedToDailyLossMagnitude } from "@/lib/sizing";
import { leverageVibe, minMarginForLeverage, settingsLeverage } from "@/lib/copyRecipe";
import { formatUsd } from "@/lib/format";
import { patchGoesLive, patchStrandsCopies } from "@/lib/settings";
import { Dialog } from "@/components/ui/Dialog";
import { Button } from "@/components/ui/Button";

const SIZING_OPTIONS = [
  { value: "fixed_margin" as const, label: "Fixed margin" },
  { value: "fixed_notional" as const, label: "Fixed notional" },
  { value: "proportional" as const, label: "Proportional" },
];
const LEVERAGE_MODE_OPTIONS = [
  { value: "max" as const, label: "Max" },
  { value: "match" as const, label: "Match trader" },
  { value: "fixed" as const, label: "Fixed" },
];
const MARGIN_MODE_OPTIONS = [
  { value: "isolated" as const, label: "Isolated" },
  { value: "cross" as const, label: "Cross" },
];

export function EngineControlsPanel({
  settings,
  onPatch,
  openRealCopies = 0,
}: {
  settings: Settings;
  onPatch: (patch: SettingsPatch) => void;
  /** Real copies open now (EngineStatus.positions when not dry run): dry run would strand them (L9). */
  openRealCopies?: number;
}) {
  // A patch that would turn on real-money trading waits here for the confirm.
  const [pendingLivePatch, setPendingLivePatch] = useState<SettingsPatch | null>(null);
  // A patch that would turn dry run on over open real copies waits here (L9).
  const [pendingDryPatch, setPendingDryPatch] = useState<SettingsPatch | null>(null);
  const [leverage, setLeverage] = useSyncedState(settings.leverage);
  const [fixedMargin, setFixedMargin] = useSyncedState(settings.fixed_margin_usd);
  const [fixedNotional, setFixedNotional] = useSyncedState(settings.fixed_notional_usd);
  const [sizeMultiplier, setSizeMultiplier] = useSyncedState(settings.size_multiplier);
  const [sleeveFrac, setSleeveFrac] = useSyncedState(Math.round(settings.sleeve_frac * 100));
  const [lossLimit, setLossLimit] = useSyncedState(storedToDailyLossMagnitude(settings.daily_loss_limit_usd));
  const [maxOpenCopies, setMaxOpenCopies] = useSyncedState(settings.max_open_copies);

  const debouncedPatch = useDebouncedCallback((patch: SettingsPatch) => onPatch(patch), 350);
  const lossLimitEnabled = lossLimit > 0;
  const recipeLev = settingsLeverage({ ...settings, leverage }).leverage;
  const leverageCap = fixedLeverageCap({ ...settings, leverage });

  /** Every enabled/dry_run change goes through here, so neither switch can go live unconfirmed. */
  function guardedPatch(patch: SettingsPatch) {
    if (patchGoesLive(settings, patch)) {
      setPendingLivePatch(patch);
      return;
    }
    if (patchStrandsCopies(settings, patch, openRealCopies)) {
      setPendingDryPatch(patch);
      return;
    }
    onPatch(patch);
  }

  return (
    <Panel>
      <PanelHeader title="Engine" description="What the copy engine is allowed to do, and how it sizes new copies." />

      <SettingRow
        title="Trading enabled"
        description="Real money. When on and dry run is off, the engine places live orders on Hyperliquid."
        htmlFor="enabled"
        inline
      >
        <div className="flex justify-end">
          <Switch id="enabled" checked={settings.enabled} onChange={(v) => guardedPatch({ enabled: v })} label="Trading enabled" />
        </div>
      </SettingRow>

      <SettingRow
        title="Dry run"
        description="Engine reads real positions and logs what it would do, but places no orders."
        htmlFor="dry_run"
        inline
      >
        <div className="flex justify-end">
          <Switch
            id="dry_run"
            checked={settings.dry_run}
            onChange={(v) => guardedPatch({ dry_run: v })}
            label="Dry run"
          />
        </div>
      </SettingRow>

      <SettingRow title="Sizing mode" description="How a new copy's size is decided." htmlFor="sizing_mode" valueClassName="sm:w-96">
        <SegmentedControl
          aria-label="Sizing mode"
          options={SIZING_OPTIONS}
          value={settings.sizing_mode}
          onChange={(v) => onPatch({ sizing_mode: v })}
        />
      </SettingRow>

      {settings.sizing_mode === "fixed_margin" ? (
        <SettingRow
          title="Fixed margin"
          description={`Margin posted per new copy. Margin x leverage must reach $10.50 (at ${recipeLev}x: at least ${formatUsd(minMarginForLeverage(recipeLev))}).`}
        >
          <Input
            leading="$"
            aria-label="Fixed margin in dollars"
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
        <SettingRow title="Fixed notional" description="Flat position size per new copy, independent of leverage. Minimum $10.50.">
          <Input
            leading="$"
            aria-label="Fixed notional in dollars"
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
              trailing="x"
              aria-label="Size multiplier"
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
            description="Share of your equity available to split across your copies in proportional mode."
          >
            <Slider
              min={0}
              max={100}
              value={sleeveFrac}
              onChange={(v) => {
                setSleeveFrac(v);
                debouncedPatch({ sleeve_frac: v / 100 });
              }}
              formatValue={(v) => `${v} %`}
            />
          </SettingRow>
        </>
      ) : null}

      <SettingRow title="Leverage mode" description="How the leverage for a new copy is resolved." htmlFor="leverage_mode" valueClassName="sm:w-96">
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
              formatValue={(v) => `${v} x`}
              vibe={leverageVibe}
              aria-label="Fixed leverage"
            />
            {leverageCap?.capped ? (
              <p data-testid="leverage-capped" className="mt-1.5 text-xs font-medium text-warning">
                Capped at {leverageCap.effective}x by Maximum position leverage. New copies open at {leverageCap.effective}x,
                not {leverageCap.set}x. Raise that cap (Copy behavior, below) to use {leverageCap.set}x.
              </p>
            ) : null}
            <LiquidationHint leverage={leverageCap?.effective ?? leverage} marginMode={settings.margin_mode} />
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
        inline
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
              leading="$"
              type="number"
              min={0}
              step={10}
              className="w-32"
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

      <SettingRow title="Max open copies" description="Caps how many positions can be open across all your copies at once." htmlFor="max_open_copies">
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
        open={pendingLivePatch !== null}
        onCancel={() => setPendingLivePatch(null)}
        onConfirm={() => {
          if (pendingLivePatch) onPatch(pendingLivePatch);
          setPendingLivePatch(null);
        }}
      />
      <Dialog
        open={pendingDryPatch !== null}
        onClose={() => setPendingDryPatch(null)}
        title="Turn on dry run with copies open?"
        description={`Dry run places no orders at all, exits included. Your ${openRealCopies === 1 ? "open copy" : `${openRealCopies} open copies`} will stop following the traders' reduces and closes and stay open at their leverage until you turn dry run off or close them. To stop new copies but keep managing exits, turn Trading enabled off instead.`}
        footer={
          <>
            <Button variant="ghost" onClick={() => setPendingDryPatch(null)}>Cancel</Button>
            <Button
              variant="danger-solid"
              onClick={() => {
                if (pendingDryPatch) onPatch(pendingDryPatch);
                setPendingDryPatch(null);
              }}
            >
              Leave copies unmanaged
            </Button>
          </>
        }
      />
    </Panel>
  );
}
