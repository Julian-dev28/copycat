"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
import type { TraderScore } from "@/lib/api/types";
import { MAX_LEADERS } from "@/lib/api/types";
import { formatPct, formatSignedPct, formatSignedUsd, shortenAddress } from "@/lib/format";
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

export function DiscoveryTable({
  results,
  leaderCount,
  onCopy,
  copyingAddress,
}: {
  results: TraderScore[];
  leaderCount: number;
  onCopy: (address: string) => void;
  copyingAddress?: string | null;
}) {
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
      <PanelHeader title={`Results (${results.length})`} description="Ranked by what copying him would have earned you, not his own PnL." />
      <div className="overflow-x-auto border-t border-border">
        <table className="w-full min-w-[920px] text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th scope="col" className="px-4 py-2 pl-5 font-medium">
                Trader
              </th>
              {COLUMNS.map((col) => (
                <th key={col.key} scope="col" className="px-4 py-2 font-medium">
                  <button
                    type="button"
                    onClick={() => toggleSort(col.key)}
                    className="flex items-center gap-1 hover:text-foreground"
                    aria-label={`Sort by ${col.label}`}
                  >
                    {col.label}
                    <SortIcon active={sort.key === col.key} dir={sort.dir} />
                  </button>
                </th>
              ))}
              <th scope="col" className="px-4 py-2 font-medium">
                Flags
              </th>
              <th scope="col" className="px-4 py-2 pr-5 font-medium">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length + 3} className="px-5 py-8 text-center text-muted">
                  No results yet.
                </td>
              </tr>
            ) : (
              sorted.map((t) => (
                <tr key={t.address} className="border-t border-border">
                  <td className="px-4 py-2.5 pl-5">
                    <div className="flex flex-col">
                      <span className="font-medium">{t.display_name ?? shortenAddress(t.address)}</span>
                      <span className="font-num text-xs text-muted" title={t.address}>
                        {shortenAddress(t.address)}
                      </span>
                    </div>
                  </td>
                  <td className="font-num px-4 py-2.5 font-medium">{t.score.toFixed(2)}</td>
                  <td className={`font-num px-4 py-2.5 ${t.sim_return_pct >= 0 ? "text-success" : "text-danger"}`}>
                    {formatSignedPct(t.sim_return_pct)}
                  </td>
                  <td className="font-num px-4 py-2.5 text-danger">{formatPct(t.sim_max_drawdown_pct)}</td>
                  <td className="font-num px-4 py-2.5">{t.sim_liquidations}</td>
                  <td className="font-num px-4 py-2.5">{t.sim_copies}</td>
                  <td className={`font-num px-4 py-2.5 ${t.pnl_30d_usd >= 0 ? "text-success" : "text-danger"}`}>
                    {formatSignedUsd(t.pnl_30d_usd)}
                  </td>
                  <td className={`font-num px-4 py-2.5 ${t.roi_30d_pct >= 0 ? "text-success" : "text-danger"}`}>
                    {formatSignedPct(t.roi_30d_pct)}
                  </td>
                  <td className="font-num px-4 py-2.5">{t.opens_per_day.toFixed(1)}</td>
                  <td className="px-4 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {t.flags.map((f) => (
                        <Badge key={f} tone="warning">
                          {f}
                        </Badge>
                      ))}
                    </div>
                  </td>
                  <td className="px-4 py-2.5 pr-5">
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={atCap || copyingAddress === t.address}
                      onClick={() => onCopy(t.address)}
                    >
                      {copyingAddress === t.address ? "Adding…" : "Copy"}
                    </Button>
                  </td>
                </tr>
              ))
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
