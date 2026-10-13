"use client";

import { Badge } from "@/components/ui/Badge";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { usePendingMcpPlans } from "@/hooks/usePendingMcpPlans";
import { useNow } from "@/hooks/useNow";
import { formatUsd } from "@/lib/format";
import { formatCountdown, livePlans, planOutcome, planTerms, planTrader, secondsLeft, spacedCode } from "@/lib/mcp/pendingPlans";

/**
 * Confirm codes for copy plans Claude Code made through the copycat MCP.
 * Claude never sees the code (audit H2): you read it here and type it to
 * Claude only if you approve. Renders nothing when no plan is waiting.
 */
export function PendingMcpPlans({ enabled = true }: { enabled?: boolean }) {
  const q = usePendingMcpPlans(enabled);
  const nowMs = useNow(1000);
  const plans = livePlans(q.data, nowMs);
  if (!enabled || plans.length === 0) return null;

  return (
    <Panel aria-labelledby="mcp-plans-title">
      <PanelHeader
        title={<span id="mcp-plans-title">Pending MCP plans</span>}
        description="Claude Code is waiting for your approval. To approve, type the code to Claude. To refuse, do nothing; the plan expires."
      />
      <ul className="divide-y divide-border border-t border-border">
        {plans.map((p) => {
          const left = secondsLeft(p, nowMs);
          const outcome = planOutcome(p);
          return (
            <li key={p.plan_id} className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="font-num font-medium" title={p.address}>{planTrader(p)}</span>
                  <Badge tone={outcome.tone}>{outcome.text}</Badge>
                </div>
                <p className="text-sm text-muted">{planTerms(p)}</p>
                <p className="font-num text-xs text-muted">
                  {formatUsd(p.planned_notional_usd)} notional, {formatUsd(p.planned_margin_usd)} margin · {p.plan_id}
                </p>
                {(p.warnings ?? []).map((w) => (
                  <p key={w} className="text-xs text-warn">{w}</p>
                ))}
              </div>
              <div className="flex flex-shrink-0 items-center gap-3 sm:flex-col sm:items-end sm:gap-1">
                <code
                  aria-label={`Confirm code ${p.confirm_code.split("").join(" ")}`}
                  className="font-num select-all rounded-lg border border-accent/25 bg-accent-soft px-3 py-1.5 text-xl font-semibold tracking-[0.2em] text-accent"
                >
                  {spacedCode(p.confirm_code)}
                </code>
                <span className="font-num text-xs text-muted" aria-live="off">expires in {formatCountdown(left)}</span>
              </div>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
