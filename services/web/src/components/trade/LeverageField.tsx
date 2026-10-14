"use client";

import Link from "next/link";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { Slider } from "@/components/ui/Slider";
import { leverageVibe } from "@/lib/copyRecipe";
import { MAX_LEVERAGE_CAP } from "@/lib/api/types";
import { formatLiquidationHint } from "@/lib/liquidation";
import type { TargetLeverageCap } from "@/lib/trade/form";
import type { ExposureMode, MarginMode } from "@/lib/trade/types";
import { effectiveLeverageText } from "@/lib/trade/ticketView";
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
  settingsHref,
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
  /** Where the cap message's "Settings" link goes (demo query carried over). */
  settingsHref: string;
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
              <p data-testid="ticket-leverage-capped" className="mt-1 text-xs text-warn">
                <span className="num font-medium">{effectiveLeverageText(cap.set, cap.cap)}</span>: Maximum position leverage in Settings caps it, so copies open at{" "}
                <span className="num">{cap.effective}x</span>.{" "}
                <Link href={`${settingsHref}#max_position_leverage`} className="font-medium text-accent hover:underline">
                  Raise the cap
                </Link>
                .
              </p>
            ) : null}
            <p className="num-sm mt-1 text-muted">{formatLiquidationHint(cap.effective, marginMode)}</p>
            <p className="mt-1 text-xs text-muted">Their positions in their proportions, at your leverage. A coin with a lower max opens at its max.</p>
          </div>
        ) : (
          <p className="text-xs text-muted">
            Each copy opens at their leverage on that coin
            {hisLeverage !== null ? <> (their whole account runs at <span className="num text-fg">{hisLeverage.toFixed(1)}x</span> now)</> : null}.
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
