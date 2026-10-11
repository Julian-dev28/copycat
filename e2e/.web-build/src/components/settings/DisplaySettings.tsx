"use client";

import { useTheme } from "next-themes";
import { Panel, PanelHeader, SettingRow } from "@/components/ui/Panel";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Pnl } from "@/components/ui/Pnl";
import { useMounted } from "@/components/shell/useDemoQuery";
import { usePnlMode } from "@/hooks/usePnlMode";
import { PNL_MODE_LABELS, PNL_MODES, type PnlMode } from "@/lib/display/pnlMode";

/**
 * Settings > Display (DESIGN.md 6): theme and PnL color mode. Both are per
 * browser (localStorage) and never touch the api, so this panel is safe in
 * demo mode too. The Settings page agent places it; it has no other deps.
 */
export function DisplaySettings({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const mounted = useMounted();
  const [mode, setMode] = usePnlMode();

  return (
    <Panel className={className} id="display">
      <PanelHeader title="Display" description="Saved in this browser only." />
      <SettingRow title="Theme">
        <SegmentedControl
          aria-label="Theme"
          options={[
            { value: "dark", label: "Dark" },
            { value: "light", label: "Light" },
          ]}
          value={mounted && theme === "light" ? "light" : "dark"}
          onChange={(v) => setTheme(v)}
        />
      </SettingRow>
      <SettingRow
        title="Gains and losses"
        description={
          <>
            {PNL_MODE_LABELS[mode].hint}. Preview: <Pnl value={1204.1} arrow /> <Pnl value={-88.2} arrow />
          </>
        }
      >
        <PnlModePicker value={mode} onChange={setMode} />
      </SettingRow>
    </Panel>
  );
}

/** The PnL color mode as a radio group (also usable on its own). */
export function PnlModePicker({ value, onChange }: { value: PnlMode; onChange: (m: PnlMode) => void }) {
  return (
    <SegmentedControl
      aria-label="PnL colors"
      size="sm"
      options={PNL_MODES.map((m) => ({ value: m, label: PNL_MODE_LABELS[m].short }))}
      value={value}
      onChange={onChange}
    />
  );
}
