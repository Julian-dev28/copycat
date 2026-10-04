"use client";

import { clsx } from "clsx";
import { ChevronRight } from "lucide-react";
import { Slider } from "@/components/ui/Slider";
import { Switch } from "@/components/ui/Switch";
import { worseEntryVibe } from "@/lib/copyRecipe";
import type { SmallAccountMode } from "@/lib/trade/types";

export const SMALL_MODE_META: Record<SmallAccountMode, { label: string; hint: string }> = {
  concentrate: { label: "Concentrate (copy their biggest bets)", hint: "Slices under $10 are dropped and their dollars go to his larger positions." },
  bump: { label: "Round up to $10 minimum", hint: "Small slices open at $10.50 while your budget has room, so you hold more than your share." },
  skip: { label: "Skip small positions", hint: "Slices under $10 are not copied; that part of your budget stays unused." },
};

export function AdvancedFields({
  smallMode,
  onSmallMode,
  smallModeSupported,
  worseEntry,
  onWorseEntry,
  onlyNew,
  onOnlyNew,
  onlyNewSaving,
}: {
  smallMode: SmallAccountMode;
  onSmallMode: (m: SmallAccountMode) => void;
  smallModeSupported: boolean;
  worseEntry: number;
  onWorseEntry: (v: number) => void;
  onlyNew: boolean;
  onOnlyNew: (v: boolean) => void;
  onlyNewSaving: boolean;
}) {
  return (
    <details className="group rounded-lg border border-border">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-sm font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRight size={14} className="transition-transform group-open:rotate-90" aria-hidden="true" />
        Advanced
        <span className="ml-auto text-xs font-normal text-muted">{SMALL_MODE_META[smallMode].label.split(" (")[0]} · {worseEntry}% entry</span>
      </summary>
      <div className="flex flex-col gap-4 border-t border-border px-3 py-3">
        <fieldset className="flex flex-col gap-1.5">
          <legend className="mb-1 text-sm font-medium">Positions under the $10 minimum</legend>
          {(Object.keys(SMALL_MODE_META) as SmallAccountMode[]).map((m) => (
            <label
              key={m}
              className={clsx(
                "flex cursor-pointer gap-2 rounded-md border px-2.5 py-2",
                smallMode === m ? "border-accent bg-accent-soft/50" : "border-border hover:bg-surface-2",
                !smallModeSupported && "cursor-not-allowed opacity-50",
              )}
            >
              <input type="radio" name="small-mode" className="mt-0.5 accent-[var(--accent)]" checked={smallMode === m} disabled={!smallModeSupported} onChange={() => onSmallMode(m)} />
              <span className="flex flex-col">
                <span className="text-xs font-medium">{SMALL_MODE_META[m].label}</span>
                <span className="text-[11px] text-muted">{SMALL_MODE_META[m].hint}</span>
              </span>
            </label>
          ))}
          {!smallModeSupported ? <p className="text-[11px] text-warning">Your api predates this setting: small slices are skipped.</p> : null}
        </fieldset>
        <div className="flex flex-col gap-1">
          <label htmlFor="worse-entry" className="text-sm font-medium">Max worse entry</label>
          <Slider id="worse-entry" aria-label="Max worse entry" min={0} max={50} value={worseEntry} onChange={onWorseEntry} formatValue={(v) => `${v}%`} vibe={worseEntryVibe} />
          <p className="text-[11px] text-muted">Skip a copy when the price already ran this far past his entry.</p>
        </div>
        <div className="flex items-start justify-between gap-3">
          <label htmlFor="only-new" className="text-sm font-medium">
            Only new positions
            <span className="block text-[11px] font-normal text-muted">Don&apos;t copy what he already holds, only what he opens next. Applies to every wallet.</span>
          </label>
          <Switch id="only-new" checked={onlyNew} onChange={onOnlyNew} disabled={onlyNewSaving} label="Only new positions" />
        </div>
      </div>
    </details>
  );
}
