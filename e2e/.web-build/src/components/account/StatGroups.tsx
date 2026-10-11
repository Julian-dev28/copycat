import { clsx } from "clsx";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { formatPct, formatUsd } from "@/lib/format";
import { analysisStats, directionBias, metricsPending, overviewStats, performanceStats, type Stat } from "@/lib/account/summary";
import type { AccountSummary } from "@/lib/account/types";

const TONE: Record<NonNullable<Stat["tone"]>, string> = { up: "text-success", down: "text-danger", flat: "text-foreground", warn: "text-warning" };

function StatList({ title, description, stats }: { title: string; description?: string; stats: Stat[] }) {
  return (
    <Panel className="flex flex-col">
      <PanelHeader title={title} description={description} />
      <dl className="flex flex-col px-4 pb-3 sm:px-5">
        {stats.map((s) => (
          <div key={s.label} className="flex items-baseline justify-between gap-3 border-t border-border/60 py-2 first:border-t-0" title={s.hint}>
            <dt className="text-xs text-muted">
              {s.label}
              {s.hint ? <span className="block text-[10px] text-muted/80">{s.hint}</span> : null}
            </dt>
            <dd className={clsx("font-num text-sm font-semibold whitespace-nowrap", s.tone ? TONE[s.tone] : "text-foreground")}>{s.value}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

export function DirectionBias({ summary }: { summary: AccountSummary }) {
  const { longPct, label } = directionBias(summary);
  const l = longPct ?? 50;
  return (
    <Panel className="flex flex-col gap-2 p-4 sm:px-5">
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold">Direction bias</h2>
        <span className="text-xs font-medium text-foreground">{label}</span>
      </div>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-surface-2" role="img" aria-label={longPct === null ? "No open positions" : `${formatPct(longPct, 0)} long, ${formatPct(100 - longPct, 0)} short`}>
        {longPct === null ? null : (
          <>
            <span className="h-full bg-success" style={{ width: `${l}%` }} />
            <span className="h-full bg-danger" style={{ width: `${100 - l}%` }} />
          </>
        )}
      </div>
      <div className="flex justify-between font-num text-[11px] text-muted">
        <span>
          <span className="text-success">Long</span> {formatUsd(summary.long_notional_usd, true)} {longPct === null ? "" : `· ${formatPct(longPct, 0)}`}
        </span>
        <span>
          {longPct === null ? "" : `${formatPct(100 - longPct, 0)} · `}
          {formatUsd(summary.short_notional_usd, true)} <span className="text-danger">Short</span>
        </span>
      </div>
    </Panel>
  );
}

export function StatGroups({ summary }: { summary: AccountSummary }) {
  return (
    <div className="flex flex-col gap-2">
      {metricsPending(summary) ? (
        <p className="text-xs text-muted">Style, streaks, win rate and risk ratios are computed by discovery. They show as n/a until its next pass covers this account.</p>
      ) : null}
      <div className="grid gap-4 md:grid-cols-3">
        <StatList title="Overview" stats={overviewStats(summary)} />
        <StatList title="Analysis" description="From your closed round trips" stats={analysisStats(summary)} />
        <div className="flex flex-col gap-4">
          <StatList title="Performance" description="Last 30 days" stats={performanceStats(summary)} />
          <DirectionBias summary={summary} />
        </div>
      </div>
    </div>
  );
}
