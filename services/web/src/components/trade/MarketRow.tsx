"use client";

import { clsx } from "clsx";
import { fitGrade } from "@/lib/scout/copyFit";
import { shortenAddress } from "@/lib/format";
import { formatIndex } from "@/lib/trade/equityIndex";
import type { MarketItem } from "@/lib/trade/markets";
import { CatAvatar } from "./CatAvatar";
import { ChangeText } from "./bits";

const FIT_TONE = {
  strong: "bg-success/15 text-success",
  fair: "bg-accent-soft text-accent",
  weak: "bg-danger/10 text-danger",
  none: "bg-surface-2 text-muted",
} as const;

export function FitPill({ value }: { value: number | null | undefined }) {
  const g = fitGrade(value);
  return (
    <span
      title={value === null || value === undefined ? "Copy Fit not scored yet" : `Copy Fit ${value.toFixed(0)} / 100`}
      className={clsx("font-num inline-flex min-w-8 justify-center rounded-md px-1.5 py-0.5 text-[11px] font-semibold", FIT_TONE[g])}
    >
      {value === null || value === undefined ? "—" : value.toFixed(0)}
    </span>
  );
}

export function MarketRow({
  m,
  selected,
  change,
  onSelect,
}: {
  m: MarketItem;
  selected: boolean;
  change: "24h" | "7d";
  onSelect: (address: string) => void;
}) {
  const ch = change === "24h" ? m.quote?.change24hPct : m.quote?.change7dPct;
  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(m.address)}
        aria-current={selected ? "true" : undefined}
        className={clsx(
          "grid w-full grid-cols-[minmax(0,1fr)_3.5rem_3.5rem_2rem] items-center gap-2 border-l-2 px-3 py-2 text-left transition-colors",
          selected ? "border-accent bg-accent-soft/60" : "border-transparent hover:bg-surface-2",
        )}
      >
        <span className="flex min-w-0 items-center gap-2">
          <CatAvatar address={m.address} size={22} />
          <span className="min-w-0">
            <span className="flex items-center gap-1">
              <span className={clsx("truncate text-sm font-medium", !m.name && "font-num")}>{m.name ?? shortenAddress(m.address, 4, 4)}</span>
              {m.inBook ? <span className="h-1.5 w-1.5 flex-shrink-0 rounded-full bg-accent" title="In your book" aria-label="In your book" /> : null}
            </span>
            {m.name ? <span className="font-num block truncate text-[11px] text-muted">{shortenAddress(m.address, 4, 4)}</span> : null}
          </span>
        </span>
        <span className="font-num text-right text-sm">{formatIndex(m.quote?.price)}</span>
        <ChangeText pct={ch} className="text-right text-xs" />
        <span className="flex justify-end">
          <FitPill value={m.row?.score.copy_fit?.value} />
        </span>
      </button>
    </li>
  );
}
