"use client";

import { useMemo, useState } from "react";
import { Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { AddToBookButton } from "@/components/scout/bits";
import { useScoutSimTerms, type ScoutBook } from "@/hooks/useScout";
import { useSyncedState } from "@/hooks/useSyncedState";
import { normAddr } from "@/lib/address";
import { formatPct, formatSignedPct, formatUsd } from "@/lib/format";
import { isBusy, whatIfErrorText } from "@/lib/scout/file/source";
import type { TraderScore, WhatIfResult } from "@/lib/scout/types";
import { useSettings } from "@/hooks/useSettings";
import { buildWhatIfRequest, DEFAULT_WHATIF_EQUITY, draftFromOverride, leverageNote, overrideDiffers, overrideSettingsPatch, SIZING_WORD, type WhatIfField } from "@/lib/scout/whatIf";
import { useFileWhatIf } from "./hooks";
import { WhatIfFields } from "./WhatIfFields";

/** "liquidated:ETH" flags -> "ETH", so "1 liq" says which copy. */
export function liquidatedCoins(flags: readonly string[] | null | undefined): string[] {
  return (flags ?? []).filter((f) => f.startsWith("liquidated:")).map((f) => f.slice("liquidated:".length));
}

function SimLine({ label, s }: { label: string; s: TraderScore }) {
  const liq = liquidatedCoins(s.flags);
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs">
      <span className="w-full text-[11px] text-muted">{label}</span>
      <span className={`font-num font-semibold ${s.sim_return_pct >= 0 ? "text-up" : "text-down"}`}>{formatSignedPct(s.sim_return_pct)}</span>
      <span className="font-num text-muted" title="Largest peak-to-trough dip of the copy's equity">max dip {formatPct(s.sim_max_drawdown_pct)}</span>
      <span className="font-num text-muted" title={liq.length ? `Copies liquidated in the sim: ${liq.join(", ")}` : "No copy got liquidated in the sim"}>
        {s.sim_liquidations} liq{liq.length ? ` (${liq.join(", ")})` : ""} · {formatUsd(s.sim_fees_usd)} fees
      </span>
    </div>
  );
}

export function WhatIfPanel({ address, base, book, onResult }: { address: string; base: TraderScore; book: ScoutBook; onResult: (r: WhatIfResult | null) => void }) {
  const a = normAddr(address);
  const stored = book.overrides[a];
  const terms = useScoutSimTerms().data;
  const seed = useMemo(() => draftFromOverride(stored, DEFAULT_WHATIF_EQUITY, terms), [stored, terms]);
  const [draft, setDraft] = useSyncedState(seed);
  const [errors, setErrors] = useState<Partial<Record<WhatIfField, string>>>({});
  const [saved, setSaved] = useState(false);
  const run = useFileWhatIf(address);
  const globalSizingMode = useSettings().data?.sizing_mode;
  const globalSizing = globalSizingMode ? (SIZING_WORD[globalSizingMode] ?? globalSizingMode) : undefined;
  const note = leverageNote(draft.sizing_mode, globalSizingMode);

  const built = buildWhatIfRequest(draft);
  const canSave = built.ok && overrideDiffers(built.body.override, stored);

  function set(field: WhatIfField, value: string) {
    setDraft({ ...draft, [field]: value });
    setErrors({ ...errors, [field]: undefined });
    setSaved(false);
  }

  function submit() {
    if (!built.ok) return setErrors(built.errors);
    run.mutate(built.body, { onSuccess: (r) => onResult(r) });
  }

  async function save() {
    if (!built.ok) return setErrors(built.errors);
    try {
      await book.saveOverride(overrideSettingsPatch(a, built.body.override));
      setSaved(true);
    } catch {
      // book.saveError renders the message
    }
  }

  return (
    <Panel>
      <PanelHeader title="What you would have made" description="Re-run the 30d copy sim with these terms; it starts from the board's sim terms, so change one thing and compare. Return is on the equity you enter. Nothing is saved unless you press save." />
      <form
        className="flex flex-col gap-3 px-4 pb-4"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <SimLine label={terms ? `Scout board sim (${formatUsd(terms.allocation_usd)} at ${terms.exposure_mode === "target" ? `${terms.target_leverage}x` : "their leverage"} from a ${formatUsd(terms.sim_equity_usd)} account)` : "Scout board sim (the board's sim terms)"} s={base} />
        {run.data ? <SimLine label="This what-if" s={run.data.score} /> : null}
        <WhatIfFields draft={draft} set={set} errors={errors} globalSizing={globalSizing} />
        {note ? <p className="text-xs text-muted">{note}</p> : null}
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" variant="primary" size="sm" disabled={run.isPending}>
            {run.isPending ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Play size={13} aria-hidden="true" />}
            {run.isPending ? "Simulating…" : "Run what-if"}
          </Button>
          {run.data ? (
            <Button type="button" size="sm" variant="ghost" onClick={() => { run.reset(); onResult(null); }}>
              Reset chart
            </Button>
          ) : null}
        </div>
        {run.isError ? (
          <p role="alert" className={`text-xs ${isBusy(run.error) ? "text-warning" : "text-danger"}`}>
            {whatIfErrorText(run.error)}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
          <Button type="button" size="sm" onClick={save} disabled={!canSave || book.savingOverride || !book.ready}>
            {book.savingOverride ? "Saving…" : "Save as this trader's override"}
          </Button>
          <AddToBookButton address={a} book={book} inBook={book.inBook(a)} />
          {saved ? <span className="text-xs text-success">Override saved.</span> : null}
          {book.saveError ? <span className="text-xs text-danger">{book.saveError.message}</span> : null}
        </div>
        <p className="text-[11px] text-muted">Equity is only for the sim; an override stores sizing, leverage, margin and entry limits for this trader.</p>
      </form>
    </Panel>
  );
}
