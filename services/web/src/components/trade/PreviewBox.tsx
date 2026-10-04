"use client";

import { clsx } from "clsx";
import { AlertTriangle, Loader2 } from "lucide-react";
import { CoinBadge } from "@/components/scout/bits";
import { formatUsd } from "@/lib/format";
import type { TicketPreview } from "@/lib/trade/ticket";
import type { ExposureMode, MarginMode } from "@/lib/trade/types";

function money(n: number): string {
  return formatUsd(n, n >= 100_000);
}

export function PreviewBox({
  preview,
  amount,
  mode,
  leverage,
  marginMode,
  pending,
  sourceNote,
  onlyNew,
  onUseFullBook,
}: {
  preview: TicketPreview;
  amount: number;
  mode: ExposureMode;
  leverage: number;
  marginMode: MarginMode;
  pending: boolean;
  sourceNote: string | null;
  onlyNew: boolean;
  onUseFullBook: (usd: number) => void;
}) {
  const p = preview;
  const skipped = p.copies.filter((c) => c.status === "skipped");
  const showFull = skipped.length > 0 && p.fullBookUsd !== null && p.fullBookUsd > amount;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface-2/50 p-3 text-xs" aria-live="polite">
      <div className="flex items-center justify-between">
        <span className="font-medium text-foreground">Preview</span>
        <span className="flex items-center gap-1 text-[11px] text-muted">
          {pending ? <Loader2 size={11} className="animate-spin" aria-hidden="true" /> : null}
          {p.source === "api" ? "engine preview" : "estimate"}
        </span>
      </div>
      <Row label="Target exposure">
        {mode === "target" ? (
          <>{money(p.targetExposureUsd)} <span className="text-muted">({money(amount)} x {leverage}x)</span></>
        ) : (
          <>≈ {money(p.targetExposureUsd)} <span className="text-muted">({money(amount)} x their {p.hisLeverage !== null ? `${p.hisLeverage.toFixed(1)}x` : "leverage"} now)</span></>
        )}
      </Row>
      {onlyNew ? (
        <p className="text-muted">Only new positions is on: nothing he holds now is copied. Sizes below apply to his next trades.</p>
      ) : null}
      {p.total === 0 ? (
        <p className="text-muted">He holds nothing right now. Copies open at this size when he trades.</p>
      ) : (
        <>
          <p className="font-medium text-foreground">You&apos;ll copy {p.copied} of {p.total} position{p.total === 1 ? "" : "s"}</p>
          <ul className="flex max-h-44 flex-col gap-1 overflow-y-auto pr-1">
            {p.copies.map((c) => (
              <li key={`${c.coin}-${c.side}`} className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1">
                  <CoinBadge coin={c.coin} />
                  <span className={clsx("text-[10px] font-semibold uppercase", c.side === "long" ? "text-success" : "text-danger")}>{c.side}</span>
                </span>
                {c.status === "skipped" ? (
                  <span className="truncate text-right text-warning" title={c.reason ?? undefined}>{c.reason ?? "skipped"}</span>
                ) : (
                  <span className="font-num text-right">
                    {money(c.notionalUsd)} <span className="text-muted">{c.leverage}x</span>
                    {c.status === "bumped" ? <span className="ml-1 text-warning" title={c.reason ?? undefined}>↑min</span> : null}
                    {c.cycles > 1 ? <span className="ml-1 text-warning">~{c.cycles} cycles</span> : null}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
      {showFull ? (
        <button type="button" onClick={() => onUseFullBook(Math.ceil(p.fullBookUsd!))} className="text-left text-accent hover:underline">
          Invest {money(Math.ceil(p.fullBookUsd!))} to copy their full book
        </button>
      ) : null}
      {p.liquidityCapped ? (
        <p className="flex items-start gap-1 rounded-md bg-warning/10 px-2 py-1 text-warning">
          <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" aria-hidden="true" />
          Large for this market: fills over ~{p.maxCycles} cycles so you don&apos;t move the price.
        </p>
      ) : null}
      <Row label="Est. margin">{money(p.marginUsd)}</Row>
      <Row label="Liquidation">
        {p.liq.kind === "isolated" ? (
          <>~{p.liq.pct.toFixed(p.liq.pct < 1 ? 2 : 1)}% adverse move <span className="text-muted">at {p.liq.leverage}x</span></>
        ) : p.liq.kind === "cross" ? (
          <>~{p.liq.pct.toFixed(1)}% move against all copies <span className="text-muted">(cross)</span></>
        ) : (
          <span className="text-muted">{marginMode === "cross" ? "depends on your whole account" : "n/a"}</span>
        )}
      </Row>
      {(p.notes ?? []).map((n) => <p key={n} className="text-muted">{n}</p>)}
      {sourceNote ? <p className="text-[11px] text-muted">{sourceNote}</p> : null}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-muted">{label}</span>
      <span className="font-num text-right text-foreground">{children}</span>
    </div>
  );
}
