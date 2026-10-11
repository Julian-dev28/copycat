"use client";

import { useMemo, useState } from "react";
import { Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { AddToBookButton } from "@/components/scout/bits";
import type { ScoutBook } from "@/hooks/useScout";
import { useSyncedState } from "@/hooks/useSyncedState";
import { normAddr } from "@/lib/address";
import { formatPct, formatSignedPct, formatUsd } from "@/lib/format";
import { isBusy, whatIfErrorText } from "@/lib/scout/file/source";
import type { TraderScore, WhatIfResult } from "@/lib/scout/types";
import { buildWhatIfRequest, DEFAULT_WHATIF_EQUITY, draftFromOverride, overrideDiffers, overrideSettingsPatch, type WhatIfField } from "@/lib/scout/whatIf";
import { useFileWhatIf } from "./hooks";
import { WhatIfFields } from "./WhatIfFields";

function SimLine({ label, s }: { label: string; s: TraderScore }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs">
      <span className="w-full text-[11px] text-muted">{label}</span>
      <span className={`font-num font-semibold ${s.sim_return_pct >= 0 ? "text-up" : "text-down"}`}>{formatSignedPct(s.sim_return_pct)}</span>
      <span className="font-num text-muted">DD {formatPct(s.sim_max_drawdown_pct)}</span>
      <span className="font-num text-muted">
        {s.sim_liquidations} liq · {formatUsd(s.sim_fees_usd)} fees
      </span>
    </div>
  );
}

export function WhatIfPanel({ address, base, book, onResult }: { address: string; base: TraderScore; book: ScoutBook; onResult: (r: WhatIfResult | null) => void }) {
  const a = normAddr(address);
  const stored = book.overrides[a];
  const seed = useMemo(() => draftFromOverride(stored, DEFAULT_WHATIF_EQUITY), [stored]);
  const [draft, setDraft] = useSyncedState(seed);
  const [errors, setErrors] = useState<Partial<Record<WhatIfField, string>>>({});
  const [saved, setSaved] = useState(false);
  const run = useFileWhatIf(address);

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
      <PanelHeader title="What you would have made" description="Re-run the 30d copy sim with your own settings. Nothing is saved unless you press save." />
      <form
        className="flex flex-col gap-3 px-4 pb-4"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <SimLine label="Saved settings" s={base} />
        {run.data ? <SimLine label="This what-if" s={run.data.score} /> : null}
        <WhatIfFields draft={draft} set={set} errors={errors} />
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
