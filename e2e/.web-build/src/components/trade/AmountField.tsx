"use client";

import { clsx } from "clsx";
import { formatUsd } from "@/lib/format";
import { CHIPS, chipAmount, parseInvest } from "@/lib/trade/form";

function chipText(n: number): string {
  return n >= 1000 ? String(Math.floor(n)) : String(n);
}

/** The big "Invest" input: $10 to $10M, 25/50/75/Max of free margin, compact echo for big numbers. */
export function AmountField({
  value,
  onChange,
  maxUsd,
  freeUsd,
  equityUsd,
  error,
  warn,
}: {
  value: string;
  onChange: (v: string) => void;
  maxUsd: number | null;
  /** Free margin right now (the label); maxUsd also counts this wallet's own margin. */
  freeUsd: number | null | undefined;
  equityUsd: number | null | undefined;
  error: string | null;
  warn: string | null;
}) {
  const amount = parseInvest(value);
  const echo = amount !== null && amount >= 10_000 ? formatUsd(amount, true) : null;
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="invest" className="flex items-baseline justify-between text-xs font-medium text-muted">
        <span className="text-sm text-foreground">Invest</span>
        <span className="font-num">
          Free {formatUsd(freeUsd, (freeUsd ?? 0) >= 100_000)} · Equity {formatUsd(equityUsd, (equityUsd ?? 0) >= 100_000)}
        </span>
      </label>
      <div
        className={clsx(
          "flex items-center gap-2 rounded-xl border bg-surface-2 px-3 py-2 focus-within:outline-2 focus-within:outline-[var(--focus-ring)]",
          error && value ? "border-danger/60" : "border-border",
        )}
      >
        <span className="text-xl text-muted">$</span>
        <input
          id="invest"
          inputMode="decimal"
          autoComplete="off"
          placeholder="0"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby="invest-help"
          aria-invalid={Boolean(error && value)}
          className="font-num min-w-0 flex-1 bg-transparent text-2xl font-semibold tabular-nums outline-none focus-visible:outline-none placeholder:text-muted/60"
        />
        {echo ? <span className="font-num text-sm text-muted">{echo}</span> : null}
        <span className="text-xs font-medium text-muted">USD</span>
      </div>
      <div className="grid grid-cols-4 gap-1.5" role="group" aria-label="Invest a share of your free margin">
        {CHIPS.map((pct) => {
          const v = chipAmount(maxUsd, pct);
          return (
            <button
              key={pct}
              type="button"
              disabled={v === null}
              onClick={() => v !== null && onChange(chipText(v))}
              title={v === null ? "Free margin unknown" : formatUsd(v)}
              className={clsx(
                "rounded-md border border-border py-1 text-xs font-medium transition-colors disabled:opacity-40",
                v !== null && amount !== null && Math.abs(amount - v) < 0.01 ? "border-accent bg-accent-soft text-accent" : "text-muted hover:text-foreground",
              )}
            >
              {pct === 100 ? "Max" : `${pct}%`}
            </button>
          );
        })}
      </div>
      <p id="invest-help" className={clsx("min-h-4 text-xs", error && value ? "text-danger" : warn ? "text-warning" : "text-muted")}>
        {error && value ? error : warn ?? "Your budget for this wallet. Copies use it as margin."}
      </p>
    </div>
  );
}
