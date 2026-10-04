"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, PauseCircle, FlaskConical } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { formatAgo, formatUsd, shortenAddress } from "@/lib/format";
import { problemText } from "@/lib/trade/apiState";
import type { TradeSettings, TradeStatus, WalletPosition } from "@/lib/trade/types";
import { AmountField } from "./AmountField";
import { LeverageField } from "./LeverageField";
import { AdvancedFields } from "./AdvancedFields";
import { PreviewBox } from "./PreviewBox";
import { LiveCopyDialog, StopDialog } from "./TicketDialogs";
import { useCopyWallet, usePatchTradeSettings, useStopWallet } from "./hooks";
import type { useTicket } from "./useTicket";

type TicketState = ReturnType<typeof useTicket>;

export function Ticket({
  address,
  name,
  t,
  settings,
  status,
  wallet,
  settingsHref,
  nowMs,
  stopRequest,
  onStopHandled,
}: {
  address: string;
  name: string | null;
  t: TicketState;
  settings: TradeSettings | undefined;
  status: TradeStatus | undefined;
  wallet: WalletPosition | null;
  settingsHref: string;
  nowMs: number;
  /** Set by "Stop" in Your wallets: open the stop dialog here. */
  stopRequest: boolean;
  onStopHandled: () => void;
}) {
  const copy = useCopyWallet();
  const stop = useStopWallet();
  const patch = usePatchTradeSettings();
  const [confirmLive, setConfirmLive] = useState(false);
  const [stopOpen, setStopOpen] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const label = name ?? shortenAddress(address);
  const live = Boolean(settings?.enabled && !settings.dry_run);
  const d = t.draft;
  const showStop = stopOpen || stopRequest;

  function submit(force = false) {
    if (!t.body || t.action === "unchanged") return;
    if (t.action === "copy" && live && !force) {
      setConfirmLive(true);
      return;
    }
    const body = t.body;
    copy.mutate(
      { address, body },
      { onSuccess: () => setDone(`${t.action === "copy" ? "Copying" : "Updated"} ${label}: ${formatUsd(body.allocation_usd)}${body.exposure_mode === "target" ? ` at ${body.target_leverage}x` : ", following his leverage"}. See it in Your wallets below.`) },
    );
  }

  const cta = t.action === "copy" ? (copy.isPending ? "Copying…" : "Copy wallet") : t.action === "update" ? (copy.isPending ? "Updating…" : "Update") : "No changes";

  return (
    <Panel className="flex flex-col gap-4 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">{t.invested ? "Adjust" : "Copy"} {label}</h2>
          {t.invested && wallet ? (
            <p className="font-num mt-0.5 text-xs text-muted">
              Invested {formatUsd(wallet.allocation_usd)} · {wallet.exposure_mode === "target" ? `${wallet.target_leverage}x` : "his leverage"}
              {wallet.invested_ms ? ` · since ${formatAgo(wallet.invested_ms, nowMs).replace(" ago", "")}` : ""}
            </p>
          ) : (
            <p className="mt-0.5 text-xs text-muted">Like opening a perp: pick a size and a leverage.</p>
          )}
        </div>
        {wallet?.stopping ? <span className="rounded-full bg-warning/15 px-2 py-0.5 text-[11px] font-medium text-warning">stopping</span> : null}
      </div>

      {settings && !settings.enabled ? (
        <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-xs">
          <PauseCircle size={14} className="mt-0.5 flex-shrink-0 text-warning" aria-hidden="true" />
          <span>Copying is paused: <Link href={settingsHref} className="font-medium text-accent hover:underline">enable it in Settings</Link>. You can still set up wallets; nothing trades until then.</span>
        </p>
      ) : settings?.dry_run ? (
        <p className="flex items-start gap-2 rounded-lg border border-accent/30 bg-accent-soft px-3 py-2 text-xs">
          <FlaskConical size={14} className="mt-0.5 flex-shrink-0 text-accent" aria-hidden="true" />
          <span>Dry run: copycat logs what it would do and places no orders. Turn it off in <Link href={settingsHref} className="font-medium text-accent hover:underline">Settings</Link>.</span>
        </p>
      ) : null}

      <AmountField
        value={d.amountText}
        onChange={(v) => setDraft(t, { amountText: v })}
        maxUsd={t.maxUsd}
        freeUsd={status?.available_margin_usd}
        equityUsd={status?.equity_usd}
        error={t.check.ok ? null : t.check.error}
        warn={t.check.ok ? t.check.warn : null}
      />
      <LeverageField
        mode={d.mode}
        leverage={d.leverage}
        marginMode={d.marginMode}
        hisLeverage={t.preview?.hisLeverage ?? null}
        onMode={(mode) => setDraft(t, { mode })}
        onLeverage={(leverage) => setDraft(t, { leverage })}
        onMarginMode={(marginMode) => setDraft(t, { marginMode })}
      />
      <AdvancedFields
        smallMode={d.smallMode}
        onSmallMode={(smallMode) => setDraft(t, { smallMode })}
        smallModeSupported={t.smallModeSupported}
        worseEntry={d.maxWorseEntryPct}
        onWorseEntry={(maxWorseEntryPct) => setDraft(t, { maxWorseEntryPct })}
        onlyNew={settings?.only_new_positions ?? false}
        onOnlyNew={(v) => patch.mutate({ only_new_positions: v })}
        onlyNewSaving={patch.isPending}
      />

      {t.preview && t.amount ? (
        <PreviewBox
          preview={t.preview}
          amount={t.amount}
          mode={d.mode}
          leverage={d.leverage}
          marginMode={d.marginMode}
          pending={t.previewPending}
          sourceNote={t.previewNote}
          onlyNew={settings?.only_new_positions ?? false}
          onUseFullBook={(usd) => setDraft(t, { amountText: String(usd) })}
        />
      ) : null}

      <div className="flex flex-col gap-2">
        <Button variant="primary" size="lg" className="w-full" disabled={!t.body || t.action === "unchanged" || copy.isPending} onClick={() => submit()}>
          {cta}
        </Button>
        {t.invested ? (
          <Button variant="ghost" className="w-full border-danger/40 !text-danger hover:bg-danger/10" onClick={() => setStopOpen(true)}>
            Stop copying
          </Button>
        ) : null}
        {copy.isError ? <p role="alert" className="text-xs text-danger">{problemText(copy.error, "wallet copy")}</p> : null}
        {stop.isError ? <p role="alert" className="text-xs text-danger">{problemText(stop.error, "wallet stop")}</p> : null}
        {done && !copy.isPending && !copy.isError ? (
          <p role="status" className="flex items-center gap-1.5 text-xs text-success">
            <CheckCircle2 size={13} aria-hidden="true" /> {done}
          </p>
        ) : null}
      </div>

      <LiveCopyDialog open={confirmLive} name={label} amount={t.amount ?? 0} onCancel={() => setConfirmLive(false)} onConfirm={() => { setConfirmLive(false); submit(true); }} />
      <StopDialog
        key={showStop ? "open" : "closed"}
        open={showStop}
        name={label}
        openCopies={wallet?.open_copies ?? 0}
        pending={stop.isPending}
        onCancel={() => { setStopOpen(false); onStopHandled(); }}
        onConfirm={(close_positions) =>
          stop.mutate({ address, body: { close_positions } }, {
            onSettled: () => { setStopOpen(false); onStopHandled(); },
            onSuccess: () => setDone(close_positions ? `Stopping ${label}: closing its copies.` : `Stopped new copies of ${label}; open ones follow him out.`),
          })
        }
      />
    </Panel>
  );
}

function setDraft(t: TicketState, patch: Parameters<TicketState["setDraft"]>[0]) {
  t.setDraft(patch);
}
