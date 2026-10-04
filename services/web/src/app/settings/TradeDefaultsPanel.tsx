"use client";

import { KeyRound } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/Button";
import { Panel, PanelHeader, SettingRow } from "@/components/ui/Panel";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Slider } from "@/components/ui/Slider";
import { useSyncedState } from "@/hooks/useSyncedState";
import { useDebouncedCallback } from "@/hooks/useDebouncedCallback";
import { getApiBase } from "@/lib/api/client";
import type { Settings, SettingsPatch } from "@/lib/api/types";
import { leverageVibe } from "@/lib/copyRecipe";
import type { ExposureMode, SmallAccountMode, TradeSettings } from "@/lib/trade/types";
import { SMALL_MODE_META } from "@/components/trade/AdvancedFields";

/** Defaults a new Trade ticket starts from (each wallet can override them in its ticket). */
export function TradeDefaultsPanel({ settings, onPatch }: { settings: Settings; onPatch: (p: SettingsPatch) => void }) {
  const s = settings as unknown as TradeSettings;
  const [lev, setLev] = useSyncedState(s.target_leverage ?? 5);
  const debounced = useDebouncedCallback((p: SettingsPatch) => onPatch(p), 350);
  const patch = (p: Partial<TradeSettings>) => onPatch(p as SettingsPatch);
  const hasV5 = "small_account_mode" in s;
  return (
    <Panel>
      <PanelHeader title="Trade defaults" description="Where a new ticket on the Trade page starts. Each wallet keeps its own terms once copied." />
      <SettingRow title="Leverage" description="Follow each wallet's own leverage, or set yours." htmlFor="def-mode">
        <SegmentedControl<ExposureMode>
          aria-label="Default leverage mode"
          options={[{ value: "match", label: "Follow theirs" }, { value: "target", label: "Set leverage" }]}
          value={s.exposure_mode ?? "match"}
          onChange={(v) => patch({ exposure_mode: v })}
        />
      </SettingRow>
      <SettingRow title="Default leverage" description="Used when a ticket is on Set leverage.">
        <Slider aria-label="Default leverage" min={1} max={50} value={lev} onChange={(v) => { setLev(v); debounced({ target_leverage: v } as SettingsPatch); }} formatValue={(v) => `${v}x`} vibe={leverageVibe} />
      </SettingRow>
      {hasV5 ? (
        <SettingRow title="Positions under $10" description={SMALL_MODE_META[s.small_account_mode ?? "concentrate"].hint}>
          <SegmentedControl<SmallAccountMode>
            aria-label="Small positions"
            options={[{ value: "concentrate", label: "Concentrate" }, { value: "bump", label: "Round up" }, { value: "skip", label: "Skip" }]}
            value={s.small_account_mode ?? "concentrate"}
            onChange={(v) => patch({ small_account_mode: v })}
          />
        </SettingRow>
      ) : null}
    </Panel>
  );
}

/** The api connection, on the page as well as in the drawer. */
export function ApiTokenPanel() {
  const { openDrawer, hasToken } = useAuth();
  return (
    <Panel>
      <PanelHeader title="API connection" description={`Talking to ${getApiBase()}.`} />
      <SettingRow title="Bearer token" description={hasToken ? "Stored in this browser only." : "Not set: nothing can be read or changed."} inline>
        <div className="flex justify-end">
          <Button size="sm" onClick={openDrawer}>
            <KeyRound size={13} aria-hidden="true" /> {hasToken ? "Change token" : "Enter token"}
          </Button>
        </div>
      </SettingRow>
    </Panel>
  );
}
