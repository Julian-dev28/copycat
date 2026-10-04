"use client";

import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Slider } from "@/components/ui/Slider";
import { leverageVibe } from "@/lib/copyRecipe";
import { MAX_LEVERAGE_CAP } from "@/lib/api/types";
import type { ExposureMode, MarginMode } from "@/lib/trade/types";

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
  onMode,
  onLeverage,
  onMarginMode,
}: {
  mode: ExposureMode;
  leverage: number;
  marginMode: MarginMode;
  hisLeverage: number | null;
  onMode: (m: ExposureMode) => void;
  onLeverage: (l: number) => void;
  onMarginMode: (m: MarginMode) => void;
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
              formatValue={(v) => `${v}x`}
              vibe={leverageVibe}
            />
            <div className="font-num relative mt-0.5 mr-[5.75rem] h-3 text-[10px] text-muted" aria-hidden="true">
              {[1, 10, 25, 50].map((v) => (
                <span key={v} className="absolute -translate-x-1/2" style={{ left: `calc(9px + ${((v - 1) / (MAX_LEVERAGE_CAP - 1)) * 100}% - ${((v - 1) / (MAX_LEVERAGE_CAP - 1)) * 18}px)` }}>
                  {v}x
                </span>
              ))}
            </div>
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
        <span className="text-sm font-medium">Margin</span>
        <SegmentedControl aria-label="Margin mode" options={MARGIN_OPTIONS} value={marginMode} onChange={onMarginMode} />
      </div>
    </div>
  );
}
