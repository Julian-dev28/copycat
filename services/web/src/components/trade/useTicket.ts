"use client";

import { useState } from "react";
import { apiProblem } from "@/lib/trade/apiState";
import { mergePreview } from "@/lib/trade/apiPreview";
import { apiCaps, buildCopyRequest, effective, initialDraft, inherit, switchesSource, ticketAction, type InheritableField, type TicketDraft } from "@/lib/trade/draft";
import { applyCoinFilter } from "@/lib/trade/coinFilter";
import { applyDirection } from "@/lib/trade/direction";
import { checkAmount, maxInvest, parseInvest, targetLeverageCap } from "@/lib/trade/form";
import { estimateNote, localPreview } from "@/lib/trade/preview";
import type { TicketPreview } from "@/lib/trade/ticket";
import type { TradeDirection, TradeSettings, TradeStatus, WalletPosition } from "@/lib/trade/types";
import type { TraderProfile } from "@/lib/scout/types";
import { useWalletPreview } from "./hooks";

/**
 * Ticket state for one wallet. The draft resets to the saved terms only when
 * those terms change (a save landed, another wallet was picked), never on the
 * 4s status poll, so typing is never clobbered. Adjusted during render, not in
 * an effect (see hooks/useSyncedState.ts).
 */
export function useTicket(address: string | null, profile: TraderProfile | undefined, settings: TradeSettings | undefined, status: TradeStatus | undefined, wallet: WalletPosition | null) {
  const saved = initialDraft(settings, address, wallet);
  const invested = Boolean(wallet && wallet.in_book !== false);
  const savedKey = `${address}|${JSON.stringify(saved)}|${invested}`;
  const [state, setState] = useState({ key: savedKey, draft: saved });
  let draft = state.draft;
  if (state.key !== savedKey) {
    setState({ key: savedKey, draft: saved });
    draft = saved;
  }
  const setDraft = (patch: Partial<TicketDraft>) => setState((s) => ({ ...s, draft: { ...s.draft, ...patch } }));
  const resetField = (field: InheritableField) => setState((s) => ({ ...s, draft: inherit(s.draft, field) }));
  /** Copy | Counter is a per-wallet term: picking one on "Use global" moves the ticket to custom (amount from Settings). */
  const setDirection = (direction: TradeDirection) =>
    setState((s) => {
      const d = s.draft;
      if (d.source === "custom") return { ...s, draft: { ...d, direction } };
      const alloc = settings?.allocation_usd;
      return { ...s, draft: { ...d, source: "custom", direction, amountText: d.amountText || (alloc && alloc > 0 ? String(alloc) : "") } };
    });

  const caps = apiCaps(settings);
  const eff = effective(draft, settings);
  const custom = draft.source === "custom";
  const amount = custom ? parseInvest(draft.amountText) : null;
  const maxUsd = maxInvest(status?.available_margin_usd, wallet?.margin_used_usd ?? 0);
  const check = custom ? checkAmount(amount, maxUsd) : ({ ok: true, warn: null } as const);
  const body = address && check.ok ? buildCopyRequest(draft, caps) : null;
  const savedForCompare = invested ? saved : null;
  const action = ticketAction(draft, savedForCompare, invested);
  const switching = switchesSource(draft, savedForCompare, invested);

  const lev = targetLeverageCap(draft.leverage, settings?.max_position_leverage);
  const otherExposure = (status?.positions ?? []).filter((c) => c.leader !== address).reduce((a, c) => a + Math.abs(c.notional_usd), 0);
  // Local estimate only for custom terms; global sizing can be any mode, so it waits for the engine.
  const local: TicketPreview | null = profile && custom
    ? localPreview({
        allocationUsd: amount ?? 0,
        mode: draft.mode,
        // The engine sizes at the capped leverage (sizing.py exchange_leverage), so the estimate does too.
        targetLeverage: lev.effective,
        marginMode: eff.marginMode,
        smallMode: caps.smallMode ? eff.smallMode : "skip",
        leaderEquityUsd: profile.row.account_value_usd,
        positions: profile.positions,
        maxPositionLeverage: settings?.max_position_leverage,
        ourEquityUsd: status?.equity_usd,
        otherExposureUsd: otherExposure,
      })
    : null;
  const api = useWalletPreview(address, body);
  const apiFailed = apiProblem(api.error);
  const fresh = api.settled && body && api.data && !api.isPlaceholderData ? api.data : null;
  const merged = local ? mergePreview(fresh, local) : fresh;
  // Filters and direction on top of either source: idempotent when the engine already applied them.
  const preview = merged ? applyDirection(applyCoinFilter(merged, eff.allow, eff.block), eff.direction) : null;
  const previewNote = estimateNote(apiFailed, Boolean(local && !fresh), profile?.positions_as_of_ms);

  return {
    draft, setDraft, resetField, setDirection, lev, amount, maxUsd, check, body, action, switching, invested, saved, caps, eff,
    preview, previewPending: Boolean(body) && (!api.settled || api.isFetching), previewNote, previewError: apiFailed,
  };
}
