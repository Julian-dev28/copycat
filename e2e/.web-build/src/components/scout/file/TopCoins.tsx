import { clsx } from "clsx";
import { CoinBadge } from "@/components/scout/bits";
import { formatSignedUsd, formatUsd } from "@/lib/format";
import type { CoinStat } from "@/lib/scout/types";

/** Per-coin volume share bars, with PnL and trips. */
export function TopCoins({ coins, max = 8 }: { coins: CoinStat[]; max?: number }) {
  if (!coins.length) return <p className="text-sm text-muted">No trades in this window.</p>;
  const total = coins.reduce((a, c) => a + c.volume_usd, 0) || 1;
  return (
    <ul className="flex flex-col gap-2">
      {coins.slice(0, max).map((c) => {
        const share = (c.volume_usd / total) * 100;
        return (
          <li key={c.coin} className="flex flex-col gap-1">
            <div className="flex items-center gap-2 text-xs">
              <CoinBadge coin={c.coin} />
              <span className="text-muted">{c.trips} trips</span>
              <span className="ml-auto font-num text-muted">{formatUsd(c.volume_usd, true)}</span>
              <span className={clsx("w-20 text-right font-num font-semibold", c.pnl_usd >= 0 ? "text-up" : "text-down")}>
                {formatSignedUsd(Math.round(c.pnl_usd))}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
              <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(1, share)}%` }} />
            </div>
          </li>
        );
      })}
      {coins.length > max ? <li className="text-[11px] text-muted">+{coins.length - max} more coins</li> : null}
    </ul>
  );
}
