"use client";

import { clsx } from "clsx";
import type { ReactNode } from "react";
import { Flame, Users, Wallet } from "lucide-react";
import type { EngineStatus, Settings } from "@/lib/api/types";
import { MAX_LEADERS } from "@/lib/api/types";
import { copyRecipe, leverageVibe } from "@/lib/copyRecipe";
import { formatUsd } from "@/lib/format";
import { applyMinOrderRule } from "@/lib/sizing";

function modeOf(settings: Settings): { label: string; className: string; dot: string } {
  if (!settings.enabled) return { label: "Paused", className: "bg-surface-2 text-muted border-border", dot: "bg-muted" };
  if (settings.dry_run) return { label: "Dry run", className: "bg-warning/10 text-warning border-warning/30", dot: "bg-warning" };
  return { label: "Live", className: "bg-danger/10 text-danger border-danger/40", dot: "bg-danger animate-pulse" };
}

/**
 * The one-glance summary at the top of /copy: what a single copy looks like
 * at the current settings, whether it clears HL's minimum, and the engine mode.
 */
export function CopyRecipeCard({ settings, status }: { settings: Settings; status?: EngineStatus }) {
  const r = copyRecipe(settings);
  const vibe = leverageVibe(r.leverage);
  const mode = modeOf(settings);
  const at10x = applyMinOrderRule(settings.fixed_margin_usd * 10, settings.min_order_bump);
  const lev = `${r.leverageUpperBound ? "up to " : ""}${r.leverage}x`;

  let headline: string;
  if (r.sizingMode === "fixed_margin") {
    headline = `${formatUsd(settings.fixed_margin_usd)} margin x ${lev} = ${r.leverageUpperBound ? "up to " : ""}${formatUsd(r.notionalUsd)} per copy`;
  } else if (r.sizingMode === "fixed_notional") {
    headline = `${formatUsd(r.notionalUsd)} per copy at ${lev}`;
  } else {
    headline = `Sized like the leader, ${Math.round(settings.sleeve_frac * 100)}% of equity x ${settings.size_multiplier}, at ${lev}`;
  }

  return (
    <section
      aria-label="Copy recipe"
      className="relative overflow-hidden rounded-xl border border-accent/30 bg-surface p-4 sm:p-5"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-24 -right-24 h-64 w-64 rounded-full bg-accent/15 blur-3xl"
      />
      <div className="relative flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className={clsx("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold", mode.className)}>
              <span className={clsx("h-1.5 w-1.5 rounded-full", mode.dot)} aria-hidden="true" />
              {mode.label}
            </span>
            <span className="text-xs text-muted">your copy recipe</span>
          </div>
          <p className="font-num mt-2 text-lg font-semibold tracking-tight text-foreground sm:text-xl">{headline}</p>
          {r.minOrder?.skipped ? (
            <p className="mt-1 text-sm text-danger">
              Under Hyperliquid&apos;s $10 minimum: copies at this size get skipped. Raise margin to at least{" "}
              {formatUsd(r.minMarginUsd)} or leverage.
            </p>
          ) : r.minOrder?.bumped ? (
            <p className="mt-1 text-sm text-warning">
              Under the $10.50 minimum, so each copy is bumped up to $10.50.
            </p>
          ) : r.leverageUpperBound && r.sizingMode === "fixed_margin" && r.leverage > 10 ? (
            <p className="mt-1 text-xs text-muted">
              That&apos;s the ceiling. A coin that maxes out at 10x opens {formatUsd(settings.fixed_margin_usd * 10)}
              {at10x.skipped ? ", under the minimum, so it gets skipped" : at10x.bumped ? ", bumped up to $10.50" : ""}.
            </p>
          ) : null}
        </div>
        <dl className="grid flex-shrink-0 grid-cols-3 gap-2 sm:gap-3">
          <Stat icon={<Users size={14} aria-hidden="true" />} label="Leaders" value={`${settings.leaders.length}/${MAX_LEADERS}`} />
          <Stat icon={<Wallet size={14} aria-hidden="true" />} label="Equity" value={formatUsd(status?.equity_usd, true)} />
          <Stat
            icon={<Flame size={14} aria-hidden="true" />}
            label="Heat"
            value={vibe.label}
            valueClassName={{ calm: "text-success", warm: "text-accent", hot: "text-warning", max: "text-danger" }[vibe.heat]}
          />
        </dl>
      </div>
    </section>
  );
}

function Stat({
  icon,
  label,
  value,
  valueClassName,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-surface-2/60 px-3 py-2">
      <dt className="flex items-center gap-1 text-[11px] text-muted">
        {icon}
        {label}
      </dt>
      <dd className={clsx("font-num mt-0.5 truncate text-sm font-semibold", valueClassName ?? "text-foreground")}>{value}</dd>
    </div>
  );
}
