"use client";

import { useState } from "react";
import type { LeaderOverride, Settings } from "@/lib/api/types";
import { MAX_LEVERAGE_CAP } from "@/lib/api/types";
import { OverrideRow } from "./OverrideRow";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Slider } from "@/components/ui/Slider";
import { Input } from "@/components/ui/Input";
import { formatLeverage, formatPct, formatUsd } from "@/lib/format";
import { useDebouncedCallback } from "@/hooks/useDebouncedCallback";
import { compactOverride, hasActiveOverride, isOverrideSet } from "@/lib/forLeader";

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

export function LeaderOverridePanel({
  settings,
  address,
  onChange,
}: {
  settings: Settings;
  address: string;
  onChange: (override: LeaderOverride | null) => void;
}) {
  // The api returns unset fields as null; compact to only the real overrides.
  const stored = compactOverride(settings.leader_overrides[address]);
  const storedKey = `${address}:${JSON.stringify(stored)}`;
  const [draft, setDraft] = useState<LeaderOverride>(stored);
  const [syncedKey, setSyncedKey] = useState(storedKey);
  // Resync the draft when the saved override changes underneath us (a save
  // landed, another tab edited it). Adjusting state during render, not in an effect.
  if (syncedKey !== storedKey) {
    setSyncedKey(storedKey);
    setDraft(stored);
  }

  const commit = useDebouncedCallback((next: LeaderOverride) => {
    onChange(hasActiveOverride(next) ? compactOverride(next) : null);
  }, 350);

  function update<K extends keyof LeaderOverride>(key: K, value: LeaderOverride[K]) {
    const next = { ...draft, [key]: value };
    setDraft(next);
    commit(next);
  }

  function clearField(key: keyof LeaderOverride) {
    const next = { ...draft };
    delete next[key];
    setDraft(next);
    commit(next);
  }

  return (
    <div className="divide-y divide-border">
      <OverrideRow
        label="Sizing mode"
        id={`${address}-sizing_mode`}
        overridden={isOverrideSet(draft.sizing_mode)}
        onToggle={(on) => (on ? update("sizing_mode", settings.sizing_mode) : clearField("sizing_mode"))}
        inheritedLabel={settings.sizing_mode.replace("_", " ")}
      >
        <SegmentedControl
          aria-label="Sizing mode override"
          options={SIZING_OPTIONS}
          value={draft.sizing_mode ?? settings.sizing_mode}
          onChange={(v) => update("sizing_mode", v)}
        />
      </OverrideRow>

      <OverrideRow
        label="Fixed margin"
        id={`${address}-fixed_margin_usd`}
        overridden={isOverrideSet(draft.fixed_margin_usd)}
        onToggle={(on) => (on ? update("fixed_margin_usd", settings.fixed_margin_usd) : clearField("fixed_margin_usd"))}
        inheritedLabel={formatUsd(settings.fixed_margin_usd)}
      >
        <Input
          leading="$"
          aria-label="Fixed margin override in dollars"
          type="number"
          min={0.01}
          step={0.5}
          value={draft.fixed_margin_usd ?? settings.fixed_margin_usd}
          onChange={(e) => update("fixed_margin_usd", Number(e.target.value))}
        />
      </OverrideRow>

      <OverrideRow
        label="Fixed notional"
        id={`${address}-fixed_notional_usd`}
        overridden={isOverrideSet(draft.fixed_notional_usd)}
        onToggle={(on) =>
          on ? update("fixed_notional_usd", settings.fixed_notional_usd) : clearField("fixed_notional_usd")
        }
        inheritedLabel={formatUsd(settings.fixed_notional_usd)}
      >
        <Input
          leading="$"
          aria-label="Fixed notional override in dollars"
          type="number"
          min={10.5}
          step={1}
          value={draft.fixed_notional_usd ?? settings.fixed_notional_usd}
          onChange={(e) => update("fixed_notional_usd", Number(e.target.value))}
        />
      </OverrideRow>

      <OverrideRow
        label="Size multiplier"
        id={`${address}-size_multiplier`}
        overridden={isOverrideSet(draft.size_multiplier)}
        onToggle={(on) => (on ? update("size_multiplier", settings.size_multiplier) : clearField("size_multiplier"))}
        inheritedLabel={`${settings.size_multiplier}x`}
      >
        <Input
          trailing="x"
          aria-label="Size multiplier override"
          type="number"
          min={0}
          max={100}
          step={0.1}
          value={draft.size_multiplier ?? settings.size_multiplier}
          onChange={(e) => update("size_multiplier", Number(e.target.value))}
        />
      </OverrideRow>

      <OverrideRow
        label="Leverage mode"
        id={`${address}-leverage_mode`}
        overridden={isOverrideSet(draft.leverage_mode)}
        onToggle={(on) => (on ? update("leverage_mode", settings.leverage_mode) : clearField("leverage_mode"))}
        inheritedLabel={settings.leverage_mode}
      >
        <SegmentedControl
          aria-label="Leverage mode override"
          options={LEVERAGE_MODE_OPTIONS}
          value={draft.leverage_mode ?? settings.leverage_mode}
          onChange={(v) => update("leverage_mode", v)}
        />
      </OverrideRow>

      <OverrideRow
        label="Leverage"
        id={`${address}-leverage`}
        overridden={isOverrideSet(draft.leverage)}
        onToggle={(on) => (on ? update("leverage", settings.leverage) : clearField("leverage"))}
        inheritedLabel={formatLeverage(settings.leverage)}
      >
        <Slider
          aria-label="Leverage override"
          min={1}
          max={MAX_LEVERAGE_CAP}
          value={draft.leverage ?? settings.leverage}
          onChange={(v) => update("leverage", v)}
          formatValue={(v) => `${v} x`}
        />
      </OverrideRow>

      <OverrideRow
        label="Margin mode"
        id={`${address}-margin_mode`}
        overridden={isOverrideSet(draft.margin_mode)}
        onToggle={(on) => (on ? update("margin_mode", settings.margin_mode) : clearField("margin_mode"))}
        inheritedLabel={settings.margin_mode}
      >
        <SegmentedControl
          aria-label="Margin mode override"
          options={MARGIN_MODE_OPTIONS}
          value={draft.margin_mode ?? settings.margin_mode}
          onChange={(v) => update("margin_mode", v)}
        />
      </OverrideRow>

      <OverrideRow
        label="Max worse entry"
        id={`${address}-max_worse_entry_pct`}
        overridden={isOverrideSet(draft.max_worse_entry_pct)}
        onToggle={(on) =>
          on ? update("max_worse_entry_pct", settings.max_worse_entry_pct) : clearField("max_worse_entry_pct")
        }
        inheritedLabel={formatPct(settings.max_worse_entry_pct)}
      >
        <Slider
          aria-label="Max worse entry override"
          min={0}
          max={100}
          value={draft.max_worse_entry_pct ?? settings.max_worse_entry_pct}
          onChange={(v) => update("max_worse_entry_pct", v)}
          formatValue={(v) => `${v} %`}
        />
      </OverrideRow>
    </div>
  );
}
