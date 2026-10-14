"use client";

import Link from "next/link";
import { Marquee } from "@/components/ui/Marquee";
import { Pnl } from "@/components/ui/Pnl";
import type { PnlUnit } from "@/lib/scout/query";
import { tickerItems, tickerSpeedS } from "@/lib/scout/ticker";
import type { PnlWindow, TraderRow } from "@/lib/scout/types";
import { formatSignedUsdCompact, WINDOW_LABEL } from "@/lib/scout/window";
import { scoutHref } from "./bits";

/** The board's top rows as a slow ticker under the Scout title: rank, name, the window's PnL. */
export function BoardTicker({ rows, window, unit, demo }: { rows: readonly TraderRow[]; window: PnlWindow; unit: PnlUnit; demo: boolean }) {
  const items = tickerItems(rows, window, unit);
  if (items.length < 3) return null;
  return (
    <div className="flex items-center border-y border-border">
      <span className="text-label flex-shrink-0 border-r border-border py-2 pr-3 text-muted">Top {WINDOW_LABEL[window]}</span>
      <Marquee label={`Top traders, ${WINDOW_LABEL[window]}`} speedS={tickerSpeedS(items.length)} className="min-w-0 flex-1">
        {items.map((it) => (
          <Link
            key={it.address}
            href={scoutHref(`/scout/${it.address}`, demo)}
            className="flex items-center gap-2 px-4 py-2 text-xs transition-colors hover:bg-surface-2"
          >
            <span className="num-sm text-muted">{String(it.rank).padStart(2, "0")}</span>
            <span className="font-num text-fg-soft">{it.name}</span>
            <Pnl value={it.value} format={unit === "pct" ? "pct" : formatSignedUsdCompact} className="num-sm" />
          </Link>
        ))}
      </Marquee>
    </div>
  );
}
