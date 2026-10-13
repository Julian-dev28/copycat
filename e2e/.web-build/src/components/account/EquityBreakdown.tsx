import { InfoTip } from "@/components/ui";
import { Panel, PanelHeader } from "@/components/ui/Panel";
import { formatPct, formatUsd } from "@/lib/format";
import { equitySlices, HL_ACCOUNT_VALUE_DEF, type EquitySlice } from "@/lib/account/summary";
import type { AccountBalances } from "@/lib/account/types";

/** Accent family for the slices: ordered by how "ours" the money is. Copytrade is the accent itself. */
const COLOR: Record<EquitySlice["key"], string> = {
  perps: "color-mix(in srgb, var(--accent) 45%, var(--surface-2))",
  copytrade: "var(--accent)",
  spot: "color-mix(in srgb, var(--foreground) 35%, var(--surface-2))",
  staked: "color-mix(in srgb, var(--success) 55%, var(--surface-2))",
};

const NOTE: Record<EquitySlice["key"], string> = {
  perps: "Perps margin not used by copies",
  copytrade: "Margin in copycat's open copies",
  spot: "Spot tokens at mark",
  staked: "HYPE staked with validators",
};

export function EquityBreakdown({ balances }: { balances: AccountBalances }) {
  const slices = equitySlices(balances);
  const total = slices.reduce((a, s) => a + s.usd, 0);
  return (
    <Panel>
      <PanelHeader
        title={
          <span className="inline-flex items-center gap-1">
            Equity
            <InfoTip id="equity-def-tip" label="What equity means" content={HL_ACCOUNT_VALUE_DEF} />
          </span>
        }
        description={`${formatUsd(balances.total_usd)} total · ${formatUsd(balances.withdrawable_usd)} withdrawable`}
      />
      <div className="flex flex-col gap-3 px-4 pb-4 sm:px-5">
        <div className="flex h-3 w-full overflow-hidden rounded-sm bg-surface-2" role="img" aria-label={slices.map((s) => `${s.label} ${formatPct(s.pct, 0)}`).join(", ")}>
          {total > 0
            ? slices.filter((s) => s.usd > 0).map((s) => <span key={s.key} style={{ width: `${s.pct}%`, background: COLOR[s.key] }} className="h-full border-r border-surface last:border-r-0" />)
            : null}
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
          {slices.map((s) => (
            <div key={s.key} className="min-w-0" title={NOTE[s.key]}>
              <dt className="flex items-center gap-1.5 text-[11px] text-muted">
                <span className="h-2 w-2 rounded-sm" style={{ background: COLOR[s.key] }} aria-hidden="true" />
                {s.label}
              </dt>
              <dd className="font-num text-sm font-semibold">
                {formatUsd(s.usd, s.usd >= 100_000)} <span className="text-[11px] font-normal text-muted">{formatPct(s.pct, 0)}</span>
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </Panel>
  );
}
