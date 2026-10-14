import { clsx } from "clsx";
import { formatPrice, formatSignedUsd, formatUsd } from "@/lib/format";
import { formatHold } from "@/lib/scout/labels";
import type { RoundTrip, TraderPositionView } from "@/lib/scout/types";
import { Badge } from "@/components/ui/Badge";
import { CoinBadge } from "@/components/scout/bits";
import { TableScroll } from "@/components/ui/Table";
import { TD, TH } from "./PositionsTable";

/** Every absolute timestamp in the trader file renders in UTC, not the viewer's
 * local timezone: a trader's "last active 2h ago" already covers relative time,
 * but an exact opened/closed/placed instant is shown and labeled as the one
 * true UTC value so two viewers in different timezones read the same trip the
 * same way (user_consensus Trade history checklist: timestamps UTC and labeled). */
export function when(ms: number): string {
  return new Date(ms).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC",
  });
}

/** Full ISO UTC, for a `title` tooltip next to the trimmed cell text. */
export function whenUtcTitle(ms: number): string {
  return `${new Date(ms).toISOString().replace("T", " ").slice(0, 16)} UTC`;
}

export const LIQUIDATION_HOVER = "Liquidated by Hyperliquid, not closed by the trader";

/** Live account positions rendered under "Open now, not in win rate": these never
 * appear in `trips` (round_trips only ever emits CLOSED trips) and are excluded
 * from hold-time/win-rate stats by construction -- shown here so a viewer sees
 * why, instead of the open position silently vanishing from the history. */
function OpenNow({ positions }: { positions: TraderPositionView[] }) {
  if (!positions.length) return null;
  return (
    <div className="border-b border-border/60 px-3 py-2">
      <p className="pb-2 text-[11px] font-medium uppercase tracking-wide text-muted">Open now, not in win rate</p>
      <ul className="flex flex-col gap-1">
        {positions.map((p) => (
          <li key={p.coin} className="flex flex-wrap items-center gap-2 text-sm">
            <CoinBadge coin={p.coin} />
            <span className={clsx("text-[11px] font-semibold uppercase", p.side === "long" ? "text-success" : "text-danger")}>{p.side}</span>
            <span className="text-muted">{formatUsd(p.notional_usd, true)} at {formatPrice(p.entry_px)}</span>
            <span className={clsx("ml-auto font-num", p.unrealized_pnl_usd >= 0 ? "text-up" : "text-down")}>
              {formatSignedUsd(p.unrealized_pnl_usd)} unrealized
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function TripsTable({
  trips,
  openPositions = [],
  truncationNotice,
}: {
  trips: RoundTrip[];
  openPositions?: TraderPositionView[];
  truncationNotice?: string | null;
}) {
  if (!trips.length && !openPositions.length) return <p className="p-4 text-sm text-muted">No closed round trips yet.</p>;
  return (
    <div className="flex flex-col">
      {truncationNotice ? <p className="border-b border-border/60 bg-warn-soft px-3 py-2 text-xs text-warn">{truncationNotice}</p> : null}
      <OpenNow positions={openPositions} />
      {trips.length ? (
        <TableScroll label="Round trips">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                {["Coin", "Opened (UTC)", "Closed (UTC)", "Hold", "Entry", "Exit", "Max size", "Gross", "Fee", "Funding", "Net PnL"].map((h) => (
                  <th key={h} scope="col" className={TH}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {trips.map((t) => (
                <tr
                  key={`${t.coin}-${t.opened_ms}`}
                  data-testid="trip-row"
                  data-coin={t.coin}
                  data-side={t.side}
                  data-liquidation={t.liquidation}
                  className={clsx("border-b border-border/60 last:border-0", t.liquidation && "bg-danger/10")}
                >
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-1.5">
                      <CoinBadge coin={t.coin} />
                      <span className={clsx("text-[11px] font-semibold uppercase", t.side === "long" ? "text-success" : "text-danger")}>{t.side}</span>
                      {t.liquidation ? <Badge tone="danger" title={LIQUIDATION_HOVER}>Liquidated</Badge> : null}
                    </span>
                  </td>
                  <td className={TD} title={whenUtcTitle(t.opened_ms)}>{when(t.opened_ms)}</td>
                  <td className={TD} title={whenUtcTitle(t.closed_ms)}>{when(t.closed_ms)}</td>
                  <td className={TD}>{formatHold(t.hold_h)}</td>
                  <td className={TD}>{formatPrice(t.entry_px)}</td>
                  <td className={TD}>{formatPrice(t.exit_px)}</td>
                  <td className={TD}>{formatUsd(t.max_notional_usd, true)}</td>
                  <td className={clsx(TD, "text-muted")}>{formatSignedUsd(t.gross_pnl_usd)}</td>
                  <td className={clsx(TD, "text-muted")}>{formatUsd(t.fee_usd)}</td>
                  <td className={clsx(TD, t.funding_usd > 0 ? "text-up" : t.funding_usd < 0 ? "text-down" : "text-muted")}>
                    {t.funding_usd ? formatSignedUsd(t.funding_usd) : "—"}
                  </td>
                  <td className={clsx(TD, "font-semibold", t.win ? "text-up" : "text-down")}>{formatSignedUsd(t.net_pnl_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      ) : null}
    </div>
  );
}
