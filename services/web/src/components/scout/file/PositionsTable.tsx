import { clsx } from "clsx";
import { formatPct, formatPrice, formatSignedPct, formatSignedUsd, formatSize, formatUsd } from "@/lib/format";
import { liqTone, netFundingSinceOpen } from "@/lib/scout/labels";
import type { TraderPositionView } from "@/lib/scout/types";
import { CoinBadge } from "@/components/scout/bits";

export const TH = "px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-muted whitespace-nowrap";
export const TD = "px-3 py-2 whitespace-nowrap font-num";

const LIQ_TEXT = { ok: "text-success", warn: "text-warning", danger: "text-danger", none: "text-muted" } as const;

export function PositionsTable({ positions, asOfMs }: { positions: TraderPositionView[]; asOfMs: number }) {
  if (!positions.length) return <p className="p-4 text-sm text-muted">No open positions.</p>;
  return (
    <div className="flex flex-col">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              {["Coin", "Lev", "Size", "Notional", "Entry", "Mark", "uPnL (ROE)", "Liq px", "To liq", "Margin", "Funding"].map((h) => (
                <th key={h} scope="col" className={TH}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => {
              const tone = liqTone(p.liq_distance_pct);
              return (
                <tr key={p.coin} className="border-b border-border/60 last:border-0">
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-1.5">
                      <CoinBadge coin={p.coin} />
                      <span className={clsx("text-[11px] font-semibold uppercase", p.side === "long" ? "text-success" : "text-danger")}>{p.side}</span>
                    </span>
                  </td>
                  <td className={TD}>
                    {p.leverage}x <span className="text-[11px] text-muted">{p.is_cross ? "cross" : "iso"}</span>
                  </td>
                  <td className={TD}>{formatSize(p.size)}</td>
                  <td className={TD}>{formatUsd(p.notional_usd, true)}</td>
                  <td className={TD}>{formatPrice(p.entry_px)}</td>
                  <td className={TD}>{formatPrice(p.mark_px)}</td>
                  <td className={clsx(TD, p.unrealized_pnl_usd >= 0 ? "text-up" : "text-down")}>
                    {formatSignedUsd(p.unrealized_pnl_usd)} <span className="text-[11px]">({formatSignedPct(p.roe_pct)})</span>
                  </td>
                  <td className={TD}>{p.liquidation_px ? formatPrice(p.liquidation_px) : "—"}</td>
                  <td className={clsx(TD, "font-semibold", LIQ_TEXT[tone])}>{formatPct(p.liq_distance_pct)}</td>
                  <td className={TD}>{formatUsd(p.margin_usd, true)}</td>
                  <td
                    className={clsx(TD, netFundingSinceOpen(p.funding_since_open_usd) >= 0 ? "text-up" : "text-down")}
                    title="Positive = funding received, negative = funding paid, since this position opened"
                  >
                    {formatSignedUsd(netFundingSinceOpen(p.funding_since_open_usd))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="px-3 py-2 text-[11px] text-muted">
        As of {new Date(asOfMs).toLocaleTimeString("en-US", { hour12: false })}. Distance to liq under 10% is red, under 25% amber.
      </p>
    </div>
  );
}
