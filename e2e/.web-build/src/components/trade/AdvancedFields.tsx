"use client";

import { clsx } from "clsx";
import { ChevronRight } from "lucide-react";
import { Slider } from "@/components/ui/Slider";
import { Switch } from "@/components/ui/Switch";
import { worseEntryVibe } from "@/lib/copyRecipe";
import type { ApiCaps, Effective, InheritableField, TicketDraft } from "@/lib/trade/draft";
import type { SmallAccountMode } from "@/lib/trade/types";
import { Inherit } from "./Inherit";

export const SMALL_MODE_META: Record<SmallAccountMode, { label: string; hint: string }> = {
  concentrate: { label: "Concentrate (copy their biggest bets)", hint: "Slices under $10 are dropped and their dollars go to his larger positions." },
  bump: { label: "Round up to $10 minimum", hint: "Small slices open at $10.50 while your budget has room, so you hold more than your share." },
  skip: { label: "Skip small positions", hint: "Slices under $10 are not copied; that part of your budget stays unused." },
};

/** Custom-wallet advanced terms. Each one either overrides the Settings tab or inherits it. */
export function AdvancedFields({
  draft,
  eff,
  caps,
  onChange,
  onReset,
}: {
  draft: TicketDraft;
  eff: Effective;
  caps: ApiCaps;
  onChange: (patch: Partial<TicketDraft>) => void;
  onReset: (field: InheritableField) => void;
}) {
  const overrides = [draft.smallMode, draft.maxWorseEntryPct, draft.onlyNew].filter((v) => v !== null).length;
  return (
    <details className="group rounded-lg border border-border">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-3 py-2 text-sm font-medium [&::-webkit-details-marker]:hidden">
        <ChevronRight size={14} className="transition-transform group-open:rotate-90" aria-hidden="true" />
        Advanced
        <span className="ml-auto text-xs font-normal text-muted">{overrides ? `${overrides} custom` : "all from Settings"}</span>
      </summary>
      <div className="flex flex-col gap-4 border-t border-border px-3 py-3">
        <fieldset className="flex flex-col gap-1.5">
          <legend className="mb-1 flex w-full items-center justify-between text-sm font-medium">
            Positions under the $10 minimum
            <Inherit set={draft.smallMode !== null} onReset={() => onReset("smallMode")} label="small positions" />
          </legend>
          {(Object.keys(SMALL_MODE_META) as SmallAccountMode[]).map((m) => (
            <label
              key={m}
              className={clsx(
                "flex cursor-pointer gap-2 rounded-md border px-2.5 py-2",
                eff.smallMode === m ? "border-accent bg-accent-soft/50" : "border-border hover:bg-surface-2",
                !caps.smallMode && "cursor-not-allowed opacity-50",
              )}
            >
              <input type="radio" name="small-mode" className="mt-0.5 accent-[var(--accent)]" checked={eff.smallMode === m} disabled={!caps.smallMode} onChange={() => onChange({ smallMode: m })} />
              <span className="flex flex-col">
                <span className="text-xs font-medium">{SMALL_MODE_META[m].label}</span>
                <span className="text-[11px] text-muted">{SMALL_MODE_META[m].hint}</span>
              </span>
            </label>
          ))}
          {!caps.smallMode ? <p className="text-[11px] text-warning">Your api predates this setting: small slices are skipped.</p> : null}
        </fieldset>
        <div className="flex flex-col gap-1">
          <span className="flex items-center justify-between">
            <label htmlFor="worse-entry" className="text-sm font-medium">Max worse entry</label>
            <Inherit set={draft.maxWorseEntryPct !== null} onReset={() => onReset("maxWorseEntryPct")} label="max worse entry" />
          </span>
          <Slider id="worse-entry" aria-label="Max worse entry" min={0} max={50} value={eff.maxWorseEntryPct} onChange={(v) => onChange({ maxWorseEntryPct: v })} formatValue={(v) => `${v}%`} vibe={worseEntryVibe} />
          <p className="text-[11px] text-muted">Skip a copy when the price already ran this far past his entry.</p>
        </div>
        <div className="flex items-start justify-between gap-3">
          <label htmlFor="only-new" className="text-sm font-medium">
            <span className="flex items-center gap-2">
              Only copy new positions
              <Inherit set={draft.onlyNew !== null} onReset={() => onReset("onlyNew")} label="only new positions" />
            </span>
            <span className="block text-[11px] font-normal text-muted">Skip what he already holds; copy only what he opens from now on.</span>
          </label>
          <Switch id="only-new" checked={eff.onlyNew} onChange={(v) => onChange({ onlyNew: v })} disabled={!caps.v7} label="Only copy new positions" />
        </div>
        {!caps.v7 ? <p className="text-[11px] text-warning">Your api predates per-wallet only-new: it follows the Settings tab.</p> : null}
        {caps.v9 && draft.oneShot ? (
          <div className="flex items-start justify-between gap-3">
            <label htmlFor="one-shot" className="text-sm font-medium">
              One-shot
              <span className="block text-[11px] font-normal text-muted">Copies only the positions he held when you invested; new ones are never copied. Turn off to follow his new trades too.</span>
            </label>
            <Switch id="one-shot" checked={draft.oneShot} onChange={(v) => onChange({ oneShot: v })} label="One-shot" />
          </div>
        ) : null}
      </div>
    </details>
  );
}
