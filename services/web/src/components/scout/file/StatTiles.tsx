import { clsx } from "clsx";
import { Panel } from "@/components/ui/Panel";
import { formatLeverage, formatPct, formatSignedUsd, formatUsd } from "@/lib/format";
import { formatHold, liqTone } from "@/lib/scout/labels";
import type { PnlWindow, TraderProfile } from "@/lib/scout/types";
import { WINDOW_LABEL, windowPerf } from "@/lib/scout/window";

const WINDOWS: PnlWindow[] = ["7d", "30d", "all"];
const n2 = (v: number | null | undefined) => (v === null || v === undefined || !Number.isFinite(v) ? "—" : v.toFixed(2));
const LIQ = { ok: "text-success", warn: "text-warning", danger: "text-danger", none: "text-foreground" } as const;

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <Panel className="flex min-w-0 flex-col gap-0.5 p-3">
      <span className="text-[11px] text-muted">{label}</span>
      <span className={clsx("font-num text-base font-semibold", tone)}>{value}</span>
      {sub ? <span className="truncate text-[11px] text-muted">{sub}</span> : null}
    </Panel>
  );
}

export function StatTiles({ profile }: { profile: TraderProfile }) {
  const { account, row } = profile;
  const p30 = windowPerf(row, "30d");
  const rows: { label: string; get: (w: PnlWindow) => string }[] = [
    { label: "PnL", get: (w) => formatSignedUsd(windowPerf(row, w)?.pnl_usd) },
    { label: "Max drawdown", get: (w) => formatPct(profile.risk.find((r) => r.window === w)?.max_drawdown_pct) },
    { label: "Sharpe", get: (w) => n2(profile.risk.find((r) => r.window === w)?.sharpe) },
    { label: "Sortino", get: (w) => n2(profile.risk.find((r) => r.window === w)?.sortino) },
    { label: "Profitable days", get: (w) => formatPct(profile.risk.find((r) => r.window === w)?.profitable_days_pct, 0) },
    { label: "Round trips", get: (w) => String(profile.trades.find((t) => t.window === w)?.trips ?? "—") },
    { label: "Win rate", get: (w) => formatPct(profile.trades.find((t) => t.window === w)?.win_rate_pct, 0) },
    { label: "Avg / median hold", get: (w) => {
      const t = profile.trades.find((x) => x.window === w);
      return t ? `${formatHold(t.avg_hold_h)} / ${formatHold(t.median_hold_h)}` : "—";
    } },
    { label: "Opens per day", get: (w) => n2(profile.trades.find((t) => t.window === w)?.opens_per_day) },
  ];
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile label="30d PnL" value={formatSignedUsd(p30?.pnl_usd)} sub={p30 ? `${formatPct(p30.roi_pct)} ROI on ${formatUsd(p30.volume_usd, true)} volume` : undefined} tone={(p30?.pnl_usd ?? 0) >= 0 ? "text-success" : "text-danger"} />
        <Tile label="Leverage" value={formatLeverage(account.account_leverage)} sub={`margin used ${formatPct(account.margin_usage_pct, 0)}`} />
        <Tile label="Nearest liq" value={formatPct(account.nearest_liq_pct)} sub="price move to his closest liquidation" tone={LIQ[liqTone(account.nearest_liq_pct)]} />
        <Tile label="Long share" value={formatPct(account.long_bias_pct, 0)} sub={`${formatUsd(account.long_notional_usd, true)} L / ${formatUsd(account.short_notional_usd, true)} S · best streak ${profile.longest_win_streak_days}d`} />
      </div>
      <Panel className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className="px-3 py-2 text-left text-[11px] font-medium text-muted">Stat</th>
              {WINDOWS.map((w) => (
                <th key={w} scope="col" className="px-3 py-2 text-right text-[11px] font-medium text-muted">
                  {WINDOW_LABEL[w]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-b border-border/60 last:border-0">
                <th scope="row" className="px-3 py-1.5 text-left text-xs font-normal text-muted">{r.label}</th>
                {WINDOWS.map((w) => (
                  <td key={w} className="px-3 py-1.5 text-right font-num">{r.get(w)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
