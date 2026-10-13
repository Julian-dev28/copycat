import { clsx } from "clsx";
import { CoinBadge } from "@/components/scout/bits";
import { formatPct, formatSignedUsd } from "@/lib/format";
import { tradeBreakdown } from "@/lib/scout/file/tradeBreakdown";
import type { RoundTrip } from "@/lib/scout/types";

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] text-muted">{label}</span>
      <span className={clsx("font-num text-sm font-semibold", tone)}>{value}</span>
    </div>
  );
}

const HOUR_LABEL = (h: number) => `${String(h).padStart(2, "0")}:00 UTC`;

/** Long/short PnL split, largest win/loss, avg trade size vs account,
 * win rate by coin, and UTC hour-of-day activity -- the copy-decision
 * numbers Hyperdash's wallet page and HL's own trade history show that
 * copycat's StatTiles didn't (user research, Trader file QA). Derived
 * client-side from `recent_trips`, no new api call. */
export function TradeBreakdown({ trips, accountValueUsd }: { trips: RoundTrip[]; accountValueUsd: number }) {
  if (!trips.length) return <p className="text-sm text-muted">No closed round trips yet.</p>;
  const b = tradeBreakdown(trips, accountValueUsd);
  const maxHour = Math.max(1, ...b.hourlyOpensUtc);
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Long PnL" value={formatSignedUsd(b.longPnlUsd)} tone={b.longPnlUsd >= 0 ? "text-up" : "text-down"} />
        <Stat label="Short PnL" value={formatSignedUsd(b.shortPnlUsd)} tone={b.shortPnlUsd >= 0 ? "text-up" : "text-down"} />
        <Stat label="Avg trade size" value={b.avgTradeSizePctOfAccount === null ? "—" : `${formatPct(b.avgTradeSizePctOfAccount, 1)} of account`} />
        <Stat label="Largest win" value={b.largestWinUsd === null ? "—" : formatSignedUsd(b.largestWinUsd)} tone="text-up" />
        <Stat label="Largest loss" value={b.largestLossUsd === null ? "—" : formatSignedUsd(b.largestLossUsd)} tone="text-down" />
        <Stat label="Long / short trips" value={`${b.longTrips} / ${b.shortTrips}`} />
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] text-muted">Win rate by coin</span>
        <ul className="flex flex-col gap-1">
          {b.winRateByCoin.slice(0, 6).map((c) => (
            <li key={c.coin} className="flex items-center gap-2 text-xs">
              <CoinBadge coin={c.coin} />
              <span className="text-muted">{c.trips} trips</span>
              <span className={clsx("ml-auto font-num font-semibold", c.winRatePct === null ? "text-muted" : c.winRatePct >= 50 ? "text-up" : "text-down")}>
                {c.winRatePct === null ? "—" : formatPct(c.winRatePct, 0)}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-1.5">
        <span className="text-[11px] text-muted">Opens by hour, UTC</span>
        <div className="flex h-10 items-end gap-0.5" role="img" aria-label="Opens by UTC hour of day">
          {b.hourlyOpensUtc.map((n, h) => (
            <div
              key={h}
              title={`${HOUR_LABEL(h)}: ${n} open${n === 1 ? "" : "s"}`}
              className={clsx("flex-1 rounded-t-sm", n > 0 ? "bg-accent" : "bg-surface-2")}
              style={{ height: `${Math.max(n > 0 ? 10 : 4, (n / maxHour) * 100)}%` }}
            />
          ))}
        </div>
        <div className="flex justify-between text-[10px] text-muted">
          <span>00:00</span>
          <span>12:00</span>
          <span>23:00</span>
        </div>
      </div>
    </div>
  );
}
