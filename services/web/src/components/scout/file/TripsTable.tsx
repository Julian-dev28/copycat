import { clsx } from "clsx";
import { formatPrice, formatSignedUsd, formatUsd } from "@/lib/format";
import { formatHold } from "@/lib/scout/labels";
import type { RoundTrip } from "@/lib/scout/types";
import { CoinBadge } from "@/components/scout/bits";
import { TableScroll } from "@/components/ui/Table";
import { TD, TH } from "./PositionsTable";

export function when(ms: number): string {
  return new Date(ms).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hour12: false });
}

/** ISO UTC, for a `title` tooltip next to a local-time cell. */
export function whenUtcTitle(ms: number): string {
  return `${new Date(ms).toISOString().replace("T", " ").slice(0, 16)} UTC`;
}

export function TripsTable({ trips }: { trips: RoundTrip[] }) {
  if (!trips.length) return <p className="p-4 text-sm text-muted">No closed round trips yet.</p>;
  return (
    <TableScroll label="Round trips">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            {["Coin", "Opened", "Closed", "Hold", "Entry", "Exit", "Max size", "Gross", "Fee", "Funding", "Net PnL"].map((h) => (
              <th key={h} scope="col" className={TH}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trips.map((t) => (
            <tr key={`${t.coin}-${t.opened_ms}`} className="border-b border-border/60 last:border-0">
              <td className="px-3 py-2">
                <span className="flex items-center gap-1.5">
                  <CoinBadge coin={t.coin} />
                  <span className={clsx("text-[11px] font-semibold uppercase", t.side === "long" ? "text-success" : "text-danger")}>{t.side}</span>
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
  );
}
