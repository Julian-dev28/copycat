import Link from "next/link";
import type { CopyPosition } from "@/lib/api/types";
import { formatAgo, formatLeverage, formatPrice, formatSignedPct, formatSignedUsd, formatSize, formatUsd } from "@/lib/format";
import { roePct } from "@/lib/positions/view";
import { AddressChip } from "@/components/ui/AddressChip";
import { Badge } from "@/components/ui/Badge";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { TableScroll } from "@/components/ui/Table";

const COLUMNS: { label: string; numeric?: boolean }[] = [
  { label: "Coin" },
  { label: "Trader" },
  { label: "Side" },
  { label: "Size", numeric: true },
  { label: "Entry", numeric: true },
  { label: "Mark", numeric: true },
  { label: "Notional", numeric: true },
  { label: "Leverage", numeric: true },
  { label: "uPnL (ROE)", numeric: true },
  { label: "Liq. px", numeric: true },
  { label: "Opened", numeric: true },
];

/** "+$5.00 (+25.0%)": HL's own positions table shows uPnL and ROE together, one column. */
function pnlRoeText(p: CopyPosition): string {
  const roe = roePct(p);
  return roe === null ? formatSignedUsd(p.unrealized_pnl_usd) : `${formatSignedUsd(p.unrealized_pnl_usd)} (${formatSignedPct(roe)})`;
}

export function PositionsTable({ positions, loading, nowMs }: { positions: CopyPosition[]; loading?: boolean; nowMs?: number }) {
  const totalPnl = positions.reduce((sum, p) => sum + p.unrealized_pnl_usd, 0);
  return (
    <Panel>
      <PanelHeader
        title={`Positions (${positions.length})`}
        description="Only positions copycat opened. Anything you trade by hand on the same account is left alone."
        action={
          positions.length ? (
            <span className={`font-num text-sm font-semibold ${totalPnl >= 0 ? "text-up" : "text-down"}`}>
              {formatSignedUsd(totalPnl)}
            </span>
          ) : undefined
        }
      />
      {loading ? (
        <div className="border-t border-border px-5 py-6">
          <div className="h-5 animate-pulse rounded bg-surface-2" />
        </div>
      ) : positions.length === 0 ? (
        <p className="border-t border-border px-5 py-10 text-center text-sm text-muted">
          No open copies. When a trader you copy opens a position, the copy shows up here within one cycle.{" "}
          {/* axe link-in-text-block: text-accent against the surrounding muted
              text is only 1.32:1, well under the 3:1 a color-only link needs,
              so the link must also carry its own non-color signal: underline,
              not only on hover.
              Same-page anchor, not a route: "/copy" is a dead legacy path
              (lib/trade/apiState.ts LEGACY_ROUTES) that redirects to
              /settings, nowhere near "your copies" (regression: this used to
              send a user with zero positions to Settings instead of the
              wallets list sitting right above). */}
          <Link href="#your-copies" className="text-accent underline underline-offset-2">
            Check your copies
          </Link>
        </p>
      ) : (
        <>
          <ul className="divide-y divide-border border-t border-border md:hidden">
            {positions.map((p) => (
              <li key={`${p.coin}-${p.leader}`} className="flex flex-col gap-2 px-4 py-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{p.coin}</span>
                    <Badge tone={p.side === "long" ? "success" : "danger"}>{p.side}</Badge>
                    <span className="font-num text-xs text-muted">
                      {formatLeverage(p.leverage)} {p.is_cross ? "cross" : "iso"}
                    </span>
                  </div>
                  <span className={`font-num font-semibold ${p.unrealized_pnl_usd >= 0 ? "text-up" : "text-down"}`}>
                    {pnlRoeText(p)}
                  </span>
                </div>
                <dl className="font-num grid grid-cols-3 gap-2 text-xs">
                  <MiniStat label="Notional" value={formatUsd(p.notional_usd)} />
                  <MiniStat label="Entry" value={formatPrice(p.entry_px)} />
                  <MiniStat label="Liq." value={formatPrice(p.liquidation_px)} />
                </dl>
                <span className="flex items-center justify-between gap-1 text-xs text-muted">
                  <span className="flex items-center gap-1">
                    from <AddressChip address={p.leader} />
                  </span>
                  {nowMs ? <span>opened {formatAgo(p.opened_ms, nowMs)}</span> : null}
                </span>
              </li>
            ))}
          </ul>
          <PositionsDesktopTable positions={positions} nowMs={nowMs} />
        </>
      )}
    </Panel>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted">{label}</dt>
      <dd className="truncate text-foreground">{value}</dd>
    </div>
  );
}

function PositionsDesktopTable({ positions, nowMs }: { positions: CopyPosition[]; nowMs?: number }) {
  return (
    <TableScroll label="Open copy positions" className="hidden border-t border-border md:block">
      <table className="w-full min-w-[820px] text-sm">
        <thead>
          <tr className="text-xs text-muted">
            {COLUMNS.map((c) => (
              <th
                key={c.label}
                scope="col"
                className={`px-3 py-2 font-medium first:pl-5 last:pr-5 ${c.numeric ? "text-right" : "text-left"}`}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={`${p.coin}-${p.leader}`} className="border-t border-border">
              <td className="px-3 py-2.5 pl-5 font-semibold whitespace-nowrap">{p.coin}</td>
              <td className="px-3 py-2.5 whitespace-nowrap">
                <AddressChip address={p.leader} />
              </td>
              <td className="px-3 py-2.5">
                <Badge tone={p.side === "long" ? "success" : "danger"}>{p.side}</Badge>
              </td>
              <td className="font-num px-3 py-2.5 text-right">{formatSize(p.size)}</td>
              <td className="font-num px-3 py-2.5 text-right">{formatPrice(p.entry_px)}</td>
              <td className="font-num px-3 py-2.5 text-right">{formatPrice(p.mark_px)}</td>
              <td className="font-num px-3 py-2.5 text-right">{formatUsd(p.notional_usd)}</td>
              <td className="font-num px-3 py-2.5 text-right whitespace-nowrap">
                {formatLeverage(p.leverage)} <span className="text-xs text-muted">{p.is_cross ? "cross" : "iso"}</span>
              </td>
              <td className={`font-num px-3 py-2.5 text-right whitespace-nowrap ${p.unrealized_pnl_usd >= 0 ? "text-up" : "text-down"}`}>
                {pnlRoeText(p)}
              </td>
              <td className="font-num px-3 py-2.5 text-right">{formatPrice(p.liquidation_px)}</td>
              <td className="font-num px-3 py-2.5 pr-5 text-right whitespace-nowrap">{nowMs ? formatAgo(p.opened_ms, nowMs) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </TableScroll>
  );
}
