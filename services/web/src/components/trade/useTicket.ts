"use client";

import { useState } from "react";
import { apiProblem } from "@/lib/trade/apiState";
import { mergePreview } from "@/lib/trade/apiPreview";
import { buildCopyRequest, checkAmount, initialDraft, maxInvest, parseInvest, ticketAction, type TicketDraft } from "@/lib/trade/form";
import { localPreview } from "@/lib/trade/preview";
import type { TicketPreview } from "@/lib/trade/ticket";
import type { TradeSettings, TradeStatus, WalletPosition } from "@/lib/trade/types";
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
  const invested = Boolean(wallet && wallet.allocation_usd && wallet.in_book !== false);
  const savedKey = `${address}|${JSON.stringify(saved)}|${invested}`;
  const [state, setState] = useState({ key: savedKey, draft: saved });
  let draft = state.draft;
  if (state.key !== savedKey) {
    setState({ key: savedKey, draft: saved });
    draft = saved;
  }
  const setDraft = (patch: Partial<TicketDraft>) => setState((s) => ({ ...s, draft: { ...s.draft, ...patch } }));

  const amount = parseInvest(draft.amountText);
  const maxUsd = maxInvest(status?.available_margin_usd, wallet?.margin_used_usd ?? 0);
  const check = checkAmount(amount, maxUsd);
  const smallModeSupported = settings ? "small_account_mode" in settings : false;
  const body = address && check.ok && amount !== null ? buildCopyRequest(draft, amount, { smallModeSupported }) : null;
  const action = ticketAction(draft, amount, invested ? saved : null, invested);

  const otherExposure = (status?.positions ?? []).filter((c) => c.leader !== address).reduce((a, c) => a + Math.abs(c.notional_usd), 0);
  const local: TicketPreview | null = profile
    ? localPreview({
        allocationUsd: amount ?? 0,
        mode: draft.mode,
        targetLeverage: draft.leverage,
        marginMode: draft.marginMode,
        smallMode: smallModeSupported ? draft.smallMode : "skip",
        leaderEquityUsd: profile.row.account_value_usd,
        positions: profile.positions,
        maxPositionLeverage: settings?.max_position_leverage,
        ourEquityUsd: status?.equity_usd,
        otherExposureUsd: otherExposure,
      })
    : null;
  const api = useWalletPreview(address, body);
  const apiFailed = apiProblem(api.error);
  // Only trust the api answer for the body on screen; while typing, show the local estimate.
  const preview = local ? (api.settled && body && api.data && !api.isPlaceholderData ? mergePreview(api.data, local) : local) : null;
  const previewNote =
    apiFailed === "too_old" ? "Local estimate: your api has no preview route yet." : apiFailed ? "Local estimate: the engine preview failed." : null;

  return {
    draft, setDraft, amount, maxUsd, check, body, action, invested, saved, smallModeSupported,
    preview, previewPending: Boolean(body) && (!api.settled || api.isFetching), previewNote,
  };
}
