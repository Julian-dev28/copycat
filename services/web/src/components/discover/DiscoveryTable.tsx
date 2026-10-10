"use client";

import { Fragment, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown, Check, ChevronDown, Minus, X } from "lucide-react";
import { clsx } from "clsx";
import type { TraderScore } from "@/lib/api/types";
import { MAX_LEADERS } from "@/lib/api/types";
import { formatPct, formatSignedPct, formatSignedUsd, formatUsd } from "@/lib/format";
import { explainScore, formatScore, isUnscored, type ExplainTone } from "@/lib/scoreExplain";
import { traderFlags } from "./flags";
import { AddressChip } from "@/components/ui/AddressChip";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Panel, PanelHeader } from "@/components/ui/Panel";

type SortKey =
  | "score"
  | "sim_return_pct"
  | "sim_max_drawdown_pct"
  | "sim_liquidations"
  | "sim_copies"
  | "pnl_30d_usd"
  | "roi_30d_pct"
  | "opens_per_day";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "score", label: "Score" },
  { key: "sim_return_pct", label: "Sim return" },
  { key: "sim_max_drawdown_pct", label: "Max DD" },
  { key: "sim_liquidations", label: "Liquidations" },
  { key: "sim_copies", label: "Copies" },
  { key: "pnl_30d_usd", label: "30d PnL" },
  { key: "roi_30d_pct", label: "30d ROI" },
  { key: "opens_per_day", label: "Opens/day" },
];

/** Sort options for the phone layout, phrased as what you'd want first. DD is <= 0, so desc = smallest dip. */
const MOBILE_SORTS: { value: `${SortKey}:${"asc" | "desc"}`; label: string }[] = [
  { value: "score:desc", label: "Best score" },
  { value: "sim_return_pct:desc", label: "Best sim return" },
  { value: "sim_max_drawdown_pct:desc", label: "Smallest drawdown" },
  { value: "sim_liquidations:asc", label: "Fewest liquidations" },
  { value: "sim_copies:desc", label: "Most copies" },
  { value: "pnl_30d_usd:desc", label: "Best 30d PnL" },
  { value: "roi_30d_pct:desc", label: "Best 30d ROI" },
  { value: "opens_per_day:asc", label: "Calmest (fewest opens/day)" },
];

