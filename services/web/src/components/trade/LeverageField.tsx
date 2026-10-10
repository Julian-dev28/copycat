"use client";

import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Slider } from "@/components/ui/Slider";
import { leverageVibe } from "@/lib/copyRecipe";
import { MAX_LEVERAGE_CAP } from "@/lib/api/types";
import { formatLiquidationHint } from "@/lib/liquidation";
import type { TargetLeverageCap } from "@/lib/trade/form";
import type { ExposureMode, MarginMode } from "@/lib/trade/types";
import { Inherit } from "./Inherit";

const MODE_OPTIONS = [
  { value: "match" as const, label: "Follow their leverage" },
  { value: "target" as const, label: "Set leverage" },
];
const MARGIN_OPTIONS = [
  { value: "isolated" as const, label: "Isolated" },
  { value: "cross" as const, label: "Cross" },
];

export function LeverageField({
  mode,
  leverage,
  marginMode,
  hisLeverage,
  marginSet,
  cap,
  onMode,
  onLeverage,
  onMarginMode,
  onMarginReset,
}: {
  mode: ExposureMode;
  leverage: number;
  marginMode: MarginMode;
  hisLeverage: number | null;
  /** True when this wallet overrides the Settings tab's margin mode. */
  marginSet: boolean;
  /** Set leverage after the Settings tab's Maximum position leverage. */
  cap: TargetLeverageCap;
  onMode: (m: ExposureMode) => void;
  onLeverage: (l: number) => void;
  onMarginMode: (m: MarginMode) => void;
  onMarginReset: () => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">Leverage</span>
        <SegmentedControl aria-label="Leverage" options={MODE_OPTIONS} value={mode} onChange={onMode} />
        {mode === "target" ? (
          <div className="pt-1">
            <Slider
              aria-label="Your leverage"
              min={1}
              max={MAX_LEVERAGE_CAP}
              value={leverage}
              onChange={onLeverage}
              formatValue={(v) => (cap.capped && v === leverage ? `${cap.effective}x` : `${v}x`)}
              vibe={(v) => leverageVibe(Math.min(v, cap.cap))}
            />
            <div className="font-num relative mt-0.5 mr-[5.75rem] h-3 text-[10px] text-muted" aria-hidden="true">
              {[1, 10, 25, 50].map((v) => (
                <span key={v} className="absolute -translate-x-1/2" style={{ left: `calc(9px + ${((v - 1) / (MAX_LEVERAGE_CAP - 1)) * 100}% - ${((v - 1) / (MAX_LEVERAGE_CAP - 1)) * 18}px)` }}>
                  {v}x
                </span>
              ))}
            </div>
            {cap.capped ? (
              <p data-testid="ticket-leverage-capped" className="mt-1 text-xs font-medium text-warning">
                Capped at {cap.cap}x by Maximum position leverage (Settings): you set {cap.set}x, copies open at {cap.effective}x.
              </p>
            ) : null}
            <p className="font-num mt-1 text-xs text-muted">{formatLiquidationHint(cap.effective, marginMode)}</p>
            <p className="mt-1 text-xs text-muted">His book in his proportions, at your leverage. A coin with a lower max opens at its max.</p>
          </div>
        ) : (
          <p className="text-xs text-muted">
            Each copy opens at his leverage on that coin
            {hisLeverage !== null ? <> (his whole book runs at <span className="font-num text-foreground">{hisLeverage.toFixed(1)}x</span> now)</> : null}.
          </p>
        )}
      </div>
      <div className="flex flex-col gap-1.5">
        <span className="flex items-center justify-between text-sm font-medium">
          Margin
          <Inherit set={marginSet} onReset={onMarginReset} label="margin mode" />
        </span>
        <SegmentedControl aria-label="Margin mode" options={MARGIN_OPTIONS} value={marginMode} onChange={onMarginMode} />
      </div>
    </div>
  );
}
