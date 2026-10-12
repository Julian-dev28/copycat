"use client";

import { clsx } from "clsx";
import { formatUsd } from "@/lib/format";
import { CHIPS, chipAmount, parseInvest } from "@/lib/trade/form";
import type { AllocationBreakdown } from "@/lib/trade/ticketView";

function chipText(n: number): string {
  return n >= 1000 ? String(Math.floor(n)) : String(n);
}

function money(n: number): string {
  return formatUsd(n, n >= 100_000);
}

/**
 * The big "Invest" input: $10 to $10M, 25/50/75/Max of free margin, compact
 * echo for big numbers, and where the money goes (UX audit #10): margin used
 * now, exposure, and what stays reserved for their next trades. One focus
 * ring, on the wrapper.
 */
export function AmountField({
  value,
  onChange,
  maxUsd,
  freeUsd,
  equityUsd,
  error,
  warn,
  breakdown,
  estimate,
}: {
  value: string;
  onChange: (v: string) => void;
  maxUsd: number | null;
  /** Free margin right now (the label); maxUsd also counts this trader's own margin. */
  freeUsd: number | null | undefined;
  equityUsd: number | null | undefined;
  error: string | null;
  warn: string | null;
  breakdown: AllocationBreakdown | null;
  /** The breakdown comes from the browser estimate, not the engine. */
  estimate: boolean;
}) {
  const amount = parseInvest(value);
  const echo = amount !== null && amount >= 10_000 ? formatUsd(amount, true) : null;
  const showError = Boolean(error && value);
  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="invest" className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-fg">Invest</span>
        <span className="num-sm text-muted">
          Free {formatUsd(freeUsd, (freeUsd ?? 0) >= 100_000)} · Equity {formatUsd(equityUsd, (equityUsd ?? 0) >= 100_000)}
        </span>
      </label>
      <div
        className={clsx(
          "flex h-14 items-center gap-2 rounded-lg border bg-surface-2 px-3 transition-[border-color,box-shadow] duration-[var(--dur-fast)]",
          "focus-within:border-accent focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--accent)_22%,transparent)]",
          showError ? "border-danger/60" : "border-border hover:border-border-strong",
        )}
      >
        <span className="num-lg text-muted" aria-hidden="true">
          $
        </span>
        <input
          id="invest"
          inputMode="decimal"
          autoComplete="off"
          placeholder="0"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-describedby="invest-help invest-breakdown"
          aria-invalid={showError}
          className="num-xl min-w-0 flex-1 bg-transparent text-fg outline-none placeholder:text-faint focus:outline-none focus-visible:outline-none"
        />
        {echo ? <span className="num-sm text-muted">{echo}</span> : null}
        <span className="text-label text-muted">USD</span>
      </div>
      <div className="grid grid-cols-4 gap-1.5" role="group" aria-label="Invest a share of your free margin">
        {CHIPS.map((pct) => {
          const v = chipAmount(maxUsd, pct);
          const on = v !== null && amount !== null && Math.abs(amount - v) < 0.01;
          return (
            <button
              key={pct}
              type="button"
              disabled={v === null}
              aria-pressed={on}
              onClick={() => v !== null && onChange(chipText(v))}
              title={v === null ? "Free margin unknown" : formatUsd(v)}
              className={clsx(
                "h-7 rounded-full border text-xs font-medium transition-colors duration-[var(--dur-fast)] active:scale-[.98] disabled:opacity-40",
                on ? "border-border-strong bg-surface-3 text-fg" : "border-border text-muted hover:border-border-strong hover:text-fg",
              )}
            >
              {pct === 100 ? "Max" : `${pct}%`}
            </button>
          );
        })}
      </div>
      <p id="invest-help" className={clsx("min-h-4 text-xs", showError ? "text-danger" : warn ? "text-warn" : "text-muted")}>
        {showError ? error : warn ?? "Your budget for this trader. Copies use part of it as margin; the rest waits for their next trades."}
      </p>
      <dl
        id="invest-breakdown"
        aria-label="Where this amount goes"
        data-testid="ticket-allocation-breakdown"
        className={clsx(
          "grid grid-cols-3 gap-2 overflow-hidden rounded-lg border border-border transition-[opacity,max-height] duration-[var(--dur-base)] ease-[var(--ease-out)]",
          breakdown ? "max-h-24 p-2.5 opacity-100" : "max-h-0 border-transparent p-0 opacity-0",
        )}
      >
        {breakdown ? (
          <>
            <Part label="Margin used now" value={money(breakdown.marginNowUsd)} estimate={estimate} />
            <Part label="Exposure" value={money(breakdown.exposureUsd)} estimate={estimate} />
            <Part label="Reserved for their next trades" value={money(breakdown.reservedUsd)} estimate={estimate} />
          </>
        ) : null}
      </dl>
    </div>
  );
}

function Part({ label, value, estimate }: { label: string; value: string; estimate: boolean }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5">
      <dt className="text-[11px] leading-tight text-muted">{label}</dt>
      <dd className={clsx("num", estimate ? "text-muted" : "text-fg")}>{value}</dd>
    </div>
  );
}
