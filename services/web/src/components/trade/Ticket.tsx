"use client";

import { useId, useState } from "react";
import { clsx } from "clsx";
import { CheckCircle2, ChevronUp, PauseCircle, ScrollText } from "lucide-react";
import { Badge, Button, SegmentedControl, Tooltip, toast } from "@/components/ui";
import { formatAgo, formatUsd, shortenAddress } from "@/lib/format";
import { LABELS } from "@/lib/labels";
import { problemText } from "@/lib/trade/apiState";
import { algoWarning } from "@/lib/trade/algo";
import { walletStatus } from "@/lib/trade/lifecycle";
import { actionSummary, allocationBreakdown, disabledReason, effectiveLeverageText } from "@/lib/trade/ticketView";
import type { TraderProfile, TraderRow } from "@/lib/scout/types";
import type { TradeSettings, TradeStatus, WalletPosition } from "@/lib/trade/types";
import { AlgoWarning, CoinFilterFields, DirectionSwitch } from "./TicketExtras";
import { ProjectionPanel } from "./ProjectionPanel";
import { WalletLogDrawer } from "./WalletLogDrawer";
import { AmountField } from "./AmountField";
import { LeverageField } from "./LeverageField";
import { AdvancedFields } from "./AdvancedFields";
import { PreviewBox } from "./PreviewBox";
import { LiveCopyDialog, StopDialog, SwitchSourceDialog } from "./TicketDialogs";
import { TicketBanners } from "./TicketBanners";
import { GlobalSummary } from "./GlobalSummary";
import { useCopyWallet, useStopWallet } from "./hooks";
import type { useTicket } from "./useTicket";

type TicketState = ReturnType<typeof useTicket>;

/** Sections fade/slide in when they mount (Use global <-> Custom). Static under reduced motion. */
const SECTION_IN =
  "transition-[opacity,translate] duration-[var(--dur-base)] ease-[var(--ease-out)] starting:translate-y-1 starting:opacity-0 motion-reduce:transition-none motion-reduce:starting:translate-y-0";

const LIQ_CLASS = { danger: "text-danger", warn: "text-warn", muted: "text-fg-soft" } as const;

/**
 * The ticket (DESIGN 5 Ticket, UX audit #8): a sticky rail whose body
 * scrolls and whose action bar (summary line + primary button) stays pinned,
 * so the button is always on screen. Under 1024px the same element is a
 * bottom sheet: the action bar shows collapsed, the body opens over the page.
 */
