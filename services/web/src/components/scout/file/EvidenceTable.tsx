import { clsx } from "clsx";
import { formatSignedPct, formatSignedUsd } from "@/lib/format";
import { contextChips } from "@/lib/scout/file/strategy";
import { formatHold } from "@/lib/scout/labels";
import type { TradeExample } from "@/lib/scout/types";
import { CoinBadge } from "@/components/scout/bits";

function day(ms: number): string {
  return new Date(ms).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** Representative trips behind the fingerprint, each with its entry context and why it was picked. */
export function EvidenceTable({ examples }: { examples: TradeExample[] }) {
  if (!examples.length) return <p className="text-sm text-muted">No example trades in this window.</p>;
  return (
    <ul className="flex flex-col divide-y divide-border">
      {examples.map((e) => (
        <li key={`${e.coin}-${e.opened_ms}`} className="flex flex-col gap-1.5 py-3 first:pt-0">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <CoinBadge coin={e.coin} />
            <span className={clsx("text-xs font-medium uppercase", e.side === "long" ? "text-success" : "text-danger")}>{e.side}</span>
            <span className="text-xs text-muted">
              {day(e.opened_ms)} · held {formatHold(e.hold_h)} · {e.adds} add{e.adds === 1 ? "" : "s"}
              {e.max_leverage ? ` · up to ${e.max_leverage}x` : ""}
            </span>
            <span className={clsx("ml-auto font-num text-sm font-semibold", e.net_pnl_usd >= 0 ? "text-success" : "text-danger")}>
              {formatSignedUsd(e.net_pnl_usd)} <span className="text-xs font-normal">({formatSignedPct(e.return_pct)})</span>
            </span>
          </div>
          <div className="flex flex-wrap gap-1">
            {contextChips(e.context).map((c) => (
              <span key={c} className="rounded-md border border-border px-1.5 py-0.5 text-[11px] text-muted">
                {c}
              </span>
            ))}
          </div>
          <p className="text-xs text-foreground">{e.why_shown}</p>
        </li>
      ))}
    </ul>
  );
}
