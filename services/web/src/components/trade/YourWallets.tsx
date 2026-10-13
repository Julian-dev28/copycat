"use client";

import { useState } from "react";
import { clsx } from "clsx";
import { AlertTriangle, ArrowDownUp, Archive, Pause, Play, ScrollText, Share2, SlidersHorizontal, Square } from "lucide-react";
import { Panel } from "@/components/ui/Panel";
import { Button } from "@/components/ui/Button";
import { formatSignedPct, formatSignedUsd, formatUsd, shortenAddress } from "@/lib/format";
import { problemText } from "@/lib/trade/apiState";
import { actionDone, inTab, LIFECYCLE_TABS, rowActions, STATUS_BADGE, tabCounts, walletStatus, type LifecycleTab, type RowAction } from "@/lib/trade/lifecycle";
import { roePct, sourceBadge, walletState } from "@/lib/trade/markets";
import type { CurvePoint } from "@/lib/scout/types";
import type { TradeSettings, WalletPosition } from "@/lib/trade/types";
import { CatAvatar } from "./CatAvatar";
import { PnlText } from "./bits";
import { useStopWallet, useWalletLifecycle } from "./hooks";
import { ArchiveDialog, StopDialog } from "./TicketDialogs";
import { WalletLogDrawer } from "./WalletLogDrawer";
import { ShareCardDialog } from "./ShareCardDialog";

const TONE: Record<string, string> = {
  success: "bg-success/15 text-success",
  neutral: "bg-surface-2 text-muted",
  warning: "bg-warning/15 text-warning",
  danger: "bg-danger/10 text-danger",
  accent: "bg-accent-soft text-accent",
};
const TH = "sticky top-0 z-10 bg-surface px-3 py-2 text-[11px] font-medium uppercase tracking-wide text-muted whitespace-nowrap";
const TD = "px-3 py-2 whitespace-nowrap font-num text-right";

type OpenDialog = { kind: "stop" | "archive" | "log" | "share"; address: string } | null;