export function Ticket({
  address,
  name,
  t,
  settings,
  status,
  wallet,
  settingsHref,
  nowMs,
  profile,
  row,
  allCoins,
  sheetOpen,
  onSheet,
}: {
  address: string;
  name: string | null;
  profile: TraderProfile | undefined;
  row: TraderRow | null;
  /** Autocomplete pool for the coin filters (every coin the board trades). */
  allCoins: string[];
  t: TicketState;
  settings: TradeSettings | undefined;
  status: TradeStatus | undefined;
  wallet: WalletPosition | null;
  settingsHref: string;
  nowMs: number;
  /** Phones and tablets: the bottom sheet is open. Ignored at 1024px and up. */
  sheetOpen: boolean;
  onSheet: (open: boolean) => void;
}) {
  const copy = useCopyWallet();
  const stop = useStopWallet();
  const [confirm, setConfirm] = useState<"live" | "switch" | null>(null);
  const [stopOpen, setStopOpen] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [logOpen, setLogOpen] = useState(false);
  const tipId = useId();
  const label = name ?? shortenAddress(address);
  const live = Boolean(settings?.enabled && !settings.dry_run);
  const d = t.draft;
  const custom = d.source === "custom";
  const lifeStatus = wallet ? walletStatus(wallet) : null;
  const warn = algoWarning({ style: profile?.row.style ?? row?.style, walletStyle: wallet?.style, flags: profile?.row.flags ?? row?.flags, scoreFlags: profile?.row.score.flags ?? row?.score.flags });
  const hisCoins = [...new Set([...(profile?.positions ?? []).map((p) => p.coin), ...(profile?.coins ?? []).map((c) => c.coin), ...(row?.top_coins ?? []).map((c) => c.coin)])];
  const showPreview = Boolean(t.preview && (!custom || t.amount));
  const preview = showPreview ? t.preview : null;
  const estimate = preview?.source === "local";
  const breakdown = custom ? allocationBreakdown(t.amount, preview) : null;
  const summary = actionSummary(preview);
  const cap = settings?.max_position_leverage;

  function finish(msg: string) {
    setDone(msg);
    toast.success(msg);
  }

  function submit(confirmed = false) {
    if (!t.body || t.action === "unchanged") return;
    if (!confirmed && t.switching) return setConfirm("switch");
    if (!confirmed && t.action === "copy" && live) return setConfirm("live");
    const body = t.body;
    const verb = t.action === "copy" ? (t.eff.direction === "counter" ? "Countering" : "Copying") : "Updated";
    const terms =
      body.settings_source === "global"
        ? "with your global settings"
        : `${formatUsd(body.allocation_usd)}${body.exposure_mode === "target" ? ` at ${effectiveLeverageText(body.target_leverage, cap)}` : ", following their leverage"}`;
    copy.mutate({ address, body }, { onSuccess: () => finish(`${verb} ${label}: ${terms}. See it in Your copies.`) });
  }

  const cta =
    t.action === "copy"
      ? copy.isPending
        ? "Copying…"
        : custom
          ? t.eff.direction === "counter"
            ? "Counter trader"
            : LABELS.copyTrader
          : "Copy with global settings"
      : t.action === "update"
        ? copy.isPending
          ? "Updating…"
          : t.switching
            ? custom
              ? "Switch to custom terms"
              : "Switch to global settings"
            : "Update"
        : "No changes";
  const disabled = !t.body || t.action === "unchanged" || copy.isPending;
  const why = disabled
    ? disabledReason({ hasBody: Boolean(t.body), action: t.action, pending: copy.isPending, custom, amountText: d.amountText, error: t.check.ok ? null : t.check.error })
    : null;

  return (
    <section
      aria-labelledby="ticket-title"
      onKeyDown={(e) => {
        if (e.key === "Escape" && sheetOpen) onSheet(false);
      }}
      className={clsx(
        "relative flex max-h-full min-h-0 flex-col overflow-hidden border-border",
        "lg:rounded-xl lg:border lg:bg-surface lg:shadow-e1",
        "max-lg:glass max-lg:rounded-t-2xl max-lg:border-t",
      )}
    >
      {sheetOpen ? (
        <button type="button" aria-label="Close the ticket" tabIndex={-1} onClick={() => onSheet(false)} className="fixed inset-0 -z-10 bg-black/40 lg:hidden" />
      ) : null}

      {/* header; on phones a tap on it (or the chevron) opens and closes the sheet */}
      <div className="flex items-start justify-between gap-2 px-4 pt-2 pb-3 lg:pt-4" onClick={(e) => e.target === e.currentTarget && onSheet(!sheetOpen)}>
        <div className="min-w-0 flex-1">
          <span className="mx-auto mb-2 block h-1 w-10 rounded-sm bg-border-strong lg:hidden" aria-hidden="true" />
          <h2 id="ticket-title" className="truncate text-heading text-fg">
            {t.invested ? "Adjust" : "Copy"} {label}
          </h2>
          {t.invested && wallet ? (
            <p className="num-sm mt-0.5 text-muted">
              {t.saved.source === "global" ? (
                "Global settings"
              ) : (
                <>
                  Invested {formatUsd(wallet.allocation_usd)} ·{" "}
                  {wallet.exposure_mode === "target" ? effectiveLeverageText(wallet.target_leverage, cap) : "their leverage"}
                </>
              )}
              {wallet.invested_ms ? ` · since ${formatAgo(wallet.invested_ms, nowMs).replace(" ago", "")}` : ""}
            </p>
          ) : (
            <p className="mt-0.5 text-xs text-muted">{custom ? "Like opening a perp: pick a size and a leverage." : "Copies with the terms on your Settings tab."}</p>
          )}
        </div>
        <div className="flex items-center gap-1">
          {wallet?.stopping ? <Badge tone="warn">stopping</Badge> : null}
          {wallet ? (
            <Button size="sm" variant="ghost" onClick={() => setLogOpen(true)} aria-label={`Open the log for ${label}`}>
              <ScrollText size={13} aria-hidden="true" /> Log
            </Button>
          ) : null}
          <button
            type="button"
            onClick={() => onSheet(!sheetOpen)}
            aria-expanded={sheetOpen}
            aria-controls="ticket-body"
            aria-label={sheetOpen ? "Hide the ticket" : "Show the ticket"}
            className="grid h-8 w-8 place-items-center rounded-sm text-muted transition-colors hover:bg-surface-2 hover:text-fg lg:hidden"
          >
            <ChevronUp size={18} aria-hidden="true" className={clsx("transition-transform duration-[var(--dur-base)]", sheetOpen && "rotate-180")} />
          </button>
        </div>
      </div>

      <div
        id="ticket-body"
        className={clsx(
          "min-h-0 flex-1 flex-col divide-y divide-border overflow-y-auto overscroll-contain px-4 [&>*]:py-4 [&>*:first-child]:pt-0",
          "max-lg:max-h-[min(62dvh,40rem)]",
          sheetOpen ? "flex" : "flex max-lg:hidden",
        )}
      >
        <div className="flex flex-col gap-3">
          {lifeStatus === "paused" ? (
            <p className="flex items-start gap-1.5 rounded-lg bg-surface-2 px-3 py-2 text-xs text-muted">
              <PauseCircle size={13} className="mt-0.5 flex-shrink-0" aria-hidden="true" /> Paused: no new copies; exits still followed. Resume it from Your copies.
            </p>
          ) : null}
          <DirectionSwitch
            value={t.eff.direction}
            onChange={t.setDirection}
            set={t.draft.direction !== null}
            onReset={() => t.resetField("direction")}
            supported={t.caps.v8}
            globalSource={!custom}
          />
          <TicketBanners settings={settings} settingsHref={settingsHref} />
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium">Settings</span>
          <SegmentedControl
            aria-label="Settings for this trader"
            options={[
              { value: "global", label: "Use global" },
              { value: "custom", label: "Custom for this trader" },
            ]}
            value={d.source}
            onChange={(source) => t.setDraft({ source })}
          />
        </div>

        {custom ? (
          <div key="custom-amount" className={SECTION_IN}>
            <AmountField
              value={d.amountText}
              onChange={(v) => t.setDraft({ amountText: v })}
              maxUsd={t.maxUsd}
              freeUsd={status?.available_margin_usd}
              equityUsd={status?.equity_usd}
              error={t.check.ok ? null : t.check.error}
              warn={t.check.ok ? t.check.warn : null}
              breakdown={breakdown}
              estimate={estimate}
            />
          </div>
        ) : (
          <div key="global" className={SECTION_IN}>
            <GlobalSummary settings={settings} settingsHref={settingsHref} supported={t.caps.v7} />
          </div>
        )}
        {custom ? (
          <div key="custom-lev" className={SECTION_IN}>
            <LeverageField
              mode={d.mode}
              leverage={d.leverage}
              marginMode={t.eff.marginMode}
              marginSet={d.marginMode !== null}
              hisLeverage={t.preview?.hisLeverage ?? null}
              cap={t.lev}
              onMode={(mode) => t.setDraft({ mode })}
              onLeverage={(leverage) => t.setDraft({ leverage })}
              onMarginMode={(marginMode) => t.setDraft({ marginMode })}
              onMarginReset={() => t.resetField("marginMode")}
            />
          </div>
        ) : null}
        {custom ? (
          <div key="custom-coins" className={clsx("flex flex-col gap-4", SECTION_IN)}>
            <CoinFilterFields
              allow={t.eff.allow}
              block={t.eff.block}
              allowSet={d.allow !== null}
              blockSet={d.block !== null}
              hisCoins={hisCoins}
              allCoins={allCoins}
              onAllow={(allow) => t.setDraft({ allow })}
              onBlock={(block) => t.setDraft({ block })}
              onReset={t.resetField}
              supported={t.caps.v8}
            />
            <AdvancedFields draft={d} eff={t.eff} caps={t.caps} onChange={t.setDraft} onReset={t.resetField} />
          </div>
        ) : null}

        {preview ? (
          <div className={SECTION_IN}>
            <PreviewBox
              preview={preview}
              amount={custom ? (t.amount ?? 0) : null}
              mode={d.mode}
              leverage={t.lev.effective}
              marginMode={t.eff.marginMode}
              pending={t.previewPending}
              sourceNote={t.previewNote}
              onlyNew={t.eff.onlyNew}
              equityUsd={status?.equity_usd}
              onUseFullBook={custom ? (usd) => t.setDraft({ amountText: String(usd) }) : null}
            />
          </div>
        ) : !custom && t.previewPending ? (
          <p className="text-xs text-muted">Asking the engine what your settings would copy…</p>
        ) : !custom && t.previewError ? (
          <p className="text-xs text-muted">The engine preview is unavailable, so there is no estimate for global sizing.</p>
        ) : null}

        <div>
          <ProjectionPanel address={address} amount={custom ? t.amount : null} direction={t.eff.direction} mode={d.mode} leverage={t.lev.effective} profile={profile} />
        </div>

        {warn ? (
          <div>
            <AlgoWarning text={warn} />
          </div>
        ) : null}
      </div>

      {/* pinned action bar: always on screen */}
      <div data-testid="ticket-action-bar" className="flex flex-col gap-2 border-t border-border px-4 pt-3 pb-3 lg:bg-surface">
        <p data-testid="ticket-summary" className="num-sm flex min-h-4 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-muted" aria-live="polite">
          {custom && t.amount ? <span className="text-fg-soft lg:hidden">Invest {formatUsd(t.amount, t.amount >= 100_000)} ·</span> : null}
          {summary.length ? (
            <>
              {summary.map((s, i) => (
                <span key={s.label} className="whitespace-nowrap">
                  {s.label} <span className={clsx(estimate ? "text-muted" : s.tone ? LIQ_CLASS[s.tone] : "text-fg-soft")}>{s.value}</span>
                  {i < summary.length - 1 ? <span aria-hidden="true"> ·</span> : null}
                </span>
              ))}
              {estimate ? <Badge tone="neutral">estimate</Badge> : null}
            </>
          ) : custom ? (
            <span>Enter an amount to see exposure, margin and liquidation.</span>
          ) : t.previewPending ? (
            <span>Asking the engine…</span>
          ) : (
            <span>Sized by your Settings.</span>
          )}
        </p>
        <div className="flex gap-2">
          <Tooltip id={tipId} content={why ?? ""} className={clsx("flex-1", !why && "[&>[role=tooltip]]:hidden")}>
            <Button
              variant="primary"
              size="lg"
              className="w-full"
              disabled={disabled}
              aria-describedby={why ? tipId : undefined}
              onClick={() => submit()}
            >
              {cta}
            </Button>
          </Tooltip>
          {t.invested ? (
            <Button variant="danger" size="lg" className="flex-shrink-0 px-4" onClick={() => setStopOpen(true)}>
              {LABELS.stopCopying}
            </Button>
          ) : null}
        </div>
        {copy.isError ? (
          <p role="alert" className="text-xs text-danger">
            {problemText(copy.error, "copy")}
          </p>
        ) : null}
        {stop.isError ? (
          <p role="alert" className="text-xs text-danger">
            {problemText(stop.error, "stop")}
          </p>
        ) : null}
        {done && !copy.isPending && !copy.isError ? (
          <p role="status" className="flex items-center gap-1.5 text-xs text-muted">
            <CheckCircle2 size={13} className="flex-shrink-0 text-ok" aria-hidden="true" /> {done}
          </p>
        ) : null}
      </div>

      <WalletLogDrawer open={logOpen} onClose={() => setLogOpen(false)} address={address} name={label} />
      <LiveCopyDialog
        open={confirm === "live"}
        name={label}
        amount={custom ? t.amount : null}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          setConfirm(null);
          submit(true);
        }}
      />
      <SwitchSourceDialog
        open={confirm === "switch"}
        name={label}
        to={d.source}
        live={live}
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          setConfirm(null);
          submit(true);
        }}
      />
      <StopDialog
        key={stopOpen ? "open" : "closed"}
        open={stopOpen}
        name={label}
        openCopies={wallet?.open_copies ?? 0}
        pending={stop.isPending}
        onCancel={() => setStopOpen(false)}
        onConfirm={(close_positions) =>
          stop.mutate(
            { address, body: { close_positions } },
            {
              onSettled: () => setStopOpen(false),
              onSuccess: () => finish(close_positions ? `Stopping ${label}: closing its copies.` : `Stopped new copies of ${label}; open ones follow them out.`),
            },
          )
        }
      />
    </section>
  );
}
