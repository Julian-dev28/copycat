"use client";

import { clsx } from "clsx";
import { AlertTriangle } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { formatSignedPct, formatSignedUsd, formatUsd, shortenAddress } from "@/lib/format";
import { roePct, sourceBadge, walletState, WALLET_STATE_LABEL, type WalletState } from "@/lib/trade/markets";
import type { TradeSettings, WalletPosition } from "@/lib/trade/types";
import { CatAvatar } from "./CatAvatar";
import { PnlText } from "./bits";

const STATE_TONE: Record<WalletState, string> = {
  active: "bg-success/15 text-success",
  dry_run: "bg-accent-soft text-accent",
  paused: "bg-surface-2 text-muted",
  stopping: "bg-warning/15 text-warning",
  no_read: "bg-danger/10 text-danger",
};
const TH = "sticky top-0 z-10 bg-surface px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-muted whitespace-nowrap";
const TD = "px-3 py-2 whitespace-nowrap font-num text-right";

export function YourWallets({
  wallets,
  settings,
  names,
  selected,
  loading,
  error,
  onAdjust,
  onStop,
  empty,
}: {
  wallets: WalletPosition[];
  settings: TradeSettings | undefined;
  names: Record<string, string | null>;
  selected: string | null;
  loading: boolean;
  error: string | null;
  onAdjust: (address: string) => void;
  onStop: (address: string) => void;
  empty: React.ReactNode;
}) {
  const totals = wallets.reduce(
    (a, w) => ({ inv: a.inv + (w.allocation_usd ?? 0), u: a.u + w.unrealized_pnl_usd, r: a.r + w.realized_pnl_usd }),
    { inv: 0, u: 0, r: 0 },
  );
  return (
    <Panel className="overflow-hidden">
      <div className="flex flex-wrap items-baseline justify-between gap-2 px-4 pt-3 pb-2">
        <h2 className="text-sm font-semibold">Your wallets {wallets.length ? <span className="font-num text-muted">({wallets.length})</span> : null}</h2>
        {wallets.length ? (
          <p className="font-num text-xs text-muted">
            Invested {formatUsd(totals.inv, totals.inv >= 100_000)} · uPnL <PnlText usd={totals.u}>{formatSignedUsd(totals.u)}</PnlText> · realized{" "}
            <PnlText usd={totals.r}>{formatSignedUsd(totals.r)}</PnlText>
          </p>
        ) : null}
      </div>
      {error ? <p className="px-4 pb-3 text-xs text-danger">{error}</p> : null}
      {!wallets.length && !loading && !error ? <div className="px-4 pb-4">{empty}</div> : null}
      {loading && !wallets.length ? <div className="mx-4 mb-4 h-16 animate-pulse rounded-lg bg-surface-2" /> : null}
      {wallets.length ? (
        <div className="max-h-[28rem] overflow-auto border-t border-border">
          <table className="w-full text-sm">
            <thead>
              <tr>
                {["Wallet", "Invested", "Leverage", "Exposure", "uPnL", "Realized", "ROE", "Copies", "Status", ""].map((h, i) => (
                  <th key={i} scope="col" className={clsx(TH, i === 0 ? "text-left" : "text-right")}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {wallets.map((w) => {
                const st = walletState(w, settings);
                const roe = roePct(w);
                const badge = sourceBadge(w);
                return (
                  <tr key={w.address} className={clsx("border-t border-border/60", w.address === selected && "bg-accent-soft/40")}>
                    <td className="px-3 py-2">
                      <button type="button" onClick={() => onAdjust(w.address)} className="flex items-center gap-2 text-left hover:text-accent">
                        <CatAvatar address={w.address} size={22} />
                        <span className="max-w-[9rem] truncate font-medium">{names[w.address] ?? <span className="font-num">{shortenAddress(w.address)}</span>}</span>
                        <span
                          title={badge === "Global" ? "Copies with your Settings tab" : "Copies with its own terms"}
                          className={clsx("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide", badge === "Global" ? "bg-surface-2 text-muted" : "bg-accent-soft text-accent")}
                        >
                          {badge}
                        </span>
                        {!w.read_ok ? <AlertTriangle size={12} className="text-danger" aria-label="Last read of his account failed" /> : null}
                      </button>
                    </td>
                    <td className={TD}>{w.allocation_usd ? formatUsd(w.allocation_usd, w.allocation_usd >= 100_000) : "—"}</td>
                    <td className={TD}>{badge === "Global" ? <span className="text-muted">settings</span> : w.exposure_mode === "target" ? `${w.target_leverage}x` : <span className="text-muted">his</span>}</td>
                    <td className={TD}>{formatUsd(w.exposure_usd, w.exposure_usd >= 100_000)}</td>
                    <td className={TD}><PnlText usd={w.unrealized_pnl_usd}>{formatSignedUsd(w.unrealized_pnl_usd)}</PnlText></td>
                    <td className={TD}><PnlText usd={w.realized_pnl_usd}>{formatSignedUsd(w.realized_pnl_usd)}</PnlText></td>
                    <td className={TD}><PnlText usd={roe}>{formatSignedPct(roe)}</PnlText></td>
                    <td className={TD}>{w.open_copies}</td>
                    <td className="px-3 py-2 text-right">
                      <span className={clsx("rounded-full px-2 py-0.5 text-[11px] font-medium", STATE_TONE[st])}>{w.in_book === false && !w.stopping ? "winding down" : WALLET_STATE_LABEL[st]}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span className="flex justify-end gap-1">
                        <Button size="sm" variant="secondary" onClick={() => onAdjust(w.address)}>Adjust</Button>
                        <Button size="sm" variant="ghost" className="text-danger" disabled={w.stopping} onClick={() => onStop(w.address)}>Stop</Button>
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </Panel>
  );
}