export function DiscoveryTable({
  results,
  leaderCount,
  leaders,
  simEquityUsd,
  onCopy,
  copyingAddress,
}: {
  results: TraderScore[];
  leaderCount: number;
  /** Addresses already being copied, so their button reads "Copying". */
  leaders: string[];
  simEquityUsd: number;
  onCopy: (address: string) => void;
  copyingAddress?: string | null;
}) {
  const [whyOpen, setWhyOpen] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; dir: "asc" | "desc" }>({ key: "score", dir: "desc" });

  const sorted = useMemo(() => {
    const copy = [...results];
    copy.sort((a, b) => {
      const diff = (a[sort.key] as number) - (b[sort.key] as number);
      return sort.dir === "asc" ? diff : -diff;
    });
    return copy;
  }, [results, sort]);

  function toggleSort(key: SortKey) {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "desc" ? "asc" : "desc" } : { key, dir: "desc" }));
  }

  const atCap = leaderCount >= MAX_LEADERS;

  return (
    <Panel>
      <PanelHeader
        title={`Results (${results.length})`}
        description="Ranked by what copying each wallet would have earned you, not by its own PnL. Tap a score to see why."
      />
      <div className="flex items-center gap-2 border-t border-border px-4 py-2 md:hidden">
        <label htmlFor="discover-sort" className="text-xs text-muted">
          Sort by
        </label>
        <select
          id="discover-sort"
          value={`${sort.key}:${sort.dir}`}
          onChange={(e) => {
            const [key, dir] = e.target.value.split(":") as [SortKey, "asc" | "desc"];
            setSort({ key, dir });
          }}
          className="rounded-md border border-border bg-surface-2 px-2 py-1 text-xs text-foreground"
        >
          {MOBILE_SORTS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <ul className="divide-y divide-border border-t border-border md:hidden">
        {sorted.length === 0 ? (
          <li className="px-4 py-8 text-center text-sm text-muted">No wallets were scored in this run. Try a larger Top N.</li>
        ) : (
          sorted.map((t) => {
            const open = whyOpen === t.address;
            const following = leaders.includes(t.address.toLowerCase());
            return (
              <li key={t.address} className="flex flex-col gap-2 px-4 py-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex min-w-0 flex-col">
                    {t.display_name ? <span className="truncate font-medium">{t.display_name}</span> : null}
                    <AddressChip address={t.address} strong={!t.display_name} />
                  </div>
                  <Button
                    size="sm"
                    variant={following ? "secondary" : "primary"}
                    disabled={following || atCap || copyingAddress === t.address}
                    onClick={() => onCopy(t.address)}
                  >
                    {following ? "Copying" : copyingAddress === t.address ? "Adding…" : "Copy"}
                  </Button>
                </div>
                <dl className="font-num grid grid-cols-4 gap-2 text-xs">
                  <div>
                    <dt className="text-muted">Score</dt>
                    <dd className={clsx("font-semibold", isUnscored(t) && "text-muted")}>{formatScore(t)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Sim</dt>
                    <dd className={t.sim_return_pct >= 0 ? "text-success" : "text-danger"}>{formatSignedPct(t.sim_return_pct)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Max DD</dt>
                    <dd className="text-danger">{formatPct(t.sim_max_drawdown_pct)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted">Liq / copies</dt>
                    <dd>
                      <span className={t.sim_liquidations > 0 ? "font-semibold text-danger" : ""}>{t.sim_liquidations}</span> /{" "}
                      {t.sim_copies}
                    </dd>
                  </div>
                </dl>
                <div className="flex flex-wrap items-center gap-1">
                  {traderFlags(t).map((f) => (
                    <span key={f.key} title={f.meaning}>
                      <Badge tone={f.key === "liquidated" || f.key === "error" ? "danger" : "warning"}>
                        {f.key.replaceAll("_", " ")}
                        {f.count > 1 ? ` x${f.count}` : ""}
                      </Badge>
                    </span>
                  ))}
                  <button
                    type="button"
                    onClick={() => setWhyOpen(open ? null : t.address)}
                    aria-expanded={open}
                    className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-accent"
                  >
                    Why this score?
                    <ChevronDown size={12} className={clsx("transition-transform", open && "rotate-180")} aria-hidden="true" />
                  </button>
                </div>
                {open ? <WhyPanel trader={t} simEquityUsd={simEquityUsd} /> : null}
              </li>
            );
          })
        )}
      </ul>
      <div className="hidden overflow-x-auto border-t border-border md:block">
        <table className="w-full min-w-[1040px] text-sm">
          <thead>
            <tr className="text-right text-xs text-muted">
              <th scope="col" className="px-3 py-2 pl-5 text-left font-medium">
                Trader
              </th>
              {COLUMNS.map((col) => (
                <th key={col.key} scope="col" className="px-3 py-2 font-medium" aria-sort={sort.key === col.key ? (sort.dir === "desc" ? "descending" : "ascending") : undefined}>
                  <button
                    type="button"
                    onClick={() => toggleSort(col.key)}
                    className="ml-auto flex items-center gap-1 whitespace-nowrap hover:text-foreground"
                    aria-label={`Sort by ${col.label}`}
                  >
                    {col.label}
                    <SortIcon active={sort.key === col.key} dir={sort.dir} />
                  </button>
                </th>
              ))}
              <th scope="col" className="px-3 py-2 text-left font-medium">
                Flags
              </th>
              <th scope="col" className="px-3 py-2 pr-5 font-medium">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length + 3} className="px-5 py-8 text-center text-muted">
                  No wallets were scored in this run. Try a larger Top N.
                </td>
              </tr>
            ) : (
              sorted.map((t) => {
                const open = whyOpen === t.address;
                const following = leaders.includes(t.address.toLowerCase());
                const flags = traderFlags(t);
                return (
                  <Fragment key={t.address}>
                    <tr className={clsx("border-t border-border text-right", open && "bg-surface-2/40")}>
                      <td className="px-3 py-2.5 pl-5 text-left">
                        <div className="flex flex-col gap-0.5">
                          {t.display_name ? <span className="font-medium">{t.display_name}</span> : null}
                          <AddressChip address={t.address} strong={!t.display_name} />
                          <span className="font-num text-xs text-muted">
                            acct {formatUsd(t.account_value_usd, true)} · {t.opens_per_day.toFixed(1)} opens/day
                          </span>
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <button
                          type="button"
                          onClick={() => setWhyOpen(open ? null : t.address)}
                          aria-expanded={open}
                          aria-controls={`why-${t.address}`}
                          className="font-num ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 font-semibold hover:bg-surface-2"
                          title="Why this score?"
                        >
                          <span className={clsx(isUnscored(t) && "text-muted")}>{formatScore(t)}</span>
                          <span className="text-[11px] font-medium text-accent">why</span>
                          <ChevronDown size={12} className={clsx("text-muted transition-transform", open && "rotate-180")} aria-hidden="true" />
                        </button>
                      </td>
                      <td className={`font-num px-3 py-2.5 ${t.sim_return_pct >= 0 ? "text-success" : "text-danger"}`}>
                        {formatSignedPct(t.sim_return_pct)}
                      </td>
                      <td className="font-num px-3 py-2.5 text-danger">{formatPct(t.sim_max_drawdown_pct)}</td>
                      <td className={clsx("font-num px-3 py-2.5", t.sim_liquidations > 0 && "font-semibold text-danger")}>
                        {t.sim_liquidations}
                      </td>
                      <td className="font-num px-3 py-2.5">{t.sim_copies}</td>
                      <td className={`font-num px-3 py-2.5 ${t.pnl_30d_usd >= 0 ? "text-success" : "text-danger"}`}>
                        {formatSignedUsd(t.pnl_30d_usd)}
                      </td>
                      <td className={`font-num px-3 py-2.5 ${t.roi_30d_pct >= 0 ? "text-success" : "text-danger"}`}>
                        {formatSignedPct(t.roi_30d_pct)}
                      </td>
                      <td className="font-num px-3 py-2.5">{t.opens_per_day.toFixed(1)}</td>
                      <td className="px-3 py-2.5 text-left">
                        <div className="flex max-w-[12rem] flex-wrap gap-1">
                          {flags.map((f) => (
                            <span key={f.key} title={f.meaning}>
                              <Badge tone={f.key === "liquidated" || f.key === "error" ? "danger" : "warning"}>
                                {f.key.replaceAll("_", " ")}
                                {f.count > 1 ? ` x${f.count}` : ""}
                              </Badge>
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 pr-5">
                        <Button
                          size="sm"
                          variant={following ? "secondary" : "primary"}
                          disabled={following || atCap || copyingAddress === t.address}
                          onClick={() => onCopy(t.address)}
                        >
                          {following ? "Copying" : copyingAddress === t.address ? "Adding…" : "Copy"}
                        </Button>
                      </td>
                    </tr>
                    {open ? (
                      <tr id={`why-${t.address}`} className="bg-surface-2/40">
                        <td colSpan={COLUMNS.length + 3} className="px-5 pt-1 pb-4">
                          <WhyPanel trader={t} simEquityUsd={simEquityUsd} />
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      {atCap ? (
        <p className="border-t border-border px-5 py-2 text-xs text-muted">
          You&apos;re at the {MAX_LEADERS}-leader cap. Remove one on /copy to add another.
        </p>
      ) : null}
    </Panel>
  );
}

function SortIcon({ active, dir }: { active: boolean; dir: "asc" | "desc" }) {
  if (!active) return <ArrowUpDown size={12} className="text-muted/50" aria-hidden="true" />;
  return dir === "desc" ? (
    <ArrowDown size={12} className="text-accent" aria-hidden="true" />
  ) : (
    <ArrowUp size={12} className="text-accent" aria-hidden="true" />
  );
}

const TONE_ICON: Record<ExplainTone, { Icon: typeof Check; className: string }> = {
  good: { Icon: Check, className: "text-success" },
  bad: { Icon: X, className: "text-danger" },
  neutral: { Icon: Minus, className: "text-muted" },
};

function WhyPanel({ trader, simEquityUsd }: { trader: TraderScore; simEquityUsd: number }) {
  const lines = explainScore(trader, simEquityUsd);
  const flags = traderFlags(trader);
  return (
    <div className="rounded-lg border border-border bg-surface p-3 text-left sm:p-4">
      <p className="text-xs font-semibold tracking-wide text-muted uppercase">{isUnscored(trader) ? "Why no score?" : `Why ${formatScore(trader)}?`}</p>
      <ul className="mt-2 flex flex-col gap-1.5">
        {lines.map((l, i) => {
          const { Icon, className } = TONE_ICON[l.tone];
          return (
            <li key={i} className="flex items-start gap-2 text-sm text-foreground">
              <Icon size={14} className={clsx("mt-0.5 flex-shrink-0", className)} aria-hidden="true" />
              <span>{l.text}</span>
            </li>
          );
        })}
      </ul>
      {flags.length ? (
        <p className="mt-3 text-xs text-muted">
          Flags: {flags.map((f) => `${f.key.replaceAll("_", " ")} (${f.meaning}${f.count > 1 ? `, ${f.count}x` : ""})`).join("; ")}.
        </p>
      ) : null}
      <p className="mt-2 text-xs text-muted">
        Score = return / max(5, dip), minus 50 per liquidation, times 0.2 if under 5 copies. Past sim, not a promise.
      </p>
    </div>
  );
}
