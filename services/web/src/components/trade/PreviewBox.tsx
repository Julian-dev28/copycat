"use client";

import { clsx } from "clsx";
import { AlertTriangle, ArrowDownUp, Loader2 } from "lucide-react";
import { CoinBadge } from "@/components/scout/bits";
import { Badge } from "@/components/ui";
import { formatUsd } from "@/lib/format";
import type { TicketPreview } from "@/lib/trade/ticket";
import { fullBookShortfall, leverageMismatch, leverageMismatchText, liqTone, skipReasonShort, type SizeStarved } from "@/lib/trade/ticketView";
import type { ExposureMode, MarginMode } from "@/lib/trade/types";
import { SideTag } from "./bits";

function money(n: number): string {
  return formatUsd(n, n >= 100_000);
}

const LIQ_CLASS = { danger: "text-danger", warn: "text-warn", muted: "text-fg" } as const;

/**
 * What the ticket would copy (DESIGN 5 Ticket: a quiet surface-2 well).
 * The engine preview renders plainly; a browser estimate is muted and
 * tagged "estimate" until the engine answers. Warnings are warn text with
 * an icon; numbers never take the accent or the PnL colors.
 */
export function PreviewBox({
  preview,
  amount,
  mode,
  leverage,
  marginMode,
  pending,
  sourceNote,
  onlyNew,
  equityUsd,
  onUseFullBook,
  starved = null,
  onStarvedFix = null,
}: {
  preview: TicketPreview;
  /** Null for "Use global": the sizing comes from the Settings tab. */
  amount: number | null;
  mode: ExposureMode;
  leverage: number;
  marginMode: MarginMode;
  pending: boolean;
  sourceNote: string | null;
  onlyNew: boolean;
  /** Your account equity, for "needs $X; you have $Y". */
  equityUsd: number | null | undefined;
  onUseFullBook: ((usd: number) => void) | null;
  /** Every position skipped for size (ticketView.sizeStarved): the cause and the terms that work. */
  starved?: SizeStarved | null;
  onStarvedFix?: ((fix: NonNullable<SizeStarved["fix"]>) => void) | null;
}) {
  const p = preview;
  const estimate = p.source === "local";
  const skipped = p.copies.filter((c) => c.status === "skipped");
  const filtered = p.copies.filter((c) => c.filtered).length;
  const wantsFull = onUseFullBook !== null && amount !== null && skipped.length > 0 && p.fullBookUsd !== null && p.fullBookUsd > amount;
  const shortfall = wantsFull ? fullBookShortfall(p.fullBookUsd, equityUsd) : null;
  const tone = liqTone(p.liq);
  const mismatch = leverageMismatch(p.liq, p.hisLeverage, mode);
  return (
    <section
      aria-label="Preview"
      aria-busy={pending || undefined}
      className={clsx("flex flex-col gap-2 rounded-lg bg-surface-2 p-3 text-xs transition-colors duration-[var(--dur-base)]", estimate && "text-muted")}
      aria-live="polite"
    >
      <div className="flex items-center justify-between">
        <span className="text-label text-muted">Preview</span>
        <span className="flex items-center gap-1.5">
          {pending ? <Loader2 size={11} className="animate-spin text-muted" aria-hidden="true" /> : null}
          {estimate ? (
            <Badge tone="neutral" title="A browser estimate; the engine preview replaces it when it lands">
              estimate
            </Badge>
          ) : (
            <Badge tone="neutral">engine preview</Badge>
          )}
        </span>
      </div>
      <Row label="Target exposure" estimate={estimate}>
        {amount === null ? (
          <>
            {p.targetExposureUsd ? `≈ ${money(p.targetExposureUsd)}` : "per your Settings"} <span className="text-muted">(global sizing)</span>
          </>
        ) : mode === "target" ? (
          <>
            {money(p.targetExposureUsd)}{" "}
            <span className="text-muted">
              ({money(amount)} x {leverage}x)
            </span>
          </>
        ) : (
          <>
            ≈ {money(p.targetExposureUsd)}{" "}
            <span className="text-muted">
              ({money(amount)} x their {p.hisLeverage !== null ? `${p.hisLeverage.toFixed(1)}x` : "leverage"} now)
            </span>
          </>
        )}
      </Row>
      {onlyNew ? <p className="text-muted">Copying new trades only: their current positions are skipped. Sizes below apply to their next trades.</p> : null}
      {p.direction === "counter" ? (
        <p className="flex items-start gap-1.5 text-fg-soft">
          <ArrowDownUp size={12} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          Counter: you take the opposite side of each of their positions. Sides below are yours.
        </p>
      ) : null}
      {filtered > 0 ? (
        <p className="text-muted">
          {filtered} of their position{filtered === 1 ? "" : "s"} filtered out by your coin lists.
        </p>
      ) : null}
      {p.total === 0 ? (
        <p className="text-muted">They hold nothing right now. Copies open at this size when they trade.</p>
      ) : (
        <>
          <p className={clsx("font-medium", estimate ? "text-muted" : "text-fg")}>
            You&apos;d copy {p.copied} of {p.total} position{p.total === 1 ? "" : "s"}
          </p>
          <ul className="flex max-h-44 flex-col gap-1 overflow-y-auto pr-1">
            {p.copies.map((c) => (
              <li key={`${c.coin}-${c.side}`} className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1">
                  <CoinBadge coin={c.coin} />
                  <SideTag side={c.ourSide ?? c.side} />
                  {c.ourSide && c.ourSide !== c.side ? <span className="text-[10px] text-muted">(they&apos;re {c.side})</span> : null}
                </span>
                {c.status === "skipped" ? (
                  <span className={clsx("flex items-center gap-1 truncate text-right", c.filtered ? "text-muted" : "text-warn")} title={c.reason ?? undefined}>
                    {c.filtered ? null : <AlertTriangle size={11} className="flex-shrink-0" aria-hidden="true" />}
                    {c.filtered ? "filtered" : skipReasonShort(c.reason)}
                  </span>
                ) : (
                  <span className={clsx("num text-right", estimate ? "text-muted" : "text-fg")}>
                    {money(c.notionalUsd)} <span className="text-muted">{c.leverage}x</span>
                    {c.status === "bumped" ? (
                      <span className="ml-1 text-warn" title={c.reason ?? undefined}>
                        ↑min
                      </span>
                    ) : null}
                    {c.cycles > 1 ? <span className="ml-1 text-warn">~{c.cycles} cycles</span> : null}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {starved ? (
        <p role="note" className="flex flex-col gap-1 text-warn" data-testid="ticket-size-starved">
          <span className="flex items-start gap-1.5">
            <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
            <span>{starved.text}</span>
          </span>
          {starved.fix && onStarvedFix ? (
            <button type="button" onClick={() => onStarvedFix(starved.fix!)} className="self-start font-medium text-accent hover:underline">
              {starved.fix.label}
            </button>
          ) : null}
        </p>
      ) : null}
      {shortfall ? (
        <p role="note" className="flex items-start gap-1.5 text-warn" data-testid="ticket-full-shortfall">
          <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span>
            Copying all their positions needs <span className="num">{money(shortfall.needUsd)}</span>; you have{" "}
            <span className="num">{money(shortfall.haveUsd)}</span>.
          </span>
        </p>
      ) : wantsFull ? (
        <button type="button" onClick={() => onUseFullBook?.(Math.ceil(p.fullBookUsd!))} className="text-left font-medium text-accent hover:underline">
          Invest {money(Math.ceil(p.fullBookUsd!))} to copy all their positions
        </button>
      ) : null}
      {p.liquidityCapped ? (
        <p className="flex items-start gap-1.5 text-warn">
          <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          Large for this market: fills over ~{p.maxCycles} cycles so you don&apos;t move the price.
        </p>
      ) : null}
      <div className="mt-1 flex flex-col gap-1 border-t border-border pt-2">
        <Row label="Est. margin" estimate={estimate}>
          {money(p.marginUsd)}
        </Row>
        <Row label="Liquidation" estimate={estimate}>
          {p.liq.kind === "isolated" ? (
            <span className={clsx("inline-flex items-center gap-1", LIQ_CLASS[tone])}>
              {tone !== "muted" ? <AlertTriangle size={11} aria-hidden="true" /> : null}~{p.liq.pct.toFixed(p.liq.pct < 1 ? 2 : 1)}% adverse move{" "}
              <span className="text-muted">at {p.liq.leverage}x</span>
            </span>
          ) : p.liq.kind === "cross" ? (
            <span className={clsx("inline-flex items-center gap-1", LIQ_CLASS[tone])}>
              {tone !== "muted" ? <AlertTriangle size={11} aria-hidden="true" /> : null}~{p.liq.pct.toFixed(1)}% move against all copies{" "}
              <span className="text-muted">(cross)</span>
            </span>
          ) : (
            <span className="text-muted">{marginMode === "cross" ? "depends on your whole account" : "n/a"}</span>
          )}
        </Row>
      </div>
      {mismatch ? (
        <p
          data-testid="ticket-leverage-mismatch"
          className={clsx("flex items-start gap-1.5", mismatch.severe ? "text-danger" : "text-warn")}
        >
          <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span>Tighter than theirs: {leverageMismatchText(mismatch)}</span>
        </p>
      ) : null}
      {(p.notes ?? []).map((n) => (
        <p key={n} className="text-muted">
          {n}
        </p>
      ))}
      {sourceNote ? <p className="text-[11px] text-muted">{sourceNote}</p> : null}
    </section>
  );
}

function Row({ label, estimate, children }: { label: string; estimate: boolean; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-muted">{label}</span>
      <span className={clsx("num text-right", estimate ? "text-muted" : "text-fg")}>{children}</span>
    </div>
  );
}
