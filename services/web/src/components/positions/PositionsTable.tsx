import type { CopyPosition } from "@/lib/api/types";
import { formatLeverage, formatSignedUsd, formatUsd, shortenAddress } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";
import { Panel, PanelHeader } from "@/components/ui/Panel";

const COLUMNS = [
  "Coin",
  "Leader",
  "Side",
  "Size",
  "Entry",
  "Mark",
  "Notional",
  "Leverage",
  "uPnL",
  "Liq. px",
];

export function PositionsTable({ positions }: { positions: CopyPosition[] }) {
  return (
    <Panel>
      <PanelHeader title={`Positions (${positions.length})`} />
      <div className="overflow-x-auto border-t border-border">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              {COLUMNS.map((c) => (
                <th key={c} scope="col" className="px-4 py-2 font-medium first:pl-5 last:pr-5">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length} className="px-5 py-8 text-center text-muted">
                  No open copies.
                </td>
              </tr>
            ) : (
              positions.map((p, i) => (
                <tr key={`${p.coin}-${p.leader}-${i}`} className="border-t border-border">
                  <td className="px-4 py-2.5 pl-5 font-medium">{p.coin}</td>
                  <td className="font-num px-4 py-2.5 text-muted" title={p.leader}>
                    {shortenAddress(p.leader)}
                  </td>
                  <td className="px-4 py-2.5">
                    <Badge tone={p.side === "long" ? "success" : "danger"}>{p.side}</Badge>
                  </td>
                  <td className="font-num px-4 py-2.5">{p.size}</td>
                  <td className="font-num px-4 py-2.5">{formatUsd(p.entry_px)}</td>
                  <td className="font-num px-4 py-2.5">{formatUsd(p.mark_px)}</td>
                  <td className="font-num px-4 py-2.5">{formatUsd(p.notional_usd)}</td>
                  <td className="font-num px-4 py-2.5">{formatLeverage(p.leverage)}</td>
                  <td
                    className={`font-num px-4 py-2.5 ${p.unrealized_pnl_usd >= 0 ? "text-success" : "text-danger"}`}
                  >
                    {formatSignedUsd(p.unrealized_pnl_usd)}
                  </td>
                  <td className="font-num px-4 py-2.5 pr-5">{formatUsd(p.liquidation_px)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
