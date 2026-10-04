import type { ReactNode } from "react";
import type { WhatIfDraft, WhatIfField } from "@/lib/scout/whatIf";

const INPUT = "w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm font-num focus:outline-none focus:ring-2 focus:ring-accent/40";

function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={id} className="text-[11px] text-muted">
        {label}
      </label>
      {children}
      {error ? (
        <span id={`${id}-err`} className="text-[11px] text-danger">
          {error}
        </span>
      ) : null}
    </div>
  );
}

type SetField = (field: WhatIfField, value: string) => void;
type Errors = Partial<Record<WhatIfField, string>>;

function Num({ f, label, draft, set, errors, placeholder }: { f: WhatIfField; label: string; draft: WhatIfDraft; set: SetField; errors: Errors; placeholder?: string }) {
  const id = `wi-${f}`;
  return (
    <Field id={id} label={label} error={errors[f]}>
      <input
        id={id}
        inputMode="decimal"
        className={INPUT}
        value={draft[f]}
        placeholder={placeholder ?? "book default"}
        aria-invalid={Boolean(errors[f])}
        aria-describedby={errors[f] ? `${id}-err` : undefined}
        onChange={(e) => set(f, e.target.value)}
      />
    </Field>
  );
}

function Pick({ f, label, options, draft, set }: { f: WhatIfField; label: string; options: [string, string][]; draft: WhatIfDraft; set: SetField }) {
  const id = `wi-${f}`;
  return (
    <Field id={id} label={label}>
      <select id={id} className={INPUT} value={draft[f]} onChange={(e) => set(f, e.target.value)}>
        <option value="">Book default</option>
        {options.map(([v, l]) => (
          <option key={v} value={v}>
            {l}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function WhatIfFields({ draft, set, errors }: { draft: WhatIfDraft; set: SetField; errors: Errors }) {
  const mode = draft.sizing_mode;
  return (
    <div className="grid grid-cols-2 gap-3">
      <Num f="equity" label="Your equity (USD)" draft={draft} set={set} errors={errors} placeholder="1000" />
      <Pick f="sizing_mode" label="Sizing" draft={draft} set={set} options={[["proportional", "Proportional"], ["fixed_margin", "Fixed margin"], ["fixed_notional", "Fixed notional"]]} />
      {mode === "proportional" || mode === "" ? <Num f="size_multiplier" label="Multiplier" draft={draft} set={set} errors={errors} /> : null}
      {mode === "fixed_margin" ? <Num f="fixed_margin_usd" label="Margin per trade (USD)" draft={draft} set={set} errors={errors} /> : null}
      {mode === "fixed_notional" ? <Num f="fixed_notional_usd" label="Notional per trade (USD)" draft={draft} set={set} errors={errors} /> : null}
      <Pick f="leverage_mode" label="Leverage" draft={draft} set={set} options={[["match", "Match his"], ["max", "Coin max"], ["fixed", "Fixed"]]} />
      {draft.leverage_mode === "fixed" ? <Num f="leverage" label="Leverage (x)" draft={draft} set={set} errors={errors} /> : null}
      <Pick f="margin_mode" label="Margin" draft={draft} set={set} options={[["cross", "Cross"], ["isolated", "Isolated"]]} />
      <Num f="max_worse_entry_pct" label="Max worse entry %" draft={draft} set={set} errors={errors} />
    </div>
  );
}
