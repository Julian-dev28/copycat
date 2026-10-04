"use client";

import { useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { formatAgo, formatUsd, shortenAddress } from "@/lib/format";
import { problemText } from "@/lib/trade/apiState";
import type { TradeSettings, TradeStatus, WalletPosition } from "@/lib/trade/types";
import { AmountField } from "./AmountField";
import { LeverageField } from "./LeverageField";
import { AdvancedFields } from "./AdvancedFields";
import { PreviewBox } from "./PreviewBox";
import { LiveCopyDialog, StopDialog, SwitchSourceDialog } from "./TicketDialogs";
import { TicketBanners } from "./TicketBanners";
import { GlobalSummary } from "./GlobalSummary";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { useCopyWallet, useStopWallet } from "./hooks";
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
  const [confirm, setConfirm] = useState<"live" | "switch" | null>(null);
  const [stopOpen, setStopOpen] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const label = name ?? shortenAddress(address);
  const live = Boolean(settings?.enabled && !settings.dry_run);
  const d = t.draft;
  const custom = d.source === "custom";
  const showStop = stopOpen || stopRequest;

  function submit(confirmed = false) {
    if (!t.body || t.action === "unchanged") return;
    if (!confirmed && t.switching) return setConfirm("switch");
    if (!confirmed && t.action === "copy" && live) return setConfirm("live");
    const body = t.body;
    const verb = t.action === "copy" ? "Copying" : "Updated";
    const terms = body.settings_source === "global"
      ? "with your global settings"
      : `${formatUsd(body.allocation_usd)}${body.exposure_mode === "target" ? ` at ${body.target_leverage}x` : ", following his leverage"}`;
    copy.mutate({ address, body }, { onSuccess: () => setDone(`${verb} ${label}: ${terms}. See it in Your wallets below.`) });
  }

  const cta = t.action === "copy"
    ? copy.isPending ? "Copying…" : custom ? "Copy wallet" : "Copy with global settings"
    : t.action === "update" ? (copy.isPending ? "Updating…" : t.switching ? (custom ? "Switch to custom terms" : "Switch to global settings") : "Update") : "No changes";

  return (
    <Panel className="flex flex-col gap-4 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">{t.invested ? "Adjust" : "Copy"} {label}</h2>
          {t.invested && wallet ? (
            <p className="font-num mt-0.5 text-xs text-muted">
              {t.saved.source === "global" ? "Global settings" : <>Invested {formatUsd(wallet.allocation_usd)} · {wallet.exposure_mode === "target" ? `${wallet.target_leverage}x` : "his leverage"}</>}
              {wallet.invested_ms ? ` · since ${formatAgo(wallet.invested_ms, nowMs).replace(" ago", "")}` : ""}
            </p>
          ) : (
            <p className="mt-0.5 text-xs text-muted">{custom ? "Like opening a perp: pick a size and a leverage." : "Copies with the terms on your Settings tab."}</p>
          )}
        </div>
        {wallet?.stopping ? <span className="rounded-full bg-warning/15 px-2 py-0.5 text-[11px] font-medium text-warning">stopping</span> : null}
      </div>

      <TicketBanners settings={settings} settingsHref={settingsHref} />

      <div className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">Settings</span>
        <SegmentedControl
          aria-label="Settings for this wallet"
          options={[{ value: "global", label: "Use global" }, { value: "custom", label: "Custom for this wallet" }]}
          value={d.source}
          onChange={(source) => t.setDraft({ source })}
        />
      </div>

      {custom ? (
        <>
          <AmountField
            value={d.amountText}
            onChange={(v) => t.setDraft({ amountText: v })}
            maxUsd={t.maxUsd}
            freeUsd={status?.available_margin_usd}
            equityUsd={status?.equity_usd}
            error={t.check.ok ? null : t.check.error}
            warn={t.check.ok ? t.check.warn : null}
          />
          <LeverageField
            mode={d.mode}
            leverage={d.leverage}
            marginMode={t.eff.marginMode}
            marginSet={d.marginMode !== null}
            hisLeverage={t.preview?.hisLeverage ?? null}
            onMode={(mode) => t.setDraft({ mode })}
            onLeverage={(leverage) => t.setDraft({ leverage })}
            onMarginMode={(marginMode) => t.setDraft({ marginMode })}
            onMarginReset={() => t.resetField("marginMode")}
          />
          <AdvancedFields draft={d} eff={t.eff} caps={t.caps} onChange={t.setDraft} onReset={t.resetField} />
        </>
      ) : (
        <GlobalSummary settings={settings} settingsHref={settingsHref} supported={t.caps.v7} />
      )}

      {t.preview && (!custom || t.amount) ? (
        <PreviewBox
          preview={t.preview}
          amount={custom ? t.amount ?? 0 : null}
          mode={d.mode}
          leverage={d.leverage}
          marginMode={t.eff.marginMode}
          pending={t.previewPending}
          sourceNote={t.previewNote}
          onlyNew={t.eff.onlyNew}
          onUseFullBook={custom ? (usd) => t.setDraft({ amountText: String(usd) }) : null}
        />
      ) : !custom && t.previewPending ? (
        <p className="text-xs text-muted">Asking the engine what your settings would copy…</p>
      ) : !custom && t.previewError ? (
        <p className="text-xs text-muted">The engine preview is unavailable, so there is no estimate for global sizing.</p>
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

      <LiveCopyDialog open={confirm === "live"} name={label} amount={custom ? t.amount : null} onCancel={() => setConfirm(null)} onConfirm={() => { setConfirm(null); submit(true); }} />
      <SwitchSourceDialog open={confirm === "switch"} name={label} to={d.source} live={live} onCancel={() => setConfirm(null)} onConfirm={() => { setConfirm(null); submit(true); }} />
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