/** Your wallets: Running | Stopped | Archived, with the lifecycle actions on each row. Self-contained (Trade and Portfolio). */
export function YourWallets({
  wallets,
  settings,
  names,
  selected,
  loading,
  error,
  onAdjust,
  empty,
  nowMs,
  sparks,
}: {
  wallets: WalletPosition[];
  settings: TradeSettings | undefined;
  names: Record<string, string | null>;
  selected: string | null;
  loading: boolean;
  error: string | null;
  onAdjust: (address: string) => void;
  empty: React.ReactNode;
  nowMs: number;
  /** His 30d index per wallet (the share card sparkline), when the board has it. */
  sparks?: Record<string, CurvePoint[]>;
}) {
  const [tab, setTab] = useState<LifecycleTab>("running");
  const [dialog, setDialog] = useState<OpenDialog>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const life = useWalletLifecycle();
  const stop = useStopWallet();
  const counts = tabCounts(wallets);
  const rows = inTab(wallets, tab);
  const totals = rows.reduce(
    (a, w) => ({ inv: a.inv + (w.allocation_usd ?? 0), u: a.u + w.unrealized_pnl_usd, r: a.r + w.realized_pnl_usd }),
    { inv: 0, u: 0, r: 0 },
  );
  const label = (a: string) => names[a] ?? shortenAddress(a);
  const current = dialog ? wallets.find((w) => w.address === dialog.address) ?? null : null;

  function act(w: WalletPosition, a: RowAction) {
    setMsg(null);
    if (a === "adjust") return onAdjust(w.address);
    if (a === "pause" || a === "resume") {
      return life.mutate({ address: w.address, action: a }, { onSuccess: () => setMsg(actionDone(a, label(w.address))) });
    }
    setDialog({ kind: a, address: w.address });
  }

  return (
    <Panel className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-3 pb-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold">Your copies</h2>
          <div role="tablist" aria-label="Wallet status" className="flex gap-1">
            {LIFECYCLE_TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={tab === t.id}
                onClick={() => setTab(t.id)}
                className={clsx("rounded-md px-2.5 py-1 text-xs font-medium", tab === t.id ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-2 hover:text-foreground")}
              >
                {t.label} <span className="font-num text-[10px]">{counts[t.id]}</span>
              </button>
            ))}
          </div>
        </div>
        {rows.length ? (
          <p className="font-num text-xs text-muted">
            Invested {formatUsd(totals.inv, totals.inv >= 100_000)} · uPnL <PnlText usd={totals.u}>{formatSignedUsd(totals.u)}</PnlText> · realized{" "}
            <PnlText usd={totals.r}>{formatSignedUsd(totals.r)}</PnlText>
          </p>
        ) : null}
      </div>
      {error ? <p className="px-4 pb-3 text-xs text-danger">{error}</p> : null}
      {life.isError ? <p role="alert" className="px-4 pb-2 text-xs text-danger">{problemText(life.error, `wallet ${life.variables?.action ?? "lifecycle"}`)}</p> : null}
      {stop.isError ? <p role="alert" className="px-4 pb-2 text-xs text-danger">{problemText(stop.error, "wallet stop")}</p> : null}
      {msg ? <p role="status" className="px-4 pb-2 text-xs text-success">{msg}</p> : null}
      {!wallets.length && !loading && !error ? <div className="px-4 pb-4">{empty}</div> : null}
      {wallets.length && !rows.length ? (
        <p className="px-4 pb-4 text-sm text-muted">
          {tab === "running"
            ? "Nothing running."
            : tab === "stopped"
              ? "No stopped wallets. Stop one and it lands here with its realized PnL."
              : "Nothing archived. Archive a stopped wallet to keep its history out of the way."}
        </p>
      ) : null}
      {loading && !wallets.length ? <div className="mx-4 mb-4 h-16 animate-pulse rounded-lg bg-surface-2" /> : null}
      {rows.length ? (
        <div className="max-h-[28rem] overflow-auto border-t border-border">
          <table className="w-full text-sm">
            <thead>
              <tr>
                {["Wallet", "Invested", "Leverage", "Exposure", "uPnL", "Realized", "ROE", "Copies", "Status", ""].map((h, i) => (
                  <th key={i} scope="col" className={clsx(TH, i === 0 ? "text-left" : "text-right")}>
                    {h || <span className="sr-only">Actions</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((w) => {
                const status = walletStatus(w);
                const badge = STATUS_BADGE[status];
                const engine = walletState(w, settings);
                const roe = roePct(w);
                const src = sourceBadge(w);
                const busy = (life.isPending && life.variables?.address === w.address) || (stop.isPending && stop.variables?.address === w.address);
                return (
                  <tr key={w.address} className={clsx("border-t border-border/60", w.address === selected && "bg-accent-soft/40")}>
                    <td className="px-3 py-2">
                      <button type="button" onClick={() => onAdjust(w.address)} className="flex items-center gap-2 text-left hover:text-accent">
                        <CatAvatar address={w.address} size={22} />
                        <span className="max-w-[9rem] truncate font-medium">{names[w.address] ?? <span className="font-num">{shortenAddress(w.address)}</span>}</span>
                        <span
                          title={src === "Global" ? "Copies with your Settings tab" : "Copies with its own terms"}
                          className={clsx("rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide", src === "Global" ? "bg-surface-2 text-muted" : "bg-accent-soft text-accent")}
                        >
                          {src}
                        </span>
                        {w.trade_direction === "counter" ? (
                          <span title="Counter: the opposite side of each of his positions" className="inline-flex items-center gap-0.5 rounded bg-danger/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-danger">
                            <ArrowDownUp size={10} aria-hidden="true" /> counter
                          </span>
                        ) : null}
                        {w.one_shot ? (
                          <span title="One-shot: copies only the positions he held when you invested; his new trades are not copied" className="rounded bg-warn-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warn">
                            one-shot
                          </span>
                        ) : null}
                        {!w.read_ok && (status === "running" || status === "paused") ? <AlertTriangle size={12} className="text-danger" aria-label="Last read of his account failed" /> : null}
                      </button>
                    </td>
                    <td className={TD}>{w.allocation_usd ? formatUsd(w.allocation_usd, w.allocation_usd >= 100_000) : "—"}</td>
                    <td className={TD}>{src === "Global" ? <span className="text-muted">settings</span> : w.exposure_mode === "target" ? `${w.target_leverage}x` : <span className="text-muted">his</span>}</td>
                    <td className={TD}>{formatUsd(w.exposure_usd, w.exposure_usd >= 100_000)}</td>
                    <td className={TD}><PnlText usd={w.unrealized_pnl_usd}>{formatSignedUsd(w.unrealized_pnl_usd)}</PnlText></td>
                    <td className={TD}><PnlText usd={w.realized_pnl_usd}>{formatSignedUsd(w.realized_pnl_usd)}</PnlText></td>
                    <td className={TD}><PnlText usd={roe}>{formatSignedPct(roe)}</PnlText></td>
                    <td className={TD}>{w.open_copies}</td>
                    <td className="px-3 py-2 text-right">
                      <span className="flex flex-col items-end gap-0.5">
                        <span title={badge.hint} className={clsx("rounded-sm px-2 py-0.5 text-[11px] font-medium", TONE[badge.tone])}>{badge.label}</span>
                        {status === "paused" ? <span className="text-[10px] whitespace-nowrap text-muted">no new copies; exits still followed</span> : null}
                        {status === "running" && w.one_shot ? <span className="text-[10px] whitespace-nowrap text-muted">new trades not copied</span> : null}
                        {status === "running" && engine === "dry_run" ? <span className="text-[10px] text-muted">dry run</span> : null}
                        {status === "running" && engine === "paused" ? <span className="text-[10px] text-muted">engine off</span> : null}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      <span className="flex justify-end gap-1">
                        {rowActions(status).map((a) => (
                          <ActionButton key={a} action={a} stopped={status === "stopped"} disabled={busy} onClick={() => act(w, a)} />
                        ))}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {dialog?.kind === "stop" && current ? (
        <StopDialog
          open
          name={label(current.address)}
          openCopies={current.open_copies}
          pending={stop.isPending}
          onCancel={() => setDialog(null)}
          onConfirm={(close_positions) =>
            stop.mutate({ address: current.address, body: { close_positions } }, {
              onSettled: () => setDialog(null),
              onSuccess: () => setMsg(close_positions ? `Stopping ${label(current.address)}: closing its copies.` : `Stopped new copies of ${label(current.address)}; open ones follow him out.`),
            })
          }
        />
      ) : null}
      {dialog?.kind === "archive" && current ? (
        <ArchiveDialog
          open
          name={label(current.address)}
          pending={life.isPending}
          onCancel={() => setDialog(null)}
          onConfirm={() =>
            life.mutate({ address: current.address, action: "archive" }, {
              onSettled: () => setDialog(null),
              onSuccess: () => setMsg(actionDone("archive", label(current.address))),
            })
          }
        />
      ) : null}
      {dialog?.kind === "log" ? <WalletLogDrawer open onClose={() => setDialog(null)} address={dialog.address} name={label(dialog.address)} /> : null}
      {dialog?.kind === "share" && current ? (
        <ShareCardDialog open onClose={() => setDialog(null)} wallet={current} name={names[current.address] ?? null} nowMs={nowMs} index={sparks?.[current.address]} />
      ) : null}
    </Panel>
  );
}

const ACTION_META: Record<RowAction, { label: string; icon: typeof Pause; variant: "secondary" | "ghost"; danger?: boolean; iconOnly?: boolean }> = {
  pause: { label: "Pause", icon: Pause, variant: "ghost" },
  resume: { label: "Resume", icon: Play, variant: "secondary" },
  adjust: { label: "Adjust", icon: SlidersHorizontal, variant: "secondary" },
  stop: { label: "Stop", icon: Square, variant: "ghost", danger: true },
  archive: { label: "Archive", icon: Archive, variant: "ghost" },
  log: { label: "Log", icon: ScrollText, variant: "ghost", iconOnly: true },
  share: { label: "Share PnL", icon: Share2, variant: "ghost", iconOnly: true },
};

function ActionButton({ action, stopped, disabled, onClick }: { action: RowAction; stopped: boolean; disabled: boolean; onClick: () => void }) {
  const m = ACTION_META[action];
  const Icon = m.icon;
  const text = action === "adjust" && stopped ? "Copy again" : m.label;
  return (
    <Button
      size="sm"
      variant={m.variant}
      className={clsx(m.danger && "text-danger")}
      disabled={disabled && action !== "log" && action !== "share"}
      onClick={onClick}
      aria-label={text}
      title={text}
    >
      <Icon size={12} aria-hidden="true" />
      {m.iconOnly ? null : <span>{text}</span>}
    </Button>
  );
}
